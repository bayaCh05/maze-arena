#!/usr/bin/env bash
# Host a game in one command (macOS): make sure the servers and tunnels are up
# (deploy_start.sh), print what to send to the other players, then open your own game
# window in room "demo". Closing the window leaves the server running for the others;
# stop everything with: bash scripts/deploy_stop.sh
#
#   bash scripts/host.sh --name baya              # TCP version
#   bash scripts/host.sh --name baya --udp        # UDP version

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/deploy_common.sh"
ROOM=demo

NAME=""
PROTO=tcp
while [ $# -gt 0 ]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --udp) PROTO=udp; shift ;;
        --tcp) PROTO=tcp; shift ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (usage: bash scripts/host.sh --name baya [--udp])" >&2; exit 2 ;;
    esac
done
[ -n "$NAME" ] || { echo "usage: bash scripts/host.sh --name baya [--udp]" >&2; exit 2; }

bash "$ROOT/scripts/deploy_start.sh" || echo "(some parts are DOWN, see above; players may not reach every address)"

UDP_ADDR=$(get_addr PLAYIT_UDP)
TCP_ADDR=$(get_addr PLAYIT_TCP)
CF=$(get_addr CLOUDFLARE_TCP)
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)

echo
echo "=== Send this to the players (room: $ROOM) ==="
if [ "$PROTO" = udp ]; then
    if [ -n "$UDP_ADDR" ]; then
        echo "  any network:  bash scripts/join_udp.sh --name <their name>     (UDP server $UDP_ADDR)"
    else
        echo "  any network:  no playit UDP address yet (create the UDP tunnel, see docs/JOIN.md)"
    fi
    [ -n "$LAN_IP" ] && echo "  same Wi-Fi:   python -m client_ui.ui --proto udp --host $LAN_IP --port $PORT --name <their name> --room $ROOM"
else
    if [ -n "$TCP_ADDR" ]; then
        echo "  any network:  bash scripts/join_tcp.sh --name <their name>     (TCP server $TCP_ADDR)"
    elif [ -n "$CF" ]; then
        echo "  any network:  bash scripts/tunnel_client.sh --hostname $CF --name <their name> --room $ROOM   (needs cloudflared)"
    fi
    [ -n "$LAN_IP" ] && echo "  same Wi-Fi:   python -m client_ui.ui --proto tcp --host $LAN_IP --port $PORT --name <their name> --room $ROOM"
fi
echo "Everyone presses R (ready) in the room; the game starts when all 2-3 players are ready."
echo

# The host plays on the local server directly: same game, no tunnel delay.
cd "$ROOT"
"$PY" -m client_ui.ui --proto "$PROTO" --host 127.0.0.1 --port "$PORT" --name "$NAME" --room "$ROOM" || true
echo "Your window is closed; the server keeps running for the others. Stop it: bash scripts/deploy_stop.sh"
