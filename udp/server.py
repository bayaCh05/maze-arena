"""UDP game server (authoritative, 10 ticks/s).

    python -m udp.server --port 5050 [--drop 0.2]

Game/lobby logic is in common/server_core.py (shared with TCP); this file
only moves datagrams. UDP has no connections, so:
  - ONE socket serves every client; a client is identified by its (ip, port)
    and gets a Session the first time a valid datagram arrives from it.
  - There is no FIN/RST: a client is gone when it is silent for
    HEARTBEAT_TIMEOUT (clients PING every second, INPUT every tick in game).
Threads:
  main     recvfrom() loop -> reliability layer -> core.handle()
  timer    every 50 ms: retransmissions; every 0.5 s: heartbeat timeouts
  game-*   one per running room (server_core.GameRunner)
"""

import argparse
import logging
import socket
import threading
import time

from common import game
from common.protocol import UDP_WARN_SIZE, ProtocolError, decode
from common.server_core import GameServer
from netutil.addresses import startup_banner
from netutil.runtime import setup_logging, stop_on_sigterm
from udp.reliability import ReliableEndpoint

log = logging.getLogger("udp.server")

HEARTBEAT_TIMEOUT = 4.0     # UDP: silent this long = disconnected
TIMER_STEP = 0.05
MAX_SESSIONS = 256          # new addresses beyond this are ignored until some expire


class Session:
    """One client address (a server_core session). send() never blocks."""

    def __init__(self, addr, endpoint):
        self.addr = addr
        self.endpoint = endpoint
        self.name = None
        self.alive = True
        self.last_seen = time.monotonic()

    def __str__(self):
        return f"{self.name or '?'}@{self.addr[0]}:{self.addr[1]}"

    def send(self, msg):
        """Send to this client's address, reliably or not depending on the message type."""
        if self.alive:
            self.endpoint.send(self.addr, msg)   # reliable or not, by message type


class Server:
    """One UDP socket for every client, a reliability layer, and the shared GameServer."""

    def __init__(self, host="0.0.0.0", port=5050, game_ticks=game.GAME_TICKS,
                 heartbeat_timeout=HEARTBEAT_TIMEOUT, drop=0.0):
        self.host, self.port = host, port
        self.heartbeat_timeout = heartbeat_timeout
        self.core = GameServer(game_ticks, log)
        self.endpoint = ReliableEndpoint(self._send_raw, drop=drop,
                                         on_retransmit=self._on_retransmit,
                                         on_give_up=self._on_give_up)
        self.sessions = {}          # (ip, port) -> Session, guarded by core.lock
        self._big_warned = set()    # message types already reported as > UDP_WARN_SIZE
        self.sock = None
        self.running = False

    # ------------------------------------------------------------ lifecycle

    def start(self):
        """Bind the UDP socket and start the timer thread; returns the actual port."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self.running = True
        threading.Thread(target=self._timer, name="timer", daemon=True).start()
        log.info("listening on %s:%d (UDP), drop=%.0f%%", self.host, self.port, self.endpoint.drop * 100)
        return self.port

    def serve_forever(self):
        """recvfrom() loop: every datagram, from any client, arrives on this one socket."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self.running:
                    break
                # e.g. Windows reports ICMP "port unreachable" from an old client here
                log.debug("recvfrom error ignored: %s", exc)
                continue
            try:
                self._on_datagram(data, addr)
            except Exception:
                log.exception("error processing datagram from %s", addr)

    def stop(self):
        """Stop the games and close the socket."""
        self.running = False
        self.core.stop()
        if self.sock:
            self.sock.close()

    def stats(self):
        """Reliability counters (sent, retransmissions, duplicates, ...), logged at exit."""
        return self.endpoint.stats.as_dict()

    # ------------------------------------------------------------ datagrams

    def _send_raw(self, data, addr):
        """The only place that writes to the socket (called by the reliability layer)."""
        if len(data) > UDP_WARN_SIZE:
            self._warn_big(data)
        self.sock.sendto(data, addr)

    def _warn_big(self, data):
        """Once per message type: tunnels (playit.gg, WARP) add headers, and datagrams near the
        path MTU (~1500 B incl. IP/UDP) get fragmented or dropped along the way."""
        mtype = decode(data)["type"]
        if mtype not in self._big_warned:
            self._big_warned.add(mtype)
            log.warning("%s datagram is %d bytes (> %d): may be fragmented or dropped through a tunnel",
                        mtype, len(data), UDP_WARN_SIZE)

    def _on_datagram(self, data, addr):
        """Reliability layer first (ACK, dedupe, ordering), then find/create the (ip, port) session."""
        try:
            msgs = self.endpoint.receive(data, addr)
        except ProtocolError as exc:
            log.warning("bad datagram from %s:%d ignored (%s)", addr[0], addr[1], exc)
            return
        with self.core.lock:
            session = self.sessions.get(addr)
            if session is None:
                if len(self.sessions) >= MAX_SESSIONS:
                    self.endpoint.forget(addr)
                    return
                session = self.sessions[addr] = Session(addr, self.endpoint)
                log.info("NEW PEER %s:%d", *addr)
            session.last_seen = time.monotonic()   # ANY datagram (PING, INPUT, ACK) proves it's alive
        self._handle(session, msgs)

    def _handle(self, session, msgs):
        """Pass the delivered messages to the shared server logic, one at a time."""
        for msg in msgs:
            try:
                self.core.handle(session, msg)
            except Exception:
                log.exception("error handling %s from %s", msg.get("type"), session)

    def _timer(self):
        """Every 50 ms: retransmit unACKed messages; every 0.5 s: heartbeat timeouts."""
        next_check = 0
        while self.running:
            time.sleep(TIMER_STEP)
            try:
                for addr, msg in self.endpoint.tick():       # messages freed by a skipped gap
                    with self.core.lock:
                        session = self.sessions.get(addr)
                    if session:
                        self._handle(session, [msg])
                now = time.monotonic()
                if now >= next_check:
                    next_check = now + 0.5
                    self._check_timeouts(now)
            except Exception:
                log.exception("timer error")

    def _check_timeouts(self, now):
        """UDP has no FIN: a client silent for heartbeat_timeout (4 s) is considered gone."""
        with self.core.lock:
            expired = [s for s in self.sessions.values() if now - s.last_seen > self.heartbeat_timeout]
        for session in expired:
            self.drop_session(session, f"heartbeat timeout ({now - session.last_seen:.1f} s without a datagram)")

    def drop_session(self, session, reason):
        """Remove a client: free its name and room, tell the others (PLAYER_LEFT), forget its seqs."""
        silent_ms = (time.monotonic() - session.last_seen) * 1000
        with self.core.lock:
            if self.sessions.get(session.addr) is not session:
                return
            del self.sessions[session.addr]
            session.alive = False
            self.core.disconnect(session, reason)
        self.endpoint.forget(session.addr)
        log.info("DISCONNECT %s reason=%r last_datagram=%.0f ms ago", session, reason, silent_ms)

    # ------------------------------------------------------------ reliability events

    def _on_retransmit(self, addr, mtype, seq, attempt):
        """Debug log of each retransmission (--log-level DEBUG)."""
        log.debug("RETRANSMIT %s seq=%d to %s:%d (attempt %d)", mtype, seq, addr[0], addr[1], attempt)

    def _on_give_up(self, addr, mtype, seq):
        """A reliable message was never ACKed after MAX_RETRIES: log it, keep the client."""
        # Liveness is decided by the heartbeat, not by one unacknowledged message
        # (often only the ACKs were lost and the client has the message).
        log.warning("GAVE UP on %s seq=%d to %s:%d after retries", mtype, seq, addr[0], addr[1])


def main():
    """Command line entry point: python -m udp.server --port 5050 [--drop 0.3]."""
    parser = argparse.ArgumentParser(description="Maze Arena UDP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--game-seconds", type=float, default=game.GAME_TICKS / game.TICK_RATE,
                        help=f"game length in seconds (default {game.GAME_TICKS // game.TICK_RATE})")
    parser.add_argument("--heartbeat-timeout", type=float, default=HEARTBEAT_TIMEOUT)
    parser.add_argument("--drop", type=float, default=0.0,
                        help="fraction of OUTGOING datagrams to drop (loss simulation)")
    parser.add_argument("--public-ip", help="only printed in the startup banner: the address players "
                        "on other networks use (e.g. the cloud VM's public IP); never bound")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    server = Server(args.host, args.port, int(args.game_seconds * game.TICK_RATE),
                    args.heartbeat_timeout, args.drop)
    server.start()
    for line in startup_banner("udp", args.host, server.port, args.public_ip):
        log.info("%s", line)
    stop_on_sigterm()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupted (Ctrl-C / SIGTERM), shutting down")
    finally:
        log.info("reliability stats: %s", server.stats())
        server.stop()


if __name__ == "__main__":
    main()
