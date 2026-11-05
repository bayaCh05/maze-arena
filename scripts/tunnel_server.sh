#!/usr/bin/env bash
# Server side of the Cloudflare Tunnel bonus (macOS or Linux): start the TCP server on
# localhost and `cloudflared tunnel run`, stop both on Ctrl-C. One-time setup (login,
# tunnel create, config.yml, DNS route) is in docs/cloudflare_tunnel.md.
#
#   bash scripts/tunnel_server.sh                     # tunnel "maze", port 5050
#   bash scripts/tunnel_server.sh --tunnel maze --port 5050 --server-args "--game-seconds 60"
#   bash scripts/tunnel_server.sh --no-server        # tunnel only, to the TCP server already on 5050
#
# Options:
#   --port N            TCP server port; must match `service: tcp://localhost:N` in config.yml (default 5050)
#   --tunnel NAME       named tunnel to run (default maze)
#   --config PATH       cloudflared config (default ~/.cloudflared/config.yml)
#   --server-args "..." extra tcp.server flags
#   --no-server         don't start a server: the TCP server is already running (LAN players use it too)
# Env: CLOUDFLARED=path overrides the cloudflared binary (tests use a fake one).

set -euo pipefail

PORT=5050
TUNNEL=maze
CONFIG="$HOME/.cloudflared/config.yml"
SERVER_ARGS=""
NO_SERVER=0
CLOUDFLARED="${CLOUDFLARED:-cloudflared}"

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --tunnel) TUNNEL="$2"; shift 2 ;;
        --config) CONFIG="$2"; shift 2 ;;
        --server-args) SERVER_ARGS="$2"; shift 2 ;;
        --no-server) NO_SERVER=1; shift ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

command -v "$CLOUDFLARED" >/dev/null || {
    echo "cloudflared not found. macOS: brew install cloudflared (docs/cloudflare_tunnel.md, step 1)" >&2; exit 1; }
[ -f "$CONFIG" ] || {
    echo "no $CONFIG: create it first (docs/cloudflare_tunnel.md, step 3)" >&2; exit 1; }
grep -q "tcp://localhost:$PORT" "$CONFIG" || grep -q "tcp://127.0.0.1:$PORT" "$CONFIG" || {
    echo "WARNING: $CONFIG has no 'service: tcp://localhost:$PORT': the tunnel would forward to another port." >&2; }
if [ "$NO_SERVER" = 1 ]; then
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || {
        echo "--no-server: nothing listens on TCP port $PORT; start: python -m tcp.server --port $PORT" >&2; exit 1; }
elif lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $PORT is already in use (an old server? or use --no-server to tunnel to it):" >&2
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2
    exit 1
fi

SERVER_PID=""
TUNNEL_PID=""
cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    echo
    echo "stopping ${SERVER_PID:+server and }tunnel ..."
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    wait 2>/dev/null
    exit "$rc"
}
trap cleanup EXIT INT TERM

# The server still binds 0.0.0.0 (LAN players can join directly too); cloudflared reaches it
# on localhost, so every tunnel player shows up as 127.0.0.1:<port> in this log.
cd "$ROOT"
if [ "$NO_SERVER" = 0 ]; then
    # shellcheck disable=SC2086
    "$PY" -u -m tcp.server --port "$PORT" $SERVER_ARGS > >(tee "$LOGS/tunnel_tcp_server.log") 2>&1 &
    SERVER_PID=$!
    for _ in $(seq 50); do
        lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && break
        kill -0 "$SERVER_PID" 2>/dev/null || { echo "the TCP server exited, see $LOGS/tunnel_tcp_server.log" >&2; exit 1; }
        sleep 0.2
    done
fi

echo "starting tunnel '$TUNNEL' (log: $LOGS/tunnel_cloudflared.log) ..."
"$CLOUDFLARED" tunnel --config "$CONFIG" run "$TUNNEL" > "$LOGS/tunnel_cloudflared.log" 2>&1 &
TUNNEL_PID=$!
for _ in $(seq 60); do
    grep -q "Registered tunnel connection" "$LOGS/tunnel_cloudflared.log" && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || { echo "cloudflared exited:" >&2; tail -20 "$LOGS/tunnel_cloudflared.log" >&2; exit 1; }
    sleep 0.5
done
if grep -q "Registered tunnel connection" "$LOGS/tunnel_cloudflared.log"; then
    echo "tunnel connected ($(grep -c "Registered tunnel connection" "$LOGS/tunnel_cloudflared.log") edge connection(s) so far)."
else
    echo "WARNING: no 'Registered tunnel connection' after 30 s; check $LOGS/tunnel_cloudflared.log" >&2
fi
HOSTNAME_IN_CONFIG="$(sed -n 's/^[[:space:]-]*hostname:[[:space:]]*//p' "$CONFIG" | head -1)"
echo
echo "Players run:  bash scripts/tunnel_client.sh --hostname ${HOSTNAME_IN_CONFIG:-maze.<your domain>} --name alice --room demo"
echo "        Windows: scripts\\tunnel_client.bat ${HOSTNAME_IN_CONFIG:-maze.<your domain>} --name alice --room demo"
if [ "$NO_SERVER" = 1 ]; then
    echo "Ctrl-C stops the tunnel (the server keeps running)."
    wait "$TUNNEL_PID"
else
    echo "Ctrl-C stops both."
    wait "$SERVER_PID"
fi
