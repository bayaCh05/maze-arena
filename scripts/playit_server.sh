#!/usr/bin/env bash
# UDP version across networks with playit.gg (macOS or Linux): start the UDP server and
# check that the playit agent is running. The agent and its UDP tunnel are set up once in
# the playit.gg dashboard: docs/playit_udp.md.
#
#   bash scripts/playit_server.sh                                  # UDP server on 5050
#   bash scripts/playit_server.sh --address xxx.at.ply.gg:12345   # also print the exact client command
#
# Options:
#   --port N            local UDP port; must be the tunnel's "local port" in the dashboard (default 5050)
#   --address HOST:PORT the public address playit shows for the tunnel (only printed)
#   --server-args "..." extra udp.server flags, e.g. "--game-seconds 60"

set -euo pipefail

PORT=5050
ADDRESS=""
SERVER_ARGS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --address) ADDRESS="$2"; shift 2 ;;
        --server-args) SERVER_ARGS="$2"; shift 2 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$ROOT/logs"

if lsof -nP -iUDP:"$PORT" >/dev/null 2>&1; then
    echo "UDP port $PORT is already in use (an old udp.server?):" >&2
    lsof -nP -iUDP:"$PORT" >&2
    exit 1
fi

if pgrep -x playitd >/dev/null 2>&1 || pgrep -x playit >/dev/null 2>&1; then
    echo "playit agent: running (check it says Online at https://playit.gg/account/agents)"
else
    echo "playit agent: NOT running. Start it first:"
    echo "  macOS: open -a playit   (menu bar app; or run: playit)"
    echo "  Linux: sudo systemctl start playit   Windows: start 'playit' from the Start menu"
    echo "(the server starts anyway; the tunnel works as soon as the agent is online)"
fi

HOST_PART="${ADDRESS%:*}"
PORT_PART="${ADDRESS##*:}"
if [ -z "$ADDRESS" ] || [ "$HOST_PART" = "$ADDRESS" ]; then
    HOST_PART="<playit address, e.g. xxx.at.ply.gg>"
    PORT_PART="<playit port>"
fi
echo
echo "Tunnel in the playit dashboard: type UDP, local address 127.0.0.1, local port $PORT."
echo "Players (nothing to install) check, then play:"
echo "  python scripts/netcheck.py --host $HOST_PART --port $PORT_PART --proto udp"
echo "  python -m client_ui.ui --proto udp --host $HOST_PART --port $PORT_PART --name alice --room demo"
echo "Server log: every playit player shows up as 127.0.0.1:<port> (the agent), one NEW PEER each."
echo

cd "$ROOT"
# shellcheck disable=SC2086
"$PY" -u -m udp.server --port "$PORT" $SERVER_ARGS 2>&1 | tee "$ROOT/logs/playit_udp_server.log"
