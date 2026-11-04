# Multiplayer Maze Arena

Pacman-style multiplayer game for a Computer Networks course, built twice on
the same game logic, **TCP-only** and **UDP-only**, to compare the two transports.

- The server is **authoritative**: clients send only `INPUT {dir}`; the server
  simulates at **10 ticks/s** and broadcasts the full `STATE` every tick.
- Messages are JSON. TCP: one message per line (newline-delimited). UDP: one
  message per datagram, with a seq/ack reliability layer for lobby and game events
  (STATE and INPUT stay unreliable).
- Lobby, rooms and game loop are shared (`common/server_core.py`); the two
  servers differ only in how they move bytes.
- The pygame UI talks to a transport interface (`send` / `on_message`), so the
  same UI runs on both versions.

## Requirements

- Python **3.10+** (developed on 3.14, also checked on 3.11)
- `requirements.txt`: `pygame-ce` (a drop-in fork of pygame, still `import pygame`,
  with wheels for Python 3.9–3.14), `pytest`, `matplotlib`
- **The servers need only the standard library.** pygame is only for the UI, matplotlib only for charts.

## Install

```bash
git clone <repo-url> maze-arena && cd maze-arena
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Always run from the repo root with `python -m ...` (so `common` imports resolve).

## Run

### TCP version

```bash
python -m tcp.server --port 5050                                                   # server
python -m client_ui.ui --proto tcp --host <server-ip> --port 5050 --name alice --room arena   # each player
```

### UDP version

```bash
python -m udp.server --port 5050                                                   # server
python -m client_ui.ui --proto udp --host <server-ip> --port 5050 --name alice --room arena   # each player
# with simulated loss (30 % of outgoing datagrams, on the server and/or clients):
python -m udp.server --port 5050 --drop 0.3
python -m client_ui.ui --proto udp --host <server-ip> --port 5050 --drop 0.3
```

The TCP and UDP servers can run **at the same time on the same port number**
(they're different ports to the OS). All players of one game use the same `--proto`.

### In the game

Login (or `--name`) → lobby: **C** create room, **↑/↓ + Enter** join, **L** refresh →
room: **R** ready (starts when ≥ 2 players are all ready) → game: **arrows/WASD** →
after GAME_OVER: **Enter** back to the room. **Esc** leaves / quits. RTT is shown in the corner.

### Other entry points

```bash
python -m client_ui.bot --proto tcp --host <server-ip> --port 5050 --name bot1 --room arena --players 3   # headless player
python local_demo.py [--bot]                     # offline, no network: try the game logic
```

## Command-line flags

| Flag | Where | Default | Meaning |
|---|---|---|---|
| `--host` | servers | `0.0.0.0` | address to bind (all interfaces) |
| `--host` | UI, bot | `127.0.0.1` | server address to connect to |
| `--port` | all | `5050` | TCP or UDP port |
| `--proto tcp\|udp` | UI, bot | `tcp` | which version to connect to |
| `--drop P` | `udp.server`, UI, bot | `0` | UDP only: drop fraction P of this process's **outgoing** datagrams |
| `--name`, `--room` | UI, bot | – | log in / create+join a room automatically |
| `--players N` | bot | `2` | bot sends READY once N players are in the room |
| `--game-seconds S` | servers | `120` | game length (shorter for rehearsals) |
| `--heartbeat-timeout S` | servers | TCP `5`, UDP `4` | silence before a client counts as disconnected |
| `--log-level` | servers | `INFO` | `DEBUG` also logs every UDP retransmission |
| `--metrics-csv PATH` | bot | – | write RTT / STATE timing samples (used by the benchmark) |

`--drop` with `--proto tcp` is refused: TCP never loses data at the application level.
To make TCP lose segments you need OS-level loss, see [metrics/netloss_mac.sh](metrics/netloss_mac.sh)
and [docs/demo_checklist.md](docs/demo_checklist.md).

On macOS avoid port **5000** (AirPlay Receiver listens there).

## Tests

```bash
python -m pytest -q                  # everything, ~75 s (includes the chaos test)
python -m pytest -q -k "not chaos"   # fast suite, ~20 s
python tests/chaos_test.py           # chaos test with a readable PASS/FAIL report (tcp + udp)
```

- Unit tests: game rules, protocol framing (split / merged `recv()`), rooms, UDP reliability.
- Integration: real sockets against both servers (disconnects, heartbeat timeouts, 20 % loss).
- Format parity: the same session on TCP and UDP must produce identical messages.
- Chaos test: real processes, garbage input, a SIGKILLed client, rule-breaking client,
  UDP at 30 % loss; the server must survive with no traceback.

## Benchmark

```bash
python metrics/run_benchmark.py                          # TCP+UDP x 0/10/30 % loss, 120 s games (~9 min)
python metrics/run_benchmark.py --protos udp --loss 0.3 --game-seconds 30   # quick run
sudo -v && python metrics/run_benchmark.py --loss-method os   # kernel-level loss (macOS), TCP included
python metrics/make_charts.py                            # re-draw charts from results.csv
```

Measures RTT, inter-update time between STATEs (mean/std/p99/max), missing ticks
and retransmissions (UDP), and disconnection detection time. Output:
`metrics/results.csv` and `metrics/charts/*.png` (raw samples in `metrics/raw/`, not committed).

## Documentation

- [docs/demo_checklist.md](docs/demo_checklist.md): the 4-computer demo, step by step, with the live script
- [docs/cross_network.md](docs/cross_network.md): server on a cloud VM or over Tailscale
- `CLAUDE.md`: project rules (message contract, authoritative server, ...)

## Layout

| Folder | Content |
|--------|---------|
| `common/` | game rules, protocol + framing, rooms, Transport interface, shared server logic. No sockets. |
| `tcp/` | TCP server (thread per client) and `TcpTransport` |
| `udp/` | UDP server (one socket), `UdpTransport`, `reliability.py` (seq/ack/retransmit) |
| `client_ui/` | pygame UI, renderer, headless bot, transport factory |
| `metrics/` | benchmark, charts, results, macOS loss helper |
| `tests/` | pytest suite + chaos test |
| `docs/` | demo checklist, cross-network setup |
