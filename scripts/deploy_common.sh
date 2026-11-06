# Shared by deploy_start.sh, deploy_stop.sh and deploy_status.sh (sourced, not run).
# Everything the deployment starts keeps its PID and log in logs/deploy/ (git-ignored).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$ROOT/logs/deploy"
ADDR_FILE="$ROOT/deploy/public_addresses.env"
PLAYIT_ENV="$DEPLOY_DIR/playit.env"          # SECRET_KEY=... (never committed)
PLAYIT_CONTAINER=maze-playit
PLAYIT_IMAGE=ghcr.io/playit-cloud/playit-agent:latest
PORT="${PORT:-5050}"
WEB_PORT="${WEB_PORT:-8080}"          # web/bridge.py: browser client + WebSocket relay
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
mkdir -p "$DEPLOY_DIR"

# pid_alive NAME: the process in logs/deploy/NAME.pid is still running
pid_alive() {
    local f="$DEPLOY_DIR/$1.pid"
    [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null
}

# get_addr KEY: value of KEY in deploy/public_addresses.env (empty if unset)
get_addr() {
    grep -E "^$1=" "$ADDR_FILE" 2>/dev/null | head -1 | cut -d= -f2-
}

# set_addr KEY VALUE: rewrite that line of deploy/public_addresses.env
set_addr() {
    local tmp="$ADDR_FILE.tmp"
    awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k{print k "=" v; next} {print}' "$ADDR_FILE" > "$tmp"
    mv "$tmp" "$ADDR_FILE"
}

# cloudflare_host: current quick tunnel hostname, read from the running tunnel's log
cloudflare_host() {
    grep -oE '[a-z0-9-]+\.trycloudflare\.com' "$DEPLOY_DIR/cloudflared.log" 2>/dev/null | head -1 || true
}

# web_url: https link of the browser version (quick tunnel to the bridge), from its log
web_url() {
    grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$DEPLOY_DIR/web_tunnel.log" 2>/dev/null | head -1 || true
}

docker_up() {
    command -v docker >/dev/null && docker info >/dev/null 2>&1
}

playit_running() {
    docker_up && [ "$(docker inspect -f '{{.State.Running}}' "$PLAYIT_CONTAINER" 2>/dev/null)" = true ]
}
