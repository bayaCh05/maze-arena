"""TCP game server (authoritative, 10 ticks/s).

    python -m tcp.server --port 5050

Game/lobby logic is in common/server_core.py (shared with UDP); this file
only moves bytes. Threads (one per client instead of selectors: blocking
code that reads top to bottom, and with 3-10 clients the thread cost is
irrelevant):
  main       accept() loop
  reader-*   one per client: recv() -> TcpStreamBuffer -> core.handle()
  writer-*   one per client: drains that client's send queue -> sendall().
             The game loop only enqueues, so one slow/frozen client can never
             block the tick or the other clients.
  game-*     one per running room (server_core.GameRunner)
  watchdog   closes connections silent for more than HEARTBEAT_TIMEOUT
             (catches half-open connections: frozen process, pulled cable)
"""

import argparse
import logging
import signal
import queue
import socket
import threading
import time

from common import game
from common.protocol import HEARTBEAT_TIMEOUT, ProtocolError, TcpStreamBuffer, encode_tcp
from common.server_core import GameServer

log = logging.getLogger("tcp.server")

RECV_SIZE = 4096
SEND_QUEUE_MAX = 256       # ~25 s of STATE; a client this far behind is dropped
SOCKET_TIMEOUT = 1.0       # so blocked recv/send wake up regularly
MAX_CONNECTIONS = 64       # 2 threads each; refuse beyond this instead of exhausting threads


class ClientConn:
    """One TCP connection (a server_core session). send() never blocks."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = f"{addr[0]}:{addr[1]}"
        self.name = None
        self.outbox = queue.Queue(maxsize=SEND_QUEUE_MAX)
        self.buffer = TcpStreamBuffer()
        self.last_seen = time.monotonic()
        self.alive = True
        self.close_reason = None
        self._close_lock = threading.Lock()

    def __str__(self):
        return f"{self.name or '?'}@{self.addr}"

    def send(self, msg):
        if not self.alive:
            return
        try:
            self.outbox.put_nowait(encode_tcp(msg))
        except queue.Full:
            self.close("send queue full (client not reading)")

    def close(self, reason):
        with self._close_lock:
            if not self.alive:
                return
            self.alive = False
            self.close_reason = reason
        try:
            self.sock.shutdown(socket.SHUT_RDWR)   # wakes up the reader's recv()
        except OSError:
            pass
        try:
            self.outbox.put_nowait(None)           # wakes up the writer
        except queue.Full:
            pass


class Server:
    def __init__(self, host="0.0.0.0", port=5050, game_ticks=game.GAME_TICKS,
                 heartbeat_timeout=HEARTBEAT_TIMEOUT):
        self.host, self.port = host, port
        self.heartbeat_timeout = heartbeat_timeout
        self.core = GameServer(game_ticks, log)
        self.conns = set()          # every open connection (guarded by core.lock)
        self.listener = None
        self.running = False

    # ------------------------------------------------------------ lifecycle

    def start(self):
        """Bind and listen; returns the actual port (useful with port 0)."""
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((self.host, self.port))
        self.listener.listen()
        self.listener.settimeout(SOCKET_TIMEOUT)
        self.port = self.listener.getsockname()[1]
        self.running = True
        threading.Thread(target=self._watchdog, name="watchdog", daemon=True).start()
        log.info("listening on %s:%d (TCP)", self.host, self.port)
        return self.port

    def serve_forever(self):
        while self.running:
            try:
                sock, addr = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    log.exception("accept failed")
                break
            try:
                self._add_connection(sock, addr)
            except Exception:
                log.exception("could not set up connection from %s", addr)
                sock.close()

    def stop(self):
        self.running = False
        if self.listener:
            self.listener.close()
        self.core.stop()
        with self.core.lock:
            conns = list(self.conns)
        for conn in conns:
            conn.close("server shutting down")

    def _add_connection(self, sock, addr):
        # Small messages at 10/s: disable Nagle so STATE leaves immediately.
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(SOCKET_TIMEOUT)
        conn = ClientConn(sock, addr)
        with self.core.lock:
            if len(self.conns) >= MAX_CONNECTIONS:
                log.warning("REFUSED %s: %d connections already", conn.addr, len(self.conns))
                sock.close()
                return
            self.conns.add(conn)
        log.info("CONNECT %s", conn.addr)
        threading.Thread(target=self._reader, args=(conn,), name=f"reader-{conn.addr}", daemon=True).start()
        threading.Thread(target=self._writer, args=(conn,), name=f"writer-{conn.addr}", daemon=True).start()

    # ------------------------------------------------------------ per-client threads

    def _reader(self, conn):
        reason = None
        try:
            while conn.alive:
                try:
                    data = conn.sock.recv(RECV_SIZE)
                except socket.timeout:
                    continue
                if not data:
                    reason = "connection closed by peer (FIN)"
                    break
                conn.last_seen = time.monotonic()
                errors = conn.buffer.errors
                messages = conn.buffer.feed(data)   # 0, 1 or many messages
                if conn.buffer.errors > errors:
                    log.warning("%s sent %d malformed line(s), ignored", conn, conn.buffer.errors - errors)
                for msg in messages:
                    try:
                        self.core.handle(conn, msg)
                    except Exception:
                        log.exception("error handling %s from %s", msg.get("type"), conn)
        except ConnectionResetError:
            reason = "connection reset by peer (RST)"
        except ProtocolError as exc:
            reason = f"protocol error: {exc}"
        except OSError as exc:
            reason = conn.close_reason or f"socket error: {exc}"
        except Exception as exc:
            log.exception("reader crashed for %s", conn)
            reason = f"internal error: {exc}"
        finally:
            silent_ms = (time.monotonic() - conn.last_seen) * 1000
            conn.close(reason or conn.close_reason or "closed")
            try:
                with self.core.lock:
                    self.conns.discard(conn)
                self.core.disconnect(conn, conn.close_reason)
            except Exception:
                log.exception("cleanup failed for %s", conn)
            log.info("DISCONNECT %s reason=%r last_message=%.0f ms ago",
                     conn, conn.close_reason, silent_ms)
            conn.sock.close()

    def _writer(self, conn):
        while True:
            data = conn.outbox.get()
            if data is None or not conn.alive:
                return
            try:
                conn.sock.sendall(data)
            except socket.timeout:
                conn.close("send timeout (client not reading)")
                return
            except OSError as exc:
                conn.close(f"send failed: {exc}")
                return

    def _watchdog(self):
        while self.running:
            time.sleep(0.5)
            now = time.monotonic()
            with self.core.lock:
                conns = list(self.conns)
            for conn in conns:
                silent = now - conn.last_seen
                if conn.alive and silent > self.heartbeat_timeout:
                    conn.close(f"heartbeat timeout ({silent:.1f} s without a message)")


def setup_logging(level):
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s.%(msecs)03d %(levelname)-5s [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="Maze Arena TCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--game-seconds", type=float, default=game.GAME_TICKS / game.TICK_RATE,
                        help="game length (default 120)")
    parser.add_argument("--heartbeat-timeout", type=float, default=HEARTBEAT_TIMEOUT)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    server = Server(args.host, args.port, int(args.game_seconds * game.TICK_RATE),
                    args.heartbeat_timeout)
    server.start()
    # `kill <pid>` (SIGTERM) shuts down like Ctrl-C. Note: background jobs of a
    # non-interactive shell script start with SIGINT ignored, so scripts must use SIGTERM.
    signal.signal(signal.SIGTERM, _interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupted (Ctrl-C / SIGTERM), shutting down")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
