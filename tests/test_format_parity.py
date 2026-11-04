"""TCP and UDP must deliver identical game messages (same types, same fields).

The same scripted session runs against both real servers. UDP transport
fields (seq/rel/ack, ACK) must never reach the game layer.
"""

import threading
import time

from common.protocol import (
    CREATE_ROOM, GAME_OVER, INPUT, JOIN_ROOM, LEAVE_ROOM, LIST_ROOMS, LOGIN,
    READY, make_msg,
)
from tcp.client import TcpTransport
from tcp.server import Server as TcpServer
from udp.client import UdpTransport
from udp.server import Server as UdpServer


def run_session(server_cls, transport_cls):
    srv = server_cls("127.0.0.1", 0, game_ticks=15)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    a = transport_cls("127.0.0.1", srv.port).connect()
    b = transport_cls("127.0.0.1", srv.port).connect()
    seen = {"a": [], "b": []}
    a.on_message(seen["a"].append)
    b.on_message(seen["b"].append)

    def step(t, msg, settle=0.15):
        t.send(msg)
        end = time.monotonic() + settle
        while time.monotonic() < end:
            a.poll(), b.poll()
            time.sleep(0.01)

    try:
        step(a, make_msg(LOGIN, name="a"))
        step(b, make_msg(LOGIN, name="a"))           # LOGIN_FAIL
        step(b, make_msg(LOGIN, name="b"))
        step(a, make_msg(LIST_ROOMS))
        step(a, make_msg(CREATE_ROOM, room="r"))
        step(a, make_msg(CREATE_ROOM, room="r"))     # ROOM_LIST with error
        step(a, make_msg(JOIN_ROOM, room="r"))
        step(b, make_msg(JOIN_ROOM, room="r"))
        step(a, make_msg(READY, ready=True))
        step(b, make_msg(READY, ready=True))
        step(a, make_msg(INPUT, dir="RIGHT"))
        deadline = time.monotonic() + 5
        while not any(m["type"] == GAME_OVER for m in seen["a"]) and time.monotonic() < deadline:
            a.poll(), b.poll()
            time.sleep(0.02)
        step(a, make_msg(LEAVE_ROOM), settle=0.3)    # b gets PLAYER_LEFT
    finally:
        a.close(), b.close()
        srv.stop()
    return seen


def shape(messages):
    """Per message type, the set of field names (PONG/STATE counts vary, shapes must not)."""
    out = {}
    for m in messages:
        out.setdefault(m["type"], set()).add(tuple(sorted(m)))
    return out


def lobby_sequence(messages):
    return [m["type"] for m in messages if m["type"] not in ("PONG", "STATE")]


def test_tcp_and_udp_deliver_identical_messages():
    tcp = run_session(TcpServer, TcpTransport)
    udp = run_session(UdpServer, UdpTransport)
    for who in ("a", "b"):
        assert shape(tcp[who]) == shape(udp[who]), who
        assert lobby_sequence(tcp[who]) == lobby_sequence(udp[who]), who
    for msgs in udp.values():
        for m in msgs:
            assert m["type"] != "ACK"
            assert not {"seq", "ack", "rel"} & set(m), m
    # sanity: the session really exercised the interesting messages
    types = set(lobby_sequence(tcp["a"])) | set(lobby_sequence(tcp["b"]))
    assert {"LOGIN_OK", "LOGIN_FAIL", "ROOM_LIST", "ROOM_UPDATE", "GAME_START",
            "GAME_OVER", "PLAYER_LEFT"} <= types
