"""Browser bridge: serves the Three.js client and relays WebSocket <-> the TCP game server.

    python -m web.bridge                                  # http://0.0.0.0:8080, game server 127.0.0.1:5050
    python -m web.bridge --port 8080 --game-host 127.0.0.1 --game-port 5050

A browser can't open a raw TCP or UDP socket, so each browser connection is a WebSocket
(RFC 6455) to this process, and this process opens one ordinary TCP connection to
tcp.server for it. Every WebSocket text frame is one JSON message: it goes to the server
as that message plus "\\n" (our TCP framing), and every line from the server goes back as
one text frame. The bridge never parses or changes messages: the game server sees each
browser as a normal TCP client (127.0.0.1:<port>), with the same rules and protocol.

Standard library only. GET / and the static files come from web/client/dist (npm run build).
"""

import argparse
import base64
import hashlib
import logging
import os
import socket
import struct
import sys
import threading
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from netutil.runtime import setup_logging, stop_on_sigterm  # noqa: E402

log = logging.getLogger("bridge")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # fixed by RFC 6455 for the accept key
MAX_FRAME = 64 * 1024        # same cap as the TCP server's line buffer
MAX_BRIDGES = 64             # same cap as the TCP server's connections
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
STATIC_DIR = ROOT / "web" / "client" / "dist"


class WsClosed(Exception):
    """The browser closed the WebSocket, or broke the framing rules."""


def accept_key(client_key):
    """Sec-WebSocket-Accept for the browser's Sec-WebSocket-Key (proves we speak WebSocket)."""
    digest = hashlib.sha1((client_key + WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def encode_frame(payload, opcode=OP_TEXT):
    """One unmasked, unfragmented server frame (servers must not mask, RFC 6455 5.1)."""
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header += bytes([n])
    elif n < 1 << 16:
        header += bytes([126]) + struct.pack("!H", n)
    else:
        header += bytes([127]) + struct.pack("!Q", n)
    return header + payload


def recv_exact(rfile, n):
    """Exactly n bytes from the browser, or WsClosed if the connection ends first."""
    data = rfile.read(n)
    if data is None or len(data) < n:
        raise WsClosed("connection closed")
    return data


def read_frame(rfile):
    """(opcode, fin, payload) of one browser frame. Browser frames must be masked."""
    b0, b1 = recv_exact(rfile, 2)
    fin, opcode = bool(b0 & 0x80), b0 & 0x0F
    if not b1 & 0x80:
        raise WsClosed("unmasked client frame")
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", recv_exact(rfile, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", recv_exact(rfile, 8))[0]
    if n > MAX_FRAME:
        raise WsClosed(f"frame of {n} bytes")
    mask = recv_exact(rfile, 4)
    data = recv_exact(rfile, n)
    return opcode, fin, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


class Relay:
    """One browser <-> one TCP connection to the game server, until either side ends."""

    def __init__(self, handler, game_addr):
        self.handler = handler
        self.peer = "%s:%s" % handler.client_address[:2]
        self.tcp = socket.create_connection(game_addr, timeout=5)
        self.tcp.settimeout(None)
        self.tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.send_lock = threading.Lock()     # both relay threads write to the browser
        self.closed = threading.Event()

    def ws_send(self, payload, opcode=OP_TEXT):
        """Write one frame to the browser (ignored once closed)."""
        if self.closed.is_set():
            return
        with self.send_lock:
            self.handler.wfile.write(encode_frame(payload, opcode))
            self.handler.wfile.flush()

    def server_to_browser(self):
        """Game server lines -> text frames. One recv() may hold several lines or half of one."""
        buf = b""
        try:
            while True:
                chunk = self.tcp.recv(4096)
                if not chunk:
                    break                              # server closed (FIN)
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    if line:
                        self.ws_send(line)
                if len(buf) > MAX_FRAME:
                    break
        except OSError:
            pass
        finally:
            self.close("game server closed the connection")

    def browser_to_server(self):
        """Text frames -> one JSON line each to the game server; answers PING, honours CLOSE."""
        parts = []
        try:
            while not self.closed.is_set():
                opcode, fin, data = read_frame(self.handler.rfile)
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    self.ws_send(data, OP_PONG)
                    continue
                if opcode in (OP_PONG, OP_BIN):
                    continue
                parts.append(data)
                if not fin:
                    if sum(map(len, parts)) > MAX_FRAME:
                        break
                    continue
                msg, parts = b"".join(parts), []
                # One frame = one message: a newline inside would let one frame smuggle
                # several messages into the TCP stream, so it is replaced by a space
                # (JSON never needs a raw newline).
                self.tcp.sendall(msg.replace(b"\n", b" ").replace(b"\r", b" ") + b"\n")
        except (WsClosed, OSError):
            pass
        finally:
            self.close("browser closed the connection")

    def close(self, reason):
        """Close both sides once; the server then sees a normal TCP disconnect (FIN)."""
        if self.closed.is_set():
            return
        try:
            self.ws_send(struct.pack("!H", 1000), OP_CLOSE)
        except OSError:
            pass
        self.closed.set()
        try:
            self.tcp.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.tcp.close()
        log.info("CLOSE %s (%s)", self.peer, reason)


class Handler(SimpleHTTPRequestHandler):
    """Static files for every path, except GET /ws which becomes a WebSocket relay."""

    protocol_version = "HTTP/1.1"     # browsers refuse a WebSocket upgrade answered as HTTP/1.0
    game_addr = ("127.0.0.1", 5050)
    active = 0
    active_lock = threading.Lock()

    def do_GET(self):
        if self.path.split("?")[0] == "/ws":
            return self.websocket()
        return super().do_GET()

    def end_headers(self):
        # index.html must not be cached, or players keep an old client after an update.
        if self.path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def websocket(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if self.headers.get("Upgrade", "").lower() != "websocket" or not key:
            return self.send_error(HTTPStatus.BAD_REQUEST, "expected a WebSocket upgrade")
        with Handler.active_lock:
            if Handler.active >= MAX_BRIDGES:
                return self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "too many players")
            Handler.active += 1
        try:
            try:
                relay = Relay(self, self.game_addr)
            except OSError as e:
                log.warning("game server %s:%s unreachable: %s", *self.game_addr, e)
                return self.send_error(HTTPStatus.BAD_GATEWAY, "game server is not running")
            self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept_key(key))
            self.end_headers()
            self.close_connection = True
            log.info("OPEN %s -> game server %s:%s", relay.peer, *self.game_addr)
            reader = threading.Thread(target=relay.server_to_browser, name=f"ws-out-{relay.peer}", daemon=True)
            reader.start()
            relay.browser_to_server()           # this request's thread is the inbound side
            reader.join(timeout=2)
        finally:
            with Handler.active_lock:
                Handler.active -= 1

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)


def make_server(host, port, game_host, game_port, static_dir=STATIC_DIR):
    """The bridge's HTTP server (not started); port 0 picks a free port."""
    handler = partial(type("BoundHandler", (Handler,), {"game_addr": (game_host, game_port)}),
                      directory=str(static_dir))
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main():
    """Parse args, check the client is built, serve until Ctrl-C / SIGTERM."""
    parser = argparse.ArgumentParser(description="Browser bridge for the Maze Arena TCP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--game-host", default="127.0.0.1", help="where tcp.server runs")
    parser.add_argument("--game-port", type=int, default=5050)
    parser.add_argument("--static", type=Path, default=STATIC_DIR, help="built client (npm run build)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)
    stop_on_sigterm()
    if not (args.static / "index.html").exists():
        log.warning("%s has no index.html: build the client first (cd web/client && npm run build)", args.static)
    server = make_server(args.host, args.port, args.game_host, args.game_port, args.static)
    log.info("bridge on http://%s:%d  ->  TCP game server %s:%d  (static: %s)",
             args.host, server.server_address[1], args.game_host, args.game_port,
             os.path.relpath(args.static, ROOT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupted (Ctrl-C / SIGTERM)")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
