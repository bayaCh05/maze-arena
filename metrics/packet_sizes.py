"""Real on-the-wire size of every message type, in a 3-player game with max-length names.

    python metrics/packet_sizes.py                 # ASCII names (12 chars)
    python metrics/packet_sizes.py --unicode-names # worst case: JSON escapes each é as \\u00e9

Runs the real UDP and TCP servers in this process and three raw clients that log in,
create/join a room, get ready and move at random. Every datagram (UDP: JSON + seq/ack/rel)
and every TCP line (JSON + "\\n") is measured as it arrives or leaves, and labelled with
the game phase: lobby, start (first STATE), middle (tick = max/2), end (last STATE, GAME_OVER).
Writes metrics/packet_sizes.csv and prints a table; warns for UDP datagrams over 1200 bytes.
"""

import argparse
import csv
import random
import select
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.protocol import (  # noqa: E402
    ACK, CREATE_ROOM, GAME_OVER, GAME_START, INPUT, JOIN_ROOM, LIST_ROOMS, LOGIN, PING,
    READY, STATE, UDP_WARN_SIZE, TcpStreamBuffer, decode, decode_udp, encode_tcp, make_msg,
)
from udp.reliability import ReliableEndpoint  # noqa: E402

OUT = ROOT / "metrics" / "packet_sizes.csv"
ASCII_NAMES = ["alice_123456", "bob_12345678", "carol_123456"]
UNICODE_NAMES = ["é" * 12, "ü" * 12, "ñ" * 12]
GAME_TICKS = 60


class Recorder:
    def __init__(self):
        self.rows = []            # (proto, direction, type, phase, bytes)
        self.lock = threading.Lock()
        self.phase = "lobby"

    def add(self, proto, direction, msg_type, size, phase=None):
        with self.lock:
            self.rows.append((proto, direction, msg_type, phase or self.phase, size))


def state_phase(tick, max_ticks):
    if tick <= 1:
        return "start"
    if tick == max_ticks // 2:
        return "middle"
    if tick >= max_ticks:
        return "end"
    return None


def run_udp(names, rec):
    from udp.server import Server
    srv = Server("127.0.0.1", 0, game_ticks=GAME_TICKS)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    clients = []
    for name in names:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("127.0.0.1", srv.port))

        def send_raw(data, _addr, sock=sock):
            rec.add("udp", "client->server", decode(data)["type"], len(data))
            sock.send(data)
        clients.append((name, sock, ReliableEndpoint(send_raw)))
    try:
        play(clients, rec, "udp", lambda c, msg: c[2].send(None, msg), recv_udp)
    finally:
        srv.stop()


def recv_udp(c, rec):
    """One datagram from a readable socket (ACKed by the endpoint, like the real client)."""
    _name, sock, ep = c
    data = sock.recv(65535)
    msg, _meta = decode_udp(data)
    rec.add("udp", "server->client", msg["type"], len(data), phase_of(msg, rec))
    return [m for m in ep.receive(data, None) if m["type"] != ACK]


def run_tcp(names, rec):
    from tcp.server import Server
    srv = Server("127.0.0.1", 0, game_ticks=GAME_TICKS)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    clients = [(name, socket.create_connection(("127.0.0.1", srv.port)), TcpStreamBuffer()) for name in names]

    def send(c, msg):
        data = encode_tcp(msg)
        rec.add("tcp", "client->server", msg["type"], len(data))
        c[1].sendall(data)
    try:
        play(clients, rec, "tcp", send, recv_tcp)
    finally:
        srv.stop()


def recv_tcp(c, rec):
    """Whatever a readable socket has; one TCP read may hold several lines."""
    _name, sock, buf = c
    out = buf.feed(sock.recv(65535))
    for msg in out:
        size = len(encode_tcp(msg))              # compact JSON + "\n": what the server wrote
        rec.add("tcp", "server->client", msg["type"], size, phase_of(msg, rec))
    return out


def phase_of(msg, rec):
    if msg["type"] == STATE:
        return state_phase(msg["tick"], GAME_TICKS) or "game"
    if msg["type"] == GAME_START:
        return "start"
    if msg["type"] == GAME_OVER:
        return "end"
    return None


def play(clients, rec, proto, send, recv):
    by_sock = {c[1]: c for c in clients}

    def pump(seconds=0.3):
        """Read all three sockets fairly (select) for this long."""
        until = time.monotonic() + seconds
        got = []
        while (left := until - time.monotonic()) > 0:
            readable, _, _ = select.select(list(by_sock), [], [], min(left, 0.02))
            for sock in readable:
                c = by_sock[sock]
                got += [(c, m) for m in recv(c, rec)]
            if proto == "udp":
                for c in clients:
                    c[2].tick()                  # retransmit our own reliable messages
        return got

    for c in clients:
        send(c, make_msg(LOGIN, name=c[0]))
        send(c, make_msg(PING, t=time.time()))
    pump()
    send(clients[0], make_msg(CREATE_ROOM, room="r" * 12))
    pump()
    for c in clients:
        send(c, make_msg(JOIN_ROOM, room="r" * 12))
        pump(0.15)
    send(clients[0], make_msg(LIST_ROOMS))
    for c in clients:
        send(c, make_msg(READY, ready=True))
    rec.phase = "game"
    rng = random.Random(1)
    deadline = time.monotonic() + GAME_TICKS / 10 + 5
    over = 0
    while over < len(clients) and time.monotonic() < deadline:
        for c in clients:
            send(c, make_msg(INPUT, dir=rng.choice(["UP", "DOWN", "LEFT", "RIGHT"])))
        over += sum(1 for _c, m in pump(0.1) if m["type"] == GAME_OVER)
    rec.phase = "after"
    pump(0.3)


def summarize(rows):
    """max bytes per (proto, direction, type, phase)."""
    out = {}
    for proto, direction, mtype, phase, size in rows:
        key = (proto, direction, mtype, phase)
        out[key] = max(out.get(key, 0), size)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unicode-names", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    names = UNICODE_NAMES if args.unicode_names else ASCII_NAMES

    rec = Recorder()
    run_udp(names, rec)
    rec.phase = "lobby"
    run_tcp(names, rec)

    table = summarize(rec.rows)
    order = ["lobby", "start", "game", "middle", "end", "after"]
    keys = sorted(table, key=lambda k: (k[0], k[1], k[2], order.index(k[3]) if k[3] in order else 9))
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["proto", "direction", "type", "phase", "max_bytes", "names"])
        for k in keys:
            w.writerow([*k, table[k], "unicode" if args.unicode_names else "ascii"])
    print(f"names: {names}\n")
    print(f"{'proto':5} {'direction':15} {'type':12} {'phase':7} {'max bytes':>9}")
    for k in keys:
        if k[2] == ACK:
            continue
        flag = "  <-- over %d" % UDP_WARN_SIZE if k[0] == "udp" and table[k] > UDP_WARN_SIZE else ""
        print(f"{k[0]:5} {k[1]:15} {k[2]:12} {k[3]:7} {table[k]:9}{flag}")
    big = [k for k in keys if k[0] == "udp" and table[k] > UDP_WARN_SIZE]
    print(f"\nwrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
    if big:
        print(f"WARNING: {len(big)} UDP message kind(s) over {UDP_WARN_SIZE} bytes:",
              ", ".join(f"{k[2]} ({k[3]}) {table[k]} B" for k in big))
    return 1 if big else 0


if __name__ == "__main__":
    sys.exit(main())
