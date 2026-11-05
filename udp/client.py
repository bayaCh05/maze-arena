"""UDP transport: send(msg) / on_message(callback).

Same Transport interface as TCP; differences stay in here:
  - reliability layer (udp/reliability.py) for lobby messages
  - STATE: older-than-last ticks are discarded; gaps are counted
    (states_lost = ticks never received, states_late = arrived after a newer one;
    a late tick is no longer counted as lost)
  - the last INPUT is re-sent every tick during a game, so a lost INPUT
    heals itself 100 ms later (and keeps the server's heartbeat fresh)
  - PING every second = heartbeat + RTT
"""

import socket
import threading
import time

from common.protocol import (
    GAME_OVER, GAME_START, INPUT, LEAVE_ROOM, PING, PING_INTERVAL, STATE,
    ProtocolError, make_msg,
)
from common.transport import Transport
from udp.reliability import ReliableEndpoint

SERVER_TIMEOUT = 10.0   # client side: lenient, PONGs need 2 lucky datagrams under loss
INPUT_REPEAT = 0.1
TIMER_STEP = 0.05


class UdpTransport(Transport):
    def __init__(self, host, port, drop=0.0, server_timeout=SERVER_TIMEOUT):
        super().__init__()
        self.host, self.port = host, port
        self.drop = drop
        self.server_timeout = server_timeout
        self.sock = None
        self.peer = None
        self.endpoint = None
        self._closed = threading.Event()
        self._input = None
        self.in_game = False
        self.last_rx = time.monotonic()
        # STATE statistics (metrics)
        self.last_tick = 0
        self.states_received = 0
        self.states_lost = 0
        self.states_late = 0
        self._missing = set()               # skipped ticks that may still arrive late

    def connect(self):
        """UDP has no handshake: this only creates the socket. LOGIN proves the server is there."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.connect((self.host, self.port))   # fixes the peer; send() without address
        self.sock.settimeout(0.2)
        self.peer = self.sock.getpeername()
        self.endpoint = ReliableEndpoint(lambda data, _addr: self.sock.send(data),
                                         drop=self.drop, on_give_up=self._on_give_up)
        self.connected = True
        self.last_rx = time.monotonic()
        threading.Thread(target=self._recv_loop, name="udp-recv", daemon=True).start()
        threading.Thread(target=self._timer_loop, name="udp-timer", daemon=True).start()
        return self

    @property
    def stats(self):
        s = self.endpoint.stats.as_dict() if self.endpoint else {}
        s.update(states_received=self.states_received, states_lost=self.states_lost,
                 states_late=self.states_late)
        return s

    def send(self, msg):
        if not self.connected:
            return False
        if msg["type"] == INPUT:
            self._input = msg
        elif msg["type"] == LEAVE_ROOM:
            self._input, self.in_game = None, False
        self.endpoint.send(self.peer, msg)
        return True

    def close(self):
        if self.connected:
            self.endpoint.send(self.peer, make_msg(LEAVE_ROOM))   # best effort, no wait
        self._shutdown("closed by client")

    # ------------------------------------------------------------ threads

    def _recv_loop(self):
        while not self._closed.is_set():
            try:
                data = self.sock.recv(65535)
            except socket.timeout:
                continue
            except (ConnectionRefusedError, ConnectionResetError):
                continue            # ICMP port unreachable (Windows: WinError 10054): server not (yet) running
            except OSError as exc:
                self._shutdown(f"socket error: {exc}")
                return
            try:
                msgs = self.endpoint.receive(data, self.peer)
            except ProtocolError:
                continue
            self.last_rx = time.monotonic()
            for msg in msgs:
                self._accept(msg)

    def _accept(self, msg):
        t = msg["type"]
        if t == STATE:
            tick = msg.get("tick", 0)
            if tick <= self.last_tick:
                self.states_late += 1               # older than what we showed: discard
                if tick in self._missing:           # ...but it did arrive: late, not lost
                    self._missing.discard(tick)
                    self.states_lost -= 1
                return
            if self.last_tick and tick > self.last_tick + 1:
                self.states_lost += tick - self.last_tick - 1
                self._missing.update(range(max(self.last_tick + 1, tick - 50), tick))
                self._missing = {t for t in self._missing if t > tick - 50}
            self.last_tick = tick
            self.states_received += 1
        elif t == GAME_START:
            self.last_tick, self.in_game, self._input = 0, True, None
            self._missing.clear()
        elif t == GAME_OVER:
            self.in_game, self._input = False, None
        self._deliver(msg)

    def _timer_loop(self):
        next_ping = next_input = 0
        while not self._closed.wait(TIMER_STEP):
            for _addr, msg in self.endpoint.tick():
                self._accept(msg)
            now = time.monotonic()
            if now >= next_ping:
                next_ping = now + PING_INTERVAL
                self.endpoint.send(self.peer, make_msg(PING, t=now))
            if self.in_game and self._input and now >= next_input:
                next_input = now + INPUT_REPEAT
                self.endpoint.send(self.peer, self._input)
            if now - self.last_rx > self.server_timeout:
                self._shutdown(f"server silent for {self.server_timeout:.0f} s")

    def _on_give_up(self, _addr, mtype, seq):
        if time.monotonic() - self.last_rx > 2.0:
            self._shutdown(f"server not answering ({mtype} never acknowledged)")

    def _shutdown(self, reason):
        if self._closed.is_set():
            return
        self._closed.set()
        self.connected = False
        self.close_reason = reason
        self.sock.close()
