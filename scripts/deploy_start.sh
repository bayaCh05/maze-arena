#!/usr/bin/env bash
# Start (or restart the missing parts of) the public Maze Arena deployment on this Mac:
#   TCP server + UDP server on 0.0.0.0:5050, Cloudflare quick tunnel (TCP backup route),
#   browser version: web/bridge.py on :8080 + an https Cloudflare quick tunnel (the link),
#   playit agent in Docker (UDP and TCP tunnels), caffeinate (no sleep).
# Parts already running are left alone, so it is safe to run again. Ends with deploy_status.sh.
#
#   bash scripts/deploy_start.sh
#   bash scripts/deploy_start.sh --server-args "--game-seconds 60"
#   bash scripts/deploy_start.sh --restart          # deploy_stop.sh first, then start everything
#
# The playit agent needs its key once: logs/deploy/playit.env containing SECRET_KEY=<key>
# (from playit.gg → Agents → Add Agent → Docker). That file is git-ignored.

set -euo pipefail
source "$(dirname "$0")/deploy_common.sh"

SERVER_ARGS=""
RESTART=0
while [ $# -gt 0 ]; do
    case "$1" in
        --server-args) SERVER_ARGS="$2"; shift 2 ;;
        --restart) RESTART=1; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
done
[ "$RESTART" = 1 ] && bash "$ROOT/scripts/deploy_stop.sh"
cd "$ROOT"

# start_server tcp|udp: nohup the server unless its PID file points to a live process.
# Refuses if another process already holds the port (e.g. a server started by hand).
start_server() {
    local proto="$1" holder
    if pid_alive "${proto}_server"; then
        echo "$proto server: already running (pid $(cat "$DEPLOY_DIR/${proto}_server.pid"))"
        return
    fi
    if [ "$proto" = tcp ]; then
        holder=$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
    else
        holder=$(udp_holder "$PORT")
    fi
    if [ -n "$holder" ]; then
        echo "$proto server: port $PORT is already used by pid $holder, not started:" >&2
        ps -p "$holder" -o pid=,command= >&2 || true
        return 1
    fi
    # shellcheck disable=SC2086
    nohup "$PY" -u -m "$proto.server" --host 0.0.0.0 --port "$PORT" $SERVER_ARGS \
        >> "$DEPLOY_DIR/${proto}_server.log" 2>&1 &
    echo $! > "$DEPLOY_DIR/${proto}_server.pid"
    echo "$proto server: started (pid $!, log logs/deploy/${proto}_server.log)"
}

start_server tcp || true
start_server udp || true

# Browser version: build the client if needed, then the bridge (WebSocket -> TCP server).
if [ ! -f "$ROOT/web/client/dist/index.html" ] && command -v npm >/dev/null; then
    echo "web client: building (first time)..."
    (cd "$ROOT/web/client" && npm install --no-audit --no-fund >/dev/null && npm run build >/dev/null) \
        || echo "web client: build failed, run: cd web/client && npm install && npm run build" >&2
fi
if pid_alive bridge; then
    echo "web bridge: already running"
elif lsof -nP -iTCP:"$WEB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "web bridge: port $WEB_PORT already in use, not started" >&2
else
    nohup "$PY" -u -m web.bridge --port "$WEB_PORT" --game-port "$PORT" >> "$DEPLOY_DIR/bridge.log" 2>&1 &
    echo $! > "$DEPLOY_DIR/bridge.pid"
    echo "web bridge: started (pid $!, http://localhost:$WEB_PORT)"
fi

# Cloudflare quick tunnel: a new random hostname every time it starts.
if pid_alive cloudflared; then
    echo "cloudflare tunnel: already running"
elif command -v cloudflared >/dev/null; then
    old=$(get_addr CLOUDFLARE_TCP)
    : > "$DEPLOY_DIR/cloudflared.log"
    nohup cloudflared tunnel --no-autoupdate --url "tcp://localhost:$PORT" \
        > "$DEPLOY_DIR/cloudflared.log" 2>&1 &
    echo $! > "$DEPLOY_DIR/cloudflared.pid"
    host=""
    for _ in $(seq 60); do
        host=$(cloudflare_host)
        [ -n "$host" ] && break
        sleep 0.5
    done
    if [ -n "$host" ]; then
        set_addr CLOUDFLARE_TCP "$host"
        echo "cloudflare tunnel: started, address $host"
        if [ "$host" != "$old" ]; then
            echo "  NEW ADDRESS (was ${old:-none}): send it to players who use the Cloudflare route,"
            echo "  and commit deploy/public_addresses.env so join_tcp --cloudflare picks it up."
        fi
    else
        echo "cloudflare tunnel: no address after 30 s, see logs/deploy/cloudflared.log" >&2
    fi
else
    echo "cloudflare tunnel: cloudflared not installed (brew install cloudflared), skipped"
fi

# The link players open: an https quick tunnel to the bridge (WebSocket works through it).
if pid_alive web_tunnel; then
    echo "web link: already running"
elif command -v cloudflared >/dev/null; then
    old=$(get_addr WEB_URL)
    : > "$DEPLOY_DIR/web_tunnel.log"
    nohup cloudflared tunnel --no-autoupdate --url "http://localhost:$WEB_PORT" \
        > "$DEPLOY_DIR/web_tunnel.log" 2>&1 &
    echo $! > "$DEPLOY_DIR/web_tunnel.pid"
    url=""
    for _ in $(seq 60); do
        url=$(web_url)
        [ -n "$url" ] && break
        sleep 0.5
    done
    if [ -n "$url" ]; then
        set_addr WEB_URL "$url"
        echo "web link: $url"
        if [ "$url" != "$old" ]; then echo "  NEW LINK (was ${old:-none}): send it to the players."; fi
    else
        echo "web link: no address after 30 s, see logs/deploy/web_tunnel.log" >&2
    fi
fi

# playit agent in Docker. --restart unless-stopped: it comes back after a Docker or Mac
# restart, until deploy_stop.sh stops it.
if [ ! -s "$PLAYIT_ENV" ]; then
    echo "playit agent: no key yet. Put SECRET_KEY=<key> in logs/deploy/playit.env, then run this again"
else
    if ! docker_up; then
        echo "playit agent: starting Docker Desktop..."
        open -a Docker
        for _ in $(seq 60); do docker_up && break; sleep 2; done
    fi
    if ! docker_up; then
        echo "playit agent: Docker is not running, skipped" >&2
    elif playit_running; then
        echo "playit agent: already running"
    elif docker inspect "$PLAYIT_CONTAINER" >/dev/null 2>&1; then
        docker start "$PLAYIT_CONTAINER" >/dev/null
        echo "playit agent: container started again"
    else
        docker run -d --name "$PLAYIT_CONTAINER" --restart unless-stopped \
            --env-file "$PLAYIT_ENV" "$PLAYIT_IMAGE" >/dev/null
        echo "playit agent: container created (tunnels point to host.docker.internal:$PORT)"
    fi
fi

if pid_alive caffeinate; then
    echo "caffeinate: already running"
else
    nohup caffeinate -dims > /dev/null 2>&1 &
    echo $! > "$DEPLOY_DIR/caffeinate.pid"
    echo "caffeinate: started (the Mac won't sleep while the deployment runs)"
fi

echo
sleep 1
bash "$ROOT/scripts/deploy_status.sh"
