"""UDP server integration tests: real sockets on 127.0.0.1, server in a thread."""

import socket
import threading
import time

import pytest

from common.protocol import (
    CREATE_ROOM, GAME_OVER, GAME_START, INPUT, JOIN_ROOM, LOGIN, LOGIN_FAIL,
    LOGIN_OK, PLAYER_LEFT, READY, ROOM_UPDATE, STATE, make_msg,
)
from udp.client import UdpTransport
from udp.server import Server


def start_server(**kwargs):
    kwargs.setdefault("game_ticks", 30)
    srv = Server("127.0.0.1", 0, **kwargs)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def server():
    srv = start_server()
    yield srv
    srv.stop()


class Client:
    def __init__(self, port, drop=0.0):
        self.t = UdpTransport("127.0.0.1", port, drop=drop).connect()
        self.got = []
        self.t.on_message(self.got.append)

    def wait_for(self, msg_type, timeout=4.0, **match):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for i, m in enumerate(self.got):
                if m["type"] == msg_type and all(m.get(k) == v for k, v in match.items()):
                    del self.got[:i + 1]
                    return m
            self.t.poll(timeout=0.05)
        raise AssertionError(f"no {msg_type} {match} within {timeout}s; got {[m['type'] for m in self.got]}")

    def login(self, name):
        self.t.send(make_msg(LOGIN, name=name))
        self.wait_for(LOGIN_OK, name=name)
        return self


def play(clients, room="r1"):
    # Ordering is per client only: let the creator be in the room before others join.
    clients[0].t.send(make_msg(CREATE_ROOM, room=room))
    clients[0].t.send(make_msg(JOIN_ROOM, room=room))
    clients[0].wait_for(ROOM_UPDATE)
    for c in clients[1:]:
        c.t.send(make_msg(JOIN_ROOM, room=room))
    for c in clients[1:]:
        c.wait_for(ROOM_UPDATE)
    for c in clients:
        c.t.send(make_msg(READY, ready=True))
    return [c.wait_for(GAME_START, timeout=6) for c in clients]


def test_login_duplicate_and_full_game(server):
    a, b = Client(server.port).login("a"), Client(server.port).login("b")
    dup = Client(server.port)
    dup.t.send(make_msg(LOGIN, name="a"))
    assert dup.wait_for(LOGIN_FAIL)["reason"] == "name already taken"
    play([a, b])
    a.t.send(make_msg(INPUT, dir="RIGHT"))
    over = a.wait_for(GAME_OVER, timeout=6)
    assert {r["name"] for r in over["ranking"]} == {"a", "b"}
    assert a.t.states_received >= 25 and a.t.states_lost == 0
    for c in (a, b, dup):
        c.t.close()


def test_garbage_datagram_does_not_crash(server):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(b"\xff not json", ("127.0.0.1", server.port))
    s.sendto(b'{"type":"NOPE"}', ("127.0.0.1", server.port))
    s.close()
    Client(server.port).login("fine").t.close()


def test_silent_client_times_out_and_others_get_player_left():
    srv = start_server(game_ticks=300, heartbeat_timeout=2.0)   # > 1 s PING interval
    try:
        a, b, c = (Client(srv.port).login(n) for n in "abc")
        play([a, b, c])
        c.t._closed.set()                      # freeze c's threads: no more datagrams
        c.t.sock.close()
        t0 = time.monotonic()
        assert a.wait_for(PLAYER_LEFT, timeout=4)["name"] == "c"
        assert 1.9 < time.monotonic() - t0 < 3.0
        a.got.clear()
        state = a.wait_for(STATE)
        assert set(state["positions"]) == {"a", "b"}
        Client(srv.port).login("c").t.close()  # name is free again
        a.t.close(), b.t.close()
    finally:
        srv.stop()


def test_lobby_and_game_work_with_20_percent_loss_both_ways():
    srv = start_server(drop=0.2)
    try:
        clients = [Client(srv.port, drop=0.2).login(n) for n in ("a", "b", "c")]
        starts = play(clients)
        assert all(sorted(s["players"]) == ["a", "b", "c"] for s in starts)   # join order may vary
        for c in clients:
            c.t.send(make_msg(INPUT, dir="DOWN"))
        overs = [c.wait_for(GAME_OVER, timeout=8) for c in clients]
        assert len({tuple(o["winner"] for o in overs)}) == 1
        assert sum(c.t.states_lost for c in clients) > 0        # loss is visible...
        assert srv.stats()["retransmissions"] > 0                # ...and repaired
        for c in clients:
            c.t.close()
    finally:
        srv.stop()


def test_late_state_is_counted_late_not_lost():
    from common.protocol import STATE
    from udp.client import UdpTransport
    t = UdpTransport("127.0.0.1", 9)                 # no socket needed for _accept
    for tick in [1, 2, 5, 3, 4, 6, 9, 8]:
        t._accept(make_msg(STATE, tick=tick))
    assert t.states_received == 5                    # 1, 2, 5, 6, 9 shown
    assert t.states_late == 3                        # 3, 4, 8 came after a newer one
    assert t.states_lost == 1                        # only 7 never arrived


def test_three_clients_from_the_same_ip():
    """Through the playit.gg agent (or any NAT) all players may arrive from one IP: the server
    must key sessions by the full (ip, port), and never dedupe or refuse by IP alone."""
    srv = start_server(game_ticks=300, heartbeat_timeout=2.0)
    try:
        a, b, c = (Client(srv.port) for _ in range(3))
        addrs = [x.t.sock.getsockname() for x in (a, b, c)]
        assert {ip for ip, _ in addrs} == {"127.0.0.1"} and len(set(addrs)) == 3
        for x, name in zip((a, b, c), ("alice", "bob", "carol")):
            x.login(name)
        assert {s.addr for s in srv.sessions.values()} == set(addrs)
        assert {s.name for s in srv.sessions.values()} == {"alice", "bob", "carol"}
        dup = Client(srv.port)                         # same IP, 4th port: refused by NAME only
        dup.t.send(make_msg(LOGIN, name="bob"))
        assert dup.wait_for(LOGIN_FAIL)["reason"] == "name already taken"
        dup.t.close()

        starts = play([a, b, c])
        assert all(s["players"] == ["alice", "bob", "carol"] for s in starts)
        c.t._closed.set()                              # carol goes silent; same IP as the others
        c.t.sock.close()
        assert a.wait_for(PLAYER_LEFT, timeout=4)["name"] == "carol"
        assert b.wait_for(PLAYER_LEFT, timeout=4)["name"] == "carol"
        a.got.clear()
        assert set(a.wait_for(STATE)["positions"]) == {"alice", "bob"}
        again = Client(srv.port).login("carol")        # from 127.0.0.1 again, new port
        for x in (a, b, again):
            x.t.close()
    finally:
        srv.stop()


def test_host_name_is_resolved_once(server):
    t = UdpTransport("localhost", server.port).connect()
    try:
        assert t.server_ip == "127.0.0.1"              # IPv4 even if localhost also has ::1
        assert t.sock.getpeername() == ("127.0.0.1", server.port)
    finally:
        t.close()
    with pytest.raises(socket.gaierror):
        UdpTransport("no-such-host.invalid", server.port).connect()


def test_big_datagram_is_warned_once_per_type(server, caplog):
    from common.protocol import UDP_WARN_SIZE, encode_udp
    sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink.bind(("127.0.0.1", 0))
    big = encode_udp(make_msg(STATE, tick=1, pad="x" * UDP_WARN_SIZE))
    with caplog.at_level("WARNING", logger="udp.server"):
        for _ in range(3):
            server._send_raw(big, sink.getsockname())
        server._send_raw(encode_udp(make_msg(STATE, tick=2)), sink.getsockname())
    warnings = [r.getMessage() for r in caplog.records if "datagram is" in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].startswith(f"STATE datagram is {len(big)} bytes")
    sink.close()
