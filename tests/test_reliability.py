"""udp/reliability.py on its own: fake network first, then a real UDP echo."""

import random
import socket
import threading
import time

from common.protocol import (
    ACK, INPUT, JOIN_ROOM, LOGIN, READY, STATE, decode_udp, encode_udp, make_msg,
)
from udp.reliability import GAP_TIMEOUT, MAX_RETRIES, ReliableEndpoint

A, B = ("10.0.0.1", 1111), ("10.0.0.2", 2222)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Link:
    """Two endpoints wired together in memory. Datagrams wait in .wire until flush()."""

    def __init__(self, drop=0.0, seed=1):
        self.clock = FakeClock()
        self.wire = []                      # (dst_addr, data)
        rng = random.Random(seed)
        self.a = ReliableEndpoint(lambda d, to: self.wire.append((A, d)), drop, rng=rng, clock=self.clock)
        self.b = ReliableEndpoint(lambda d, to: self.wire.append((B, d)), drop, rng=rng, clock=self.clock)
        self.got = {A: [], B: []}           # (who received, msg)

    def flush(self, reorder=False):
        while self.wire:
            batch, self.wire = self.wire, []
            if reorder:
                batch.reverse()
            for sender, data in batch:
                dst, src = (self.b, B) if sender == A else (self.a, A)
                self.got[src].extend(dst.receive(data, sender))

    def run(self, seconds, step=0.05):
        for _ in range(int(seconds / step)):
            self.clock.now += step
            for ep, me in ((self.a, A), (self.b, B)):
                self.got[me].extend(m for _, m in ep.tick())
            self.flush()


def test_reliable_message_is_acked_and_not_resent():
    link = Link()
    link.a.send(B, make_msg(LOGIN, name="x"))
    link.flush()
    assert link.got[B] == [{"type": "LOGIN", "name": "x"}]
    assert link.a.pending_count() == 0
    link.run(2)
    assert link.a.stats.retransmissions == 0


def test_unreliable_message_has_no_seq_and_no_ack():
    link = Link()
    link.a.send(B, make_msg(STATE, tick=1))
    assert link.wire[0][1] == b'{"type":"STATE","tick":1}'
    link.flush()
    assert link.got[B] == [{"type": "STATE", "tick": 1}]
    assert link.b.stats.sent == 0                     # no ACK for unreliable


def test_lost_message_is_retransmitted_after_rto():
    link = Link()
    link.a.send(B, make_msg(JOIN_ROOM, room="r"))
    link.wire.clear()                                 # first copy lost
    link.clock.now = 0.1
    link.a.tick()
    assert link.wire == []                            # not yet: RTO is 200 ms
    link.clock.now = 0.25
    link.a.tick()
    assert len(link.wire) == 1 and link.a.stats.retransmissions == 1
    link.flush()
    assert link.got[B] == [{"type": "JOIN_ROOM", "room": "r"}]


def test_duplicate_is_dropped_but_acked_again():
    link = Link()
    link.a.send(B, make_msg(JOIN_ROOM, room="r"))
    copy = link.wire[0][1]
    link.flush()
    link.b.receive(copy, A)                           # retransmission arrives late
    assert link.got[B] == [{"type": "JOIN_ROOM", "room": "r"}]   # joined once
    assert link.b.stats.duplicates == 1
    assert decode_udp(link.wire[-1][1])[0]["type"] == ACK         # ...but re-ACKed


def test_retransmitted_join_when_ack_lost_joins_once():
    link = Link()
    link.a.send(B, make_msg(JOIN_ROOM, room="r"))
    link.flush()                                      # B got it, B's ACK delivered...
    link.a.peers[B].pending[1] = [encode_udp(make_msg(JOIN_ROOM, room="r"), seq=1, rel=True), JOIN_ROOM, 0, 0]
    link.run(1)                                       # ...pretend the ACK was lost: A resends
    assert link.a.stats.retransmissions == 1
    assert link.got[B] == [{"type": "JOIN_ROOM", "room": "r"}]
    assert link.a.pending_count() == 0


def test_gives_up_after_max_retries():
    gave = []
    link = Link()
    link.a.on_give_up = lambda *args: gave.append(args)
    link.a.send(B, make_msg(READY))
    for _ in range(MAX_RETRIES + 5):
        link.wire.clear()                             # everything lost
        link.clock.now += 0.25
        link.a.tick()
    assert link.a.stats.retransmissions == MAX_RETRIES
    assert link.a.stats.gave_up == 1
    assert gave == [(B, READY, 1)]


def test_in_order_delivery_when_datagrams_swap():
    link = Link()
    link.a.send(B, make_msg(LOGIN, name="x"))
    link.a.send(B, make_msg(JOIN_ROOM, room="r"))
    link.a.send(B, make_msg(READY))
    link.flush(reorder=True)                          # arrive READY, JOIN, LOGIN
    assert [m["type"] for m in link.got[B]] == [LOGIN, JOIN_ROOM, READY]
    assert link.b.stats.out_of_order == 2


def test_gap_is_skipped_if_never_filled():
    link = Link()
    link.a.send(B, make_msg(LOGIN, name="x"))
    link.wire.clear()
    link.a.peers[B].pending.clear()                   # sender gave up on seq 1
    link.a.send(B, make_msg(READY))
    link.flush()
    assert link.got[B] == []                          # held, waiting for seq 1
    link.run(GAP_TIMEOUT + 0.5)
    assert link.got[B] == [{"type": "READY"}]
    assert link.b.stats.gaps_skipped == 1


def test_everything_arrives_exactly_once_in_order_under_30_percent_loss():
    link = Link(drop=0.3, seed=7)
    for i in range(200):
        link.a.send(B, make_msg(READY, i=i))
        link.flush()
    link.run(5)
    assert [m["i"] for m in link.got[B]] == list(range(200))
    assert link.a.stats.retransmissions > 50
    # Round trip succeeds 0.7*0.7 = 49%: P(16 tries all fail) = 0.51**16 = 0.002%.
    assert link.a.stats.gave_up == 0


def test_peer_restart_is_detected_and_numbering_starts_over():
    link = Link()
    for _ in range(3):
        link.a.send(B, make_msg(READY))
    link.flush()
    link.run(GAP_TIMEOUT + 1)
    link.a.forget(B)                                  # A forgets B (e.g. timed it out)
    link.a.send(B, make_msg(JOIN_ROOM, room="again"))  # A's seq starts at 1 again
    link.flush()
    assert link.got[B][-1] == {"type": "JOIN_ROOM", "room": "again"}
    assert link.b.stats.peer_resets == 1
    link.b.send(A, make_msg(READY))                   # B also restarted at 1 towards A
    link.flush()
    assert link.got[A][-1] == {"type": "READY"}


def test_early_seq1_retransmission_is_still_a_duplicate():
    link = Link()
    link.a.send(B, make_msg(LOGIN, name="x"))
    copy = link.wire[0][1]
    link.a.send(B, make_msg(READY))
    link.flush()
    link.b.receive(copy, A)                           # late copy within the retry window
    assert [m["type"] for m in link.got[B]] == [LOGIN, READY]
    assert link.b.stats.peer_resets == 0


def test_forged_huge_seq_cannot_poison_the_channel():
    link = Link()
    link.b.receive(encode_udp(make_msg(READY), seq=999_999_999, rel=True), A)
    link.run(GAP_TIMEOUT + 1)                         # a gap skip must not jump to it
    link.a.send(B, make_msg(LOGIN, name="real"))
    link.flush()
    assert link.got[B] == [{"type": "LOGIN", "name": "real"}]
    assert link.b.stats.out_of_window == 1


def test_drop_only_affects_outgoing():
    link = Link(drop=1.0)
    link.a.send(B, make_msg(INPUT, dir="UP"))
    assert link.wire == [] and link.a.stats.dropped == 1


def test_real_udp_echo_with_loss():
    """Small echo test over loopback: echo server returns every reliable message."""
    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv_sock.bind(("127.0.0.1", 0))
    srv_sock.settimeout(0.05)
    cli_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cli_sock.bind(("127.0.0.1", 0))
    cli_sock.settimeout(0.05)
    srv_addr = srv_sock.getsockname()
    srv = ReliableEndpoint(lambda d, to: srv_sock.sendto(d, to), drop=0.3, rng=random.Random(3))
    cli = ReliableEndpoint(lambda d, to: cli_sock.sendto(d, to), drop=0.3, rng=random.Random(4))
    stop = threading.Event()

    def echo_server():
        while not stop.is_set():
            srv.tick()
            try:
                data, addr = srv_sock.recvfrom(65535)
            except socket.timeout:
                continue
            for msg in srv.receive(data, addr):
                srv.send(addr, msg)

    echo = threading.Thread(target=echo_server, daemon=True)
    echo.start()
    echoed = []
    for i in range(30):
        cli.send(srv_addr, make_msg(JOIN_ROOM, room=f"r{i}"))
    deadline = time.monotonic() + 10
    while len(echoed) < 30 and time.monotonic() < deadline:
        cli.tick()
        try:
            data, addr = cli_sock.recvfrom(65535)
        except socket.timeout:
            continue
        echoed += cli.receive(data, addr)
    stop.set()
    echo.join(1)
    srv_sock.close(), cli_sock.close()
    assert [m["room"] for m in echoed] == [f"r{i}" for i in range(30)]
    assert cli.stats.retransmissions > 0 and srv.stats.retransmissions > 0
