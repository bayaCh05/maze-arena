---
name: multi-client-testing
description: How to run Maze Arena with 1 server + 3 clients locally in separate processes (TCP or UDP), simulate a client disconnect/crash, test across 4 machines, and run pytest. Use when testing, debugging multiplayer behavior, rehearsing the demo, or verifying the server survives disconnects.
---

# Multi-client testing

All commands run from the repo root (`maze-arena/`) so `common` imports
resolve. Use `python -m <pkg>.<module>`, never `python tcp/server.py`.

Setup once:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 1 server + 3 clients on one machine

Each in its own terminal (best for reading logs):
```bash
python -m tcp.server --host 0.0.0.0 --port 5050
python -m client_ui.ui --proto tcp --host 127.0.0.1 --port 5050 --name alice --room arena
python -m client_ui.ui --proto tcp --host 127.0.0.1 --port 5050 --name bob   --room arena
python -m client_ui.ui --proto tcp --host 127.0.0.1 --port 5050 --name carol --room arena
```
UDP: `python -m udp.server ...` and `--proto udp`. Add `--drop 0.2` to the UDP
server, UI or bot to drop 20 % of that process's outgoing datagrams.

Headless bots (no window; send READY once `--players` are in the room,
wander randomly, exit 0 on GAME_OVER, 1 on disconnect):
```bash
python -m client_ui.bot --proto tcp --port 5050 --name bot1 --room arena --players 3
```
Short games for testing: `python -m tcp.server --port 5050 --game-seconds 20`.

Or as background processes with logs and PIDs (scripted runs):
Run this with **bash** (zsh aborts the whole line on an unmatched glob).
```bash
mkdir -p logs
PROTO=tcp PORT=5050
python -m $PROTO.server --host 0.0.0.0 --port $PORT > logs/server.log 2>&1 & echo $! > logs/server.pid
for n in alice bob carol; do
  python -m client_ui.bot --proto $PROTO --port $PORT --name $n --room arena --players 3 > logs/$n.log 2>&1 &
  echo $! > logs/$n.pid
done
tail -f logs/server.log
```
Stop everything: `kill $(cat logs/*.pid)`.

Port already in use → previous server still alive: `lsof -nP -iTCP:5050 -sTCP:LISTEN` then kill it.
**Never use port 5000 on macOS**: AirPlay Receiver (ControlCenter) listens there;
clients would connect to AirPlay and time out after 5 s ("server silent").

## Simulating a disconnect

| Scenario | Command | What the server should see |
|----------|---------|----------------------------|
| Clean quit | close the pygame window / Esc | TCP: `recv()` → `b""`. UDP: best-effort `LEAVE_ROOM` → immediate PLAYER_LEFT; session itself expires after 4 s |
| Crash | `kill -9 $(cat logs/bob.pid)` | TCP: OS sends FIN/RST → immediate. UDP: **nothing** → detected only after the 4 s heartbeat timeout |
| Frozen client | `kill -STOP <pid>` (resume `kill -CONT <pid>`) | No heartbeats → timeout on both versions; TCP socket stays open! |
| Cable pulled (multi-machine) | Turn Wi-Fi off on a client | Heartbeat timeout on both versions |

Pass criteria every time:
- server process still running (`ps -p $(cat logs/server.pid)`),
- remaining clients get `PLAYER_LEFT {name}` and a `ROOM_UPDATE`,
- game continues for the others (STATE ticks keep arriving),
- the same name can log in again afterwards.

`kill -STOP` is the most interesting demo case: it shows why heartbeats are
needed even with TCP.

Measured on macOS loopback (TCP, 2026-11-04): `kill -9` detected in ~12 ms
(kernel sends FIN); `kill -STOP` detected after 4.9 s (heartbeat timeout).
UDP: both `kill -9` and `kill -STOP` → ~4 s (no connection = no FIN).

In tests, keep the heartbeat timeout well above the 1 s PING interval
(≥ 2 s), or healthy clients get dropped too.

## 4 machines (demo setup)

- All on the same network. Server IP on macOS: `ipconfig getifaddr en0`
  (Linux: `hostname -I`, Windows: `ipconfig`).
- Server: `python -m tcp.server --host 0.0.0.0 --port 5050`.
- Clients: `python -m client_ui.ui --proto tcp --host <server-ip> --port 5050 --name <name>`.
- macOS firewall prompts "accept incoming connections" for Python — click Allow.
  Windows: allow Python on Private networks.
- Check reachability first: `nc -vz <server-ip> 5050` (TCP) /
  `nc -vu <server-ip> 5050` (UDP, inconclusive by nature).
- University Wi-Fi often isolates clients — have a phone hotspot or a
  travel router as plan B.

## pytest

```bash
python -m pytest -q                 # everything
python -m pytest tests/test_game.py -q
python -m pytest -k disconnect -q
```
- `common/` tests: pure unit tests, no sockets, no sleeps.
- Integration tests: start the server in a thread or subprocess on
  `--port 0` / a free port, connect real sockets on `127.0.0.1`, always
  close sockets and stop the server in a fixture `finally`.
- Use timeouts on every socket in tests (`sock.settimeout(2)`) so a bug
  hangs for 2 s, not forever.
- For UDP loss tests, wrap the socket in a test helper that drops every Nth
  datagram rather than relying on real packet loss.

## Chaos test (robustness, both protocols)

```bash
python tests/chaos_test.py          # tcp + udp, readable PASS/FAIL report (~70 s)
python tests/chaos_test.py udp      # one protocol
python -m pytest -q -k "not chaos"  # fast suite without it (~20 s)
```
Real processes: server + alice/bob/carol bots; garbage (bad JSON, NaN,
recursion bomb, random bytes, 70 KB line, forged UDP seq), carol SIGKILLed
mid-game, "mallory" breaks lobby rules (INPUT before LOGIN, double JOIN,
LEAVE of a missing room, non-string room, non-bool ready). UDP at `--drop 0.3`.
Asserts: server alive, **no "Traceback" in the server log**, alice/bob got
PLAYER_LEFT carol + GAME_OVER, every refusal correct, new login still works.
Logs in `logs/chaos/`. When matching replies in lobby tests, match on the
`error` field: lobby clients also receive unsolicited ROOM_LIST broadcasts.
