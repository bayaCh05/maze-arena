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

macOS / Linux:

```bash
git clone https://github.com/bayaCh05/maze-arena.git && cd maze-arena
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
git clone https://github.com/bayaCh05/maze-arena.git; cd maze-arena
py -m venv .venv
.venv\Scripts\Activate.ps1          # cmd.exe: .venv\Scripts\activate.bat
pip install -r requirements.txt
```

- Install Python from python.org with **"Add python.exe to PATH"** ticked. `python` from the
  Microsoft Store alias (it opens the Store) is not the one you want; `py` always works.
- PowerShell refuses `Activate.ps1` ("running scripts is disabled")? Once:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Or skip activation and call the
  venv's Python directly: `.venv\Scripts\python -m client_ui.ui ...`.
- If `pip install` starts **compiling** pygame-ce ("Building wheel for pygame-ce"), your Python
  is newer than the published wheels: install Python 3.12 or 3.13 and recreate the venv.
- After activation the commands below are the same on every OS (`python -m ...`;
  forward slashes like `scripts/netcheck.py` work on Windows too).

The repository is public: anyone can clone it (or GitHub → Code → Download ZIP).
Players joining the public server only need [docs/JOIN.md](docs/JOIN.md).

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

**Where do clients connect?** At startup each server prints all this machine's IPv4
addresses (LAN, Tailscale, ...) and the exact client command to copy:

```
Players connect to ONE of these addresses (the one on their network):
  192.168.1.23     en0, LAN / private, default route
Client command to copy (change the name):
  python -m client_ui.ui --proto udp --host 192.168.1.23 --port 5050 --name alice --room demo
```

On a cloud VM, pass `--public-ip X` so the banner shows the address players outside use.

### Check the network path first

On each player laptop, before starting the game:

```bash
python scripts/netcheck.py --host <server-ip> --port 5050
```

It tests a TCP connect + PING/PONG and a UDP PING/PONG with the real server (no login,
no game), prints the RTT, and on failure says what is most likely wrong:
**REFUSED** (machine reachable, server not running or wrong port), **TIMEOUT** (wrong IP,
firewall on the server, Wi-Fi client isolation), **NO ROUTE**, or "TCP works but UDP
doesn't" (UDP firewall rule). Standard library only; macOS, Linux and Windows.

### In the game

Everything works with the mouse (buttons, click a room to join) or the keyboard (keys shown
at the bottom of each screen): login (or `--name`) → lobby: **C** create room, **↑/↓ + Enter**
join, **L** refresh → room: **R** ready (starts when ≥ 2 players are all ready) → game:
**arrows/WASD** → after GAME_OVER: **Enter** play again (a tied top score shows **DRAW!**).
**Esc** leaves / quits, **M** mutes the sound effects (`--mute` starts muted).

In the game you are the Pac-Man with the white ring and the "YOU" label. The sidebar shows
the live scores, power-up time left, RTT and (UDP) the share of lost updates. Eat a big
pellet to be powered up for 5 s: touching another player then sends them back to their
start and costs them 50 points. If the server goes away the window shows **Disconnected**
(TCP at once, UDP after 10 s of silence).

### Other entry points

```bash
python -m client_ui.bot --proto tcp --host <server-ip> --port 5050 --name bot1 --room arena --players 3   # headless player
python local_demo.py [--bot]                     # offline, no network: try the game logic
```

## Command-line flags

| Flag | Where | Default | Meaning |
|---|---|---|---|
| `--host` | servers | `0.0.0.0` | address to bind (all interfaces) |
| `--host` | UI, bot | `127.0.0.1` | server IP or hostname (e.g. the playit.gg address), resolved once at startup |
| `--port` | all | `5050` | TCP or UDP port |
| `--proto tcp\|udp` | UI, bot | `tcp` | which version to connect to |
| `--drop P` | `udp.server`, UI, bot | `0` | UDP only: drop fraction P of this process's **outgoing** datagrams |
| `--name`, `--room` | UI, bot | – | log in / create+join a room automatically |
| `--players N` | bot | `2` | bot sends READY once N players are in the room |
| `--game-seconds S` | servers | `120` | game length (shorter for rehearsals) |
| `--heartbeat-timeout S` | servers | TCP `5`, UDP `4` | silence before a client counts as disconnected |
| `--public-ip IP` | servers | – | only printed in the startup banner (cloud VM's public IP); never bound |
| `--log-level` | servers | `INFO` | `DEBUG` also logs every UDP retransmission |
| `--metrics-csv PATH` | bot | – | write RTT / STATE timing samples (used by the benchmark) |

`--drop` with `--proto tcp` is refused: TCP never loses data at the application level.
To make TCP lose segments you need OS-level loss, see [metrics/netloss_mac.sh](metrics/netloss_mac.sh)
and [docs/demo_checklist.md](docs/demo_checklist.md).

On macOS avoid port **5000** (AirPlay Receiver listens there).

## Windows: commands that differ

Everything with `python -m ...`, `python scripts/...` and `python tests/...` is the same.
These are not:

| What | macOS / Linux | Windows (PowerShell) |
|---|---|---|
| create / activate the venv | `python3 -m venv .venv` · `source .venv/bin/activate` | `py -m venv .venv` · `.venv\Scripts\Activate.ps1` |
| this machine's IP | `ipconfig getifaddr en0` · Linux `hostname -I` | `ipconfig` ("IPv4 Address"); or read the server's banner |
| public IP (cross-network proof) | `curl -4 ifconfig.me` | `curl.exe -4 ifconfig.me` |
| crash one client (kill test) | `pkill -9 -f client_ui.ui` | `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| Where-Object CommandLine -match 'client_ui' \| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }` (or `taskkill /F /IM python.exe`: kills **every** Python on that PC) |
| freeze a client (heartbeat test) | `kill -STOP <pid>` / `kill -CONT <pid>` | no built-in equivalent: do this test from a Mac/Linux client |
| stop a server | Ctrl-C, or `pkill -f tcp.server` | Ctrl-C (wakes up within 1 s), or close the window |
| who uses port 5050? | `lsof -nP -i :5050` | `netstat -ano \| findstr :5050` then `taskkill /PID <pid> /F` |
| test TCP/UDP reachability | `python scripts/netcheck.py ...` (or `nc`) | `python scripts/netcheck.py ...` (no `nc` on Windows) |
| server firewall | macOS: "accept incoming connections" → Allow | Defender prompt: allow **Private** networks, and set the Wi-Fi to *Private* |
| TCP under kernel loss | `metrics/netloss_mac.sh` (macOS), `tc netem` (Linux) | not supported; use a Mac or Linux server for that part |

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

Through a real network, against a server already running elsewhere (3 bots here, one full
game there; rows get a `network` column, local runs are `loopback`):

```bash
python metrics/run_benchmark.py --host <server LAN IP> --port 5050 --network lan --protos tcp udp
python metrics/run_benchmark.py --host 127.0.0.1 --port 15050 --network cloudflare --protos tcp   # via cloudflared access tcp
python metrics/run_benchmark.py --host xxx.at.ply.gg --port 41234 --network playit --protos udp
python metrics/run_benchmark.py --host ... --network ... --rtt-only        # PING RTT only -> rtt_paths.csv
python metrics/packet_sizes.py               # bytes of every message type in a 3-player game
```

Output: `metrics/results.csv` + `metrics/charts/networks.png` (and `rtt_paths.*` for `--rtt-only`).

## Documentation

- [docs/demo_day_sheet.md](docs/demo_day_sheet.md): one page for demo day (roles, commands per laptop, order, plan B)
- [docs/demo_checklist.md](docs/demo_checklist.md): the 4-computer demo, step by step, with the live script
- [docs/cloudflare_tunnel.md](docs/cloudflare_tunnel.md): **cross-network bonus, TCP**: server on the Mac, players on other networks through a Cloudflare Tunnel; bonus-slide explanation of both paths
- [docs/playit_udp.md](docs/playit_udp.md): **cross-network bonus, UDP**: playit.gg agent on the Mac, clients connect directly to the playit address
- [docs/cross_network.md](docs/cross_network.md): alternatives: server on a cloud VM (`deploy/setup_vm.sh`) or over Tailscale
- `CLAUDE.md`: project rules (message contract, authoritative server, ...)

## Layout

| Folder | Content |
|--------|---------|
| `common/` | game rules, protocol + framing, rooms, Transport interface, shared server logic. No sockets. |
| `tcp/` | TCP server (thread per client) and `TcpTransport` |
| `udp/` | UDP server (one socket), `UdpTransport`, `reliability.py` (seq/ack/retransmit) |
| `client_ui/` | pygame UI, renderer, headless bot, transport factory |
| `netutil/` | server startup banner (this machine's IPv4 addresses, client command), `--host` resolution, log/SIGTERM setup shared by both servers |
| `scripts/` | `netcheck.py`: TCP/UDP reachability check with diagnosis; `tunnel_server.sh`, `tunnel_client.sh`/`.bat`: Cloudflare Tunnel; `playit_server.sh`: UDP via playit.gg |
| `deploy/` | cloud VM: `setup_vm.sh`, systemd units for the TCP and UDP servers |
| `metrics/` | benchmark, charts, results, macOS loss helper |
| `tests/` | pytest suite + chaos test |
| `docs/` | demo checklist, demo day sheet, Cloudflare Tunnel (TCP), playit.gg (UDP), cross-network alternatives |
