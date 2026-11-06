# Maze Arena in the browser

```
browser (Three.js) --WebSocket /ws--> web/bridge.py --TCP, one JSON per line--> tcp.server
```

- `bridge.py` (stdlib only) serves `client/dist/` and upgrades `/ws` (RFC 6455). Each text
  frame becomes one line to the TCP server; each server line becomes one frame. Newlines
  inside a frame are replaced with spaces, so a browser cannot inject a second message.
  The server sees a normal TCP client: same LOGIN, rooms, INPUT, PING heartbeat.
- `client/` renders only what STATE says (glides between cells over one tick, cosmetic).

## Run locally

```bash
.venv/bin/python -m tcp.server --port 5050
(cd web/client && npm install && npm run build)
.venv/bin/python -m web.bridge --port 8080 --game-port 5050
# open http://localhost:8080
```

Dev mode with hot reload: `cd web/client && npm run dev` (proxies `/ws` to the bridge on 8080).

## Checks

```bash
.venv/bin/python -m pytest tests/test_ws_bridge.py      # handshake, relay, injection, 502
cd web/client && node tests/live-game.mjs http://127.0.0.1:8080 [--mobile]
```

`live-game.mjs` plays a full game in Chromium (Playwright) against whoever else is in the
room (e.g. `python -m client_ui.bot`); set `ROOM=name` to pick the room.
