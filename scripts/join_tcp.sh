#!/usr/bin/env bash
# Join the public Maze Arena server, TCP version (macOS / Linux). Run from the repo root
# after the setup in docs/JOIN.md. The server address comes from deploy/public_addresses.env.
#
#   bash scripts/join_tcp.sh --name alice
#   bash scripts/join_tcp.sh --name alice --cloudflare   # backup route (needs cloudflared)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADDR_FILE="$ROOT/deploy/public_addresses.env"
ROOM=demo

NAME=""
ROUTE=playit
while [ $# -gt 0 ]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --cloudflare) ROUTE=cloudflare; shift ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (usage: bash scripts/join_tcp.sh --name alice)" >&2; exit 2 ;;
    esac
done
[ -n "$NAME" ] || { echo "usage: bash scripts/join_tcp.sh --name alice" >&2; exit 2; }

addr() { grep -E "^$1=" "$ADDR_FILE" | head -1 | cut -d= -f2-; }
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "no .venv here: do the setup in docs/JOIN.md first" >&2; exit 1; }

PLAYIT=$(addr PLAYIT_TCP)
CLOUDFLARE=$(addr CLOUDFLARE_TCP)
[ "$ROUTE" = playit ] && [ -z "$PLAYIT" ] && ROUTE=cloudflare
cd "$ROOT"
if [ "$ROUTE" = playit ]; then
    echo "TCP server: $PLAYIT"
    exec "$PY" -m client_ui.ui --proto tcp --host "${PLAYIT%:*}" --port "${PLAYIT##*:}" --name "$NAME" --room "$ROOM"
fi
[ -n "$CLOUDFLARE" ] || { echo "no TCP address in deploy/public_addresses.env yet: git pull, or ask the host" >&2; exit 1; }
echo "TCP server via Cloudflare: $CLOUDFLARE"
exec bash "$ROOT/scripts/tunnel_client.sh" --hostname "$CLOUDFLARE" --name "$NAME" --room "$ROOM"
