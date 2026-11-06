#!/usr/bin/env bash
# Double-click in Finder to host a game: asks your name and TCP/UDP, then runs scripts/host.sh.
cd "$(dirname "$0")"
read -r -p "Your name (1-12 characters): " NAME
read -r -p "Version, tcp or udp [tcp]: " PROTO
if [ "${PROTO:-tcp}" = udp ]; then
    bash scripts/host.sh --name "$NAME" --udp
else
    bash scripts/host.sh --name "$NAME"
fi
read -r -p "Press Enter to close this window."
