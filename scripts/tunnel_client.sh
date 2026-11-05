#!/usr/bin/env bash
# Client side of the Cloudflare Tunnel bonus (macOS or Linux): start
# `cloudflared access tcp` in the background, wait until its local port listens, start the
# game client on 127.0.0.1:<local port>, and stop cloudflared when the game exits.
#
#   bash scripts/tunnel_client.sh --hostname maze.example.com --name alice --room demo
#   bash scripts/tunnel_client.sh --hostname maze.example.com --local-port 15051 --bot --name bob --room demo --players 3
#
# Options (everything else is passed to the game client):
#   --hostname H      the tunnel's public hostname (required)
#   --local-port N    local port cloudflared listens on (default 15050)
#   --bot             run the headless bot (client_ui.bot) instead of the window
# Env: CLOUDFLARED=path overrides the cloudflared binary (tests use a fake one).
# Windows: scripts\tunnel_client.bat

set -euo pipefail

HOSTNAME_=""
LOCAL_PORT=15050
MODULE=client_ui.ui
CLOUDFLARED="${CLOUDFLARED:-cloudflared}"
CLIENT_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --hostname) HOSTNAME_="$2"; shift 2 ;;
        --local-port) LOCAL_PORT="$2"; shift 2 ;;
        --bot) MODULE=client_ui.bot; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) CLIENT_ARGS+=("$1"); shift ;;
    esac
done
[ -n "$HOSTNAME_" ] || { echo "usage: $0 --hostname maze.<domain> [--local-port N] [client args]" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$ROOT/logs"
CF_LOG="$ROOT/logs/cloudflared_access_$LOCAL_PORT.log"

listening() {
    if command -v lsof >/dev/null; then
        lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1
    else
        ss -ltn "sport = :$LOCAL_PORT" 2>/dev/null | grep -q LISTEN
    fi
}

command -v "$CLOUDFLARED" >/dev/null || {
    echo "cloudflared not found. macOS: brew install cloudflared (docs/cloudflare_tunnel.md, step 5)" >&2; exit 1; }
if listening; then
    echo "local port $LOCAL_PORT is already in use (an old cloudflared?). Use --local-port 15051, or:" >&2
    lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >&2 || true
    exit 1
fi

CF_PID=""
cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [ -n "$CF_PID" ] && kill -0 "$CF_PID" 2>/dev/null; then
        echo "stopping cloudflared (pid $CF_PID)"
        kill "$CF_PID" 2>/dev/null
        wait "$CF_PID" 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

echo "cloudflared access tcp --hostname $HOSTNAME_ --url localhost:$LOCAL_PORT  (log: $CF_LOG)"
"$CLOUDFLARED" access tcp --hostname "$HOSTNAME_" --url "localhost:$LOCAL_PORT" > "$CF_LOG" 2>&1 &
CF_PID=$!
for _ in $(seq 75); do
    listening && break
    kill -0 "$CF_PID" 2>/dev/null || { echo "cloudflared exited:" >&2; tail -20 "$CF_LOG" >&2; exit 1; }
    sleep 0.2
done
listening || { echo "localhost:$LOCAL_PORT not open after 15 s, see $CF_LOG" >&2; exit 1; }

# cloudflared only opens the edge connection when the game connects, so a wrong hostname
# shows up here as a refused/closed connection and in $CF_LOG, not before.
echo "local port $LOCAL_PORT open; starting $MODULE --proto tcp --host 127.0.0.1 --port $LOCAL_PORT"
cd "$ROOT"
"$PY" -m "$MODULE" --proto tcp --host 127.0.0.1 --port "$LOCAL_PORT" ${CLIENT_ARGS[@]+"${CLIENT_ARGS[@]}"}
