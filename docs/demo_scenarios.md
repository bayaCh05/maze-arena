# Demo scenarios: Friday 13 November 2026

The live part of the 20-minute talk (slides 13-18 of `slides/maze_arena_tcp_vs_udp.pptx`).
Four short games, each proving one thing. Run all of them **once in the morning** on the real
laptops and the real network (section 1), then again live (section 2).

| Laptop | Who | Job in the demo |
|---|---|---|
| **S** | Presenter 3 | runs the servers; the server log is on the projector |
| **A** | Presenter 1 | plays `alice` |
| **B** | Presenter 2 | plays `bob`; turns Wi-Fi off in game 4 |
| **C** | Presenter 4 | plays `carol`; its game is killed in games 1 and 2 |

`S_IP` = the address S's server prints at startup. Port **5050**. Games last **60 s**.
Every command runs in the `maze-arena` folder with the venv active
(`source .venv/bin/activate`, Windows `.venv\Scripts\Activate.ps1`).
Windows versions of every command: [FOUR_PC_TEST.md](FOUR_PC_TEST.md).

---

## 1. Morning check (30 min, before the talk)

- [ ] Same network for all 4 (not a "Guest" Wi-Fi), **no VPN**, S plugged in, `caffeinate -dims` on S.
- [ ] `git pull` on all 4, same commit (`git log -1 --oneline`).
- [ ] S: `bash scripts/deploy_stop.sh` if the public deployment runs (it uses port 5050).
- [ ] S: start both servers once and click **Allow** on the macOS firewall prompt.
- [ ] A, B, C: `python scripts/netcheck.py --host S_IP --port 5050` → **TCP OK** and **UDP OK**.
      Both time out → Wi-Fi isolation: everyone joins a phone hotspot (a 5th phone), S restarts the servers, new `S_IP`.
- [ ] Play games 1 to 4 below once, start to end. Tick the boxes.
- [ ] Projector: S's terminal font large (Cmd +), the slides open on a second laptop or as the PDF.
- [ ] Optional extras: `sudo -v` on S works (TCP loss); a teammate on a phone hotspot can run `scripts/join_tcp.sh`.

---

## 2. The four games

### Game 1: TCP, a normal game, then a crash (2 min)

| Who | Command |
|---|---|
| S | `python -u -m tcp.server --port 5050` |
| A | `python -m client_ui.ui --proto tcp --host S_IP --port 5050 --name alice --room demo` |
| B | first the same command with `--name alice` → "name already taken", close it; then `--name bob` |
| C | same with `--name carol` |

All three press **R**. At **0:40 left**, C runs `pkill -9 -f client_ui.ui` in a second terminal.

Check:
- [ ] B's wrong login: "name already taken"; S's log shows `LOGIN_FAIL`.
- [ ] S's log: `CONNECT` and `LOGIN` from **3 different IP addresses**, `GAME_START room 'demo'`.
- [ ] Same maze, same scores on the 3 screens; `TCP  RTT n ms` in the corner (a few ms).
- [ ] S's log, **same second** as the kill: `PLAYER_LEFT carol ... (connection closed by peer (FIN))`.
- [ ] A and B: "carol left the game", the game goes on, same results screen on both.

### Game 2: UDP, the same game, then a crash (1 min 40)

| Who | Command |
|---|---|
| S | Ctrl-C the TCP server (or keep it), `python -u -m udp.server --port 5050` |
| A, B, C | `python -m client_ui.ui --proto udp --host S_IP --port 5050 --name alice --room demo` (bob, carol) |

All press **R**. At **0:40 left**, C runs `pkill -9 -f client_ui.ui`.

- [ ] S's log: `NEW PEER <ip>:<port>` (no CONNECT: there is no connection).
- [ ] Corner: `UDP  RTT n ms` and `lost 0 % of updates`.
- [ ] S's log **about 4 s** after the kill: `PLAYER_LEFT carol ... (heartbeat timeout (4.x s without a datagram))`.

### Game 3: UDP with 30 % packet loss (1 min 50)

| Who | Command |
|---|---|
| S | Ctrl-C, `python -u -m udp.server --port 5050 --drop 0.3` |
| A, B, C | `python -m client_ui.ui --proto udp --host S_IP --port 5050 --drop 0.3 --name alice --room demo` (bob, carol) |

- [ ] S's first line: `listening on 0.0.0.0:5050 (UDP), drop=30%`.
- [ ] Login, room and ready work (maybe a short pause: a resend).
- [ ] Corner: `lost ~30 % of updates`; movement is jumpier but never stops; nobody is kicked.
- [ ] After GAME_OVER, Ctrl-C on S: `reliability stats: {... 'retransmissions': >0, ... 'gave_up': 0 ...}`.
- [ ] S restarts the UDP server **without** `--drop`.

### Game 4: TCP, Wi-Fi off in the middle (1 min 40)

A, B, C start the **TCP** client again (game 1 commands), all press **R**.
At **0:40 left**, B turns **Wi-Fi off** (menu bar) and leaves the game window open.

- [ ] On A and C: bob stops moving; **about 5 s later** "bob left the game"; the game goes on.
- [ ] S's log: `PLAYER_LEFT bob ... (heartbeat timeout (5.x s without a message))`.
- [ ] B's window: "server silent for 5 s".
- [ ] B turns Wi-Fi back on (needed for the rest of the talk).

---

## 3. Extras, only if ahead of time

**TCP with 30 % loss** (S is a Mac, needs `sudo`):
`sudo sh metrics/netloss_mac.sh on 5050 0.3 0 en0`, then a TCP game as in game 1.
- [ ] The game freezes and jumps (head-of-line blocking); nothing is lost.
- [ ] **Turn it off right after:** `sudo sh metrics/netloss_mac.sh off`.

**A player on another network** (TCP through Cloudflare):
S runs `bash scripts/deploy_start.sh`; one teammate on a phone hotspot runs `bash scripts/join_tcp.sh`
(Windows `scripts\join_tcp.bat`).
- [ ] `curl -4 ifconfig.me` on that laptop shows a different public IP than S.
- [ ] The game works; RTT higher than on the Wi-Fi.
- [ ] If it doesn't work in the morning check: skip it and say "UDP and TCP across networks are
      on slide 24" instead of trying live.

---

## 4. If something goes wrong live

| Problem | Do |
|---|---|
| A laptop can't connect | Run the game on S with two bots: `python -m client_ui.bot --proto tcp --name bob --room demo --players 3` (and carol); keep going |
| "name already taken" after a crash | Wait 5 s (TCP) / 4 s (UDP), or use another name |
| Port 5050 busy on S | `lsof -nP -i :5050`, stop the old server; or `--port 5051` everywhere |
| Running late | Skip game 4 and the extras; slide 12 explains the Wi-Fi case |
| Nothing works | Show the recorded numbers (slides 19-21) and the 3-bot rehearsal logs |
