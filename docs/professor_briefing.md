# Maze Arena: briefing for the progress presentation (Fri 6 Nov 2026)

Written for you, the presenter. Every number below was measured on our code; where a number
only comes from one Mac (loopback), it says so. File references are `file → function`.

---

## 1. The project in 30 seconds

**What it is.** A Pac-Man-style maze game for 2-3 players over the network. Each player moves
around a 20 × 15 maze, eats pellets (10 points) and power pellets (50 points). A power pellet
lets you eat the other players for 5 seconds: the victim loses 50 points and respawns.
A game lasts 1 minute (server `--game-seconds`), or until all pellets are gone, or until one player is left.

**Why it's competitive.** The players are in the same maze at the same time and race for the
same pellets; whoever reaches a pellet first gets it, and a power pellet turns the others
into prey. So the outcome depends on who acts first, which is exactly what the network has
to get right and fair.

**What we built.** Two complete versions of the same game: one that uses **only TCP**, one that
uses **only UDP**. Both share 100 % of the game rules and the lobby/room logic; only the
transport layer differs. Around that: a pygame client, a headless bot, a test suite (111
test cases, a chaos test), a benchmark that measures RTT / update regularity / loss /
disconnect detection, and tools for playing across different networks.

---

## 2. Architecture

```
               ┌──────────────────────── server process ────────────────────────┐
               │                                                                 │
 client A ──┐  │  tcp/server.py  OR  udp/server.py      common/server_core.py    │
 client B ──┼──┼─▶ (bytes ⇄ message dicts)  ──handle()──▶ login, lobby, rooms,   │
 client C ──┘  │   one per version                       game loop (10 ticks/s)  │
               │                                          │                      │
               │                                          ▼                      │
               │                              common/game.py  common/rooms.py    │
               │                              (pure rules, no sockets)           │
               └─────────────────────────────────────────────────────────────────┘

 client process:  client_ui/ui.py (pygame)  ──send()/on_message()──▶  Transport
                                                                     ├─ tcp/client.py  TcpTransport
                                                                     └─ udp/client.py  UdpTransport
```

| Folder / file | Role |
|---|---|
| `common/game.py` | The rules: maze, movement (1 cell per tick, walls block), pellets, power, eating, end of game, ranking, winner. Plain dicts, no I/O. |
| `common/rooms.py` | Lobby state: create / join / leave rooms, ready flags, "can the game start?" (≥ 2 players, all ready). |
| `common/protocol.py` | Message type names, `make_msg`, JSON encode/decode, TCP framing buffer, UDP transport fields (`seq`, `ack`, `rel`). |
| `common/server_core.py` | Everything the server does that doesn't depend on TCP/UDP: handling each message, rooms, starting/ending games, the game thread (`GameRunner`), disconnect cleanup. |
| `common/transport.py` | The interface the UI uses: `send(msg)`, `on_message(callback)`, `poll()`. |
| `tcp/server.py`, `tcp/client.py` | TCP version: sockets, threads, framing. |
| `udp/server.py`, `udp/client.py`, `udp/reliability.py` | UDP version: one socket, sessions by address, our own seq/ACK reliability. |
| `client_ui/` | pygame window (`ui.py`, `render.py`, `sfx.py`), headless bot (`bot.py`), `connect.py` picks TCP or UDP. |
| `netutil/` | Server startup banner (IP addresses to give players), `--host` resolution, shared log/SIGTERM setup. |
| `scripts/` | `netcheck.py` (is the server reachable over TCP/UDP?), tunnel helper scripts. |
| `metrics/` | Benchmark, charts, packet-size measurement, results. |
| `tests/` | pytest suite + chaos test. |

**Why the game logic is shared and separated from networking.** The assignment asks for the
same game with identical rules in both versions. If each version had its own copy of the
rules, they would drift apart (that actually happened once: an eaten TCP player stopped,
a UDP player kept moving; fixed by making the rule independent of the transport). With one
copy, "identical rules" is true by construction. It also makes the rules testable without
any network (28 game tests run in milliseconds), and it makes the comparison fair: when we
measure TCP vs UDP, the *only* difference is the transport. The project rule is strict:
`common/` imports no socket, select or asyncio.

**Why the server is authoritative.** Clients only send their wish ("I want to go UP");
the server computes positions, pellets, collisions and scores and sends the result to
everyone. Reasons: (1) **fairness / one truth**: two clients can't disagree about who ate the
pellet, because only the server decides; (2) **no cheating** by a modified client (it can't
send "my score is 9999"); (3) **simple clients**: they only draw what they receive.
The cost: an action shows up only after a round trip (RTT + up to one tick).

**Tick rate: 10 ticks per second.** Every 100 ms the server applies the stored directions,
moves everyone one cell, resolves pellets and collisions, and broadcasts the full `STATE`.
10/s is enough for grid movement (one cell per tick) and keeps traffic small (3 players ×
10 STATE/s ≈ 37 kB/s from the server). The loop sleeps until the next 100 ms slot instead
of "sleep 100 ms", so it doesn't drift (`server_core.py → GameRunner.run`); measured mean
interval at the client: 100.0 ms, standard deviation 2.3-2.6 ms.

---

## 3. The message contract

Every message is one JSON object with a `"type"`. The same messages are used by both
versions (checked by `tests/test_format_parity.py`). The game layer never sees transport
fields; UDP adds `seq` / `ack` / `rel` around them (section 5).

| Message | Sender → receiver | When | Example |
|---|---|---|---|
| `LOGIN` | client → server | first thing after connecting | `{"type":"LOGIN","name":"alice"}` |
| `LOGIN_OK` | server → client | name accepted | `{"type":"LOGIN_OK","name":"alice"}` |
| `LOGIN_FAIL` | server → client | name invalid or taken | `{"type":"LOGIN_FAIL","reason":"name already taken"}` |
| `LIST_ROOMS` | client → server | lobby refresh | `{"type":"LIST_ROOMS"}` |
| `CREATE_ROOM` | client → server | create a room (then JOIN it) | `{"type":"CREATE_ROOM","room":"arena1"}` |
| `ROOM_LIST` | server → client | answer to LIST/CREATE/LEAVE; pushed to the lobby on any change; with `error` when a request is refused | `{"type":"ROOM_LIST","rooms":[{"room":"arena1","players":2,"max_players":3,"in_game":false}]}` |
| `JOIN_ROOM` | client → server | enter a room | `{"type":"JOIN_ROOM","room":"arena1"}` |
| `LEAVE_ROOM` | client → server | leave the room (or the game) | `{"type":"LEAVE_ROOM"}` |
| `READY` | client → server | ready / not ready | `{"type":"READY","ready":true}` |
| `ROOM_UPDATE` | server → room members | after any join / leave / ready | `{"type":"ROOM_UPDATE","room":"arena1","players":[{"name":"alice","ready":true},{"name":"bob","ready":false}]}` |
| `GAME_START` | server → room | everyone ready (≥ 2 players) | `{"type":"GAME_START","room":"arena1","tick_rate":10,"max_ticks":600,"maze":["####…"],"players":["alice","bob","carol"],"colors":{"alice":"yellow","bob":"cyan","carol":"magenta"}}` |
| `INPUT` | client → server | arrow key pressed (UDP: repeated every tick) | `{"type":"INPUT","dir":"UP"}` |
| `STATE` | server → players | every tick (10/s) | `{"type":"STATE","tick":42,"positions":{"alice":[1,1],"bob":[7,2]},"pellets":[[2,1],[3,1]],"power_pellets":[[1,2]],"scores":{"alice":120,"bob":70},"powered":{"alice":0,"bob":37}}` |
| `GAME_OVER` | server → players | time up / no pellets / one player left | `{"type":"GAME_OVER","winner":"alice","ranking":[{"name":"alice","score":30},{"name":"bob","score":15}]}` (`winner` is `null` on a tie) |
| `PING` | client → server | every second (RTT + heartbeat) | `{"type":"PING","t":183.4521}` |
| `PONG` | server → client | answer to PING, echoes `t` | `{"type":"PONG","t":183.4521}` |
| `PLAYER_LEFT` | server → room | a player left, disconnected or timed out | `{"type":"PLAYER_LEFT","name":"bob"}` |
| `ACK` | both (UDP only) | "I got your reliable message number `ack`" | `{"type":"ACK","ack":3}` |

Two details to know: `PING.t` is the sender's own clock, and `PONG` returns it unchanged,
so RTT = now − t is computed on one machine (no clock synchronization needed).
`STATE` is the **full** state every tick, not a difference ("delta"), so any single STATE is
enough to draw the game: a lost one doesn't break anything.

---

## 4. TCP version in detail

**Sockets.** Server: one listening socket (`socket(AF_INET, SOCK_STREAM)`, `SO_REUSEADDR`,
`bind(("0.0.0.0", 5050))`, `listen()`), plus one connected socket per client returned by
`accept()`. Client: one socket, `create_connection((ip, 5050))`. On every connected socket we
set `TCP_NODELAY`: it disables Nagle's algorithm, which would otherwise hold small messages
(a 30-byte INPUT) for up to ~40 ms to batch them.

**Threads (`tcp/server.py`).**
- `main`: the `accept()` loop (`serve_forever`), with a 1 s timeout so Ctrl-C works.
- `reader-<ip:port>`: one per client: `recv()` → framing buffer → `core.handle(msg)`.
- `writer-<ip:port>`: one per client: takes messages from that client's queue and `sendall()`s them.
- `game-<room>`: one per running game: the 10 ticks/s loop.
- `watchdog`: every 0.5 s closes connections silent for more than 5 s.

Why a separate writer per client: the game thread must never wait on a slow client. It only
puts the STATE into each client's queue (`ClientConn.send` → `queue.put_nowait`, never blocks)
and moves on. If one client stops reading, only its own queue fills up (max 256 messages ≈ 25 s);
then that client is dropped with "send queue full", the others are unaffected.

**Locks.** All shared game/lobby state is protected by **one** lock, `GameServer.lock`
(see section 6). Each connection also has a small `_close_lock` so it is closed exactly once.

**Framing: why one `recv()` is not one message.** TCP is a byte stream, not a message
service. The sender's two `sendall()` calls can arrive as one `recv()`, or one message can
arrive split over two `recv()` calls (Nagle, segment sizes, timing). So we need our own
boundary: **every message is one line of JSON ending with `\n`** (compact JSON never contains a
raw newline). `TcpStreamBuffer.feed()` in `common/protocol.py`, step by step:

1. `recv()` returns `b'{"type":"PI'`. Append to the buffer. No `\n` in the buffer → return `[]`
   and keep the bytes.
2. Next `recv()` returns `b'NG","t":1}\n{"type":"INP'`. Buffer is now
   `{"type":"PING","t":1}\n{"type":"INP`. There is a `\n`: split off the first line,
   decode it → `PING`. The rest (`{"type":"INP`) stays in the buffer.
3. Next `recv()` returns `b'UT","dir":"UP"}\n'` → completes `INPUT`, buffer empty.

A line that is not valid JSON is skipped and counted (logged as "malformed line"); the
connection stays. If 64 KiB arrive without any `\n`, the client is dropped: otherwise a
broken or hostile client could make the buffer grow forever.

**Broadcast.** "Send to everyone in the room" = loop over the room's sessions and call
`send()` on each, which only enqueues; each writer thread does the actual network send.

**How a disconnection is detected, and what happens next.**
- `recv()` returns `b''` → the other side closed the connection (FIN). That's what happens
  when the client process exits or crashes: its operating system closes the socket for it.
  Detected **immediately** (measured: 0-27 ms after the kill).
- `recv()` raises `ConnectionResetError` → RST (abrupt close). Other socket errors likewise.
- **Heartbeat timeout**: if the client's process is frozen, or the cable / Wi-Fi is gone, *nothing*
  arrives, not even a FIN; the connection looks open. Clients send a PING every second, so the
  `watchdog` closes any connection silent for more than 5 s.

In every case the reader's `finally:` block runs `core.disconnect(conn)`: the name is freed,
the player is removed from the room and from the running game, `PLAYER_LEFT {name}` is sent to
the others, and the game continues (or ends if only one player is left). The server never
crashes because every per-client receive/send is inside try/except.

---

## 5. UDP version in detail

**One socket for all.** `socket(AF_INET, SOCK_DGRAM)`, `bind(("0.0.0.0", 5050))`.
There is no `listen`/`accept` and no connection: every datagram from every client arrives on
this one socket through `recvfrom()`, which also returns the sender's address `(ip, port)`.

**The (ip, port) → session map.** `udp/server.py → Server.sessions`. The first valid datagram
from a new address creates a `Session` (logged `NEW PEER ip:port`); after LOGIN it has a name.
To answer, the server `sendto(data, session.addr)`. Players are told apart by the full
`(ip, port)`, never by IP alone: behind a NAT or a tunnel several players can share one IP
(tested: 3 clients from 127.0.0.1). Max 256 sessions.

**Which messages are reliable, and why.** UDP can lose, duplicate and reorder datagrams.
- **Reliable** (`RELIABLE_TYPES`): LOGIN, LOGIN_OK/FAIL, LIST_ROOMS, CREATE_ROOM, ROOM_LIST,
  JOIN_ROOM, LEAVE_ROOM, READY, ROOM_UPDATE, GAME_START, GAME_OVER, PLAYER_LEFT. These are
  **one-time events**: if a GAME_START is lost, that player never enters the game; nothing later
  replaces it. So they must arrive, exactly once, in order.
- **Unreliable**: STATE, INPUT, PING/PONG, ACK. These are **repeated or replaced** anyway.

**How seq / ACK / resend works (`udp/reliability.py`).** Each side keeps, per peer, a counter
`next_seq` for what it sends and `expected` for what it receives. A reliable message gets
`"seq": n, "rel": true`, a copy is kept in `pending[n]`. The receiver answers **every copy**
with `{"type":"ACK","ack":n}`. The timer thread (every 50 ms) resends anything in `pending`
older than **200 ms** (RTO), up to 15 times (3.2 s).

*Walk-through: alice joins a room, and an ACK gets lost.*
1. alice's client sends `{"type":"JOIN_ROOM","room":"arena1","seq":3,"rel":true}` and stores
   it in `pending[3]` with the time.
2. The server receives it, immediately sends `{"type":"ACK","ack":3}`, sees that 3 is the seq it
   `expected`, delivers the JOIN_ROOM to `server_core` (alice joins) and now expects 4.
3. **The ACK is lost** on the way back.
4. 200 ms later alice's timer sees `pending[3]` still there → sends the exact same datagram again.
5. The server receives seq 3 again. It **ACKs it again** (that's why every copy is ACKed: the
   sender needs an ACK to stop) but 3 < `expected` (4) → it's a **duplicate** → dropped, not
   delivered. Alice does **not** join twice (`stats.duplicates += 1`).
6. This ACK arrives → alice removes `pending[3]`. Done.

If a message arrives early (seq 5 while expecting 4), it is held until 4 arrives, then both are
delivered in order. If 4 never comes (the sender gave up after 15 retries), after 4 s the gap
is skipped so the channel doesn't block forever. A seq absurdly far ahead (forged) is ignored.

**Why STATE and INPUT are unreliable.** STATE is a full snapshot sent every 100 ms. If one is
lost, retransmitting it 200 ms later is pointless: by then two newer STATEs have been sent, and
each of them alone is enough to draw the game. Retransmitting would only add delay (that is
exactly TCP's problem under loss: it holds back new data until the old data is repaired, called
head-of-line blocking). INPUT: the UDP client re-sends its current direction every 100 ms
during a game, so a lost INPUT is repaired by the next tick anyway, and the server only needs
the latest direction.

**Stale tick discard.** Datagrams can arrive out of order: STATE 41 after STATE 42. Drawing 41
would move players backwards. The client remembers the last tick it accepted and drops any
STATE with `tick <= last_tick` (counted as "late"). Gaps (42 then 45) are counted as missing
ticks: that's our loss metric. (`udp/client.py → UdpTransport._accept`)

**Heartbeat timeout.** UDP has no FIN: a crashed client simply goes silent. **Any** datagram
from a client (PING every 1 s, INPUT every 100 ms in a game, ACKs) refreshes its `last_seen`.
The timer thread checks every 0.5 s and drops sessions silent for more than **4 s**
(`_check_timeouts` → `drop_session` → `core.disconnect`: PLAYER_LEFT to the others). The client
side gives up on the server after 10 s of silence (more tolerant, because under heavy loss
PONGs can be lost several times in a row).

**The `--drop` flag.** `--drop 0.3` on the server and/or the client makes that process discard
30 % of the datagrams it **sends** (all types, including ACKs), chosen at random, inside
`ReliableEndpoint._transmit`. Set on both sides, it simulates a lossy network in both directions
without root privileges. It's how we test and measure UDP under loss.

---

## 6. Concurrency

| | TCP server | UDP server |
|---|---|---|
| threads | main (accept), reader + writer per client, game per room, watchdog | main (recvfrom), timer (retransmit + timeouts), game per room |
| shared state | `GameServer.clients`, `lobby`, `games`; `Server.conns` | `GameServer.*`; `Server.sessions`; reliability `peers` |
| protection | `GameServer.lock` (one lock for all game/lobby state); per-client `queue.Queue` (thread-safe) for sending; `_close_lock` per connection | `GameServer.lock`; `ReliableEndpoint.lock` for seq/pending state |

**How we avoid race conditions.**
- **One lock for all shared game state.** Every message handler and every game tick runs inside
  `with self.lock:`. Two players' messages can't modify the room at the same time, and a tick
  never sees a half-applied JOIN. One lock also means no deadlock between locks. It's an
  `RLock` (re-entrant) so a function holding it can call another one that takes it too.
- **Critical sections are tiny** (microseconds: update a dict, enqueue a message). Network I/O
  is never done while holding the lock in the TCP server: sending is just `put_nowait` into a
  queue; the writer thread does the slow part.
- **Fixed lock order in UDP**: game lock first, then the reliability lock; the reliability layer
  never calls back into the game while holding its lock (callbacks run after releasing it).
- **Client side**: network threads never touch the UI. They put received messages in a
  thread-safe queue; the pygame thread calls `poll()` and handles them itself
  (`common/transport.py`). TCP `send()` uses a `_send_lock` because the UI and ping threads both send.
- Python's GIL doesn't make our code thread-safe by itself (a check-then-act on a dict can be
  interleaved), which is why the lock is still needed.

---

## 7. Disconnection handling

| | TCP | UDP |
|---|---|---|
| client process killed | OS sends FIN → `recv()` returns `b''` | nothing is sent |
| detected by | the reader thread, immediately | heartbeat timeout (4 s of silence) |
| frozen client / cable pulled | watchdog, 5 s | heartbeat timeout, 4 s |
| what follows (both) | `core.disconnect`: name freed, removed from room and game, `PLAYER_LEFT` to the others, game goes on; ends if only one player is left | same |

**Measured** (SIGKILL of carol mid-game, server log timestamps):
- Benchmark, loopback: TCP **0 ms** (FIN); UDP **4004 ms** at 0 % loss, **4508 ms** at 10 %,
  **4446 ms** at 30 % loss.
- Live check today: TCP `PLAYER_LEFT carol (FIN)` within the same second as the kill;
  UDP `heartbeat timeout (4.4 s without a datagram)`.

**Why the difference.** TCP has a connection state in the operating system. When a process
dies, its OS closes its sockets and sends FIN, so the server learns it at once. UDP has no
connection: the server can't tell "dead" from "quiet" except by waiting. 4 s = 4 missed PINGs:
short enough for the game, long enough not to kick a player for a few lost datagrams. Under loss
it can be a bit more (the check runs every 0.5 s) or a bit less (the last PINGs before the kill
may have been lost, so the silence started earlier).

---

## 8. Metrics

What we measure (`metrics/run_benchmark.py`, 3 bot processes + server, 120 s games):

| Metric | How | Why it matters |
|---|---|---|
| RTT | PING with the client's clock time → PONG echo → now − t | responsiveness |
| inter-update time | time between two accepted STATEs at the client, measured on the network thread at arrival | smoothness; ideal = 100 ms |
| freezes | inter-update > 250 ms | visible stutter |
| missing ticks | gaps in STATE tick numbers (UDP; always 0 on TCP) | loss actually felt by the player |
| retransmissions | reliability-layer counters (UDP) | cost of making events reliable |
| detection time | SIGKILL time → server's PLAYER_LEFT log time | disconnect handling |

**Current numbers (one Mac, loopback, loss injected with `--drop`):**

| | RTT mean / p95 | inter-update mean / p99 / max | freezes > 250 ms | missing ticks | retransmissions (gave up) | detection |
|---|---|---|---|---|---|---|
| TCP 0 % | 0.88 / 1.41 ms | 100.0 / 105.0 / 113 ms | 0 | 0 % | n/a | 0 ms (FIN) |
| UDP 0 % | 0.79 / 1.24 ms | 100.0 / 104.9 / 114 ms | 0 | 0 % | 0 (0) | 4.0 s |
| UDP 10 % | 0.83 / 1.14 ms | 109.8 / 204 / 399 ms | 18 | 9.0 % | 6 (0) | 4.5 s |
| UDP 30 % | 0.90 / 1.20 ms | 143.8 / 402 / 903 ms | 146 | 30.5 % | 48 (0) | 4.4 s |

How to read it: under loss, UDP loses snapshots (missing ticks ≈ the loss rate, as expected),
so movement gets choppier, but **no reliable message was ever given up** and the game always
finished. RTT stays low because lost PINGs are simply not counted.

**Only from loopback so far (to say honestly):** all of the above. Loopback RTT (< 1 ms) is far
below a real network. Not measured yet: **TCP under loss** (needs kernel-level loss with sudo,
`--loss-method os`, ready but not run), and anything on a **real LAN, Cloudflare or playit**
(the benchmark supports `--host … --network lan|cloudflare|playit` since yesterday; no data yet).

Packet size (measured, `metrics/packet_sizes.py`): the largest message is STATE at game start,
**1228 bytes** with 3 players with 12-character names. Everything else is under 600 bytes.

---

## 9. Testing and robustness

**Test suite: 111 test cases** (100 test functions, some parametrized), all passing, 5 runs in a
row today. All network tests use real sockets on 127.0.0.1.

| File | Tests | What |
|---|---|---|
| `test_game.py` | 28 | movement, walls, pellets, power, eating (also when two players swap cells), end conditions, ranking, tie = no winner, STATE fits in a datagram |
| `test_protocol.py` | 19 | encode/decode, TCP framing (split message, 3 in one recv, byte by byte, bad line, overflow), UDP fields, hostile JSON |
| `test_reliability.py` | 14 | ACK, retransmission after 200 ms, duplicate dropped but re-ACKed, JOIN with lost ACK joins once, in-order delivery, gap skip, forged seq, everything arrives once under 30 % loss |
| `test_rooms.py` | 10 | room rules |
| `test_tcp_server.py` | 11 | full game, abrupt disconnect, heartbeat timeout, flood without newline, 3 clients from one IP |
| `test_udp_server.py` | 8 | full game, garbage datagrams, silent client times out, game at 20 % loss both ways, late STATE, 3 clients from one IP |
| `test_format_parity.py` | 1 | TCP and UDP servers produce identical messages for the same session |
| `test_netcheck.py` | 7 | the reachability tool |
| `chaos_test.py` | 2 | see below |

**The chaos test** (`tests/chaos_test.py`), for each protocol: real server + 3 bot processes
(UDP: 30 % loss on every process). During the game it throws garbage at the server, SIGKILLs
carol, and runs "mallory", a client that breaks the lobby rules on purpose (INPUT before LOGIN,
joining a running game, joining twice, READY with a wrong type...). It checks: the server is
alive with no traceback, alice and bob got PLAYER_LEFT carol and GAME_OVER, mallory got the right
refusal every time, and a new client can still log in. Passed today on both protocols.

**Seven robustness protections, and what each one protects against** (our grouping):

1. **Every receive/send is guarded; bad input is dropped, never fatal** (`ProtocolError` caught,
   malformed lines/datagrams logged and skipped). → one bad client or one garbage packet can't
   crash the server.
2. **64 KiB cap on the TCP framing buffer.** → a client that sends without ever sending `\n`
   can't eat the server's memory (`test_server_survives_client_flood_without_newline`).
3. **Per-client send queue + writer thread (TCP).** → a slow or frozen client can't block the
   game tick or the other players; it's dropped after 256 queued messages.
4. **Connection / session caps** (64 TCP connections, 256 UDP sessions). → a flood of
   connections can't exhaust threads or memory.
5. **Heartbeat timeouts** (TCP watchdog 5 s, UDP 4 s). → half-open connections, frozen
   processes, pulled cables and crashed UDP clients are cleaned up.
6. **Reliability hardening**: duplicates re-ACKed but delivered once; out-of-window seq
   ignored; a peer that restarts its numbering is detected; retries raised from 5 to 15. → no
   double JOIN, no poisoned channel by a forged seq, no GAME_START/GAME_OVER lost at 30 % loss
   (before the fix 1.8 % of reliable messages were given up at 30 % loss).
7. **Strict validation of names and requests** (1-12 printable characters, no outer spaces,
   unique; room/lobby rules enforced in `rooms.py`). → invisible or fake-looking names, duplicate
   players, and rule-breaking clients (mallory) get a clean refusal.

The pre-demo review (commit `6c5b873`) also fixed four rule bugs: an eaten player now keeps its
direction (TCP and UDP behaved differently before), a tied top score is a draw, the game starts
when the only unready player leaves, and no duplicate STATE when a leave ends the game.

---

## 10. Done vs left

**Done and verified (today, on one Mac):**
- TCP version and UDP version: login, lobby, rooms, ready, game, scores, ranking, winner/draw,
  PLAYER_LEFT, game over → back to the room.
- Shared rules and server logic; message parity test between both versions.
- UDP reliability layer (seq/ACK/retransmit/dedupe/order) with unit tests.
- Disconnect handling (FIN, RST, heartbeat) on both; live SIGKILL test on both.
- 111 tests × 5 runs green; chaos test green on both protocols.
- Benchmark + charts on loopback (RTT, inter-update, missing ticks, retransmissions, detection).
- pygame UI (redesigned, mouse + keyboard, sounds), headless bot.
- Code cleanup (this week): dead code removed, docstrings, comments on the networking parts.

**Done but not yet tested on real, separate computers:**
- Play across 4 laptops on a LAN (only simulated with separate processes on one Mac).
- Windows client and the Windows `tunnel_client.bat`.
- `netcheck.py` from other machines.
- Cross-network tooling: Cloudflare Tunnel scripts (tested with a fake `cloudflared`), playit
  server script (tested locally without the agent), hostname `--host` (tested with `localhost`).
- Benchmark `--host` mode on a real network.

**Not started:**
| Item | What we'll do | When (before Fri 13 Nov) |
|---|---|---|
| Accounts for the bonus | Cloudflare account + a domain on Cloudflare DNS; playit.gg account, check a free UDP tunnel is allowed | Sat 7 Nov |
| 4-laptop test (incl. Windows) | 1 server + 3 clients on the same Wi-Fi/hotspot, TCP then UDP, kill test, `netcheck` first | Sun 8 Nov |
| Cross-network bonus | TCP via Cloudflare Tunnel, UDP via playit.gg, 3 clients on 3 different networks (campus Wi-Fi + 2 phone hotspots), proof with `curl ifconfig.me` | Mon 9 Nov |
| Real-network metrics | `run_benchmark.py --host … --network lan / cloudflare / playit` → `networks.png` | Mon 9 – Tue 10 Nov |
| TCP under loss | `sudo -v && run_benchmark.py --loss-method os` (kernel loss on the Mac) | Tue 10 Nov |
| STATE size decision | apply (or not) the smaller pellet encoding (section 12) | Tue 10 Nov |
| Slides | architecture, protocol, TCP vs UDP, metrics charts, bonus | Wed 11 Nov |
| Full rehearsal | the demo day sheet, start to finish, with plan B | Thu 12 Nov |

---

## 11. The bonus plan (players on different networks)

**Goal**: the server runs on our Mac; three players on three different networks (e.g. campus
Wi-Fi, two phone hotspots) play together, without a cloud VM and without router configuration.

**Why not just connect to the Mac's IP?** The Mac is behind NAT (campus or phone). Its IP is
private; nobody outside can open a connection to it unless someone forwards a port on the router,
which we don't control. Tunnels solve this: the Mac opens an **outgoing** connection to a public
service, and players' traffic comes back through it.

**TCP version → Cloudflare Tunnel.**
```
game ─TCP─▶ cloudflared (on the player's laptop, 127.0.0.1:15050)
     ─HTTPS/WebSocket─▶ Cloudflare edge ─tunnel (opened by the Mac)─▶ cloudflared (Mac)
     ─TCP─▶ tcp.server on localhost:5050
```
Each player runs `cloudflared access tcp` (our script `tunnel_client.sh` / `.bat` does it) and
the game connects to `127.0.0.1:15050`. The server sees every player as `127.0.0.1:<port>`
(the local cloudflared), which is why players are identified by connection and name, never IP.

**Why Cloudflare can't carry the UDP version.** A Cloudflare public tunnel hostname carries
HTTP(S) and TCP **streams**; `cloudflared access tcp` wraps a byte stream in a WebSocket. A UDP
datagram is not a stream, so it can't go that way. Cloudflare can carry UDP only in its
private-network mode with the WARP VPN client installed on every player: that's a VPN overlay,
not what we want to show.

**UDP version → playit.gg.**
```
game ─UDP─▶ playit edge (xxx.at.ply.gg:PORT) ─tunnel (opened by the playit agent on the Mac)─▶
     agent ─UDP─▶ udp.server on 127.0.0.1:5050
```
Players install nothing: they run the normal client with `--host xxx.at.ply.gg --port PORT`
(the hostname is resolved once at startup). The agent on the Mac dials out to playit (reverse
tunnel), so no port forwarding. The 1 s PING keeps the UDP flow alive in playit's and every NAT's
mapping table. The server sees `127.0.0.1:<port>` per player, and sessions are keyed by
(ip, port), so that works.

**What we'll show as proof.** On each player laptop, `curl -4 ifconfig.me` → three different
public IPs = three different networks. On the projector, the server log with the three logins.
Then a full game on each version, and the RTT/inter-update numbers per network on a chart
(`networks.png`).

---

## 12. Honest weak points and future work

- **No client-side prediction / interpolation of the game itself.** The client draws what the
  server sent. The renderer only glides a player between two consecutive cells over one tick
  (cosmetic); when a STATE is lost the player jumps two cells. An action is visible after
  RTT + up to 100 ms. Future: client-side prediction for your own player, or interpolation with
  a small buffer.
- **No rejoin.** A player who disconnects mid-game can't come back into that game (a running
  room refuses joins). With UDP, a client the server timed out gets `LOGIN_FAIL "not logged in"`
  and must log in again. Future: a session token to resume a game.
- **STATE size near the MTU.** 1228 bytes at game start with 12-character names; up to ~1770
  bytes with non-ASCII names (JSON writes `é` as `é`). Ethernet allows ~1472 bytes of UDP
  payload; tunnels add headers, so big datagrams risk being fragmented or dropped. The server
  logs a warning above 1200 bytes. Proposed fix (not applied, waiting for our decision): send
  pellets as cell numbers (`y*20+x`) and UTF-8 JSON → 786 / 894 bytes.
- **No authentication on UDP.** A session is just an `(ip, port)`. Someone who can send
  datagrams with a forged source address could send INPUT as another player. Also, if a
  player's NAT changes its port mid-game, the server sees a new peer and the old one times out.
  Future: a random token in LOGIN_OK that must accompany every datagram.
- **Fixed retransmission timeout (200 ms), no backoff.** On a path with RTT above 200 ms every
  reliable message is sent at least twice (harmless: duplicates are filtered, but wasteful), and
  under congestion we don't slow down. Future: adaptive RTO from measured RTT (like TCP,
  RFC 6298) with exponential backoff.
- **Everything measured on loopback so far** (section 8).
- **Minor**: no encryption (fine for a course demo, plain-text JSON); one game thread per room
  (fine for a few rooms, not for thousands).

---

## 13. Questions the professor is likely to ask

1. **Why not TCP for everything?** — TCP retransmits every lost byte and delivers in order, so one
   lost packet holds back all newer data (head-of-line blocking): the game freezes, then catches
   up. For a 10/s full snapshot, an old snapshot is worthless once a newer one exists. UDP lets
   us skip lost snapshots and only make the one-time events reliable.
2. **Why not UDP for everything then?** — The assignment asks for both, and TCP is simpler and
   good enough on a clean network. Our metrics show both are equal at 0 % loss; the difference
   appears under loss.
3. **Is your UDP version reliable?** — Partly, on purpose. Lobby and game events (LOGIN, JOIN,
   GAME_START, GAME_OVER, PLAYER_LEFT...) are reliable: seq numbers, ACK, resend every 200 ms up to
   15 times, duplicates dropped, delivered in order. STATE, INPUT and PING are not, because they
   are replaced every 100 ms.
4. **What happens if an ACK is lost?** — The sender doesn't know the message arrived, so it resends
   after 200 ms. The receiver ACKs the copy again, sees the seq is below what it expects, and drops
   it as a duplicate. So the message is applied exactly once.
5. **How do you know a UDP client is gone?** — We don't get any signal; we wait. Clients send a
   PING every second (and INPUT every tick in a game). If nothing arrives from an address for 4 s,
   the server removes it and sends PLAYER_LEFT. Measured: 4.0-4.5 s.
6. **And in TCP?** — When the client process dies its OS closes the socket: we get a FIN, `recv()`
   returns empty bytes, and we react immediately (measured 0 ms). For a frozen client or pulled
   cable, no FIN comes, so a 5 s heartbeat watchdog catches it.
7. **Why JSON?** — Readable in logs and Wireshark, easy to debug and to explain, the same encoder for
   both versions, and the standard library has it. The cost is size (STATE ≈ 1.2 kB); a binary
   format would be 5-10× smaller and is the obvious optimization.
8. **How do you handle 3 players at the same time?** — TCP: one reader and one writer thread per
   player. UDP: one socket receives from everyone, sessions by (ip, port). In both, all game
   changes go through one lock, so two players' messages are applied one after the other, never
   interleaved; the game thread applies all inputs at the tick, in a fixed order.
9. **Why is the server authoritative?** — One source of truth: no disagreement about who got the
   pellet, no cheating by a modified client, and simple clients. The price is one round trip of
   delay.
10. **Why 10 ticks per second?** — The game moves one cell per tick, so 10/s feels smooth and
    STATE traffic stays small (~37 kB/s for 3 players). Higher rates multiply traffic without
    making grid movement better.
11. **How do you split the TCP stream into messages?** — Each message is one JSON line ending in
    `\n`. We append received bytes to a buffer and cut it at each `\n`; an incomplete message waits
    for the next `recv()`. One `recv()` can contain half a message or several.
12. **What if UDP packets arrive out of order?** — Reliable messages are held and delivered in seq
    order. STATEs carry a tick number: anything older than the last one shown is dropped.
13. **How did you test loss?** — `--drop` discards a fraction of outgoing datagrams in our own code,
    on server and clients, so both directions lose. At 30 %: ~30 % of STATEs missing, choppy but
    playable, no reliable message given up, every game finished. For TCP, loss must be injected in
    the kernel (dummynet on macOS, `--loss-method os`): ready, not measured yet.
14. **How do you guarantee the rules are identical in both versions?** — There is only one copy of
    the rules (`common/game.py`) and of the server logic (`common/server_core.py`); the TCP and UDP
    servers only convert bytes to messages. A parity test runs the same session on both servers and
    compares every message.
15. **What would you improve with more time?** — Smaller STATE (binary or cell indices), a session
    token for UDP, adaptive retransmission timeout, client-side prediction, and rejoining a game
    after a disconnect.
