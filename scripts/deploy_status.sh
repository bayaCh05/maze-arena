#!/usr/bin/env bash
# One line per part of the public deployment, OK or DOWN, then the public addresses.
#
#   bash scripts/deploy_status.sh
#   bash scripts/deploy_status.sh --check     # also netcheck every public address (RTT)

set -uo pipefail
source "$(dirname "$0")/deploy_common.sh"

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1
DOWN=0

line() {   # line OK|DOWN NAME DETAIL
    printf '  %-5s %-18s %s\n' "$1" "$2" "$3"
    [ "$1" = DOWN ] && DOWN=$((DOWN + 1))
    return 0
}

echo "Maze Arena deployment ($(date '+%Y-%m-%d %H:%M:%S'))"
if pid_alive tcp_server && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    line OK "TCP server" "pid $(cat "$DEPLOY_DIR/tcp_server.pid"), TCP 0.0.0.0:$PORT"
else
    line DOWN "TCP server" "start: bash scripts/deploy_start.sh"
fi
if pid_alive udp_server && [ -n "$(udp_holder "$PORT")" ]; then
    line OK "UDP server" "pid $(cat "$DEPLOY_DIR/udp_server.pid"), UDP 0.0.0.0:$PORT"
else
    line DOWN "UDP server" "start: bash scripts/deploy_start.sh"
fi
if pid_alive bridge && lsof -nP -iTCP:"$WEB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    line OK "web bridge" "pid $(cat "$DEPLOY_DIR/bridge.pid"), http://localhost:$WEB_PORT -> TCP $PORT"
else
    line DOWN "web bridge" "start: bash scripts/deploy_start.sh"
fi
if pid_alive web_tunnel && [ -n "$(web_url)" ]; then
    line OK "web link" "$(web_url)"
else
    line DOWN "web link" "https quick tunnel not running"
fi
if pid_alive cloudflared && [ -n "$(cloudflare_host)" ]; then
    line OK "Cloudflare tunnel" "$(cloudflare_host) -> localhost:$PORT (TCP)"
else
    line DOWN "Cloudflare tunnel" "quick tunnel not running"
fi
if playit_running; then
    if docker logs --tail 50 "$PLAYIT_CONTAINER" 2>&1 | grep -qiE 'invalid|unauthorized|SECRET_KEY'; then
        line DOWN "playit agent" "container runs but the key is refused: docker logs $PLAYIT_CONTAINER"
    else
        line OK "playit agent" "docker container $PLAYIT_CONTAINER (Online? see playit.gg → Agents)"
    fi
elif ! docker_up; then
    line DOWN "playit agent" "Docker Desktop is not running"
else
    line DOWN "playit agent" "container $PLAYIT_CONTAINER not running"
fi
if pid_alive caffeinate; then
    line OK "caffeinate" "Mac kept awake"
else
    line DOWN "caffeinate" "the Mac may sleep and drop every player"
fi

echo
echo "Public addresses (deploy/public_addresses.env):"
printf '  %-15s %s\n' "Browser link" "$(get_addr WEB_URL || true)"
printf '  %-15s %s\n' "UDP (playit)" "$(get_addr PLAYIT_UDP || true)"
printf '  %-15s %s\n' "TCP (playit)" "$(get_addr PLAYIT_TCP || true)"
printf '  %-15s %s\n' "TCP (Cloudflare)" "$(get_addr CLOUDFLARE_TCP || true)"
cf_file=$(get_addr CLOUDFLARE_TCP)
cf_live=$(cloudflare_host)
if [ -n "$cf_live" ] && [ "$cf_file" != "$cf_live" ]; then
    echo "  note: the running Cloudflare tunnel is $cf_live (file says ${cf_file:-nothing})"
fi

if [ "$CHECK" = 1 ]; then
    cd "$ROOT"
    for key in PLAYIT_UDP PLAYIT_TCP; do
        addr=$(get_addr "$key")
        [ -z "$addr" ] && continue
        proto=$(echo "${key#PLAYIT_}" | tr 'A-Z' 'a-z')
        echo
        echo "netcheck $proto $addr"
        "$PY" scripts/netcheck.py --host "${addr%:*}" --port "${addr##*:}" --proto "$proto" | tail -3
    done
fi

exit $(( DOWN > 0 ))
