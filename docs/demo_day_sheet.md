# Demo day sheet: Fri 13 Nov 2026

Port **5050** everywhere (TCP and UDP). Every laptop: `cd maze-arena`, venv active
(macOS `source .venv/bin/activate` · Windows `.venv\Scripts\Activate.ps1`), `git pull` done.
`S_IP` = the address the server prints at startup. `maze.<domain>` = the Cloudflare Tunnel hostname
([cloudflare_tunnel.md](cloudflare_tunnel.md)); cloudflared installed on S, A, B, C. `PLAYIT` = the playit.gg
UDP address, e.g. `xxx.at.ply.gg:41234` → `--host xxx.at.ply.gg --port 41234` ([playit_udp.md](playit_udp.md)).

**Clients for the grade: the pygame clients** (`python -m client_ui.ui --proto tcp|udp`) are the
official TCP and UDP clients and every demo step below uses them. The 3D browser link
(`deploy/public_addresses.env` → `WEB_URL`) is an extra for the **TCP version only** (WebSocket bridge
→ TCP server); never present it as a UDP client. Games last **1 minute** (server `--game-seconds`).

## Roles

| Laptop | Person | Job |
|---|---|---|
| **S** | narrator | runs the LAN servers, **server log on the projector**, explains each step |
| **A** | alice | player; reads RTT / "lost %" from the HUD aloud |
| **B** | bob | player |
| **C** | carol | player; does the **kill test** (has the kill command ready in a 2nd terminal) |

## Before the audience (10 min)

1. All 4 on the same Wi-Fi (or S's phone hotspot). S starts both servers, in two terminals:
   `python -m tcp.server --port 5050` and `python -m udp.server --port 5050`. Note `S_IP` from the banner.
2. A, B, C: `python scripts/netcheck.py --host S_IP --port 5050` → **TCP OK and UDP OK**.
   Anything else: read the diagnosis it prints (refused / timeout / no route).
3. Tunnel: on S, 3rd terminal, `bash scripts/tunnel_server.sh --no-server` (tunnel to the TCP server
   already on 5050: LAN and tunnel players share it) → "tunnel connected".
   One player, off the LAN (hotspot): `cloudflared access tcp --hostname maze.<domain> --url localhost:15050`,
   then `python scripts/netcheck.py --host 127.0.0.1 --port 15050 --proto tcp` → TCP OK.
4. playit: the agent on S says **Online** (menu bar / dashboard); its UDP tunnel points to `127.0.0.1:5050`,
   so the UDP server from step 1 serves LAN and playit players alike. Same hotspot player:
   `python scripts/netcheck.py --host xxx.at.ply.gg --port 41234 --proto udp` → UDP OK.

## The demo, in order

| # | Step | S | A, B, C |
|---|---|---|---|
| 1 | **TCP game** | point at CONNECT → LOGIN → JOIN → READY → GAME_START in the log | `python -m client_ui.ui --proto tcp --host S_IP --port 5050 --name alice --room demo` (bob, carol) → **R** |
| 2 | **Kill test (TCP)** | log: `PLAYER_LEFT carol … (FIN)` within ms; game goes on with 2 | C: macOS `pkill -9 -f client_ui.ui` · Windows Task Manager → python.exe → End task |
| 3 | **UDP game** (+ kill again) | log: `PLAYER_LEFT carol … heartbeat timeout` after ~4 s: no FIN in UDP | same command with `--proto udp` → **R**; C kills again mid-game |
| 4 | **UDP at 30 % loss** | Ctrl-C the UDP server, `python -m udp.server --port 5050 --drop 0.3` | `… --proto udp … --drop 0.3` → **R**; A reads "lost ~30 %": choppy but never frozen, login/join/ready still worked (reliable messages) |
| 5a | **Cross-network** (bonus, TCP) | TCP server log on the projector: 3 `CONNECT 127.0.0.1:<port>` + LOGIN lines (explain why 127.0.0.1) | switch to **3 different networks** (campus Wi-Fi, phone hotspot 1, phone hotspot 2); each runs `curl -4 ifconfig.me` (Windows `curl.exe -4 ifconfig.me`) to show a different public IP, then `bash scripts/tunnel_client.sh --hostname maze.<domain> --name alice --room net` (Windows `scripts\tunnel_client.bat maze.<domain> --name alice --room net`) → **R** |
| 5b | **Cross-network** (bonus, UDP) | first restart the UDP server **without** `--drop`; UDP log on the projector: 3 `NEW PEER 127.0.0.1:<port>` (the playit agent) | same 3 networks, nothing extra to install: `python -m client_ui.ui --proto udp --host xxx.at.ply.gg --port 41234 --name alice --room net2` → **R**; C kills the client mid-game → `heartbeat timeout` after ~4 s, as on the LAN |

Talking points for 5 ([cloudflare_tunnel.md §10](cloudflare_tunnel.md#10-bonus-slide-how-it-works)): client → local
cloudflared → Cloudflare edge → tunnel → cloudflared on S → server on localhost; no open port or NAT
setup because both cloudflared only connect outward; the server sees 127.0.0.1 (players told apart
by connection + name); UDP isn't carried by a Cloudflare public hostname, hence playit.gg for 5b: clients
send plain UDP to the playit address, the agent on S dialed out (reverse tunnel), the 1 s PING keeps the flow alive.
Optional extra (S is a Mac, rehearsed): TCP under kernel loss, `sudo sh metrics/netloss_mac.sh on 5050 0.3 0 en0`.

## Plan B

| Problem | Do this |
|---|---|
| netcheck: TIMEOUT on the campus Wi-Fi (client isolation) | everyone joins **S's phone hotspot**; S restarts the servers and reads the new `S_IP` from the banner |
| Server laptop firewall (macOS prompt / Windows Defender) | allow Python; Windows: Wi-Fi set to *Private* |
| Tunnel won't connect (campus blocks port 7844 out of S) | S on a phone hotspot, or `cloudflared tunnel run --protocol http2 maze`; see [cloudflare_tunnel.md §8](cloudflare_tunnel.md#8-troubleshooting) |
| playit: netcheck UDP timeout | agent Online? tunnel type **UDP**, local port **5050**? ([playit_udp.md §8](playit_udp.md#8-troubleshooting)); otherwise show UDP on the LAN only |
| Tunnel unusable on the day | **Tailscale**: all 4 install and log in to the same tailnet; S runs the servers, clients use `--host <tailscale ip -4 of S>`. Say it is a WireGuard VPN overlay, not a raw internet path |
| Only one laptop works | everything on S: server + `python -m client_ui.ui …` (host defaults to 127.0.0.1) + two bots: `python -m client_ui.bot --proto tcp --name bob --room demo --players 3` (and carol) |
| "name already taken" after a crash | wait 5 s (TCP) / 4 s (UDP) or use another name |
| Port 5050 busy on S | `lsof -nP -i :5050` (Windows `netstat -ano \| findstr :5050`), or `--port 5051` everywhere |

After: stop the servers (Ctrl-C in `tunnel_server.sh` stops the tunnel too).
