# 4-computer test: 1 server + 3 clients

> **Today's live demo (13 Nov) follows [demo_scenarios.md](demo_scenarios.md)**: server on Yassine's
> PC over Tailscale (`100.66.86.49`), TCP port 5050, UDP port **5051**, players Baya, Yahia, Aziz.
> This file is the general LAN / cross-network reference.

A script for 4 people on 4 laptops, to run **before** the demo so it works the first time.
About 30 minutes. Tick each box as you go; if a check fails, stop and look at
[Common problems](#common-problems-going-from-2-to-4-machines).

| Laptop | Person | Job |
|---|---|---|
| **S** | server | runs the TCP and UDP servers, reads the server log aloud |
| **A** | client 1, name `alice` | player |
| **B** | client 2, name `bob` | player; turns off Wi-Fi in step 6 |
| **C** | client 3, name `carol` | player; kills its client in step 2 |

`S_IP` below = the address S's server prints at startup (e.g. `192.168.1.20`). Port **5050**
for both TCP and UDP. Games last **60 s**. Every command runs from the `maze-arena` folder
with the venv active:

| | macOS | Windows (PowerShell) |
|---|---|---|
| go to the repo | `cd ~/maze-arena` | `cd $HOME\maze-arena` (or wherever you cloned it) |
| activate the venv | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| make the log folder | `mkdir -p logs/four_pc` | `mkdir -Force logs\four_pc` |

Every command below copies its output into `logs/four_pc/` (`tee` on macOS, `Tee-Object`
on Windows), so `collect_logs` can zip it at the end.

---

## 0. Before we start

All 4 laptops:

- [ ] **Same network.** Everyone on the same Wi-Fi (not a "Guest" network). The first three
      numbers of each laptop's IP must match S's (e.g. all `192.168.1.x`).
      macOS `ipconfig getifaddr en0` · Windows `ipconfig` → "IPv4 Address".
- [ ] **Same code.** `git pull`, then `git log -1 --oneline`: **the same commit on all 4**.
      Clients print `code version (commit) xxxxxxx` at startup and S's server prints
      `Code version (commit): xxxxxxx`: they must match. `+changes` means someone edited files:
      `git stash` (or re-clone). Zip downloads show `unknown (no git)`: prefer `git clone`.
- [ ] **Dependencies.** `pip install -r requirements.txt` done; `python local_demo.py` opens a
      window (then close it).
- [ ] **No VPN** on any laptop (NordVPN, Proton, Cloudflare WARP, a school/work VPN...). Turn it off.
- [ ] **Unique names**: alice, bob, carol (1-12 characters).

Laptop S only:

- [ ] Plugged in, sleep off (macOS: `caffeinate -dims` in a spare terminal; Windows: Power settings).
- [ ] Nothing else on port 5050. If S also runs the public deployment:
      `bash scripts/deploy_stop.sh`. Check: macOS `lsof -nP -i :5050` · Windows
      `netstat -ano | findstr :5050` → nothing.
- [ ] Start both servers, each in its own terminal (keep them open the whole test):

| | macOS | Windows |
|---|---|---|
| S, terminal 1 (TCP) | `python -u -m tcp.server --port 5050 2>&1 \| tee logs/four_pc/tcp_server.log` | `python -u -m tcp.server --port 5050 2>&1 \| Tee-Object logs\four_pc\tcp_server.log` |
| S, terminal 2 (UDP) | `python -u -m udp.server --port 5050 2>&1 \| tee logs/four_pc/udp_server.log` | `python -u -m udp.server --port 5050 2>&1 \| Tee-Object logs\four_pc\udp_server.log` |

  (Windows PowerShell may print stderr lines in red: harmless.)

- [ ] **Firewall prompt accepted.** macOS: "Do you want Python to accept incoming network
      connections?" → **Allow** (missed it: System Settings → Network → Firewall → Options →
      Python → Allow). Windows: Defender prompt → tick **Private networks** → Allow, and the
      Wi-Fi must be a **Private** network (Settings → Network & internet → Wi-Fi → this network →
      Network profile type → Private).
- [ ] Read `S_IP` from the banner (`Players connect to ONE of these addresses`) and post it in the
      group chat. Note the commit line too.

Laptops A, B, C:

- [ ] Firewall prompt accepted if one appears (same as above; clients usually get none).
- [ ] **netcheck OK:** `python scripts/netcheck.py --host S_IP --port 5050`
      → ends with **TCP OK** and **UDP OK** and an RTT of a few ms.
      - `refused` → the server isn't running on S, or wrong port.
      - `timeout` for both → firewall on S, or **Wi-Fi isolation** (the router blocks laptops from
        talking to each other; common on campus and café Wi-Fi). Check: `ping S_IP` also fails.
        **Fix: everyone joins a phone hotspot** (a 5th phone, not one of the players' laptops),
        S restarts both servers (the IP changes: post the new `S_IP`), redo netcheck.
      - TCP OK but UDP timeout → a firewall allows TCP but not UDP on S (Windows: allow Python for
        Private networks again; macOS: the Python app must be allowed, not just one port).

---

## 1. TCP: full game

| Who | macOS | Windows |
|---|---|---|
| A | `python -u -m client_ui.ui --proto tcp --host S_IP --port 5050 --name alice --room test 2>&1 \| tee -a logs/four_pc/client.log` | `python -u -m client_ui.ui --proto tcp --host S_IP --port 5050 --name alice --room test 2>&1 \| Tee-Object -Append logs\four_pc\client.log` |
| B | same with `--name bob` | same with `--name bob` |
| C | same with `--name carol` | same with `--name carol` |

All three press **R** (ready). Play the 60 s.

- [ ] On screen: 3 colored players, the same maze on all laptops, moves are smooth, the HUD
      shows `TCP RTT n ms` (a few ms on a LAN), the timer counts down from 1:00.
- [ ] Results screen on all 3: the same ranking and winner.
- [ ] S's TCP log, one line each:
      `CONNECT <A_IP>:<port>` and `LOGIN alice@<A_IP>:<port>` (×3, with **three different IPs**),
      `JOIN alice@... -> room 'test' (1/3 players)` ... `(3/3 players)`,
      `GAME_START room 'test', 60 s, players: alice@..., bob@..., carol@...`,
      `GAME_OVER room 'test' tick=600 winner=...@... ranking: 1. ... 2. ... 3. ...`.

## 2. TCP: kill one client mid-game

Everyone stays in the room and presses **R** again (or restart the clients as in step 1).
About 20 s into the game, **C** kills its client (no goodbye message):

| | macOS | Windows |
|---|---|---|
| C, in a 2nd terminal | `pkill -9 -f client_ui.ui` | `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| Where-Object CommandLine -match 'client_ui' \| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }` |

- [ ] A and B: `carol left the game` at the top of the window; **the game continues** with 2 players until 1:00 runs out.
- [ ] S's TCP log, **within the same second** as the kill:
      `PLAYER_LEFT carol@<C_IP>:<port> from room 'test' (connection closed by peer (FIN)) during game`
      (or `(RST)`): the operating system on C closed the TCP connection for the killed process.
- [ ] The server is still running; GAME_OVER arrives normally for A and B.
- [ ] C restarts its client (step 1 command) and logs in as carol again: works (no "name taken").

## 3. UDP: full game

A, B, C close their TCP client (Esc / close the window) and start the UDP one:

| Who | macOS | Windows |
|---|---|---|
| A | `python -u -m client_ui.ui --proto udp --host S_IP --port 5050 --name alice --room test 2>&1 \| tee -a logs/four_pc/client.log` | `python -u -m client_ui.ui --proto udp --host S_IP --port 5050 --name alice --room test 2>&1 \| Tee-Object -Append logs\four_pc\client.log` |
| B, C | same with `bob`, `carol` | same |

All press **R**, play the 60 s.

- [ ] On screen: same as step 1; HUD shows `UDP RTT n ms` and `lost 0 % of updates` on a good LAN.
- [ ] S's **UDP** log (terminal 2): `NEW PEER <A_IP>:<port>` (UDP has no connection: the server
      just sees datagrams from a new address) then `LOGIN alice@<A_IP>:<port>` (×3, three IPs),
      `JOIN`, `GAME_START room 'test', 60 s, players: ...`, `GAME_OVER room 'test' tick=600 ...`.
- [ ] Optional: C kills its client again (step 2 command). S's UDP log after **~4 s**:
      `PLAYER_LEFT carol@... (heartbeat timeout (4.x s without a datagram)) during game`.
      Compare with TCP's same-second FIN: UDP has nothing to close, only silence.

## 4. UDP with 30 % packet loss

S: in terminal 2, **Ctrl-C** the UDP server, then restart it with loss on everything it sends:

| | macOS | Windows |
|---|---|---|
| S, terminal 2 | `python -u -m udp.server --port 5050 --drop 0.3 2>&1 \| tee logs/four_pc/udp_server_drop30.log` | `python -u -m udp.server --port 5050 --drop 0.3 2>&1 \| Tee-Object logs\four_pc\udp_server_drop30.log` |

A, B, C: restart the UDP client (step 3 command) adding `--drop 0.3` (loss on what they send too).
Press **R**, play the 60 s.

- [ ] Banner/log first line on S: `listening on 0.0.0.0:5050 (UDP), drop=30%`.
- [ ] On screen: the game **still works**: login, room, start and results all arrive (they are
      sent reliably: seq + ACK + retransmit); movement skips frames, the HUD shows
      `lost ~30 % of updates`. No one is disconnected.
- [ ] Results screen identical on all 3.
- [ ] S, after the game: **Ctrl-C** terminal 2. The last log line `reliability stats: {...}` shows
      `retransmissions` > 0 and `gave_up` 0 (or close to 0) while all clients were still running.
      (`GAVE UP on ... after retries` lines **after** a client quit are normal: nobody is left to ACK.)
- [ ] S restarts the UDP server **without** `--drop` (step 0 command) for the next steps.

## 5. (Back to TCP) all 3 clients connected

A, B, C: start the **TCP** client again (step 1 command). All press **R**.

## 6. Turn off a laptop's Wi-Fi mid-game

About 20 s into the game, **B** turns Wi-Fi off (macOS: menu bar Wi-Fi → off · Windows: taskbar
network icon → Wi-Fi off). Don't close the client.

- [ ] A and C: bob stops moving; after ~5 s `bob left the game`; **the game continues**.
- [ ] S's TCP log after **~5 s** (not instantly: with no network, B's laptop can't send a FIN):
      `PLAYER_LEFT bob@<B_IP>:<port> from room 'test' (heartbeat timeout (5.x s without a message)) during game`.
      This is the heartbeat (PING every 1 s) catching a dead connection that TCP alone would keep
      "open" for minutes.
- [ ] B's own window: after ~5 s, `server silent for 5 s` (the client detects it too).
- [ ] B turns Wi-Fi back on, restarts the client, logs in as bob: works.
- [ ] Optional: the same with the UDP client: ~4 s, `heartbeat timeout (... without a datagram)`.

## 7. After the test: collect the logs

Every laptop (S, A, B, C):

| | macOS | Windows |
|---|---|---|
| S | `bash scripts/collect_logs.sh S` | `scripts\collect_logs.bat S` |
| A | `bash scripts/collect_logs.sh A` | `scripts\collect_logs.bat A` |
| B | `bash scripts/collect_logs.sh B` | `scripts\collect_logs.bat B` |
| C | `bash scripts/collect_logs.sh C` | `scripts\collect_logs.bat C` |

- [ ] Each prints `Saved .../logs/four_pc_<ROLE>_<laptop>_<date>.zip`: send the 4 zips to the
      group (WhatsApp, AirDrop, USB). Each has that laptop's logs plus `system_info.txt`
      (IP, Wi-Fi, VPN adapters, Python version, **commit**). No passwords or keys are included.
- [ ] S: if it ran the public deployment before, start it again: `bash scripts/deploy_start.sh`.

### Result

| Step | TCP | UDP |
|---|---|---|
| full game, 3 clients on 3 laptops | [ ] | [ ] |
| kill a client mid-game | [ ] FIN, same second | [ ] heartbeat, ~4 s (optional) |
| 30 % loss | (benchmark: `scripts/tcp_loss_benchmark.sh`) | [ ] |
| Wi-Fi off mid-game | [ ] heartbeat, ~5 s | [ ] (optional) |

---

## Common problems going from 2 to 4 machines

| Symptom | Cause | Fix |
|---|---|---|
| One laptop's netcheck times out, the other two are OK | That laptop is on **another network or band**: "Box-5G" vs "Box" is usually the same network, but a **Guest** SSID, a mesh extender or a phone hotspot is not. Its IP prefix differs from S's. | Join exactly the same SSID as S; compare the first three numbers of the IPs. |
| One laptop can't reach S although the IPs look right | A **VPN** on that laptop sends all traffic away (corporate VPN, NordVPN, Proton, Cloudflare WARP). | Turn the VPN off fully (quit the app), redo netcheck. `collect_logs` lists VPN adapters in `system_info.txt`. |
| Worked with 2 machines, fails when S is a Windows laptop on new Wi-Fi | Windows marked the new Wi-Fi as a **Public network**: the firewall blocks incoming connections even though Python was allowed for Private. | Set the network to **Private** (Settings → Network & internet → Wi-Fi → network → Private), or allow Python on Public networks in Windows Defender Firewall. Restart the servers. |
| `That name is taken` / `LOGIN_FAIL ... taken` on S | **Two clients with the same name**, or a client restarted before the server dropped its old session. | Use alice/bob/carol; after a crash wait 5 s (TCP) or 4 s (UDP) and log in again. |
| Odd errors, different maze/colors, a client crashes on a message | **Old copy of the repo** on one laptop. | Compare the `code version (commit)` line printed by each client with S's banner. Different → `git pull` (or re-clone) on that laptop. |
| Everyone times out, `ping S_IP` fails, but each laptop has internet | **Wi-Fi client isolation** (campus/café/hotel Wi-Fi). | Phone hotspot for all 4; S restarts the servers and posts the new `S_IP`. |
| S's server says the port is in use | The public deployment (or an old server) still runs on 5050. | `bash scripts/deploy_stop.sh`, or find the process: macOS `lsof -nP -i :5050`, Windows `netstat -ano \| findstr :5050` → `taskkill /PID <pid> /F`. |
| A client freezes now and then on S's side, S's screen went dark | S went to **sleep**. | Plug S in, `caffeinate -dims` (macOS) / disable sleep (Windows). |
