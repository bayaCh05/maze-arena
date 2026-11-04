#!/bin/sh
# OS-level packet loss on macOS (dummynet), loopback or a real interface, ONE port, TCP and UDP.
# This is the only honest way to make TCP lose segments: the kernel drops them,
# TCP notices and retransmits (so the game sees delays, never missing data).
#
#   sudo sh metrics/netloss_mac.sh on 5061 0.1 [delay_ms] [iface]   # 10 % loss on port 5061
#        iface defaults to lo0 (local tests); use en0 on a Mac SERVER in the 4-machine demo
#   sudo sh metrics/netloss_mac.sh set 0.3 [delay_ms]       # change the loss rate
#   sudo sh metrics/netloss_mac.sh status
#   sudo sh metrics/netloss_mac.sh off                      # undo everything
#
# How it works: dnctl creates dummynet pipe 1 with a packet-loss rate (plr);
# pf sends packets to/from the port through that pipe. Apple's own pf rules are
# reloaded unchanged from /etc/pf.conf; ours live in the anchor "mazearena".
# On lo0 each packet crosses the interface once on its way OUT, so two "out" rules
# hit it exactly once. On a real interface (en0) client->server packets come IN and
# server->client packets go OUT, so it's one "in" rule and one "out" rule.
set -e
ANCHOR=mazearena
TOKEN_FILE=/tmp/mazearena_pf_token

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

case "$1" in
on)
    PORT=$2; PLR=$3; DELAY=${4:-0}; IFACE=${5:-lo0}
    [ -n "$PORT" ] && [ -n "$PLR" ] || { echo "usage: on PORT LOSS [DELAY_MS] [IFACE]"; exit 1; }
    if [ "$IFACE" = lo0 ]; then TO_DIR=out; else TO_DIR=in; fi
    dnctl pipe 1 config plr "$PLR" delay "$DELAY"
    (cat /etc/pf.conf; echo "dummynet-anchor \"$ANCHOR\""; echo "anchor \"$ANCHOR\"") | pfctl -q -f -
    printf 'dummynet %s quick on %s proto { tcp udp } from any to any port %s pipe 1\ndummynet out quick on %s proto { tcp udp } from any port %s to any pipe 1\n' \
        "$TO_DIR" "$IFACE" "$PORT" "$IFACE" "$PORT" | pfctl -q -a "$ANCHOR" -f -
    # -E enables pf and returns a reference token; releasing it later restores
    # pf's previous on/off state instead of blindly disabling it.
    pfctl -E 2>&1 | sed -n 's/^Token : //p' > "$TOKEN_FILE"
    echo "loss $PLR (delay ${DELAY} ms) on $IFACE port $PORT"
    ;;
set)
    dnctl pipe 1 config plr "$2" delay "${3:-0}"
    echo "loss now $2 (delay ${3:-0} ms)"
    ;;
status)
    dnctl list
    pfctl -a "$ANCHOR" -s dummynet 2>/dev/null || true
    ;;
off)
    pfctl -q -a "$ANCHOR" -F all 2>/dev/null || true
    pfctl -q -f /etc/pf.conf
    dnctl -q flush
    if [ -s "$TOKEN_FILE" ]; then pfctl -X "$(cat "$TOKEN_FILE")" 2>/dev/null || true; fi
    rm -f "$TOKEN_FILE"
    echo "loss removed, Apple pf rules restored"
    ;;
*)
    echo "usage: $0 on PORT LOSS [DELAY_MS] [IFACE] | set LOSS [DELAY_MS] | status | off"; exit 1 ;;
esac
