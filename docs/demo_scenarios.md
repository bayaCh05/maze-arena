# Demo scenarios: Friday 13 November 2026

The live part of the 20-minute talk: slides 12-17 of `slides/maze_arena_tcp_vs_udp.pptx`.
Three tests, in this order: **TCP → UDP → UDP with 30 % loss**. Each line is
**what we do → what you should see**. Run every test **once in the morning** on the real laptops
(section 1), then live (section 2). Matches the team's sheet *Maze Arena — Network Demonstration
Commands*.

| Laptop | Who | Job in the demo |
|---|---|---|
| **S** (Windows) | Yassine Friaa | runs the servers; server log and Wireshark on the projector |
| **1** | Baya Chaabene | plays **Baya** |
| **2** | Yahia Mahfoudh | plays **Yahia**; tells the demo (slides 12-17) |
| **3** | Mohamed Aziz Souissi | plays **Aziz**; first tries the name "Baya" (test 1); Aziz's game is the one killed (tests 1 and 2) |

- All 4 laptops are in **one Tailscale network**. Server address: **`100.66.86.49`** (S's Tailscale IP).
- **TCP on port 5050, UDP on port 5051.** One protocol at a time: Ctrl-C the previous server first.
- Games last **60 s**. Every command runs in the `maze-arena` folder with the venv active
  (Windows `.\.venv\Scripts\Activate.ps1`, macOS `source .venv/bin/activate`).

## How to "crash" a game

Close the **terminal window that runs the game** (not the game window), or kill the process:
macOS `pkill -9 -f client_ui.ui`; Windows Task Manager → python → End task.

Why not the game window? Closing the game window on UDP sends a polite LEAVE_ROOM, so the server
removes the player at once and the 4 s UDP delay never shows. On TCP both ways give a FIN at once.

---

## 1. Morning check (30 min, before the talk)

- [ ] All 4: `git pull`, same commit (`git log -1 --oneline`).
- [ ] All 4: Tailscale connected. `tailscale status` lists the 4 machines;
      `tailscale ping 100.66.86.49` answers (it says `direct` or `via DERP`; both work).
- [ ] S: start the TCP server once and the UDP server once; Windows Defender prompt → allow Python
      (tick **Private** and **Public**: the Tailscale network can be classed as either).
- [ ] Players, with S's server running: `python scripts/netcheck.py --host 100.66.86.49 --port 5050`
      (TCP server) → **TCP OK**; same with `--port 5051` (UDP server) → **UDP OK**.
- [ ] S: Wireshark open on the **Tailscale** interface (on Wi-Fi you only see encrypted WireGuard).
- [ ] Run tests 1 to 3 once. Tick each box.
- [ ] Projector: S's terminal font large; slides from another laptop or the PDF.

---

## 2. The three tests

The player command (change `--proto`, `--port`, `--name`):
```
python -m client_ui.ui --proto tcp --host 100.66.86.49 --port 5050 --name Baya --room demo
```

### Test 1 (TCP): a normal game, then a crash

S: `python -m tcp.server --host 100.66.86.49 --port 5050` · Wireshark filter `tcp.port == 5050`

| # | What we do | What you should see | ✓ |
|---|---|---|---|
| 1 | Baya joins. Aziz starts with `--name Baya` | Aziz sees **"Login refused: name already taken"**; S: `LOGIN_FAIL ... name 'Baya' taken`. Aziz restarts with `--name Aziz` | [ ] |
| 2 | Yahia and Aziz join `demo`; all three press **R** | 3 × `CONNECT 100.x.x.x:port` (three different addresses); Wireshark: SYN, SYN-ACK, ACK for each; same maze and scores on 3 screens; `TCP RTT n ms` in the corner | [ ] |
| 3 | At **0:40 left**, Aziz closes the terminal of the game | S, **same second**: `PLAYER_LEFT Aziz ... (connection closed by peer (FIN))` (or `(RST)`); Wireshark: FIN or RST; Baya and Yahia see "Aziz left" and keep playing | [ ] |
| 4 | The timer reaches 0:00 | Same ranking on both screens; S: `GAME_OVER ... ranking` | [ ] |

### Test 2 (UDP): the same game, then a crash

S: Ctrl-C the TCP server, then `python -m udp.server --host 100.66.86.49 --port 5051` ·
Wireshark `udp.port == 5051`. Players close their game and restart with `--proto udp --port 5051`.

| # | What we do | What you should see | ✓ |
|---|---|---|---|
| 1 | All three join `demo`, press **R** | S: `NEW PEER 100.x.x.x:port` (no CONNECT: no connection); corner: `lost 0 % of updates` | [ ] |
| 2 | Look at Wireshark | No handshake: the first datagram is the LOGIN JSON; `{"type":"ACK","ack":n}` packets are **our** ACKs; filter `udp contains "rel"` = the important (reliable) messages | [ ] |
| 3 | At **0:40 left**, Aziz closes the terminal of the game | Nothing at first; **about 4 s later**: `PLAYER_LEFT Aziz ... (heartbeat timeout (4.x s without a datagram))` | [ ] |
| 4 | The timer reaches 0:00 | Same ranking on both screens | [ ] |

### Test 3 (UDP): 30 % of packets lost

S: Ctrl-C, then `python -m udp.server --host 100.66.86.49 --port 5051 --drop 0.3 --log-level DEBUG`.
Players restart their game with the **same command as test 2**.

`--drop 0.3` makes the **server** throw away 30 % of the datagrams it sends (players could add
`--drop 0.3` too; we keep their command unchanged). `--log-level DEBUG` prints one
`RETRANSMIT <type> seq=n ...` line per resend, so the safety net is visible live.

| # | What we do | What you should see | ✓ |
|---|---|---|---|
| 1 | Start the server | First line: `listening on 100.66.86.49:5051 (UDP), drop=30%` | [ ] |
| 2 | Log in, join, press **R** | Still works, maybe after a short pause; `RETRANSMIT LOGIN_OK seq=1 ...` lines | [ ] |
| 3 | Play the whole game | Corner: `lost ~30 % of updates`; moves jump but never stop; nobody is kicked | [ ] |
| 4 | At GAME_OVER, **before anyone closes their game**, Ctrl-C on S | Last line: `reliability stats: {'sent': N, 'dropped': ≈0.3·N, ..., 'retransmissions': >0, ..., 'gave_up': 0, ...}` | [ ] |

Stop the server **before** players close: a game closed after GAME_OVER can no longer ACK, so the
server's last messages to it end as `GAVE UP` warnings and `gave_up > 0` (harmless, but confusing
on the projector). Restart the UDP server **without** `--drop` afterwards.

---

## 3. Extras, only if ahead of time (slide 17)

**Wi-Fi off during a TCP game** (TCP server again):
- [ ] At 0:40 left, Aziz turns the Wi-Fi off and leaves the game open → Aziz stops moving on the
      other screens; **about 5 s later** `PLAYER_LEFT Aziz ... (heartbeat timeout (5.x s without a message))`;
      Aziz's window: "server silent for 5 s".
- [ ] Wi-Fi back on; Tailscale reconnects by itself (check `tailscale status`).

**Logging in again too fast on UDP**: Aziz keeps a second terminal with the UDP command typed,
kills the game and presses Enter at once → **"name already taken"** for about 4 s, then accepted.

---

## 4. If something goes wrong live

| Problem | Do |
|---|---|
| A player can't connect | `tailscale status` on that laptop; reconnect Tailscale. Still stuck: that player plays on S with a bot: `python -m client_ui.bot --proto tcp --host 100.66.86.49 --port 5050 --name Aziz --room demo --players 3` |
| "name already taken" when nobody else uses it | The server still holds the old session: wait 5 s (TCP) / 4 s (UDP) and log in again |
| "game already running" | The room is in a game: wait for GAME_OVER, or use another `--room` |
| Port busy on S | Windows `netstat -ano \| findstr 5050` (or 5051), end that python; or use another port everywhere |
| Wireshark shows only WireGuard | Wrong interface: pick the one named **Tailscale** |
| Running late | Skip the extras (slide 17); slide 11 already explains the Wi-Fi case |
| Nothing works | Show the measured numbers: backup slides 22-24 |
