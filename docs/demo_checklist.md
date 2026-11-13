# Demo checklist: Friday 13 November 2026

> **Today's live demo (13 Nov) follows [demo_scenarios.md](demo_scenarios.md)**: server on Yassine's
> PC over Tailscale (`100.66.86.49`), TCP port 5050, UDP port **5051**, players Baya, Yahia, Aziz.
> This file is the general LAN / cross-network reference.

4 computers: **S** = server, **A**, **B**, **C** = players (alice, bob, carol).
Port **5050** for both TCP and UDP. All commands run from the repo root
(`cd maze-arena && source .venv/bin/activate`; Windows: `.venv\Scripts\activate`).

Server choice:
- **LAN demo** (all 4 on the same Wi-Fi/hotspot): S is a laptop. Simplest; this checklist assumes it.
- **Cross-network demo**: S is the cloud VM from [cross_network.md](cross_network.md);
  replace "S's IP" below with the VM's public IP and skip S's laptop firewall step.

---

## 1. The day before (every computer)

- [ ] Every laptop has cloned the repo (it's public), or brings it on a USB stick / as a zip.
- [ ] Repo up to date (`git pull`), venv created, `pip install -r requirements.txt` works.
- [ ] `python local_demo.py` opens a window and you can move (pygame works on this machine).
- [ ] `python -m pytest -q -k "not chaos"` passes (do it on S at least).
- [ ] Power adapter, sleep disabled during the demo, notifications off, terminal font large.
- [ ] Decide the network. Campus Wi-Fi often isolates devices from each other: **bring a
      phone hotspot** (or travel router) as plan B and test it the day before.
- [ ] Full rehearsal of section 4, including the TCP-loss step (it needs `sudo` on S).

## 2. Find the IPs

Only **S's IP** matters (clients connect to it). Clients' IPs show up in S's log anyway
(`CONNECT 192.168.1.23:51234`).

| OS | Command | Look for |
|---|---|---|
| macOS | `ipconfig getifaddr en0` (Wi-Fi; try `en1` if empty) | `192.168.x.y` / `10.x.y.z` / `172.20.10.x` (iPhone hotspot) |
| Windows | `ipconfig` | "IPv4 Address" under the Wi-Fi adapter |
| Linux | `hostname -I` or `ip -4 addr show` | the address on `wlan0` / `wlp…` |

Write S's IP on the board/slide. Below it's `S_IP`.

## 3. Firewall: only S needs to accept incoming traffic

Clients only make outgoing connections; their replies are allowed back automatically.

**macOS (S)**: check with `/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate`.
If it is off, nothing to do. If it is on, the first time the server starts, macOS asks *"Do you want the application
Python to accept incoming network connections?"* → **Allow**. If someone clicked Deny:
System Settings → Network → Firewall → Options → Python → "Allow incoming connections"
(and make sure "Block all incoming connections" is off). The rule is per Python binary:
the venv's Python needs its own "Allow" even if another Python was allowed before.
Start the server once before the demo to get the prompt out of the way.

**Windows (S)**: allow Python on **Private** networks in the prompt, and make sure the
Wi-Fi is set to *Private* (Settings → Network → Wi-Fi → network properties). Or as admin:
```powershell
netsh advfirewall firewall add rule name="Maze Arena TCP" dir=in action=allow protocol=TCP localport=5050
netsh advfirewall firewall add rule name="Maze Arena UDP" dir=in action=allow protocol=UDP localport=5050
```
Undo: `netsh advfirewall firewall delete rule name="Maze Arena TCP"` (and `... UDP`).

**Linux (S)**:
```bash
sudo ufw allow 5050/tcp && sudo ufw allow 5050/udp               # Ubuntu (ufw)
sudo firewall-cmd --add-port=5050/tcp --add-port=5050/udp        # Fedora (firewalld, until reboot)
```

**Check from each client before the audience arrives** (same command on macOS and Windows):
```bash
python scripts/netcheck.py --host S_IP --port 5050     # TCP + UDP PING/PONG, RTT, diagnosis on failure
```
Both lines must say `OK, ready to play`. Without the repo, on macOS/Linux:
`echo '{"type":"PING","t":1}' | nc -w 2 S_IP 5050` (TCP) and the same with `nc -u` (UDP;
only a PONG proves UDP works).

More troubleshooting: [cross_network.md → Troubleshooting checklist](cross_network.md#troubleshooting-checklist).

## 4. Live script (~12 minutes)

Keep **S's server log on the projector**: every event is timestamped there.

### Act 1: TCP, normal game (3 min)

| Who | Do |
|---|---|
| S | `python -m tcp.server --port 5050` |
| A | `python -m client_ui.ui --proto tcp --host S_IP --port 5050 --name alice --room demo` |
| B | same with `--name bob` |
| C | same with `--name carol` |
| A, B, C | press **R** (ready) → game starts when all 3 are ready |

Say:
- Server log: CONNECT → LOGIN → JOIN → READY → GAME_START.
- The server is authoritative: clients only send INPUT; the server ticks 10×/s and sends the full STATE.
- TCP framing: newline-delimited JSON. We never assume one `recv()` = one message.
- Point at the **RTT** in the corner of a client window.

### Act 2: kill a client, no goodbye (2 min)

| Who | Do |
|---|---|
| C | crash carol: macOS/Linux `pkill -9 -f client_ui.ui` · Windows: Task Manager → python.exe → End task, or `taskkill /F /IM python.exe` (kills every Python on C) |

Say:
- S's log: `PLAYER_LEFT carol … (connection closed by peer (FIN))`, detected **within milliseconds**:
  when a process dies, its OS closes the TCP connection for it.
- A and B see "carol left"; the game continues with 2 players; the server did not crash.
- (Optional) Freeze instead of kill: `kill -STOP <pid>` on C → no FIN, so it takes the
  **5 s heartbeat timeout**. That's why we need heartbeats even with TCP. `kill -CONT <pid>` afterwards.

Let the game finish or restart: **Enter** after GAME_OVER, everyone **R** again.

### Act 3: UDP, clean then with 30 % loss (4 min)

| Who | Do |
|---|---|
| S | Ctrl-C the TCP server (or leave it: both can run at once), then `python -m udp.server --port 5050` |
| A, B, C | `python -m client_ui.ui --proto udp --host S_IP --port 5050 --name alice --room demo` (bob, carol) → **R** |
| C | kill carol again (`pkill -9 -f client_ui.ui`) |

Say:
- UDP has no connection: nobody tells the server carol is gone. It notices after the **4 s
  heartbeat timeout** (`PLAYER_LEFT carol … heartbeat timeout`). Compare with TCP's milliseconds.

Then add loss on every side:

| Who | Do |
|---|---|
| S | Ctrl-C, then `python -m udp.server --port 5050 --drop 0.3` |
| A, B, C | `python -m client_ui.ui --proto udp --host S_IP --port 5050 --drop 0.3 --name …` → **R** |

Say:
- 30 % of the datagrams each side sends are thrown away (`--drop` simulates loss).
- The HUD shows **`lost ~30 %`**: those STATE snapshots are simply skipped; the client draws
  the next one. Movement is choppier, but it never freezes and never falls behind.
- Login, join and ready still worked: lobby messages are **reliable** (seq + ACK + resend
  every 200 ms, duplicates ignored, delivered in order). STATE and INPUT are not, on purpose.

### Act 4: TCP with 30 % loss (3 min)

`--drop` can't do this: TCP never loses data at the application level. Loss must happen in the
**kernel**, below TCP. Apply it on S (rehearse this the day before; it needs `sudo`):

| S is… | Turn loss on | Turn it off |
|---|---|---|
| macOS | `sudo sh metrics/netloss_mac.sh on 5050 0.3 0 en0` | `sudo sh metrics/netloss_mac.sh off` |
| Linux (incl. cloud VM) | see the block below | `sudo tc qdisc del dev IFACE root` |

On macOS the script drops 30 % in **both** directions (client→S and S→client);
the Linux block below drops only what S sends. Say which one you used.

Linux: drop 30 % of what S **sends from port 5050** (STATE, the bulk of the traffic); find
`IFACE` with `ip -4 route get 1.1.1.1` (the word after `dev`):
```bash
sudo tc qdisc add dev IFACE root handle 1: prio
sudo tc qdisc add dev IFACE parent 1:3 handle 30: netem loss 30%
sudo tc filter add dev IFACE parent 1:0 protocol ip u32 match ip sport 5050 0xffff flowid 1:3
```
(Only port 5050 is affected, so your SSH session stays usable.)

| Who | Do |
|---|---|
| S | `python -m tcp.server --port 5050` (with the loss on) |
| A, B, C | `--proto tcp` clients as in Act 1 → **R** |

Say:
- Nothing is ever missing (TCP retransmits), but the game **freezes and then jumps**:
  one lost segment holds back everything behind it until it's resent. That's
  **head-of-line blocking**. For a real-time game, an old STATE is worthless; UDP's
  "skip it" behaviour is better.
- **Turn the loss off right after** (`… off` / `tc qdisc del …`).

### Act 5: numbers (1 min)

Show `metrics/charts/` (from `python metrics/run_benchmark.py`). These numbers were measured on
**one machine (loopback)**: RTT there is ~1 ms; point at the RTT in a client window for the
real Wi-Fi value.
- `inter_update.png`: time between updates; UDP's spread grows with loss.
- `udp_loss.png`: missing ticks ≈ loss rate; only a handful of reliable resends.
- `detection.png`: TCP < 1 ms vs UDP ~4 s after a SIGKILL.
- `rtt.png`: RTT is the same for both; loss doesn't show in RTT.

The TCP 10 % / 30 % rows of `metrics/results.csv` are empty until you run
`sudo -v && python metrics/run_benchmark.py --loss-method os` on a Mac; only then do the
`*_os.png` charts (TCP under kernel loss) exist.

## 5. Plan B

- **Clients can't reach S** → everyone joins the phone hotspot; re-check `S_IP` (it changes!).
- **Still nothing** → run everything on S: server in one terminal, then
  `python -m client_ui.ui --proto tcp --name alice --room demo` (host defaults to
  127.0.0.1) plus two bots: `python -m client_ui.bot --proto tcp --name bob --room demo --players 3`
  and the same for carol. The whole script still works, apart from it being one machine.
- **Port 5050 busy on S** → `lsof -nP -i :5050` (macOS/Linux) or `netstat -ano | findstr :5050`
  (Windows) to find the old server,
  or use `--port 5051` everywhere. (On a Mac never use 5000: AirPlay.)
- **"name already taken"** after a crash → wait 5 s (TCP) / 4 s (UDP heartbeat) or pick another name.

## 6. After the demo

- [ ] Loss off on S (`netloss_mac.sh off` / `tc qdisc del …`), check with `… status`.
- [ ] Remove Windows firewall rules / cloud ingress rules if you added them.
- [ ] Stop servers (Ctrl-C, or `pkill -f tcp.server; pkill -f udp.server`).
