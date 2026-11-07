#!/usr/bin/env bash
# TCP under real packet loss, in one command (macOS). Run it yourself in a Terminal, NOT with
# sudo in front: it asks for your password once, then
#   1. adds a kernel packet-loss rule (dnctl + pfctl, metrics/netloss_mac.sh) on loopback
#      port 5061 only (the benchmark's own servers; the game on 5050 is not touched),
#   2. plays a full benchmark game over TCP at 10 % loss, then at 30 % loss (3 bots each,
#      120 s games, one bot killed mid-game to time disconnect detection),
#   3. ALWAYS removes the rule at the end: normal exit, error or Ctrl+C,
#   4. checks the rule is gone, redraws the charts and prints the new rows.
#
#   bash scripts/tcp_loss_benchmark.sh              # TCP at 10 % and 30 % (~5 min)
#   bash scripts/tcp_loss_benchmark.sh --with-udp   # also UDP under the same kernel loss (~10 min)
#
# Results: metrics/results.csv (rows with loss_method "os"), charts in metrics/charts/,
# full log in metrics/raw/tcp_loss_benchmark.log.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
NETLOSS="$ROOT/metrics/netloss_mac.sh"
LOG="$ROOT/metrics/raw/tcp_loss_benchmark.log"
PROTOS="tcp"
[ "${1:-}" = "--with-udp" ] && PROTOS="tcp udp"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[ "$(uname)" = Darwin ] || { echo "macOS only (dnctl/pfctl). On Linux use tc netem, see metrics/run_benchmark.py."; exit 1; }
[ "$(id -u)" != 0 ] || { echo "Run it WITHOUT sudo (it asks for the password itself): bash scripts/tcp_loss_benchmark.sh"; exit 1; }
if lsof -nP -iTCP:5061 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port 5061 is in use (an earlier benchmark still running?). Stop it first."; exit 1
fi

KEEPALIVE=""
HAVE_SUDO=0
cleanup() {
    local code=$?
    trap - EXIT INT TERM
    [ "$HAVE_SUDO" = 1 ] || exit "$code"   # no password given: nothing was applied
    step "Removing the packet-loss rule"
    sudo -n sh "$NETLOSS" off 2>/dev/null || sudo sh "$NETLOSS" off
    [ -n "$KEEPALIVE" ] && kill "$KEEPALIVE" 2>/dev/null
    if sudo -n dnctl list 2>/dev/null | grep -q plr || sudo -n pfctl -a mazearena -s dummynet 2>/dev/null | grep -q pipe; then
        echo "WARNING: a loss rule is still there. Run: sudo sh metrics/netloss_mac.sh off"
    else
        echo "Network back to normal: no dummynet pipe, no mazearena pf rule."
    fi
    if [ "$code" -ne 0 ]; then
        echo "Stopped before the end (exit $code). Rows already finished are saved in metrics/results.csv."
    fi
    exit "$code"
}
trap cleanup EXIT
trap 'echo; echo "Interrupted."; exit 130' INT TERM

step "Asking for your password once (needed for dnctl/pfctl)"
sudo -v || exit 1
HAVE_SUDO=1
# Keep sudo alive during the ~5-10 minutes (the benchmark calls sudo -n).
( while true; do sudo -n true 2>/dev/null; sleep 30; done ) &
KEEPALIVE=$!

mkdir -p "$(dirname "$LOG")"
step "Benchmark: $PROTOS at 10 % then 30 % kernel loss on loopback port 5061 (120 s per game)"
echo "    progress below; full log: ${LOG#$ROOT/}"
"$PY" -u metrics/run_benchmark.py --loss-method os --protos $PROTOS --loss 0.1 0.3 --no-charts 2>&1 | tee "$LOG"
[ "${PIPESTATUS[0]}" -eq 0 ] || { echo "The benchmark failed, see ${LOG#$ROOT/}"; exit 1; }

step "Redrawing charts (metrics/charts/)"
"$PY" metrics/make_charts.py

step "New rows in metrics/results.csv (loss_method os)"
"$PY" - <<'EOF'
import csv
cols = ["proto", "loss_pct", "status", "rtt_mean_ms", "inter_update_p99_ms", "inter_update_max_ms",
        "freezes_over_250ms", "states_missing_pct", "detect_ms"]
with open("metrics/results.csv") as f:
    rows = [r for r in csv.DictReader(f) if r["loss_method"] == "os"]
print("  ".join(f"{c:>20}" for c in cols))
for r in rows:
    print("  ".join(f"{r.get(c, ''):>20}" for c in cols))
EOF
echo
echo "Done. Tell Claude \"done\"."
