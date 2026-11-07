#!/usr/bin/env bash
# Store a new playit.gg agent secret key without it ever appearing on screen or in git, then
# recreate the playit container with it and run deploy_start.sh.
#
#   bash scripts/set_playit_key.sh --clipboard   # copy the key in the browser first (macOS pbpaste)
#   bash scripts/set_playit_key.sh               # or paste it at a hidden prompt
#
# The key goes to logs/deploy/playit.env (git-ignored, chmod 600) as SECRET_KEY=<key>.

set -euo pipefail
source "$(dirname "$0")/deploy_common.sh"

if [ "${1:-}" = "--clipboard" ]; then
    key=$(pbpaste)
else
    read -r -s -p "Paste the playit secret key (hidden), then Enter: " key
    echo
fi
# Accept "SECRET_KEY=abc", a whole "docker run ... -e SECRET_KEY=abc ..." line, or the bare key.
key=$(printf '%s' "$key" | tr -d '[:space:]"'"'" | sed -E 's/.*SECRET_KEY=([0-9a-fA-F]+).*/\1/')
if ! printf '%s' "$key" | grep -qE '^[0-9a-fA-F]{32,}$'; then
    echo "That does not look like a playit secret key (expected a long hex string). Nothing changed." >&2
    exit 1
fi

umask 077
printf 'SECRET_KEY=%s\n' "$key" > "$PLAYIT_ENV"
chmod 600 "$PLAYIT_ENV"
echo "key saved to ${PLAYIT_ENV#$ROOT/} (git-ignored, ${#key} characters, not shown)"
git -C "$ROOT" check-ignore -q "$PLAYIT_ENV" || { echo "WARNING: $PLAYIT_ENV is NOT git-ignored" >&2; exit 1; }

# The container reads --env-file only when it is created: remove the old one.
if docker_up && docker inspect "$PLAYIT_CONTAINER" >/dev/null 2>&1; then
    docker rm -f "$PLAYIT_CONTAINER" >/dev/null
    echo "old playit container removed"
fi
bash "$ROOT/scripts/deploy_start.sh"
echo
echo "Agent log (key hidden):"
sleep 8
docker logs --tail 6 "$PLAYIT_CONTAINER" 2>&1 | sed -E 's/[0-9a-fA-F]{32,}/<hidden>/g'
