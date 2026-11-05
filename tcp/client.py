"""TCP transport: send(msg) / on_message(callback).

A receive thread turns the byte stream into messages (TcpStreamBuffer) and
queues them; the owner calls poll() to handle them in its own thread.
A ping thread sends PING {t} every second: it measures RTT and doubles as
the heartbeat the server expects.
"""

import socket
import sys
import threading
import time

from common.protocol import (
    HEARTBEAT_TIMEOUT, PING, PING_INTERVAL, ProtocolError, TcpStreamBuffer,
    encode_tcp, make_msg,
)
from common.transport import Transport
from netutil.addresses import resolve_ipv4


class TcpTransport(Transport):
    """Client side of the TCP version: one connection, a receive thread and a ping thread."""

    def __init__(self, host, port, connect_timeout=5.0):
        super().__init__()
        self.host, self.port = host, port
        self.server_ip = None               # host resolved once in connect()
        self.connect_timeout = connect_timeout
        self.sock = None
        self._send_lock = threading.Lock()
        self._closed = threading.Event()

    def connect(self):
        """Open the connection; raises OSError if the server is unreachable or the name doesn't resolve."""
        self.server_ip = resolve_ipv4(self.host, self.port, "tcp")
        if self.server_ip != self.host:
            print(f"server {self.host} resolved to {self.server_ip} (TCP port {self.port})", file=sys.stderr)
        self.sock = socket.create_connection((self.server_ip, self.port), timeout=self.connect_timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # The server talks at least once per second (PONG, STATE), so a longer
        # silence means it is gone even if the TCP connection looks open.
        self.sock.settimeout(HEARTBEAT_TIMEOUT)
        self.connected = True
        threading.Thread(target=self._recv_loop, name="tcp-recv", daemon=True).start()
        threading.Thread(target=self._ping_loop, name="tcp-ping", daemon=True).start()
        return self

    def send(self, msg):
        """Send one message as a JSON line; False if the connection is gone."""
        if not self.connected:
            return False
        try:
            with self._send_lock:          # recv/ping/UI threads may all send
                self.sock.sendall(encode_tcp(msg))
            return True
        except OSError as exc:
            self._shutdown(f"send failed: {exc}")
            return False

    def close(self):
        """Close the connection (the server sees a FIN at once)."""
        self._shutdown("closed by client")

    def _recv_loop(self):
        """recv() -> framing buffer -> _deliver(); ends on FIN, error, or 5 s of silence."""
        buffer = TcpStreamBuffer()
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    self._shutdown("server closed the connection")
                    return
                for msg in buffer.feed(data):
                    self._deliver(msg)
        except socket.timeout:
            self._shutdown(f"server silent for {HEARTBEAT_TIMEOUT:.0f} s")
        except (OSError, ProtocolError) as exc:
            self._shutdown(f"connection lost: {exc}")

    def _ping_loop(self):
        """PING {t} every second: RTT measurement and heartbeat for the server."""
        while not self._closed.wait(PING_INTERVAL):
            self.send(make_msg(PING, t=time.monotonic()))

    def _shutdown(self, reason):
        """Mark closed (once) and close the socket; the UI reads close_reason."""
        if self._closed.is_set():
            return
        self._closed.set()
        self.connected = False
        self.close_reason = reason
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
