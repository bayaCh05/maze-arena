# Demo scenarios: Friday 13 November 2026

The live part of the 20-minute talk: slides 13-19 of `slides/maze_arena_tcp_vs_udp.pptx`.
Five short tests. Each line is **what we try → what should happen**. Run every test **once in the
morning** on the real laptops and the real network (section 1), then live (section 2).

| Laptop | Who | Job in the demo |
|---|---|---|
| **S** | Yassine Friaa | runs the servers, server log on the projector; also plays **dave** (a 4th player) in test 1 |
| **A** | Baya Chaabene | plays **alice** |
| **B** | Mohamed Aziz Souissi | plays **bob**; turns Wi-Fi off in test 5 |
| **C** | Yahia Mahfoudh | plays **carol**; carol's game is killed in tests 2 and 3 |

`S_IP` = the address S's server prints at startup. Port **5050**. Games last **60 s**.
Run every command in the `maze-arena` folder with the venv active
(`source .venv/bin/activate`, Windows `.venv\Scripts\Activate.ps1`).
Windows versions of the commands: [FOUR_PC_TEST.md](FOUR_PC_TEST.md).

The client command, used everywhere below (change `--proto`, `--name`):
```
python -m client_ui.ui --proto tcp --host S_IP --port 5050 --name alice --room demo
```
Kill a game (no goodbye): `pkill -9 -f client_ui.ui` in a second terminal (macOS/Linux).

All expected results were checked against the real servers on 2026-11-12 (one machine).

---

## 1. Morning check (30 min, before the talk)

- [ ] Same network for all 4 (not a "Guest" Wi-Fi), **no VPN**, S plugged in, `caffeinate -dims` on S.
- [ ] `git pull` on all 4, same commit (`git log -1 --oneline`).
- [ ] S: `bash scripts/deploy_stop.sh` if the public deployment runs (it uses port 5050).
- [ ] S: start both servers once, click **Allow** on the macOS firewall prompt.
- [ ] A, B, C: `python scripts/netcheck.py --host S_IP --port 5050` → **TCP OK** and **UDP OK**.
      Both time out → Wi-Fi isolation: everyone joins a phone hotspot (a 5th phone), S restarts the servers, new `S_IP`.
- [ ] Run tests 1 to 5 below once. Tick each box.
- [ ] Projector: S's terminal font large (Cmd +); slides on another laptop or as the PDF.

---

## 2. The five tests

### Test 1 (TCP): joining rules, the server says no

S starts `python -u -m tcp.server --port 5050`.

| # | What we try | What should happen | ✓ |
|---|---|---|---|
| 1 | A and B both start the client with `--name alice` and press Enter **at the same moment** | Only one gets in. The other sees **"Login refused: name already taken"**; S's log: `LOGIN_FAIL ... name 'alice' taken`. That laptop restarts with `--name bob` (the one that got in keeps alice) | [ ] |
| 2 | C joins with `--name carol` → the room has 3 players. Then S starts a 4th client, `--name dave` | dave sees **"Room is full"** | [ ] |
| 3 | Only alice and bob press **R** | **Nothing starts**: the room shows carol not ready | [ ] |
| 4 | carol presses **R**; then dave tries to join `demo` again (Enter on the room in the lobby) | The game starts; dave sees **"Game already running"** | [ ] |

### Test 2 (TCP): playing, then a crash (same game as test 1)

| # | What we try | What should happen | ✓ |
|---|---|---|---|
| 1 | Everyone plays | Same maze, scores and timer on the 3 screens; `TCP RTT n ms` (a few ms) in the corner | [ ] |
| 2 | At **0:40 left**, C runs `pkill -9 -f client_ui.ui` | S's log, **same second**: `PLAYER_LEFT carol ... (connection closed by peer (FIN))`; A and B see "carol left the game" and keep playing | [ ] |
| 3 | C starts the client again with `--name carol` straight away | **Accepted** (the old carol is already gone) | [ ] |
| 4 | The timer reaches 0:00 | Same ranking and winner on A's and B's screens; S's log: `GAME_OVER ... ranking` | [ ] |

### Test 3 (UDP): the same game over UDP, then a crash

S starts `python -u -m udp.server --port 5050` (the TCP server can keep running).
A, B, C close their client and start it with `--proto udp`. Everyone presses **R**.

| # | What we try | What should happen | ✓ |
|---|---|---|---|
| 1 | Everyone plays | S's log: `NEW PEER <ip>:<port>` (no CONNECT: no connection); corner: `lost 0 % of updates` | [ ] |
| 2 | At **0:40 left**, C runs `pkill -9 -f client_ui.ui` | Nothing at first; **about 4 s later**: `PLAYER_LEFT carol ... (heartbeat timeout (4.x s without a datagram))` | [ ] |
| 3 | C restarts the client with `--name carol` **straight away** (before the 4 s) | **Refused: "name already taken"** (the server still thinks the old carol is there) | [ ] |
| 4 | C tries again after the 4 s | **Accepted** | [ ] |

### Test 4 (UDP): 30 % of packets lost

S: Ctrl-C the UDP server, then `python -u -m udp.server --port 5050 --drop 0.3`.
A, B, C: restart the client with `--proto udp --drop 0.3`.

| # | What we try | What should happen | ✓ |
|---|---|---|---|
| 1 | Start everything with `--drop 0.3` | S's first line: `listening on 0.0.0.0:5050 (UDP), drop=30%` | [ ] |
| 2 | Log in, join, press **R** | Still works, maybe after a short pause (lost messages are resent) | [ ] |
| 3 | Play the whole game | Corner: `lost ~30 % of updates`; moves jump but never stop; nobody is kicked | [ ] |
| 4 | After GAME_OVER, Ctrl-C on S | Last line: `reliability stats: {... 'retransmissions': >0 ... 'gave_up': 0 ...}` | [ ] |

S restarts the UDP server **without** `--drop` afterwards.

### Test 5 (TCP): Wi-Fi off in the middle of a game

A, B, C start the client with `--proto tcp` again. Everyone presses **R**.

| # | What we try | What should happen | ✓ |
|---|---|---|---|
| 1 | Play | A normal game | [ ] |
| 2 | At **0:40 left**, B turns **Wi-Fi off** (menu bar) and leaves the game open | On A and C, bob stops moving | [ ] |
| 3 | Wait | **About 5 s later**: "bob left the game"; S's log: `PLAYER_LEFT bob ... (heartbeat timeout (5.x s without a message))`; the game goes on | [ ] |
| 4 | Look at B's window | "server silent for 5 s" | [ ] |
| 5 | B turns Wi-Fi back on | (needed for the rest of the talk) | [ ] |

---

## 3. Extras, only if ahead of time

**TCP with 30 % loss** (S is a Mac, needs `sudo`):
`sudo sh metrics/netloss_mac.sh on 5050 0.3 0 en0`, then a TCP game.
- [ ] The game freezes and jumps (head-of-line blocking); nothing is lost.
- [ ] **Turn it off right after:** `sudo sh metrics/netloss_mac.sh off`.

**A player on another network** (TCP through Cloudflare):
S runs `bash scripts/deploy_start.sh`; one teammate on a phone hotspot runs `bash scripts/join_tcp.sh`
(Windows `scripts\join_tcp.bat`).
- [ ] `curl -4 ifconfig.me` on that laptop shows a different public IP than S.
- [ ] The game works; RTT higher than on the Wi-Fi.
- [ ] If it fails in the morning check, skip it live (slide 27 covers it).

---

## 4. If something goes wrong live

| Problem | Do |
|---|---|
| A laptop can't connect | Play on S with two bots: `python -m client_ui.bot --proto tcp --name bob --room demo --players 3` (and carol); keep going |
| "name already taken" when nobody else uses it | The server still holds the old session: wait 5 s (TCP) / 4 s (UDP) and log in again |
| Port 5050 busy on S | `lsof -nP -i :5050`, stop the old server; or `--port 5051` everywhere |
| Running late | Skip test 5 and the extras; slide 12 explains the Wi-Fi case |
| Nothing works | Show the measured numbers (slides 22-24) |
