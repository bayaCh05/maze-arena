"""Transport interface used by the UI and bots. No sockets here.

Implementations: tcp.client.TcpTransport, udp.client.UdpTransport.

Network threads call _deliver(msg); the owner of the transport (pygame main
loop, bot loop) calls poll() to run the on_message callbacks in its own
thread, so UI code never runs on a network thread.
"""

import queue
import time
from collections import deque

from common.protocol import PONG, STATE


class Transport:
    """Base class of TcpTransport and UdpTransport: inbox queue, callbacks, RTT bookkeeping."""

    def __init__(self):
        self._callbacks = []
        self._inbox = queue.Queue()
        self.connected = False
        self.close_reason = None
        self.rtt_ms = None                    # last measured RTT
        self.rtt_samples = deque(maxlen=1000)
        # Metrics (network-metrics skill): recorded on the network thread, at arrival.
        self.rtt_log = deque(maxlen=5000)       # (wall time, rtt ms)
        self.state_arrivals = deque(maxlen=20000)  # (monotonic time, tick) of accepted STATEs

    # --- interface ------------------------------------------------------
    def send(self, msg):
        """Send one message dict. Returns False if the transport is closed."""
        raise NotImplementedError

    def close(self):
        """Close the connection / socket and stop the network threads."""
        raise NotImplementedError

    def on_message(self, callback):
        """Register callback(msg) for every message received."""
        self._callbacks.append(callback)

    def poll(self, timeout=None):
        """Run callbacks for all queued messages; wait up to `timeout` s for the first."""
        count = 0
        try:
            msg = self._inbox.get(timeout=timeout) if timeout else self._inbox.get_nowait()
            while True:
                for cb in self._callbacks:
                    cb(msg)
                count += 1
                msg = self._inbox.get_nowait()
        except queue.Empty:
            return count

    # --- for implementations ---------------------------------------------
    def _deliver(self, msg):
        """Called from a network thread for each received message."""
        if msg.get("type") == PONG and isinstance(msg.get("t"), (int, float)):
            self.rtt_ms = (time.monotonic() - msg["t"]) * 1000
            self.rtt_samples.append(self.rtt_ms)
            self.rtt_log.append((time.time(), self.rtt_ms))
        elif msg.get("type") == STATE:
            self.state_arrivals.append((time.monotonic(), msg.get("tick")))
        self._inbox.put(msg)
