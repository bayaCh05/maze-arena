# Demo day sheet: Fri 13 Nov 2026

Port **5050** everywhere (TCP and UDP). Every laptop: `cd maze-arena`, venv active
(macOS `source .venv/bin/activate` · Windows `.venv\Scripts\Activate.ps1`), `git pull` done.
`S_IP` = the address the server prints at startup. `VM_IP` = the cloud VM's public IP.

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
3. Cloud VM: from one laptop, `python scripts/netcheck.py --host VM_IP --port 5050` → both OK.

## The demo, in order

| # | Step | S | A, B, C |
|---|---|---|---|
| 1 | **TCP game** | point at CONNECT → LOGIN → JOIN → READY → GAME_START in the log | `python -m client_ui.ui --proto tcp --host S_IP --port 5050 --name alice --room demo` (bob, carol) → **R** |
| 2 | **Kill test (TCP)** | log: `PLAYER_LEFT carol … (FIN)` within ms; game goes on with 2 | C: macOS `pkill -9 -f client_ui.ui` · Windows Task Manager → python.exe → End task |
| 3 | **UDP game** (+ kill again) | log: `PLAYER_LEFT carol … heartbeat timeout` after ~4 s: no FIN in UDP | same command with `--proto udp` → **R**; C kills again mid-game |
| 4 | **UDP at 30 % loss** | Ctrl-C the UDP server, `python -m udp.server --port 5050 --drop 0.3` | `… --proto udp … --drop 0.3` → **R**; A reads "lost ~30 %": choppy but never frozen, login/join/ready still worked (reliable messages) |
| 5 | **Cross-network** (bonus) | show `journalctl -u maze-arena-udp -f` over SSH on the VM: 3 different `NEW PEER` public IPs | switch to **3 different networks** (campus Wi-Fi, phone hotspot 1, phone hotspot 2); each runs `curl -4 ifconfig.me` (Windows `curl.exe -4 ifconfig.me`) to show a different public IP, then `--host VM_IP` with `--proto tcp`, then `udp` |

Talking points for 5: public IP + ports 5050 tcp/udp open in the cloud firewall and the
VM's iptables; clients are behind NAT and always start the flow; the 1 s PING keeps the
UDP NAT mapping alive ([cross_network.md A7](cross_network.md#a7-explaining-the-setup-bonus-slide)).
Optional extra (S is a Mac, rehearsed): TCP under kernel loss, `sudo sh metrics/netloss_mac.sh on 5050 0.3 0 en0`.

## Plan B

| Problem | Do this |
|---|---|
| netcheck: TIMEOUT on the campus Wi-Fi (client isolation) | everyone joins **S's phone hotspot**; S restarts the servers and reads the new `S_IP` from the banner |
| Server laptop firewall (macOS prompt / Windows Defender) | allow Python; Windows: Wi-Fi set to *Private* |
| Cloud VM unreachable (campus blocks the port, VM down) | **Tailscale**: all 4 install and log in to the same tailnet; S runs the servers, clients use `--host <tailscale ip -4 of S>`. Say it is a WireGuard VPN overlay, not a raw internet path |
| Only one laptop works | everything on S: server + `python -m client_ui.ui …` (host defaults to 127.0.0.1) + two bots: `python -m client_ui.bot --proto tcp --name bob --room demo --players 3` (and carol) |
| "name already taken" after a crash | wait 5 s (TCP) / 4 s (UDP) or use another name |
| Port 5050 busy on S | `lsof -nP -i :5050` (Windows `netstat -ano \| findstr :5050`), or `--port 5051` everywhere |

After: stop the servers; on the VM `sudo systemctl stop maze-arena-tcp maze-arena-udp`.
