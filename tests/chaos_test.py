"""Chaos test: real processes, hostile clients, a SIGKILL mid-game. Both protocols.

    python tests/chaos_test.py              # readable report, exit code 1 on failure
    python tests/chaos_test.py udp          # one protocol only
    python -m pytest tests/chaos_test.py    # same checks as pytest tests (~70 s)

For each protocol: start the server and 3 bots (alice, bob, carol) as separate
processes; once the game runs, throw garbage at the server, SIGKILL carol, and
run "mallory", a client that breaks the lobby rules on purpose. UDP runs with
--drop 0.3 on the server and on every client. Then check:
  - the server process is still alive and logged no traceback
  - alice and bob got PLAYER_LEFT carol and GAME_OVER (bot exit code 0)
  - mallory got the right refusal for every bad request
  - a brand-new client can still log in
Logs: logs/chaos/<proto>_*.log
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.protocol import (  # noqa: E402
    CREATE_ROOM, INPUT, JOIN_ROOM, LEAVE_ROOM, LOGIN, LOGIN_FAIL, LOGIN_OK,
    READY, ROOM_LIST, ROOM_UPDATE, encode_udp, make_msg,
)
from client_ui.connect import make_transport  # noqa: E402

PY = sys.executable
GAME_SECONDS = 25
UDP_DROP = 0.3
LOG_DIR = ROOT / "logs" / "chaos"


# ---------------------------------------------------------------- processes

class Proc:
    def __init__(self, label, args, log_path):
        self.label = label
        self.log_path = log_path
        self.log_file = open(log_path, "w")
        self.popen = subprocess.Popen([PY, "-u", "-m", *args], cwd=ROOT,
                                      stdout=self.log_file, stderr=subprocess.STDOUT)

    def text(self):
        return self.log_path.read_text(errors="replace")

    def alive(self):
        return self.popen.poll() is None

    def wait_text(self, needle, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self.text():
                return True
            if not self.alive():
                return needle in self.text()
            time.sleep(0.1)
        return False

    def wait_exit(self, timeout):
        try:
            return self.popen.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self, kill=False):
        if self.alive():
            self.popen.kill() if kill else self.popen.terminate()   # SIGKILL / SIGTERM (Windows: both TerminateProcess)
            if self.wait_exit(3) is None:
                self.popen.kill()
                self.popen.wait()
        self.log_file.close()


def free_port():
    """A port free for both TCP and UDP."""
    while True:
        with socket.socket() as t:
            t.bind(("", 0))
            port = t.getsockname()[1]
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.bind(("", port))
            return port
        except OSError:
            continue


# ---------------------------------------------------------------- hostile traffic

GARBAGE = [
    b"\x00\xff\xfe binary junk",
    b"{not json}",
    b"[1, 2, 3]",
    b'{"type": "NOPE"}',
    b'{"type": 5}',
    b'{"name": "no type"}',
    b'{"type": "PING", "t": NaN}',
    b"[" * 100_000,                                   # recursion bomb
    b'{"type": "JOIN_ROOM", "room": [1]}',
    b'{"type": "INPUT", "dir": {"x": 1}}',
    b'{"type": "STATE", "tick": -1}',                 # server-to-client type from a client
]


def send_garbage_tcp(port):
    # 1. every garbage line on one connection, then half a message, then close
    with socket.create_connection(("127.0.0.1", port)) as s:
        for g in GARBAGE:
            s.sendall(g + b"\n")
        s.sendall(b'{"type": "LOGIN", "na')
        time.sleep(0.2)
    # 2. 70 KB without a newline (buffer overflow guard)
    with socket.create_connection(("127.0.0.1", port)) as s:
        try:
            s.sendall(b"A" * 70_000)
        except OSError:
            pass
        time.sleep(0.2)
    # 3. random bytes, 4. connect-and-close
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(os.urandom(4096))
    socket.create_connection(("127.0.0.1", port)).close()


def send_garbage_udp(port):
    extra = [
        b"",
        os.urandom(512),
        encode_udp(make_msg(READY), seq=999_999_999, rel=True),       # forged huge seq
        b'{"type": "ACK", "ack": "x"}',
        b'{"type": "READY", "seq": true, "rel": true}',
        b'{"type": "LOGIN", "name": "' + b"x" * 8000 + b'"}',          # big datagram
    ]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for g in GARBAGE + extra:
            try:
                s.sendto(g, ("127.0.0.1", port))
            except OSError:
                pass                                   # e.g. macOS refuses > 9216 bytes


# ---------------------------------------------------------------- mallory

class Mallory:
    def __init__(self, proto, port):
        drop = UDP_DROP if proto == "udp" else 0.0
        self.t = make_transport(proto, "127.0.0.1", port, drop)
        self.got = []
        self.t.on_message(self.got.append)

    def wait_for(self, msg_type, timeout=6.0, **match):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for i, m in enumerate(self.got):
                if m["type"] == msg_type and all(m.get(k) == v for k, v in match.items()):
                    del self.got[:i + 1]
                    return m
            self.t.poll(timeout=0.05)
        return None

    def ask(self, msg, reply_type, **match):
        self.t.send(msg)
        return self.wait_for(reply_type, **match)


def run_mallory(proto, port, check):
    m = Mallory(proto, port)
    try:
        # INPUT before LOGIN (unreliable on UDP: repeat until the refusal arrives)
        reply = None
        for _ in range(8):
            m.t.send(make_msg(INPUT, dir="UP"))
            reply = m.wait_for(LOGIN_FAIL, timeout=0.5)
            if reply:
                break
        check("INPUT before LOGIN refused", reply and reply.get("reason") == "not logged in", reply)

        check("LOGIN mallory", m.ask(make_msg(LOGIN, name="mallory"), LOGIN_OK) is not None)
        reply = m.ask(make_msg(LEAVE_ROOM, room="does-not-exist"), ROOM_LIST)
        check("LEAVE_ROOM of a room that doesn't exist answered", reply is not None and "error" not in reply, reply)
        # Lobby clients also get unsolicited ROOM_LIST broadcasts: match the error itself.
        reply = m.ask(make_msg(JOIN_ROOM, room=[1]), ROOM_LIST, error="no such room")
        check("JOIN_ROOM with a non-string room refused", reply, m.got)
        reply = m.ask(make_msg(JOIN_ROOM, room="arena"), ROOM_LIST, error="game already running")
        check("JOIN_ROOM of a running game refused", reply, m.got)

        m.ask(make_msg(CREATE_ROOM, room="side"), ROOM_LIST)
        reply = m.ask(make_msg(JOIN_ROOM, room="side"), ROOM_UPDATE)
        check("JOIN_ROOM side", reply is not None, reply)
        reply = m.ask(make_msg(JOIN_ROOM, room="side"), ROOM_LIST, error="already in a room")
        check("second JOIN_ROOM of the same room refused", reply, m.got)
        reply = m.ask(make_msg(READY, ready="yes"), ROOM_UPDATE)
        check("READY with a non-bool value handled", reply and reply["players"] == [{"name": "mallory", "ready": True}], reply)
        m.t.send(make_msg(INPUT, dir=[1]))            # no game running, bad dir: must be ignored
        reply = m.ask(make_msg(LEAVE_ROOM), ROOM_LIST)
        check("LEAVE_ROOM side", reply is not None, reply)
        reply = m.ask(make_msg(LEAVE_ROOM), ROOM_LIST)
        check("LEAVE_ROOM when in no room answered", reply is not None and "error" not in reply, reply)
        check("mallory never disconnected", m.t.connected, m.t.close_reason)
    finally:
        m.t.close()


# ---------------------------------------------------------------- one protocol

def run_chaos(proto):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    port = free_port()
    results = []

    def check(name, ok, detail=None):
        results.append((name, bool(ok), "" if ok else repr(detail)[:200]))

    drop = ["--drop", str(UDP_DROP)] if proto == "udp" else []
    server = Proc("server", [f"{proto}.server", "--port", str(port),
                             "--game-seconds", str(GAME_SECONDS), *drop],
                  LOG_DIR / f"{proto}_server.log")
    bots = {}
    try:
        if not server.wait_text("listening on", 10):
            check("server started", False, server.text()[-500:])
            return results
        for name in ("alice", "bob", "carol"):
            bots[name] = Proc(name, ["client_ui.bot", "--proto", proto, "--port", str(port),
                                     "--name", name, "--room", "arena", "--players", "3", *drop],
                              LOG_DIR / f"{proto}_{name}.log")
            time.sleep(0.2)
        started = all(b.wait_text("GAME_START", 30) for b in bots.values())
        check("game started with 3 bots", started, {n: b.text()[-300:] for n, b in bots.items()})
        if not started:
            return results

        (send_garbage_tcp if proto == "tcp" else send_garbage_udp)(port)
        time.sleep(1.5)
        bots["carol"].popen.kill()                             # SIGKILL: no goodbye
        killed_at = time.monotonic()
        run_mallory(proto, port, check)

        for name in ("alice", "bob"):
            code = bots[name].wait_exit(GAME_SECONDS + 30)
            log = bots[name].text()
            check(f"{name} got PLAYER_LEFT carol", "PLAYER_LEFT carol" in log)
            check(f"{name} got GAME_OVER", "GAME_OVER" in log, log[-300:])
            check(f"{name} exited cleanly (code 0)", code == 0, code)

        late = Mallory(proto, port)
        check("new client can still log in", late.ask(make_msg(LOGIN, name="late"), LOGIN_OK) is not None)
        late.t.close()

        server_log = server.text()
        check("server process still alive", server.alive(), server_log[-500:])
        check("server logged no traceback", "Traceback" not in server_log,
              server_log[server_log.find("Traceback"):][:400])
        check("server noticed carol left", "PLAYER_LEFT carol" in server_log)
        detect = [line for line in server_log.splitlines() if "DISCONNECT carol" in line]
        check("carol's disconnect was logged", detect, None)
        if detect:
            results.append((f"  ({detect[0].split('reason=')[1]})", True, ""))
        del killed_at
    finally:
        for b in bots.values():
            b.stop(kill=True)
        server.stop()
    return results


def report(proto, results):
    print(f"\n=== {proto.upper()} {'(--drop %.1f)' % UDP_DROP if proto == 'udp' else ''}")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'   ' + detail if detail else ''}")
    return all(ok for _, ok, _ in results)


# ---------------------------------------------------------------- pytest entry points

def _assert_all(results):
    failed = [f"{n}: {d}" for n, ok, d in results if not ok]
    assert not failed, "\n".join(failed)


def test_chaos_tcp():
    _assert_all(run_chaos("tcp"))


def test_chaos_udp():
    _assert_all(run_chaos("udp"))


if __name__ == "__main__":
    protos = sys.argv[1:] or ["tcp", "udp"]
    ok = all([report(p, run_chaos(p)) for p in protos])
    print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED (logs in logs/chaos/)")
    sys.exit(0 if ok else 1)
