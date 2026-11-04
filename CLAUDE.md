# Multiplayer Maze Arena — rules for Claude

University Computer Networks project. Pacman-style multiplayer game in Python
(`socket` + `pygame`, JSON messages), built in **two versions — TCP-only and
UDP-only — that share the same game logic**.
Demo: **Friday 2026-11-13**, 1 server + 3 clients on 4 different computers.

## Non-negotiable rules

1. **Game logic lives ONLY in `common/` and has NO networking imports.**
   No `socket`, `select`, `selectors`, `asyncio`, `threading`-for-I/O, or
   anything from `tcp/` / `udp/` inside `common/`. `common/` must be testable
   with plain pytest and no network.
2. **The server is authoritative.** Clients send only `INPUT {dir}`. The server
   runs the simulation at **10 ticks/s** and broadcasts the **full `STATE`**
   every tick. Clients never compute positions, scores, or collisions — they
   only render what the server sent.
3. **Message contract** — never change it without updating `common/protocol.py`
   AND `.claude/skills/protocol-contract/SKILL.md` in the same change:

   | Client → Server               | Server → Client                                   |
   |-------------------------------|---------------------------------------------------|
   | `LOGIN {name}`                | `LOGIN_OK` / `LOGIN_FAIL`                         |
   | `LIST_ROOMS`, `CREATE_ROOM`   | `ROOM_LIST`                                       |
   | `JOIN_ROOM`, `LEAVE_ROOM`, `READY {ready}` | `ROOM_UPDATE {players}`             |
   | `INPUT {dir}`                 | `GAME_START {maze, players, colors, tick_rate}`, `STATE {tick, positions, pellets, power_pellets, scores, powered}` |
   |                               | `GAME_OVER {ranking, winner}`                     |
   | `PING` / `HEARTBEAT`          | `PONG`, `PLAYER_LEFT {name}`                      |

4. **Servers bind to `0.0.0.0`**; host and port are configurable by CLI args
   (`--host`, `--port`). Clients take `--host` / `--port` for the server address.
   Never hard-code `localhost` or `127.0.0.1` in server code.
5. **The server must never crash on a client disconnect.** Every per-client
   recv/send is guarded; a dead/silent client is removed, its room is updated,
   and the others receive `PLAYER_LEFT {name}`. One bad client never affects
   the others.
6. **The UI only talks to a transport interface**: `send(msg)` and
   `on_message(callback)`. `client_ui/` must not import `socket`, `tcp/`, or
   `udp/` internals — the same UI runs on both versions.

## Layout

```
common/      game.py, protocol.py, rooms.py, transport.py, server_core.py
             # pure logic, Transport interface, shared server logic (lobby/rooms/game loop)
tcp/         server.py, client.py             # TCP transport only (bytes <-> server_core)
udp/         server.py, client.py, reliability.py  # UDP transport only + seq/ack/retransmit
client_ui/   ui.py, render.py, bot.py, connect.py  # pygame UI, headless bot; connect.py picks the transport
metrics/     CSV output of measurements
tests/       pytest
```

## Framing (details in the protocol-contract skill)

- **TCP**: newline-delimited JSON (`json.dumps(msg) + "\n"`), buffer until `\n`.
- **UDP**: one datagram = one message. Lobby/game-event messages are reliable
  and ordered (`seq`/`rel`, `ACK {ack}`, 200 ms RTO, 5 retries); STATE, INPUT,
  PING/PONG are unreliable. All of it lives in `udp/reliability.py`.

Servers differ only in transport: lobby, rooms and the game loop are in
`common/server_core.py` and must stay shared — never fork that logic into
`tcp/` or `udp/`.

## Project skills (in `.claude/skills/`)

- `protocol-contract` — every message with example JSON, encode/decode, framing.
- `multi-client-testing` — run 1 server + 3 clients locally, simulate disconnects, pytest.
- `network-metrics` — what we measure and the CSV format in `metrics/`.

## Dependencies

Standard library + pygame (installed as `pygame-ce`, same `import pygame`) for networking/game; matplotlib only for metric
plots; pytest for tests. Nothing else without asking.
