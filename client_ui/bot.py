"""Headless bot client (no pygame) for tests and rehearsals.

    python -m client_ui.bot --proto tcp --host 127.0.0.1 --port 5050 --name bot1 --room arena --players 3

Logs in, creates/joins the room, sends READY once `--players` are in the
room, then wanders the maze (straight ahead, random turns) until GAME_OVER.
Uses only the Transport interface. Exit code 0 = saw GAME_OVER, 1 = disconnected.
"""

import argparse
import csv
import logging
import random
import sys
import time

from client_ui.connect import make_transport
from common.protocol import (
    CREATE_ROOM, GAME_OVER, GAME_START, INPUT, JOIN_ROOM, LOGIN, LOGIN_FAIL,
    LOGIN_OK, PLAYER_LEFT, READY, ROOM_LIST, ROOM_UPDATE, STATE, make_msg,
)

STEP = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def write_metrics(path, proto, name, transport):
    """Long-format CSV (network-metrics skill): ts,proto,role,node,metric,value,extra."""
    offset = time.time() - time.monotonic()           # monotonic arrival -> wall clock
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "proto", "role", "node", "metric", "value", "extra"])
        row = lambda ts, metric, value, extra="": w.writerow(
            [f"{ts:.3f}", proto, "client", name, metric, f"{value:.3f}" if isinstance(value, float) else value, extra])
        for ts, rtt in transport.rtt_log:
            row(ts, "rtt", rtt)
        prev = None
        for t, tick in transport.state_arrivals:
            if prev is not None:
                row(t + offset, "inter_update", (t - prev[0]) * 1000, tick)
                row(t + offset, "tick_gap", tick - prev[1] - 1, tick)
            prev = (t, tick)
        stats = getattr(transport, "stats", {})
        for key in ("states_received", "states_lost", "states_late", "retransmissions",
                    "gave_up", "duplicates", "dropped", "sent"):
            if key in stats:
                row(time.time(), f"total_{key}", stats[key])


class Bot:
    def __init__(self, transport, name, room, players):
        self.t, self.name, self.room, self.players = transport, name, room, players
        self.log = logging.getLogger(name)
        self.walls = set()
        self.dir = "NONE"
        self.ready_sent = False
        self.in_room = False
        self.done = False
        self.last_tick = 0
        self.gaps = 0                       # missed ticks (should stay 0 on TCP)
        self.t.on_message(self.on_message)
        self.t.send(make_msg(LOGIN, name=name))

    def join(self):
        self.t.send(make_msg(CREATE_ROOM, room=self.room))
        self.t.send(make_msg(JOIN_ROOM, room=self.room))

    def on_message(self, msg):
        t = msg["type"]
        if t == LOGIN_OK:
            self.log.info("logged in")
            self.join()
        elif t == LOGIN_FAIL and msg.get("reason") == "not logged in":
            self.log.warning("server forgot us (timed out); logging in again")
            self.ready_sent = self.in_room = False
            self.t.send(make_msg(LOGIN, name=self.name))
        elif t == LOGIN_FAIL:
            self.log.error("login refused: %s", msg.get("reason"))
            self.t.close()
        elif t == ROOM_LIST and msg.get("error") and msg["error"] != "room already exists":
            self.log.warning("lobby error: %s (retrying)", msg["error"])
            time.sleep(0.5)
            if not self.in_room:
                self.join()
        elif t == ROOM_UPDATE:
            self.in_room = True
            names = [p["name"] for p in msg["players"]]
            self.log.info("room %s: %s", msg["room"], msg["players"])
            if len(names) >= self.players and not self.ready_sent:
                self.ready_sent = True
                self.t.send(make_msg(READY, ready=True))
        elif t == GAME_START:
            self.walls = {(x, y) for y, row in enumerate(msg["maze"]) for x, ch in enumerate(row) if ch == "#"}
            self.log.info("GAME_START players=%s", msg["players"])
        elif t == STATE:
            if self.last_tick and msg["tick"] != self.last_tick + 1:
                self.gaps += msg["tick"] - self.last_tick - 1
            self.last_tick = msg["tick"]
            if msg["tick"] % 100 == 0:
                self.log.info("tick %d scores=%s rtt=%s ms", msg["tick"], msg["scores"],
                              f"{self.t.rtt_ms:.1f}" if self.t.rtt_ms is not None else "?")
            pos = msg["positions"].get(self.name)
            if pos:
                self.steer(*pos)
        elif t == PLAYER_LEFT:
            self.log.info("PLAYER_LEFT %s", msg["name"])
        elif t == GAME_OVER:
            self.log.info("GAME_OVER winner=%s ranking=%s missed_ticks=%d",
                          msg["winner"], msg["ranking"], self.gaps)
            self.done = True

    def steer(self, x, y):
        free = [d for d, (dx, dy) in STEP.items() if (x + dx, y + dy) not in self.walls]
        blocked = self.dir not in STEP or (x + STEP[self.dir][0], y + STEP[self.dir][1]) in self.walls
        if free and (blocked or random.random() < 0.15):
            new = random.choice(free)
            if new != self.dir:
                self.dir = new
                self.t.send(make_msg(INPUT, dir=new))


def main():
    parser = argparse.ArgumentParser(description="Maze Arena bot client")
    parser.add_argument("--proto", choices=["tcp", "udp"], default="tcp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--name", required=True)
    parser.add_argument("--room", default="arena")
    parser.add_argument("--players", type=int, default=2, help="send READY once this many are in the room")
    parser.add_argument("--drop", type=float, default=0.0, help="UDP only: drop this fraction of outgoing datagrams")
    parser.add_argument("--metrics-csv", help="write RTT / STATE timing samples here at exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s.%(msecs)03d [%(name)s] %(message)s")

    try:
        transport = make_transport(args.proto, args.host, args.port, args.drop)
    except (OSError, ValueError) as exc:
        sys.exit(f"cannot connect: {exc}")
    bot = Bot(transport, args.name, args.room, args.players)
    while transport.connected and not bot.done:
        transport.poll(timeout=0.2)
    if not bot.done:
        bot.log.error("disconnected: %s", transport.close_reason)
    if hasattr(transport, "stats"):
        bot.log.info("transport stats: %s", transport.stats)
    if transport.rtt_samples:
        rtts = sorted(transport.rtt_samples)
        bot.log.info("RTT ms: n=%d median=%.2f p95=%.2f max=%.2f", len(rtts),
                     rtts[len(rtts) // 2], rtts[int(len(rtts) * 0.95)], rtts[-1])
    transport.close()
    if args.metrics_csv:
        write_metrics(args.metrics_csv, args.proto, args.name, transport)
    sys.exit(0 if bot.done else 1)


if __name__ == "__main__":
    main()
