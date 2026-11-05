#!/usr/bin/env bash
# Set up a fresh Ubuntu VM (Oracle Cloud Free Tier, or any Ubuntu 22.04/24.04) as the
# Maze Arena server: packages, code, venv, both systemd services, the VM's own firewall,
# and a self-test. Run it ON THE VM as the normal user (ubuntu); it calls sudo itself.
# Safe to run again (e.g. after `git pull`): every step is idempotent.
#
#   bash deploy/setup_vm.sh                       # code already on the VM (rsync or clone)
#   bash setup_vm.sh --repo https://github.com/bayaCh05/maze-arena.git   # clone it for you
#   bash deploy/setup_vm.sh --dry-run             # print every command, change nothing
#
# Options:
#   --port N            TCP and UDP port (default 5050)
#   --dir PATH          where the code lives (default: the repo this script is in, else ~/maze-arena)
#   --repo URL          git URL to clone if --dir has no code yet (private repo: see docs/cross_network.md)
#   --public-ip IP      shown in the server banner and the summary (default: asked to ifconfig.me)
#   --server-args "..." extra server flags, e.g. "--game-seconds 30" for rehearsals
#   --all-deps          pip install all of requirements.txt (default: only pytest; servers need no deps)
#   --no-firewall       don't touch the VM firewall (iptables/ufw)
#   --dry-run           print the commands instead of running them
#
# The CLOUD firewall (Oracle Security List / AWS Security Group / GCP firewall rule) can't
# be opened from inside the VM: do it in the cloud console, see docs/cross_network.md (A4).

set -euo pipefail

PORT=5050
DIR=""
REPO=""
PUBLIC_IP=""
SERVER_ARGS=""
ALL_DEPS=0
FIREWALL=1
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT=$2; shift 2 ;;
        --dir) DIR=$2; shift 2 ;;
        --repo) REPO=$2; shift 2 ;;
        --public-ip) PUBLIC_IP=$2; shift 2 ;;
        --server-args) SERVER_ARGS=$2; shift 2 ;;
        --all-deps) ALL_DEPS=1; shift ;;
        --no-firewall) FIREWALL=0; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see --help)"; exit 2 ;;
    esac
done

case "$PORT" in ''|*[!0-9]*) echo "--port must be a number"; exit 2 ;; esac

SCRIPT_REPO=$(cd "$(dirname "$0")/.." && pwd)
if [ -z "$DIR" ]; then
    if [ -f "$SCRIPT_REPO/tcp/server.py" ]; then DIR=$SCRIPT_REPO; else DIR=$HOME/maze-arena; fi
fi
RUN_USER=${SUDO_USER:-$(id -un)}
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

step() { printf '\n=== %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
# run CMD...: show it, then run it (or only show it with --dry-run)
run() {
    printf '  + %s\n' "$*"
    [ "$DRY_RUN" -eq 1 ] || "$@"
}

if [ "$DRY_RUN" -eq 0 ]; then
    [ "$(uname -s)" = Linux ] || { echo "This script sets up an Ubuntu VM. Use --dry-run to read it elsewhere."; exit 1; }
    command -v apt-get >/dev/null || { echo "apt-get not found: this script expects Ubuntu/Debian."; exit 1; }
fi
[ "$DRY_RUN" -eq 1 ] && echo "DRY RUN: nothing is changed, commands are only printed."
info "user=$RUN_USER dir=$DIR port=$PORT (tcp+udp)"

# ---------------------------------------------------------------- 1. packages
step "1/7 Packages (Python, venv, git, network tools)"
run $SUDO apt-get update -q
run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    python3 python3-venv python3-pip git curl iproute2 netcat-openbsd tcpdump

# ---------------------------------------------------------------- 2. code
step "2/7 Code in $DIR"
if [ -d "$DIR/.git" ]; then
    run git -C "$DIR" pull --ff-only || info "git pull failed (local changes?): using the code as it is"
elif [ -f "$DIR/tcp/server.py" ]; then
    info "code already there (copied with rsync?): using it as it is"
elif [ -n "$REPO" ]; then
    info "private repo: git asks for your GitHub user name and a personal access token as password"
    run git clone "$REPO" "$DIR"
else
    echo "No code in $DIR. Copy it first (from the laptop):"
    echo "    rsync -av --exclude .venv --exclude logs maze-arena ubuntu@PUBLIC_IP:~/"
    echo "or pass --repo https://github.com/bayaCh05/maze-arena.git"
    [ "$DRY_RUN" -eq 1 ] || exit 1
fi

# ---------------------------------------------------------------- 3. venv
step "3/7 Virtualenv $DIR/.venv"
run python3 -m venv "$DIR/.venv"
run "$DIR/.venv/bin/pip" install -q --upgrade pip
if [ "$ALL_DEPS" -eq 1 ]; then
    run "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
else
    info "the servers need only the standard library; pytest lets you run the tests here"
    run "$DIR/.venv/bin/pip" install -q pytest
fi

# ---------------------------------------------------------------- 4. public IP
step "4/7 Public IP"
if [ -z "$PUBLIC_IP" ] && [ "$DRY_RUN" -eq 0 ]; then
    PUBLIC_IP=$(curl -4 -s --max-time 5 ifconfig.me || true)
fi
if printf '%s' "$PUBLIC_IP" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    info "public IP: $PUBLIC_IP (players use this one)"
else
    [ "$DRY_RUN" -eq 1 ] && info "(dry run: would ask ifconfig.me)" || info "could not find it: copy it from the cloud console"
    PUBLIC_IP=""
fi
EXTRA_ARGS=""
[ -n "$PUBLIC_IP" ] && EXTRA_ARGS=" --public-ip $PUBLIC_IP"
[ -n "$SERVER_ARGS" ] && EXTRA_ARGS="$EXTRA_ARGS $SERVER_ARGS"

# ---------------------------------------------------------------- 5. services
step "5/7 systemd services maze-arena-tcp and maze-arena-udp"
for old in maze-arena@tcp maze-arena@udp; do            # the template unit from older docs: same port
    if [ "$DRY_RUN" -eq 0 ] && systemctl list-unit-files "maze-arena@.service" 2>/dev/null | grep -q maze-arena@; then
        run $SUDO systemctl disable --now "$old" || true
    fi
done
for proto in tcp udp; do
    unit=/etc/systemd/system/maze-arena-$proto.service
    printf '  + render deploy/maze-arena-%s.service -> %s\n' "$proto" "$unit"
    rendered=$(sed -e "s|@USER@|$RUN_USER|g" -e "s|@DIR@|$DIR|g" -e "s|@PORT@|$PORT|g" \
                   -e "s|@EXTRA_ARGS@|$EXTRA_ARGS|g" "$SCRIPT_REPO/deploy/maze-arena-$proto.service")
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '%s\n' "$rendered" | grep -E '^(User|WorkingDirectory|ExecStart)=' | sed 's/^/      /'
    else
        printf '%s\n' "$rendered" | $SUDO tee "$unit" >/dev/null
    fi
done
run $SUDO systemctl daemon-reload
run $SUDO systemctl enable maze-arena-tcp maze-arena-udp
run $SUDO systemctl restart maze-arena-tcp maze-arena-udp     # restart: picks up new code too

# ---------------------------------------------------------------- 6. VM firewall
step "6/7 VM firewall (port $PORT tcp+udp)"
if [ "$FIREWALL" -eq 0 ]; then
    info "skipped (--no-firewall)"
elif [ "$DRY_RUN" -eq 0 ] && command -v ufw >/dev/null && $SUDO ufw status | grep -q "Status: active"; then
    run $SUDO ufw allow "$PORT/tcp"
    run $SUDO ufw allow "$PORT/udp"
elif [ "$DRY_RUN" -eq 1 ] || $SUDO iptables -S INPUT | grep -q -- "-j REJECT"; then
    # Oracle's Ubuntu images: INPUT ends with "REJECT all" (only SSH allowed). Our rules go above it.
    [ "$DRY_RUN" -eq 1 ] && info "(dry run: showing the Oracle iptables path; with ufw active it runs 'ufw allow')"
    for proto in tcp udp; do
        if [ "$DRY_RUN" -eq 0 ] && $SUDO iptables -C INPUT -p "$proto" --dport "$PORT" -j ACCEPT 2>/dev/null; then
            info "$proto/$PORT already allowed"
            continue
        fi
        N=1
        [ "$DRY_RUN" -eq 0 ] && N=$($SUDO iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')
        run $SUDO iptables -I INPUT "$N" -p "$proto" --dport "$PORT" -j ACCEPT
    done
    if [ "$DRY_RUN" -eq 1 ] || ! command -v netfilter-persistent >/dev/null; then
        run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q iptables-persistent
    fi
    run $SUDO netfilter-persistent save                     # survives reboots
else
    info "no blocking firewall on the VM (no ufw, no REJECT rule): nothing to open here"
fi

# ---------------------------------------------------------------- 7. self-test
step "7/7 Self-test on the VM"
if [ "$DRY_RUN" -eq 1 ]; then
    run systemctl is-active maze-arena-tcp maze-arena-udp
    run ss -ltnup
    run "$DIR/.venv/bin/python" "$DIR/scripts/netcheck.py" --host 127.0.0.1 --port "$PORT" --count 3
else
    sleep 2
    systemctl is-active maze-arena-tcp maze-arena-udp || { journalctl -u maze-arena-tcp -u maze-arena-udp -n 30 --no-pager; exit 1; }
    ss -ltnup | grep ":$PORT " || true
    "$DIR/.venv/bin/python" "$DIR/scripts/netcheck.py" --host 127.0.0.1 --port "$PORT" --count 3
fi

HOST=${PUBLIC_IP:-PUBLIC_IP}
cat <<EOF

=== Done. The servers start by themselves after a crash or a reboot.

STILL TO DO BY HAND: open $PORT/tcp AND $PORT/udp in the CLOUD firewall
(Oracle: VCN -> Security List -> Ingress rules; see docs/cross_network.md A4).

From each player laptop:
    python scripts/netcheck.py --host $HOST --port $PORT
    python -m client_ui.ui --proto tcp --host $HOST --port $PORT --name alice --room demo
    python -m client_ui.ui --proto udp --host $HOST --port $PORT --name alice --room demo

On the VM:
    journalctl -u maze-arena-tcp -u maze-arena-udp -f       # live log of both servers
    sudo systemctl restart maze-arena-tcp maze-arena-udp    # after new code (or re-run this script)
EOF
