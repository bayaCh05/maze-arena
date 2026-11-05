# Cross-network bonus with Cloudflare Tunnel

The server runs on the Mac (Apple Silicon). Players on **other networks** reach it through a
Cloudflare Tunnel. No cloud VM, no router port forwarding, no firewall rule on the Mac.

What a tunnel can and can't carry for us:

| | Option A: tunnel + `cloudflared access tcp` (this page, sections 1-7) | Option B: Zero Trust + WARP (section 9) |
|---|---|---|
| TCP version | yes | yes |
| UDP version | **no**: public hostnames don't carry UDP | yes |
| On each client | `cloudflared` running next to the game | the WARP app, enrolled in your Zero Trust org |
| Client connects to | `127.0.0.1:<local port>` | the Mac's private IP, port 5050 |

So the cross-network demo is the **TCP version through the tunnel**. The **UDP version
crosses networks through playit.gg** instead ([playit_udp.md](playit_udp.md): nothing to
install on the clients). Option B is a further alternative for UDP.

Contents: [1 What you need](#1-what-you-need) ·
[2 Install cloudflared](#2-install-cloudflared) ·
[3 Server: create the tunnel (once)](#3-server-create-the-tunnel-once) ·
[4 Server: run it](#4-server-run-it) · [5 Clients](#5-clients) ·
[6 Prove the clients are on different networks](#6-prove-the-clients-are-on-different-networks) ·
[7 Measure RTT: LAN vs tunnel](#7-measure-rtt-lan-vs-tunnel) ·
[8 Troubleshooting](#8-troubleshooting) ·
[9 Option B: Zero Trust + WARP (TCP and UDP)](#9-option-b-zero-trust--warp-tcp-and-udp) ·
[10 Bonus slide](#10-bonus-slide-how-it-works)

Below, `maze.example.com` stands for your hostname: replace it everywhere.

## 1. What you need

- A **Cloudflare account** (free plan): <https://dash.cloudflare.com/sign-up>.
- A **domain whose DNS is on Cloudflare** (it gives the `maze.<domain>` name):
  - you already own one: Cloudflare dashboard → **Add a domain** → Free plan → at your
    registrar, replace the nameservers with the two Cloudflare shows. Wait until the
    domain says **Active** (minutes to a few hours);
  - or buy one in the dashboard (**Domain Registration → Register Domains**, at cost,
    ~10 USD/year for `.com`); it is on Cloudflare DNS straight away.
- The Mac stays on and connected during the demo, on **any** network with internet
  access (home, campus, hotspot). It only makes outgoing connections.

## 2. Install cloudflared

| | command | check |
|---|---|---|
| macOS (server and clients) | `brew install cloudflared` | `cloudflared --version` |
| Windows (clients) | `winget install --id Cloudflare.cloudflared` | open a **new** terminal (PATH update), then `cloudflared --version` |

## 3. Server: create the tunnel (once)

On the Mac, in a terminal:

```bash
cloudflared tunnel login
```

A browser opens: log in, pick your domain, **Authorize**. This saves
`~/.cloudflared/cert.pem` (allows the next commands to manage tunnels and DNS for the domain).

```bash
cloudflared tunnel create maze
```

Prints `Created tunnel maze with id <UUID>` and writes the tunnel's secret to
`~/.cloudflared/<UUID>.json`. Note the UUID (`cloudflared tunnel list` shows it again).

Create `~/.cloudflared/config.yml` (replace `<UUID>`, `mac` with your user name, and the hostname):

```yaml
tunnel: <UUID>
credentials-file: /Users/mac/.cloudflared/<UUID>.json

ingress:
  - hostname: maze.example.com
    service: tcp://localhost:5050     # our TCP server; same port as tcp.server --port
  - service: http_status:404          # required catch-all, must be last
```

Check it: `cloudflared tunnel ingress validate` → `OK`, and
`cloudflared tunnel ingress rule https://maze.example.com` → shows the `tcp://localhost:5050` rule (it matches on the hostname).

Create the DNS record (a CNAME `maze` → `<UUID>.cfargotunnel.com`):

```bash
cloudflared tunnel route dns maze maze.example.com
```

## 4. Server: run it

One command starts the TCP server **and** the tunnel, and stops both on Ctrl-C:

```bash
cd ~/maze-arena
bash scripts/tunnel_server.sh                    # tunnel "maze", port 5050
```

It refuses to start if port 5050 is busy, warns if `config.yml` points to another port,
waits for `Registered tunnel connection` in the cloudflared log, and prints the client
command. Logs: `logs/tunnel_tcp_server.log` and `logs/tunnel_cloudflared.log`.
Options: `--port N`, `--tunnel NAME`, `--config PATH`, `--server-args "--game-seconds 60"`,
`--no-server` (only the tunnel, to a TCP server you already started on that port: on demo day the
LAN server on 5050 then serves LAN and tunnel players together).

By hand, in two terminals, it is the same as:

```bash
.venv/bin/python -m tcp.server --port 5050
cloudflared tunnel run maze
```

`cloudflared tunnel info maze` (from any terminal) lists the live edge connections: if it
says the tunnel has no active connections, the tunnel isn't running.

## 5. Clients

Each player, on their own laptop and network, with the repo and venv set up (README → Install)
and cloudflared installed (section 2).

**macOS / Linux**:

```bash
bash scripts/tunnel_client.sh --hostname maze.example.com --name alice --room demo
```

**Windows** (cmd or PowerShell, from the repo folder):

```bat
scripts\tunnel_client.bat maze.example.com --name alice --room demo
```

The scripts:
1. start `cloudflared access tcp --hostname maze.example.com --url localhost:15050` in the background;
2. wait until local port 15050 is listening (15 s max; they show the cloudflared log if it fails);
3. start the game: `python -m client_ui.ui --proto tcp --host 127.0.0.1 --port 15050 --name alice --room demo`;
4. stop cloudflared when the game closes.

Other local port: `--local-port 15051` (macOS) / `set LOCAL_PORT=15051` before the `.bat` (Windows).
Headless bot through the tunnel (macOS/Linux): add `--bot` and `--players 3`.
Windows: quit by closing the game window. If you press Ctrl-C and answer *Y*, cloudflared is left
running: `taskkill /IM cloudflared.exe /F`.

By hand, in two terminals:

```bash
cloudflared access tcp --hostname maze.example.com --url localhost:15050
python -m client_ui.ui --proto tcp --host 127.0.0.1 --port 15050 --name alice --room demo
```

`scripts/netcheck.py` works through the tunnel too, TCP only:
`python scripts/netcheck.py --host 127.0.0.1 --port 15050 --proto tcp`.

## 6. Prove the clients are on different networks

The server log **can't** show it: every tunnel player appears as `127.0.0.1:<port>`
(section 10 says why). Show it on the clients instead. On each laptop, right before playing:

| | public IP (what the internet sees) | local address |
|---|---|---|
| macOS | `curl -4 ifconfig.me` | `ipconfig getifaddr en0` |
| Windows | `curl.exe -4 ifconfig.me` | `ipconfig` |

Three different public IPs = three different networks (for example campus Wi-Fi, phone
hotspot 1, phone hotspot 2). Phone hotspots often use carrier-grade NAT, so the IP may be
shared with other customers of that carrier, but it still differs from the others. Run the
same command on the Mac: a fourth IP. Then show the server log: the three players' `CONNECT
127.0.0.1:<port>` / `LOGIN` lines arrive as they join.

## 7. Measure: LAN vs tunnel

`metrics/run_benchmark.py --host` runs 3 bots on one client laptop against the server
that is already running on the Mac, for one full game (its length is the server's
`--game-seconds`; pass the same value here, it is the benchmark's timeout):

```bash
# on the same LAN as the Mac, direct (TCP and UDP):
python metrics/run_benchmark.py --host <Mac LAN IP> --port 5050 --network lan --protos tcp udp
# from another network, through the tunnel (cloudflared access tcp running on 15050):
python metrics/run_benchmark.py --host 127.0.0.1 --port 15050 --network cloudflare --protos tcp
# UDP through playit.gg (playit_udp.md):
python metrics/run_benchmark.py --host xxx.at.ply.gg --port 41234 --network playit --protos udp
```

Each run adds rows (RTT mean/p95, inter-update time, missing ticks) to `metrics/results.csv`
with that `network` (a re-run replaces it; the local loss runs are `loopback`) and draws
`metrics/charts/networks.png`, which compares all networks side by side. Expect about a ms on the
LAN and tens of ms through a tunnel, because every message makes a detour through the tunnel
provider's data center. On the slide, report the mean and p95 next to the path.

Quick RTT only (100 PINGs before login, no game): add `--rtt-only` (→ `metrics/rtt_paths.csv`,
`charts/rtt_paths.png`).

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `tunnel_server.sh`: no `Registered tunnel connection` after 30 s; log shows `failed to dial to edge` / timeouts | the Mac's network blocks outgoing port 7844 (UDP for QUIC, TCP for HTTP/2). Try `cloudflared tunnel run --protocol http2 maze` (or `protocol: http2` in config.yml); if it is still blocked, put the Mac on a phone hotspot |
| `cloudflared tunnel info maze` says no active connections | the tunnel isn't running, or runs with another config: `ps aux \| grep cloudflared`, check `tunnel:` in config.yml |
| `Cannot determine default origin certificate path` / `cert.pem` not found | `cloudflared tunnel login` wasn't run as this user, or was cancelled in the browser |
| `route dns` fails: `record with that host already exists` | a DNS record `maze` already exists: delete it in the dashboard (DNS → Records), or `cloudflared tunnel route dns --overwrite-dns maze maze.example.com` |
| client: the game says connection closed / disconnected right after start; `logs/cloudflared_access_15050.log` shows `no such host` or an error status for the hostname | **wrong hostname**, a typo, or the DNS record doesn't exist yet: `nslookup maze.example.com` must answer (Cloudflare IPs). The script only notices when the game connects, because cloudflared opens the edge connection per game connection |
| client: `websocket: bad handshake` in the cloudflared log | the hostname exists but isn't routed to a running tunnel, or the ingress rule isn't `tcp://` |
| `cloudflared` log on the Mac: `dial tcp [::1]:5050: connection refused` | `localhost` resolved to IPv6 first; our server listens on IPv4. Use `service: tcp://127.0.0.1:5050` in config.yml |
| `local port 15050 is already in use` | an old cloudflared from a previous run: macOS `pkill cloudflared` (or `lsof -nP -iTCP:15050 -sTCP:LISTEN`), Windows `taskkill /IM cloudflared.exe /F`; or use another local port |
| `port 5050 is already in use` on the Mac | an old server, or AirPlay if you used 5000: `lsof -nP -iTCP:5050 -sTCP:LISTEN`, stop it, or `--port 5051` in both the script and config.yml |
| `cloudflared` not found on Windows right after winget | open a new terminal (PATH is read at start) |
| the game connects but nothing happens after LOGIN | the server isn't running behind the tunnel (cloudflared accepts, then the Mac side can't reach `localhost:5050`): check `logs/tunnel_cloudflared.log` on the Mac |
| UDP client through the tunnel never gets an answer | expected: public hostnames carry no UDP. Use the TCP version, or Option B |

Disconnect detection through the tunnel: when a client process dies, its own OS closes
the local socket, cloudflared closes the stream, and the server's cloudflared closes its
localhost connection, so the server still logs a FIN, a little later than on the LAN.
When a client laptop **loses its network** instead, nothing closes on the Mac side: the
server notices through the 5 s heartbeat timeout.

## 9. Option B: Zero Trust + WARP (TCP and UDP)

Optional. Instead of one public hostname per TCP service, the tunnel carries **traffic to
the Mac's private IP** for devices running Cloudflare's WARP client in your Zero Trust
organization. That includes UDP, so both versions work across networks with the normal
commands (`--host <Mac private IP> --port 5050`).

**This is a VPN-like overlay**, like Tailscale: each client's traffic goes into an encrypted
WARP tunnel to Cloudflare, and through cloudflared to the Mac. Say so on the slide. It shows
the game working across networks, not a raw internet path, and not the public-hostname
tunnel either.

Setup (Zero Trust free plan, up to 50 users; the sign-up may ask for a payment method):

1. **Zero Trust organization**: <https://one.dash.cloudflare.com> → pick a team name (gives
   `<team>.cloudflareaccess.com`).
2. **Who can enroll**: Settings → WARP Client → Device enrollment permissions → add a rule:
   allow the three players' emails (login by one-time PIN sent to the email).
3. **Server (Mac)**: the same tunnel (`maze`), plus a route to the Mac's private IP
   (`ipconfig getifaddr en0`, for example `192.168.110.177`):

   ```bash
   cloudflared tunnel route ip add 192.168.110.177/32 maze
   ```

   and add to `~/.cloudflared/config.yml` (top level):

   ```yaml
   warp-routing:
     enabled: true
   ```

   Start **both** servers and the tunnel: `python -m tcp.server --port 5050`,
   `python -m udp.server --port 5050`, `cloudflared tunnel run maze`. Keep the default QUIC
   protocol: cloudflared proxies UDP to private networks only over QUIC, not with `--protocol http2`.
   If the Mac changes network, its IP changes: delete the route (`cloudflared tunnel route ip delete …`) and add the new one.
4. **Split tunnels**: by default WARP *excludes* private ranges (`192.168.0.0/16`,
   `10.0.0.0/8`, `172.16.0.0/12`) and sends them to the local network, so the Mac's IP would never enter
   the tunnel. Settings → WARP Client → Device settings → Default profile → Split Tunnels →
   remove the range that contains the Mac's IP (e.g. `192.168.0.0/16`) from the Exclude list.
5. **Clients**: install the WARP client (macOS `brew install --cask cloudflare-warp`,
   Windows `winget install --id Cloudflare.Warp`, or <https://one.one.one.one>), then
   Preferences → Account → **Login to Cloudflare Zero Trust** → team name → email PIN.
   The app must show **Connected** (Zero Trust mode, not plain 1.1.1.1).
6. Play: `python -m client_ui.ui --proto udp --host 192.168.110.177 --port 5050 --name alice --room demo`
   (and `--proto tcp`). `python scripts/netcheck.py --host 192.168.110.177 --port 5050`
   tests both.

The server again sees cloudflared as the source: the Mac's own address for every player,
told apart by port. The UDP server keys sessions by (IP, port), so that works too.

## 10. Bonus slide: how it works

We use **two services**, one per version, because a Cloudflare public tunnel carries only HTTP(S)
and TCP streams, not UDP datagrams:

| | TCP version: Cloudflare Tunnel | UDP version: playit.gg |
|---|---|---|
| client runs | the game + `cloudflared access tcp` | the game only |
| client connects to | `127.0.0.1:15050` (its own cloudflared) | `xxx.at.ply.gg:41234` directly |
| on the Mac | `cloudflared tunnel run` → `tcp.server` 5050 | playit agent → `udp.server` 5050 |
| server sees players as | `127.0.0.1:<port>` (cloudflared) | `127.0.0.1:<port>` (playit agent) |
| keeps the path alive | TCP connections + PING/PONG every 1 s | PING every 1 s (+ INPUT every tick) refreshes the mapping |
| ports opened / NAT config | none: both ends dial out | none: the agent dials out |

**Path of one game message (TCP version):**

```
client game ──TCP──▶ cloudflared (client laptop, 127.0.0.1:15050)
            ──HTTPS/WebSocket, port 443──▶ Cloudflare edge (nearest data center)
            ──tunnel (QUIC or HTTP/2, port 7844, opened BY the Mac)──▶ cloudflared (Mac)
            ──TCP──▶ tcp.server on localhost:5050
```

Replies take the same path back, over the same connections.

- **No open ports, no NAT setup.** Both cloudflared processes only make **outgoing**
  connections: the Mac's cloudflared dials Cloudflare when the tunnel starts and keeps the
  connection open, and each client's cloudflared dials Cloudflare when the game connects.
  Every NAT and firewall on the way already allows outgoing connections and their replies,
  so nothing has to accept a connection from the internet: no port forwarding on a
  router, no inbound firewall rule, no public IP. The Mac can sit behind campus NAT or a
  phone's carrier-grade NAT.
- **The server sees 127.0.0.1.** cloudflared on the Mac terminates the tunnel and opens a
  **new** TCP connection to `localhost:5050` for each player. The server only sees that last
  hop, so every player is `127.0.0.1:<random port>`. That's why the server identifies players
  per connection and by unique name, never by IP (the test
  `test_three_clients_from_the_same_ip` checks exactly this).
- **TCP end to end?** Not one connection but three TCP legs (game → cloudflared,
  cloudflared → edge → cloudflared, cloudflared → server). Each leg is reliable and
  ordered, so the game still gets a byte stream with our newline-delimited JSON.
- **Why UDP isn't carried.** A public hostname maps to an HTTP(S) or a TCP stream service;
  `cloudflared access tcp` wraps a **TCP byte stream** in a WebSocket. A UDP datagram has
  no stream or connection to wrap, so that path doesn't carry it. UDP needs Cloudflare's
  private-network mode with the WARP client on every player (Option B): a VPN-like overlay.
- **Cost of the detour.** Every message goes through a Cloudflare data center, which adds
  latency; the chart `networks.png` (section 7) shows LAN vs tunnel.

**Path of one game message (UDP version, playit.gg):**

```
client game ──UDP──▶ playit edge (xxx.at.ply.gg:41234)
            ──tunnel (opened OUTWARD by the playit agent on the Mac)──▶ playit agent (Mac)
            ──UDP──▶ udp.server on 127.0.0.1:5050
```

- **Clients connect directly**: a plain UDP socket to a public address, the same client code
  as on the LAN. `--host` accepts the hostname; it is resolved once at startup.
- **Reverse tunnel**: the agent on the Mac connects *out* to playit and keeps the connection; playit's
  edge receives the players' datagrams on the public port and pushes them down that tunnel. No
  port forwarding, no public IP, works behind campus or carrier-grade NAT.
- **The heartbeat keeps the flow alive**: UDP has no connection, so playit's per-player mapping and
  every NAT on the way forget a flow that goes quiet. Our client sends a PING every second
  (and INPUT every tick in a game), so the flow never idles; the server's 4 s heartbeat timeout
  still removes players who vanish.
- **Same IP, different ports**: the agent delivers every player from 127.0.0.1, one local port per player.
  The UDP server keys sessions by the full (IP, port) (test `test_three_clients_from_the_same_ip`).
- **Datagram size**: the tunnel adds headers, so datagrams should stay under ~1200 bytes
  (`metrics/packet_sizes.py` measures every message; the server warns above that).
