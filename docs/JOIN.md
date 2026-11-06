# Join a Maze Arena game

Maze Arena is a 2-3 player maze game over the network. The server runs on the host's Mac;
you only need Python and this repository. About 5 minutes the first time.

## Easiest: open the link (nothing to install)

Open the **browser link** the host sends you (it looks like
`https://something.trycloudflare.com`, also in `deploy/public_addresses.env` as `WEB_URL`)
in Chrome, Edge, Safari or Firefox, on a computer or a phone. Type your name, press **Play**,
then **Ready**. Move with the arrow keys / WASD, swipes or the on-screen pad.

The browser version is the same game on the same server (it joins over TCP through a small
WebSocket bridge), so you can play against people using the Python clients below.
If the link stops working, the host restarted the tunnel: ask for the new one.

The rest of this page is the **Python client** (the TCP and UDP versions of the course project).

## 1. Install Python (once)

- **macOS**: <https://www.python.org/downloads/>, install Python 3.12 or 3.13.
- **Windows**: same page; in the installer **tick "Add python.exe to PATH"**.

## 2. Get the game (once)

macOS (Terminal):

```bash
git clone https://github.com/bayaCh05/maze-arena.git
cd maze-arena
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Windows (PowerShell or cmd):

```bat
git clone https://github.com/bayaCh05/maze-arena.git
cd maze-arena
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

No git? On the GitHub page: **Code → Download ZIP**, unzip it, open a terminal in that folder.

## 3. Play

Replace `alice` with your name (1-12 characters, each player a different one).
You land in room `demo`; press **R** (or click Ready) when everyone is in.

| | macOS | Windows |
|---|---|---|
| **TCP version** | `bash scripts/join_tcp.sh --name alice` | `scripts\join_tcp.bat --name alice` |
| **UDP version** | `bash scripts/join_udp.sh --name alice` | `scripts\join_udp.bat --name alice` |

The same thing without the scripts (any OS, from the `maze-arena` folder):

```bash
# TCP
.venv/bin/python -m client_ui.ui --proto tcp --host PLAYIT_TCP_HOST --port PLAYIT_TCP_PORT --name alice --room demo
# UDP
.venv/bin/python -m client_ui.ui --proto udp --host PLAYIT_UDP_HOST --port PLAYIT_UDP_PORT --name alice --room demo
```

(Windows: `.venv\Scripts\python` instead of `.venv/bin/python`.)

## If it doesn't work

- **"no TCP/UDP address" or it can't connect**: run `git pull` (the host may have new addresses), then try again. Still nothing? The host's server may be off: ask them.
- **"name already taken"**: pick another name, or wait 5 seconds after a crash and retry.
- **Check the connection**: `.venv/bin/python scripts/netcheck.py --host PLAYIT_UDP_HOST --port PLAYIT_UDP_PORT --proto udp` should end with `OK`. If UDP fails but TCP works, your network blocks UDP (some campus Wi-Fi): use the TCP version or a phone hotspot.

Backup TCP route (only if the host asks): install `cloudflared`
(macOS `brew install cloudflared`, Windows `winget install Cloudflare.cloudflared`), `git pull`,
then `bash scripts/join_tcp.sh --name alice --cloudflare` (Windows: `scripts\join_tcp.bat --name alice --cloudflare`).
