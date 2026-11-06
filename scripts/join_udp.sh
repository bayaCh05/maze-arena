#!/usr/bin/env bash
# Join the public Maze Arena server, UDP version (macOS / Linux). Run from the repo root
# after the setup in docs/JOIN.md. The server address comes from deploy/public_addresses.env.
#
#   bash scripts/join_udp.sh --name alice

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADDR_FILE="$ROOT/deploy/public_addresses.env"
ROOM=demo

NAME=""
while [ $# -gt 0 ]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (usage: bash scripts/join_udp.sh --name alice)" >&2; exit 2 ;;
    esac
done
[ -n "$NAME" ] || { echo "usage: bash scripts/join_udp.sh --name alice" >&2; exit 2; }

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "no .venv here: do the setup in docs/JOIN.md first" >&2; exit 1; }
ADDR=$(grep -E "^PLAYIT_UDP=" "$ADDR_FILE" | head -1 | cut -d= -f2-)
[ -n "$ADDR" ] || { echo "no UDP address in deploy/public_addresses.env yet: git pull, or ask the host" >&2; exit 1; }

echo "UDP server: $ADDR"
cd "$ROOT"
exec "$PY" -m client_ui.ui --proto udp --host "${ADDR%:*}" --port "${ADDR##*:}" --name "$NAME" --room "$ROOM"
