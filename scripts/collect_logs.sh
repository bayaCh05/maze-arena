#!/usr/bin/env bash
# After the 4-computer test: zip this laptop's logs + a short system report, named after the
# laptop, so the team can check afterwards what happened on each machine.
#
#   bash scripts/collect_logs.sh S      # the server laptop (S, A, B or C: see docs/FOUR_PC_TEST.md)
#   bash scripts/collect_logs.sh A
#
# Output: logs/four_pc_<ROLE>_<hostname>_<date>.zip (logs/ is git-ignored). Secrets are
# never included (logs/deploy/playit.env and any *.env are skipped).

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
HOST="$( (scutil --get ComputerName 2>/dev/null || hostname -s) | tr -c 'A-Za-z0-9_-' '-' | sed 's/-*$//')"
ROLE="${1:-$HOST}"
STAMP="$(date +%Y%m%d_%H%M)"
NAME="four_pc_${ROLE}_${HOST}_${STAMP}"
WORK="$(mktemp -d)"
DEST="$WORK/$NAME"
mkdir -p "$DEST" logs

# Everything the test wrote into logs/ (tee'd server and client output), never secrets.
find logs -maxdepth 2 -type f \( -name '*.log' -o -name '*.txt' -o -name '*.csv' \) \
    ! -name '*.env' ! -path 'logs/deploy/playit.env' -newermt "$(date -v-1d '+%Y-%m-%d %H:%M' 2>/dev/null || date -d '1 day ago' '+%Y-%m-%d %H:%M')" \
    -exec cp {} "$DEST/" \; 2>/dev/null || true

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
{
    echo "role:        $ROLE"
    echo "hostname:    $HOST"
    echo "collected:   $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "os:          $(uname -srm)"
    echo "python:      $("$PY" --version 2>&1)"
    echo "commit:      $("$PY" -c 'from netutil.version import commit; print(commit())' 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo
    echo "== IPv4 addresses"
    ifconfig 2>/dev/null | awk '/inet / && $2 != "127.0.0.1" {print "  " $2}' || ip -4 addr 2>/dev/null
    echo
    echo "== Wi-Fi network"
    wifi=$(networksetup -getairportnetwork en0 2>/dev/null || iwgetid 2>/dev/null || true)
    case "$wifi" in
        *"not associated"*|"") echo "  (name hidden by macOS or not on Wi-Fi: compare the IP prefixes above instead)" ;;
        *) echo "  $wifi" ;;
    esac
    echo
    echo "== VPN / tunnel interfaces (utun/tun/wg with an IPv4 address)"
    ifconfig 2>/dev/null | awk '/^(utun|tun|wg|ppp)[0-9]*:/ {i=$1} /inet / && i {print "  " i " " $2; i=""}' || true
    echo
    echo "== processes of the game still running"
    pgrep -fl 'tcp.server|udp.server|client_ui' || echo "  none"
} > "$DEST/system_info.txt" 2>&1

(cd "$WORK" && zip -qr "$NAME.zip" "$NAME")
mv "$WORK/$NAME.zip" "logs/$NAME.zip"
rm -rf "$WORK"
COUNT=$(unzip -l "logs/$NAME.zip" | tail -1 | awk '{print $2}')
echo "Saved $ROOT/logs/$NAME.zip ($COUNT files)."
echo "Send it to the team (AirDrop, WhatsApp, USB). It contains no passwords or keys."
