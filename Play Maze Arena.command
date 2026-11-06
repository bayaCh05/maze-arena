#!/usr/bin/env bash
# Double-click to play Maze Arena on the public server (macOS; also: bash "Play Maze Arena.command").
# First run: creates .venv and installs pygame-ce (needs Python 3.10+ and internet).
# Every run: fetches the current server addresses from GitHub, asks TCP or UDP, starts the game.
cd "$(dirname "$0")" || exit 1
ADDR_URL=https://raw.githubusercontent.com/bayaCh05/maze-arena/main/deploy/public_addresses.env
ROOM=demo

fail() { echo "$1"; read -r -p "Press Enter to close."; exit 1; }

if [ ! -x .venv/bin/python ]; then
    command -v python3 >/dev/null || {
        open https://www.python.org/downloads/
        fail "Python is not installed: install it from python.org (page opened), then double-click this file again."
    }
    echo "First run: setting up the game (about 1 minute)..."
    python3 -m venv .venv || fail "Could not create .venv"
    .venv/bin/python -m pip install --disable-pip-version-check -q pygame-ce || fail "Could not install pygame-ce: check your internet"
fi

# Fresh addresses (the ZIP may be older than the server); keep the local file if offline.
if curl -fsS -m 5 "$ADDR_URL" -o deploy/public_addresses.env.new 2>/dev/null; then
    mv deploy/public_addresses.env.new deploy/public_addresses.env
else
    rm -f deploy/public_addresses.env.new
fi
addr() { grep -E "^$1=" deploy/public_addresses.env | head -1 | cut -d= -f2-; }

echo
echo "  MAZE ARENA"
echo "  1 = TCP version"
echo "  2 = UDP version"
read -r -p "Choose 1 or 2 [1]: " CHOICE
if [ "$CHOICE" = 2 ]; then PROTO=udp; ADDR=$(addr PLAYIT_UDP); else PROTO=tcp; ADDR=$(addr PLAYIT_TCP); fi
echo "Same Wi-Fi as the host? Type the host's IP (e.g. 192.168.1.23)."
read -r -p "Otherwise just press Enter for the internet server: " LAN
[ -n "$LAN" ] && ADDR="$LAN:5050"
[ -n "$ADDR" ] || fail "The internet $PROTO address is not published yet: ask the host for their IP and type it."

echo "Connecting to $ADDR ($PROTO). Type your name in the game window."
.venv/bin/python -m client_ui.ui --proto "$PROTO" --host "${ADDR%:*}" --port "${ADDR##*:}" --room "$ROOM" \
    || fail "The game stopped with an error (see above). Is the host's server on? Try the other version, or a phone hotspot."
