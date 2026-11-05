# UDP version across networks with playit.gg

The **TCP** version crosses networks through Cloudflare Tunnel ([cloudflare_tunnel.md](cloudflare_tunnel.md)).
Cloudflare public tunnels don't carry UDP, so the **UDP** version uses playit.gg:

- the **playit agent** runs on the Mac (next to `udp.server`) and keeps an outgoing
  connection to playit's servers;
- in the playit dashboard you create a **UDP tunnel** whose local side is `127.0.0.1:5050`;
- playit gives a public address like `xxx.at.ply.gg:PORT`, and players connect **directly** to it with the normal
  client: `--host xxx.at.ply.gg --port PORT`. **Nothing to install on the clients.**

> **Check first (free account):** playit's homepage lists custom **UDP** tunnels in the free
> tier (TCP, TCP+UDP, HTTPS and SSH tunnels are shown under Premium, and free accounts get 4
> ports). The pages don't state this in plain text, so before relying on it: log in, **Tunnels →
> Add Tunnel**, and check that the type **UDP** can be created without upgrading. If it
> can't, either pay for Premium (about 3 USD/month) or demo UDP on the LAN and TCP across networks only.

Contents: [1 Install the agent](#1-install-the-agent) · [2 Claim the agent](#2-claim-the-agent) ·
[3 Create the UDP tunnel](#3-create-the-udp-tunnel) · [4 Start the server](#4-start-the-server) ·
[5 Clients](#5-clients) · [6 Check it works](#6-check-it-works) · [7 Measure it](#7-measure-it) ·
[8 Troubleshooting](#8-troubleshooting) · [9 What happens on the wire](#9-what-happens-on-the-wire)

## 1. Install the agent

Only on the **server** machine.

**macOS (Apple Silicon or Intel)**: download `playit-<version>.pkg` from
<https://playit.gg/download> and open it. It installs:
- `playit.app`, a menu bar icon showing whether the agent is online;
- `playitd`, a background service (a per-user LaunchAgent, so it keeps running after you close the window);
- the `playit` command.

At the end, Terminal opens with a setup link (step 2).
Without the installer: `playit-macos-universal.tar.gz`, keep `playit` and `playitd` in one
folder and run `./playit`.

**Windows** (only if the server ever runs on Windows): `winget install DevelopedMethods.playit`, or
the installer from <https://playit.gg/download>. It adds a Windows service and a tray icon.

Logs if something is wrong: macOS `~/Library/Logs/playit`, Windows `%ProgramData%\playit_gg\logs`.

## 2. Claim the agent

1. Create a free account at <https://playit.gg> (top right, Login → sign up).
2. Open the link the agent printed (in the Terminal window after install, or run `playit`).
   Log in, and approve / **claim** the agent so it's linked to your account.
3. Dashboard → **Agents**: the Mac's agent shows **Online**.

The agent's secret is saved in `~/Library/Application Support/playit_gg/playit.toml`
(macOS), so reinstalling or rebooting reconnects the same agent: you do this once.

## 3. Create the UDP tunnel

Dashboard → **Tunnels → Add Tunnel**:

| Field | Value |
|---|---|
| Tunnel type | **UDP** (not TCP, not "Minecraft Bedrock"/game presets) |
| Agent | the Mac's agent |
| Local address / Local IP | `127.0.0.1` |
| Local port | **5050** (our UDP server port, `udp.server --port`) |
| Port count | 1 |

Save. The tunnel page shows the **public address**, e.g. `xxx.at.ply.gg:41234` (and usually a
numeric IP:port too). The public port is chosen by playit and is **not** 5050: give
players exactly what the page shows. The address stays the same across restarts, so
you can write it on the demo sheet.

## 4. Start the server

```bash
cd ~/maze-arena
bash scripts/playit_server.sh --address xxx.at.ply.gg:41234
```

It refuses to start if UDP 5050 is already taken. If the playit agent isn't running, it
reminds you to start it (`open -a playit`). Then it prints the exact netcheck and client
commands for the players and runs `udp.server --port 5050`, logging to `logs/playit_udp_server.log`.
Without `--address` it prints the commands with placeholders.
Options: `--port N` (must match the tunnel's local port), `--server-args "--game-seconds 60"`.

The TCP server and the Cloudflare tunnel can run at the same time (`bash scripts/tunnel_server.sh`):
TCP 5050 and UDP 5050 are different ports.

## 5. Clients

Repo + venv only, as for the LAN (README → Install). No playit, no cloudflared:

```bash
python -m client_ui.ui --proto udp --host xxx.at.ply.gg --port 41234 --name alice --room demo
```

Windows: the same command (`python` from the activated venv). The client resolves the
hostname **once** at startup and prints `server xxx.at.ply.gg resolved to <IP> (UDP port 41234)`;
every datagram after that goes to that IP. To prove the clients are on different networks,
use the same commands as for the tunnel: `curl -4 ifconfig.me` (Windows `curl.exe -4 ifconfig.me`),
see [cloudflare_tunnel.md §6](cloudflare_tunnel.md#6-prove-the-clients-are-on-different-networks).

## 6. Check it works

From a laptop on **another** network (phone hotspot):

```bash
python scripts/netcheck.py --host xxx.at.ply.gg --port 41234 --proto udp
```

Expected: `xxx.at.ply.gg resolved to <IP>`, then `UDP: OK` with an RTT. On the Mac, the server
log shows `NEW PEER 127.0.0.1:<port>` for each player: the agent delivers every player from
localhost, one local port per player. The server tells players apart by the full
(IP, port) pair, never by IP alone; `tests/test_udp_server.py::test_three_clients_from_the_same_ip`
checks exactly that.

Don't test from the Mac itself or the same Wi-Fi only: a path that works on the LAN
proves nothing about the tunnel. (Some routers also can't "hairpin" to their own public IP.)

## 7. Measure it

From a client laptop, with the server running behind the tunnel (game length = the
server's `--game-seconds`; pass the same value here, it is the benchmark's timeout):

```bash
python metrics/run_benchmark.py --host xxx.at.ply.gg --port 41234 --network playit --protos udp --game-seconds 120
```

3 bots play one game through playit; the row (RTT, inter-update time, missing ticks) goes to
`metrics/results.csv` with `network=playit`, and `metrics/charts/networks.png` compares it
with loopback, LAN (`--network lan`) and Cloudflare (`--network cloudflare --protos tcp`).
Missing ticks are real losses on the internet path: nothing is injected.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| netcheck: `UDP: TIMEOUT`, server log shows **no** `NEW PEER` | **agent offline**: menu bar icon / dashboard → Agents must say Online. Start it (`open -a playit`); check `~/Library/Logs/playit`. Some networks block the agent's outgoing traffic: try the Mac on a phone hotspot |
| timeout, agent Online, still no `NEW PEER` | **wrong local port**: the tunnel's local port must be the UDP server's port (5050) and local IP `127.0.0.1`. Fix it on the tunnel page, or start the server with `--port <that port>` |
| timeout, tunnel looks right | **tunnel type is TCP** (or a game preset), not **UDP**: delete it and create a UDP one. The game client and netcheck only send UDP to that port |
| clients use port 5050 | wrong: use the **public** port playit shows, not the local one |
| `cannot resolve 'xxx.at.ply.gg'` | typo, or a stale address: copy it again from the tunnel page. The numeric IP:port shown there works too |
| works on the Mac/LAN, not from outside | you tested the LAN path, not the tunnel; or the client's network blocks outgoing UDP to unusual ports (some campus/guest Wi-Fi): try a phone hotspot |
| macOS firewall | the agent reaches the server over 127.0.0.1, which the macOS Application Firewall doesn't filter, so playit players aren't blocked by it. LAN players are: if macOS asks "accept incoming network connections?" for Python, click **Allow** (System Settings → Network → Firewall → Options) |
| `UDP port 5050 is already in use` | an old server: `lsof -nP -iUDP:5050`, stop it |
| `name already taken` after a crash | the old session expires after 4 s of silence (UDP heartbeat), then retry |
| server log: `STATE datagram is N bytes (> 1200)` | big datagrams risk fragmentation or loss inside tunnels: see `python metrics/packet_sizes.py` |

## 9. What happens on the wire

```
client (any network) ──UDP──▶ playit edge  xxx.at.ply.gg:41234
        ──playit tunnel (opened OUTWARD by the agent on the Mac)──▶ playit agent (Mac)
        ──UDP──▶ udp.server 127.0.0.1:5050
```

- **No port forwarding, no public IP on the Mac.** The agent dials out to playit and keeps that
  connection; replies and new datagrams come back over it. Any NAT allows that.
- **The flow stays alive** because the client sends a PING every second (and INPUT every tick in a
  game): playit's per-player mapping and every NAT on the way see traffic well before
  they'd time out, and the server's 4 s heartbeat timeout still detects players that vanish.
- **The server sees 127.0.0.1:<port>** for every playit player: the agent opens one local
  UDP socket per remote player. Sessions are keyed by (IP, port), so that's enough.
- **Size matters:** the tunnel wraps each datagram in its own headers. A datagram near the path MTU
  (~1500 bytes including IP/UDP headers) can be fragmented or dropped, so the server warns above 1200 bytes.
