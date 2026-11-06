#!/usr/bin/env bash
# Stop the public Maze Arena deployment: both servers, the Cloudflare quick tunnel, the
# playit container (kept, so deploy_start.sh restarts it without the key) and caffeinate.
#
#   bash scripts/deploy_stop.sh

set -uo pipefail
source "$(dirname "$0")/deploy_common.sh"

# stop NAME: SIGTERM the process in logs/deploy/NAME.pid (servers exit like on Ctrl-C)
stop() {
    if pid_alive "$1"; then
        local pid
        pid=$(cat "$DEPLOY_DIR/$1.pid")
        kill "$pid"
        for _ in $(seq 25); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
        echo "$1: stopped (pid $pid)"
    else
        echo "$1: not running"
    fi
    rm -f "$DEPLOY_DIR/$1.pid"
}

stop tcp_server
stop udp_server
stop cloudflared
if playit_running; then
    docker stop "$PLAYIT_CONTAINER" >/dev/null && echo "playit agent: stopped"
else
    echo "playit agent: not running"
fi
stop caffeinate
