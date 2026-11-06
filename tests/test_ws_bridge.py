"""Browser bridge tests: real TCP server + real bridge + a minimal WebSocket client (RFC 6455)."""

import base64
import json
import os
import socket
import struct
import threading
import time

import pytest

from common.protocol import (
    CREATE_ROOM, GAME_OVER, GAME_START, JOIN_ROOM, LOGIN, LOGIN_OK, PING, PLAYER_LEFT, PONG,
    READY, ROOM_UPDATE, STATE, make_msg,
)
from tcp.server import Server
from udp.server import Server as UdpServer
from web.bridge import accept_key, make_server


@pytest.fixture
def stack(tmp_path):
    """TCP game server + bridge on free ports; yields the bridge port."""
    (tmp_path / "index.html").write_text("<!doctype html><title>Maze Arena</title>")
    srv = Server("127.0.0.1", 0, game_ticks=20)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    bridge = make_server("127.0.0.1", 0, "127.0.0.1", srv.port, tmp_path)
    threading.Thread(target=bridge.serve_forever, daemon=True).start()
    yield bridge.server_address[1]
    bridge.shutdown()
    bridge.server_close()
    srv.stop()


class WsClient:
    """Just enough of a browser's WebSocket: handshake, masked text frames, frame reader."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            "GET /ws HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.sock.recv(1)
        assert head.startswith(b"HTTP/1.1 101"), head
        assert f"Sec-WebSocket-Accept: {accept_key(key)}".encode() in head
        self.received = []

    def send_frame(self, payload, opcode=0x1, fin=True):
        mask = os.urandom(4)
        n = len(payload)
        head = bytes([(0x80 if fin else 0) | opcode])
        head += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack("!H", n)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, msg):
        self.send_frame(json.dumps(msg).encode())

    def _recv_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("bridge closed the connection")
            data += chunk
        return data

    def read_frame(self):
        b0, b1 = self._recv_exact(2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._recv_exact(8))[0]
        return b0 & 0x0F, self._recv_exact(n)

    def wait_for(self, msg_type, timeout=4.0):
        deadline = time.monotonic() + timeout
        for i, m in enumerate(self.received):
            if m["type"] == msg_type:
                return self.received.pop(i)
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.01, deadline - time.monotonic()))
            opcode, payload = self.read_frame()
            if opcode == 0x1:
                msg = json.loads(payload)
                if msg["type"] == msg_type:
                    return msg
                self.received.append(msg)
        raise AssertionError(f"no {msg_type}; got {[m['type'] for m in self.received]}")

    def close(self):
        self.sock.close()


def test_static_index_is_served(stack):
    s = socket.create_connection(("127.0.0.1", stack), timeout=3)
    s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    data = b""
    while chunk := s.recv(4096):
        data += chunk
    assert data.startswith(b"HTTP/1.1 200") and b"Maze Arena" in data
    assert b"Cache-Control: no-store" in data


def test_login_and_ping_through_the_bridge(stack):
    ws = WsClient(stack)
    ws.send(make_msg(LOGIN, name="web1"))
    assert ws.wait_for(LOGIN_OK)["name"] == "web1"
    ws.send(make_msg(PING, t=12.5))
    assert ws.wait_for(PONG)["t"] == 12.5
    ws.close()


def test_fragmented_frame_and_websocket_ping(stack):
    ws = WsClient(stack)
    raw = json.dumps(make_msg(LOGIN, name="frag")).encode()
    ws.send_frame(raw[:7], opcode=0x1, fin=False)       # one message split over two frames
    ws.send_frame(raw[7:], opcode=0x0, fin=True)
    assert ws.wait_for(LOGIN_OK)["name"] == "frag"
    ws.send_frame(b"hi", opcode=0x9)                    # WebSocket-level ping -> pong
    opcode, payload = ws.read_frame()
    assert (opcode, payload) == (0xA, b"hi")
    ws.close()


def test_newline_inside_a_frame_cannot_inject_a_second_message(stack):
    ws = WsClient(stack)
    ws.send_frame(b'{"type":"LOGIN","name":"inj"}\n{"type":"LOGIN","name":"evil"}')
    # Joined into one (malformed) line: the server skips it, nobody logs in.
    ws.send(make_msg(LOGIN, name="ok"))
    assert ws.wait_for(LOGIN_OK)["name"] == "ok"
    ws.close()


def test_full_game_and_disconnect_reach_the_other_players(stack):
    a, b = WsClient(stack), WsClient(stack)
    for ws, name in ((a, "alice"), (b, "bob")):
        ws.send(make_msg(LOGIN, name=name))
        ws.wait_for(LOGIN_OK)
    a.send(make_msg(CREATE_ROOM, room="web"))
    for ws in (a, b):
        ws.send(make_msg(JOIN_ROOM, room="web"))
        ws.wait_for(ROOM_UPDATE)
        ws.send(make_msg(READY, ready=True))
    for ws in (a, b):
        assert ws.wait_for(GAME_START)["players"] == ["alice", "bob"]
        assert "positions" in ws.wait_for(STATE)
    b.close()                                           # browser tab closed mid-game
    assert a.wait_for(PLAYER_LEFT)["name"] == "bob"
    assert a.wait_for(GAME_OVER)["winner"] == "alice"   # one player left -> game over
    a.close()


def test_bridge_answers_502_when_the_game_server_is_down(tmp_path):
    bridge = make_server("127.0.0.1", 0, "127.0.0.1", 1, tmp_path)   # nothing listens on port 1
    threading.Thread(target=bridge.serve_forever, daemon=True).start()
    try:
        s = socket.create_connection(("127.0.0.1", bridge.server_address[1]), timeout=3)
        s.sendall(b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
        assert s.recv(64).startswith(b"HTTP/1.1 502")
    finally:
        bridge.shutdown()
        bridge.server_close()


def test_bridge_cannot_reach_the_udp_version(tmp_path):
    # Only the UDP server runs on this port: the bridge speaks TCP only, so the browser is refused.
    udp = UdpServer("127.0.0.1", 0)
    port = udp.start()
    threading.Thread(target=udp.serve_forever, daemon=True).start()
    bridge = make_server("127.0.0.1", 0, "127.0.0.1", port, tmp_path)
    threading.Thread(target=bridge.serve_forever, daemon=True).start()
    try:
        s = socket.create_connection(("127.0.0.1", bridge.server_address[1]), timeout=3)
        s.sendall(b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
        assert s.recv(64).startswith(b"HTTP/1.1 502")
    finally:
        bridge.shutdown()
        bridge.server_close()
        udp.stop()
