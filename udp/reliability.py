"""Seq/ack tracking, retransmission of reliable messages, duplicate filtering.

Two channels share one UDP socket:

  reliable    LOGIN, JOIN_ROOM, GAME_START, ... (protocol.RELIABLE_TYPES)
              Carries `seq` (1, 2, 3, ... per sender and peer) and `rel: true`.
              The receiver answers every copy with {"type": "ACK", "ack": seq}.
              The sender retransmits every RTO until ACKed, at most MAX_RETRIES
              times. The receiver delivers IN ORDER: it knows the next seq it
              expects, so anything below it is a duplicate (dropped, re-ACKed:
              a retransmitted JOIN never joins twice), and anything above it is
              held until the gap is filled. A gap not filled within GAP_TIMEOUT
              (the sender gave up) is skipped so the channel never stalls.
              A new seq 1 long after the first one means the peer forgot us
              (e.g. the server timed us out) and restarted: both directions
              start over at 1.

  unreliable  STATE, INPUT, PING/PONG, HEARTBEAT, ACK. No transport fields,
              sent once, may be lost. STATE/INPUT are re-sent every tick anyway.

No sockets here: the owner passes send_raw(data, addr) and feeds received
datagrams to receive(), and calls tick() every ~50 ms for retransmissions.
`drop` simulates loss by discarding that fraction of OUTGOING datagrams.
"""

import random
import threading
import time

from common.protocol import ACK, RELIABLE_TYPES, decode_udp, encode_udp, make_msg

RTO = 0.2              # retransmission timeout (s)
MAX_RETRIES = 5        # retransmissions after the first send
GAP_TIMEOUT = 2.0      # > RTO * (MAX_RETRIES + 1): the sender has surely given up
MAX_HELD = 256         # out-of-order reliable messages kept per peer


class Stats:
    def __init__(self):
        self.sent = 0               # datagrams handed to the network (incl. dropped)
        self.dropped = 0            # discarded by --drop
        self.send_errors = 0
        self.reliable_sent = 0      # reliable messages (first transmission)
        self.retransmissions = 0
        self.acked = 0
        self.gave_up = 0            # reliable messages never ACKed
        self.duplicates = 0         # reliable copies received again (re-ACKed, dropped)
        self.out_of_order = 0       # reliable messages that arrived before an earlier one
        self.gaps_skipped = 0       # reliable seqs never received
        self.peer_resets = 0        # peer restarted its numbering
        self.out_of_window = 0      # seq absurdly far ahead: ignored

    def as_dict(self):
        return dict(vars(self))


class _Peer:
    def __init__(self, now):
        self.created = now
        self.next_seq = 1
        self.pending = {}           # seq -> [data, type, last_sent, retries]
        self.expected = 1           # next reliable seq to deliver
        self.held = {}              # seq -> msg, arrived early
        self.hole_since = None


class ReliableEndpoint:
    def __init__(self, send_raw, drop=0.0, rto=RTO, max_retries=MAX_RETRIES,
                 gap_timeout=GAP_TIMEOUT, on_retransmit=None, on_give_up=None,
                 rng=None, clock=time.monotonic):
        self.send_raw = send_raw
        self.drop = drop
        self.rto, self.max_retries, self.gap_timeout = rto, max_retries, gap_timeout
        self.on_retransmit = on_retransmit      # (addr, type, seq, attempt)
        self.on_give_up = on_give_up            # (addr, type, seq)
        self.rng = rng or random.Random()
        self.clock = clock
        self.stats = Stats()
        self.peers = {}
        self.lock = threading.Lock()

    def _peer(self, addr):
        peer = self.peers.get(addr)
        if peer is None:
            peer = self.peers[addr] = _Peer(self.clock())
        return peer

    def forget(self, addr):
        """Drop all state for a peer (after it disconnected)."""
        with self.lock:
            self.peers.pop(addr, None)

    def pending_count(self, addr=None):
        with self.lock:
            peers = [self.peers.get(addr)] if addr else list(self.peers.values())
            return sum(len(p.pending) for p in peers if p)

    # ------------------------------------------------------------ sending

    def send(self, addr, msg, reliable=None):
        """Send one message; reliable defaults to the type's delivery class."""
        if reliable is None:
            reliable = msg["type"] in RELIABLE_TYPES
        with self.lock:
            if reliable:
                peer = self._peer(addr)
                seq = peer.next_seq
                peer.next_seq += 1
                data = encode_udp(msg, seq=seq, rel=True)
                peer.pending[seq] = [data, msg["type"], self.clock(), 0]
                self.stats.reliable_sent += 1
            else:
                data = encode_udp(msg)
            self._transmit(addr, data)

    def _transmit(self, addr, data):
        self.stats.sent += 1
        if self.drop and self.rng.random() < self.drop:
            self.stats.dropped += 1
            return
        try:
            self.send_raw(data, addr)
        except OSError:
            self.stats.send_errors += 1

    # ------------------------------------------------------------ receiving

    def receive(self, data, addr):
        """Process one datagram; returns the messages now deliverable (0..n).

        Raises ProtocolError for garbage (caller logs and ignores it).
        """
        msg, meta = decode_udp(data)
        with self.lock:
            if msg["type"] == ACK:
                peer = self.peers.get(addr)
                if peer is not None and peer.pending.pop(meta.ack, None) is not None:
                    self.stats.acked += 1
                return []
            if not meta.rel or meta.seq is None:
                return [msg]

            self._transmit(addr, encode_udp(make_msg(ACK), ack=meta.seq))   # ACK every copy
            peer = self._peer(addr)
            seq = meta.seq
            if seq == 1 and peer.expected > 1 and self.clock() - peer.created > self.gap_timeout:
                # A seq-1 retransmission can't be this late: the peer restarted.
                self.stats.peer_resets += 1
                peer = self.peers[addr] = _Peer(self.clock())
            if seq < peer.expected or seq in peer.held:
                self.stats.duplicates += 1
                return []
            if seq >= peer.expected + MAX_HELD:
                # Far ahead of anything we could be missing: forged or corrupt.
                # Holding it would later make us skip to it and drop real messages.
                self.stats.out_of_window += 1
                return []
            peer.held[seq] = msg
            if seq != peer.expected:
                self.stats.out_of_order += 1
            return self._release(peer)

    def _release(self, peer):
        out = []
        while peer.expected in peer.held:
            out.append(peer.held.pop(peer.expected))
            peer.expected += 1
        peer.hole_since = (peer.hole_since or self.clock()) if peer.held else None
        return out

    # ------------------------------------------------------------ timer

    def tick(self):
        """Retransmit overdue messages, skip dead gaps.

        Returns [(addr, msg)] released by skipping a gap (deliver them).
        """
        released, retx, gave_up = [], [], []
        with self.lock:
            now = self.clock()
            for addr, peer in self.peers.items():
                for seq, entry in list(peer.pending.items()):
                    data, mtype, last_sent, retries = entry
                    if now - last_sent < self.rto:
                        continue
                    if retries >= self.max_retries:
                        del peer.pending[seq]
                        self.stats.gave_up += 1
                        gave_up.append((addr, mtype, seq))
                        continue
                    entry[2], entry[3] = now, retries + 1
                    self.stats.retransmissions += 1
                    retx.append((addr, mtype, seq, retries + 1))
                    self._transmit(addr, data)
                if peer.held and now - peer.hole_since > self.gap_timeout:
                    first = min(peer.held)
                    self.stats.gaps_skipped += first - peer.expected
                    peer.expected = first
                    peer.hole_since = None
                    released += [(addr, m) for m in self._release(peer)]
        for args in retx:
            if self.on_retransmit:
                self.on_retransmit(*args)
        for args in gave_up:
            if self.on_give_up:
                self.on_give_up(*args)
        return released
