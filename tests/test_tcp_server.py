"""TCP server integration tests: real sockets on 127.0.0.1, server in a thread."""

import socket
import threading
import time

import pytest

from common.protocol import (
    CREATE_ROOM, GAME_OVER, GAME_START, INPUT, JOIN_ROOM, LIST_ROOMS, LOGIN,
    LOGIN_FAIL, LOGIN_OK, PING, PLAYER_LEFT, PONG, READY, ROOM_LIST,
    ROOM_UPDATE, STATE, TcpStreamBuffer, encode_tcp, make_msg,
)
from tcp.server import Server


def start_server(**kwargs):
    srv = Server("127.0.0.1", 0, game_ticks=30, **kwargs)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def server():
    srv = start_server()            # default 5 s heartbeat: raw clients here don't PING
    yield srv
    srv.stop()


@pytest.fixture
def fast_heartbeat_server():
    srv = start_server(heartbeat_timeout=1.0)
    yield srv
    srv.stop()


class RawClient:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.buf = TcpStreamBuffer()
        self.received = []

    def send(self, msg):
        self.sock.sendall(encode_tcp(msg))

    def wait_for(self, msg_type, timeout=3.0):
        """Return the first unseen message of this type, keeping everything in .received."""
        deadline = time.monotonic() + timeout
        for i, m in enumerate(self.received):
            if m["type"] == msg_type:
                return self.received.pop(i)
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.01, deadline - time.monotonic()))
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                break
            if not data:
                raise ConnectionError("server closed the connection")
            self.received.extend(self.buf.feed(data))   # keep every message of this recv()
            for i, m in enumerate(self.received):
                if m["type"] == msg_type:
                    return self.received.pop(i)
        raise AssertionError(f"no {msg_type} within {timeout}s; got {[m['type'] for m in self.received]}")

    def login(self, name):
        self.send(make_msg(LOGIN, name=name))
        assert self.wait_for(LOGIN_OK)["name"] == name
        return self

    def close(self):
        self.sock.close()


def join_and_ready(clients, room="r1"):
    clients[0].send(make_msg(CREATE_ROOM, room=room))
    for c in clients:
        c.send(make_msg(JOIN_ROOM, room=room))
        c.wait_for(ROOM_UPDATE)
    for c in clients:
        c.send(make_msg(READY, ready=True))
    for c in clients:
        start = c.wait_for(GAME_START)
    return start


def test_login_and_duplicate_name(server):
    a = RawClient(server.port).login("alice")
    b = RawClient(server.port)
    b.send(make_msg(LOGIN, name="alice"))
    assert b.wait_for(LOGIN_FAIL)["reason"] == "name already taken"
    b.login("bob")                                   # same connection can retry
    a.close(), b.close()


def test_message_split_across_two_sends(server):
    c = RawClient(server.port)
    data = encode_tcp(make_msg(PING, t=42.5))
    c.sock.sendall(data[:5])
    time.sleep(0.2)                                  # forces two separate recv() on the server
    c.sock.sendall(data[5:])
    assert c.wait_for(PONG)["t"] == 42.5
    c.close()


def test_three_messages_in_one_send(server):
    c = RawClient(server.port)
    c.sock.sendall(encode_tcp(make_msg(LOGIN, name="zed"))
                   + encode_tcp(make_msg(LIST_ROOMS))
                   + encode_tcp(make_msg(PING, t=1)))
    c.wait_for(LOGIN_OK)
    c.wait_for(ROOM_LIST)
    c.wait_for(PONG)
    c.close()


def test_garbage_line_does_not_kill_connection(server):
    c = RawClient(server.port)
    c.sock.sendall(b"this is not json\n")
    c.login("ok")
    c.close()


def test_full_game_ticks_and_game_over(server):
    a, b = RawClient(server.port).login("a"), RawClient(server.port).login("b")
    start = join_and_ready([a, b])
    assert start["players"] == ["a", "b"] and len(start["maze"]) == 15
    a.send(make_msg(INPUT, dir="RIGHT"))
    ticks = [a.wait_for(STATE)["tick"] for _ in range(10)]
    assert ticks == list(range(ticks[0], ticks[0] + 10))   # TCP: no gaps, in order
    over = a.wait_for(GAME_OVER, timeout=5)
    assert {r["name"] for r in over["ranking"]} == {"a", "b"}
    b.wait_for(GAME_OVER, timeout=5)
    update = a.wait_for(ROOM_UPDATE)                 # back in the room, not ready
    assert all(not p["ready"] for p in update["players"])
    a.close(), b.close()


def test_disconnect_mid_game_others_continue(server):
    a, b, c = (RawClient(server.port).login(n) for n in ("a", "b", "c"))
    join_and_ready([a, b, c])
    a.wait_for(STATE)
    c.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    c.close()                                        # abrupt close
    assert a.wait_for(PLAYER_LEFT)["name"] == "c"
    assert b.wait_for(PLAYER_LEFT)["name"] == "c"
    a.received.clear()
    state = a.wait_for(STATE)
    assert set(state["positions"]) == {"a", "b"}     # game goes on without c
    d = RawClient(server.port).login("c")            # name is free again
    for x in (a, b, d):
        x.close()


def test_last_player_wins_when_other_leaves(server):
    a, b = RawClient(server.port).login("a"), RawClient(server.port).login("b")
    join_and_ready([a, b])
    first = a.wait_for(STATE)
    b.close()
    a.wait_for(PLAYER_LEFT)
    over = a.wait_for(GAME_OVER)
    assert over["winner"] == "a"
    ticks = [first["tick"]] + [m["tick"] for m in a.received if m["type"] == STATE]
    assert ticks == sorted(set(ticks))               # no repeated tick before GAME_OVER
    a.close()


def test_game_starts_when_the_only_unready_player_leaves(server):
    a, b, c = (RawClient(server.port).login(n) for n in ("a", "b", "c"))
    a.send(make_msg(CREATE_ROOM, room="r1"))
    for x in (a, b, c):
        x.send(make_msg(JOIN_ROOM, room="r1"))
        x.wait_for(ROOM_UPDATE)
    a.send(make_msg(READY, ready=True))
    b.send(make_msg(READY, ready=True))
    c.close()                                        # c never got ready
    assert a.wait_for(GAME_START)["players"] == ["a", "b"]
    b.wait_for(GAME_START)
    a.close()
    b.close()


def test_heartbeat_timeout_closes_silent_client(fast_heartbeat_server):
    server = fast_heartbeat_server
    silent = RawClient(server.port).login("sleepy")
    other = RawClient(server.port).login("other")
    join_and_ready([silent, other])
    t0 = time.monotonic()
    deadline = t0 + 3
    while time.monotonic() < deadline:             # keep 'other' alive, 'sleepy' says nothing
        other.send(make_msg(PING, t=0))
        try:
            other.wait_for(PLAYER_LEFT, timeout=0.3)
            break
        except AssertionError:
            pass
    else:
        pytest.fail("silent client was never dropped")
    assert 0.9 < time.monotonic() - t0 < 2.5
    with pytest.raises((ConnectionError, OSError)):
        while True:
            silent.wait_for("NEVER", timeout=1)
    other.close()


def test_server_survives_client_flood_without_newline(server):
    c = RawClient(server.port)
    try:
        c.sock.sendall(b"x" * 70000)                 # > 64 KiB without newline
    except OSError:
        pass
    time.sleep(0.3)
    RawClient(server.port).login("still-alive").close()
