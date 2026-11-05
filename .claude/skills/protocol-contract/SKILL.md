---
name: protocol-contract
description: The Maze Arena message contract — every message type with example JSON, encode/decode rules, TCP newline framing vs UDP one-datagram-per-message with seq/ack. Use whenever writing or changing common/protocol.py, any server/client send/receive code, or anything that builds or parses a message.
---

# Maze Arena protocol contract

Source of truth in code: `common/protocol.py`. This file and `protocol.py`
change **together or not at all**. Do not invent message types or fields —
if one is needed, update both here and in `protocol.py` first.

## Envelope

Every message is a JSON object with a `"type"` field (UPPERCASE string) plus
the type's fields. Field names are `snake_case`. Unknown fields are ignored on
receive; a missing `type` or unknown `type` is dropped (logged, never crashes).

UDP adds transport fields to the same object (see below): `seq`, `ack`,
`rel`. The game layer never sees or sets them.

## Messages

### Login
```json
{"type": "LOGIN", "name": "alice"}
{"type": "LOGIN_OK", "name": "alice"}
{"type": "LOGIN_FAIL", "reason": "name already taken"}
```
Names: 1–12 printable chars, no leading/trailing spaces, unique per server
(room names: the same rules, up to 16 chars).

### Lobby / rooms
```json
{"type": "LIST_ROOMS"}
{"type": "CREATE_ROOM", "room": "arena1"}
{"type": "ROOM_LIST", "rooms": [
  {"room": "arena1", "players": 2, "max_players": 3, "in_game": false}
]}
```
`CREATE_ROOM` is answered with a fresh `ROOM_LIST` (creator still has to
`JOIN_ROOM`). The server also pushes `ROOM_LIST` to every client in the lobby
(logged in, not in a room) whenever rooms change, and replies `ROOM_LIST`
after `LEAVE_ROOM`.

Refused lobby actions (CREATE/JOIN/READY) are answered with a `ROOM_LIST`
carrying an optional `error` field:
```json
{"type": "ROOM_LIST", "rooms": [...], "error": "room is full"}
```

```json
{"type": "JOIN_ROOM", "room": "arena1"}
{"type": "LEAVE_ROOM"}
{"type": "READY", "ready": true}
{"type": "ROOM_UPDATE", "room": "arena1", "players": [
  {"name": "alice", "ready": true},
  {"name": "bob",   "ready": false}
]}
```
`ROOM_UPDATE` goes to every member of the room after any join/leave/ready.
`READY.ready` is optional (default `true`; `false` = un-ready).
Game starts when ≥2 players are in the room and all are ready.
The check also runs when a player leaves (the only unready player leaving
starts the game). After GAME_OVER the room returns to the lobby state
(everyone un-ready) and a `ROOM_UPDATE` is sent.

### Game
```json
{"type": "GAME_START", "room": "arena1", "tick_rate": 10, "max_ticks": 1200,
 "maze": ["#########", "#...#...#", "#.#...#.#", "#########"],
 "players": ["alice", "bob", "carol"],
 "colors": {"alice": "yellow", "bob": "cyan", "carol": "magenta"}}

{"type": "INPUT", "dir": "UP"}
```
`dir` ∈ `"UP" | "DOWN" | "LEFT" | "RIGHT" | "NONE"`. INPUT is the **only**
thing a client sends during a game (besides PING). The server keeps
the latest dir per player and applies it at the next tick.

```json
{"type": "STATE", "tick": 42,
 "positions": {"alice": [1, 1], "bob": [7, 2], "carol": [3, 2]},
 "pellets": [[2, 1], [3, 1], [5, 2]],
 "power_pellets": [[1, 2], [18, 11]],
 "scores": {"alice": 120, "bob": 70, "carol": 90},
 "powered": {"alice": 0, "bob": 37, "carol": 0}}
```
Full state every tick (10/s), not deltas. Positions are `[x, y]` grid cells;
`pellets` / `power_pellets` = remaining ones; `powered` = ticks of power left.
Body = `common.game.get_state()`; GAME_START body = `common.game.get_setup()`.
Full STATE with 3 players at game start: ~1230 bytes with 12-char ASCII names, ~1770 with
12 non-ASCII chars each (JSON escapes them as \uXXXX); `python metrics/packet_sizes.py`
measures it. The UDP server logs a warning once per type above `UDP_WARN_SIZE` (1200).
Clients render the newest tick only.

```json
{"type": "GAME_OVER", "winner": "alice",
 "ranking": [{"name": "alice", "score": 30},
             {"name": "carol", "score": 21},
             {"name": "bob",   "score": 15}]}
```
`ranking` lists the players still in the game, best first (ties: alphabetical).
`winner` is `null` when the top score is tied (a draw) or nobody is left.
A player who gets eaten respawns and keeps their direction.

### Liveness
```json
{"type": "PING", "t": 183.4521}
{"type": "PONG", "t": 183.4521}
{"type": "PLAYER_LEFT", "name": "bob"}
```
- `PING.t` = sender's `time.monotonic()`; `PONG` echoes it unchanged, so RTT
  is computed by the pinger only (clocks of different machines are not compared).
- Clients send `PING` every 1 s (`PING_INTERVAL`); it doubles as the heartbeat
  (there is no separate HEARTBEAT message). A PING without `t` gets a PONG without `t`.
- `PLAYER_LEFT` is sent to the remaining room members when a client leaves,
  disconnects, or times out. Timeouts: TCP 5 s both ways
  (`protocol.HEARTBEAT_TIMEOUT`); UDP server 4 s, UDP client 10 s (see below).

## Encoding / decoding

```python
def encode(msg: dict) -> bytes:   # json.dumps(msg, separators=(",", ":")).encode("utf-8")
def decode(data: bytes) -> dict:  # json.loads(data.decode("utf-8")); raise ProtocolError on bad input
```
- UTF-8, compact separators, no NaN.
- `decode` must reject non-objects and objects without a string `type`.
- Callers catch `ProtocolError` and drop the message — never crash the server.

## TCP framing — newline-delimited JSON

TCP is a byte stream: one `recv()` can hold half a message or three.
- Send: `sock.sendall(encode(msg) + b"\n")` (JSON never contains a raw `\n`
  with compact encoding).
- Receive: append to a per-connection buffer; while `b"\n"` in buffer, split
  off one line and `decode` it. Keep the remainder.
- `recv()` returning `b""` = peer closed → disconnect handling.
- Cap the buffer (e.g. 64 KiB without a newline → drop client).

## UDP framing — one datagram = one message

- Send: `sock.sendto(encode(msg), addr)`; receive: `data, addr = sock.recvfrom(65535)`.
- The server identifies clients by `addr` (ip, port) → name mapping after LOGIN.
- Keep datagrams under ~1400 bytes (fits Ethernet MTU, no IP fragmentation), and under
  1200 for tunnels (playit.gg adds headers): `UDP_WARN_SIZE`.
  STATE must stay small: short names, compact JSON.
- UDP gives no ordering, no delivery, no duplicate protection. `udp/reliability.py`
  runs two channels over the one socket:

| field | on | meaning |
|-------|----|---------|
| `seq` | reliable messages only | per-sender, per-peer counter 1, 2, 3, ... (consecutive, so gaps are detectable) |
| `rel` | reliable messages only | `true`: please ACK, I will retransmit |
| `ack` | `ACK` only | the `seq` being acknowledged |

```json
{"type": "JOIN_ROOM", "room": "arena1", "seq": 17, "rel": true}
{"type": "ACK", "ack": 17}
{"type": "STATE", "tick": 42, "positions": {...}, ...}        // unreliable: no transport fields
```
`ACK` is a **transport-only** message, consumed in `udp/reliability.py` and
never passed to the game layer / UI.

Delivery classes (UDP) — `protocol.RELIABLE_TYPES`:
- **Reliable, ordered**: LOGIN, LOGIN_OK, LOGIN_FAIL, LIST_ROOMS, CREATE_ROOM,
  ROOM_LIST, JOIN_ROOM, LEAVE_ROOM, READY, ROOM_UPDATE, GAME_START, GAME_OVER,
  PLAYER_LEFT. (Replies are reliable too: a lost LOGIN_OK would strand the client.)
  - Retransmit every 200 ms (RTO), at most 15 retransmissions, then give up
    (logged + counted; liveness is decided by the heartbeat, not by one message).
  - Receiver ACKs **every** copy; `seq < expected` = duplicate → dropped but
    re-ACKed (a retransmitted JOIN never joins twice).
  - `seq > expected` is held until the gap fills (in-order delivery: CREATE_ROOM
    is always processed before the JOIN_ROOM sent right after it). A gap not
    filled within 4 s (sender gave up) is skipped.
  - A fresh `seq: 1` arriving > 4 s after the first one = the peer forgot us and
    restarted; both directions restart at 1.
  - Ordering is per client only: two different clients' messages can still
    arrive in any order.
- **Unreliable, newest wins**: STATE (client drops `tick` ≤ last tick, counts
  gaps), INPUT (UDP client re-sends the current dir every 100 ms in a game),
  PING/PONG, ACK.

Liveness (UDP): clients PING every 1 s; the server drops a client silent for
**4 s** (`udp.server.HEARTBEAT_TIMEOUT`). Clients give up on a server silent for
10 s (lenient: a PONG needs two datagrams to survive). TCP uses 5 s both ways.

`--drop P` (UDP server, UI and bot) discards fraction P of **outgoing**
datagrams to simulate loss. With P on both sides a reliable round trip succeeds
with (1-P)², so the sender gives up with probability (1-(1-P)²)¹⁶
(0.002 % at P=0.3; it was 1.8 % with the old 5 retries, enough to lose a
GAME_START or GAME_OVER now and then in the 30 % demo).

TCP needs none of the transport fields — never send `seq`/`ack`/`rel` over TCP.
