# Playing across different networks

Goal: the server runs somewhere reachable from the internet, and the 3 clients
join from **different networks** (home Wi-Fi, phone hotspot, campus) with
`--host <public IP>`.

Two ways:

- **A. Cloud VM (Oracle Cloud Free Tier, Ubuntu)**: a real internet path. Recommended for the demo.
- **B. Tailscale**: zero firewall work, but it's a VPN overlay (see the note you must say in the demo).

Facts that make this simple:

- The **servers use only the Python standard library**: no `pip install` on the VM.
- The TCP and UDP servers can run **at the same time on the same port number**
  (TCP 5050 and UDP 5050 are different ports), so both versions are always available.
- Default port in this doc: **5050** for both TCP and UDP. (Avoid 5000 if a Mac is the
  server: AirPlay Receiver uses it.)

> Do this **several days before the demo (Fri 13 Nov 2026)**. Free-tier capacity
> and campus firewalls are the two things that go wrong, and both take time to work around.

---

## A. Server on an Oracle Cloud Free Tier VM

### A1. Create the VM

1. Sign up at <https://www.oracle.com/cloud/free/> (needs a card for identity
   verification; Always Free resources are not charged).
2. Console → **Compute → Instances → Create instance**.
3. **Image**: *Canonical Ubuntu 24.04* (ships Python 3.12).
4. **Shape** (both are "Always Free eligible"):
   - `VM.Standard.E2.1.Micro` (AMD, 1 GB RAM): plenty for this server, or
   - `VM.Standard.A1.Flex` (Ampere ARM). If you get *"Out of host capacity"*, pick
     another availability domain or fall back to E2.1.Micro.
5. **Networking**: keep "Create new virtual cloud network" + "public subnet" and make
   sure **Assign a public IPv4 address** is checked.
6. **SSH keys**: upload your public key (`~/.ssh/id_ed25519.pub`; create one with
   `ssh-keygen -t ed25519` if you have none) or download the generated private key.
7. Create, wait for *Running*, and copy the **Public IP address**. Below it's `PUBLIC_IP`.

```bash
ssh ubuntu@PUBLIC_IP          # default user on Oracle Ubuntu images is "ubuntu"
```

### A2. Install Python and get the code onto the VM

```bash
sudo apt update && sudo apt install -y python3 git netcat-openbsd tcpdump
python3 --version             # 3.10+ is fine (24.04 has 3.12)
```

Get the project there, one of:

```bash
# a) from GitHub (push it first from the laptop: git remote add origin ...; git push -u origin main)
git clone https://github.com/<you>/maze-arena.git ~/maze-arena

# b) or copy straight from the laptop (run this ON THE LAPTOP, from the folder above maze-arena)
rsync -av --exclude .venv --exclude logs --exclude metrics/raw maze-arena ubuntu@PUBLIC_IP:~/
```

Quick local check on the VM (no dependencies needed):

```bash
cd ~/maze-arena
python3 -m tcp.server --port 5050      # Ctrl-C to stop; should log "listening on 0.0.0.0:5050 (TCP)"
```

(Only if you want to run the tests on the VM: `sudo apt install -y python3-venv`,
`python3 -m venv .venv && .venv/bin/pip install pytest`. pygame/matplotlib are not needed on the server.)

### A3. Open the ports: TWO firewalls, both must allow it

A packet from a player crosses **(1) Oracle's cloud firewall** and then **(2) the VM's
own firewall**. Forgetting either one gives the same symptom (timeouts), so do both.

**(1) Cloud: the subnet's Security List** (or a Network Security Group if you use one)

Console → **Networking → Virtual cloud networks →** your VCN → **Subnets →** the public
subnet → **Security Lists → Default Security List → Add Ingress Rules**. Add two rules:

| Source CIDR | IP Protocol | Source port | Destination port | Description |
|---|---|---|---|---|
| `0.0.0.0/0` | TCP | (empty = all) | `5050` | Maze Arena TCP |
| `0.0.0.0/0` | UDP | (empty = all) | `5050` | Maze Arena UDP |

Optional, for `ping` tests: ICMP, type `8` (echo request). Oracle does **not** allow
ping by default, so a failing ping means nothing until you add this.

Tighter alternative: instead of `0.0.0.0/0`, put each player's public IP
(`curl -4 ifconfig.me` on each laptop) as `x.x.x.x/32`.

**(2) On the VM: iptables (Oracle's Ubuntu images)**

Oracle's Ubuntu images come with their own iptables rules that **REJECT everything
except SSH**. New rules must go **before** that REJECT line:

```bash
sudo iptables -L INPUT --line-numbers                  # look: there's a REJECT near the end
N=$(sudo iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')
sudo iptables -I INPUT "$N" -p tcp --dport 5050 -m state --state NEW -j ACCEPT
sudo iptables -I INPUT "$N" -p udp --dport 5050 -j ACCEPT
sudo netfilter-persistent save                         # survive reboots (/etc/iptables/rules.v4)
sudo iptables -L INPUT --line-numbers                  # the two ACCEPTs must be ABOVE the REJECT
```

Undo later: `sudo iptables -D INPUT -p tcp --dport 5050 -m state --state NEW -j ACCEPT`,
`sudo iptables -D INPUT -p udp --dport 5050 -j ACCEPT`, then `sudo netfilter-persistent save`.

**ufw instead?** On Oracle images, stick to the iptables commands above: they already manage
iptables, and enabling ufw on top replaces those rules (an easy way to lock yourself
out of SSH). On other providers or your own Ubuntu box, ufw is the normal tool:

```bash
sudo ufw allow OpenSSH          # FIRST, or enabling ufw cuts your SSH session
sudo ufw allow 5050/tcp
sudo ufw allow 5050/udp
sudo ufw enable && sudo ufw status
```

### A4. Run the server

**Option 1: nohup (quick)**

```bash
cd ~/maze-arena
nohup python3 -m tcp.server --port 5050 > tcp_server.log 2>&1 &
nohup python3 -m udp.server --port 5050 > udp_server.log 2>&1 &
tail -f tcp_server.log udp_server.log          # watch events (Ctrl-C stops tail, not the servers)
pkill -f "tcp.server"; pkill -f "udp.server"   # stop (SIGTERM: clean shutdown, prints stats)
```

nohup servers do not come back after a VM reboot.

**Option 2: systemd service (survives reboots and crashes; recommended for demo day)**

One template unit serves both versions (`%i` = `tcp` or `udp`):

```bash
sudo tee /etc/systemd/system/maze-arena@.service > /dev/null <<'EOF'
[Unit]
Description=Maze Arena %i server
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/maze-arena
ExecStart=/usr/bin/python3 -u -m %i.server --host 0.0.0.0 --port 5050
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now maze-arena@tcp maze-arena@udp
systemctl status maze-arena@tcp maze-arena@udp --no-pager
```

Daily use:

```bash
journalctl -u maze-arena@tcp -f                 # live log (all events are timestamped)
journalctl -u maze-arena@udp --since "10 min ago"
sudo systemctl restart maze-arena@udp           # e.g. after pulling new code
sudo systemctl stop maze-arena@tcp maze-arena@udp
ss -ltnup | grep 5050                           # expect tcp LISTEN and udp UNCONN on 0.0.0.0:5050
```

Short games for rehearsal: add `--game-seconds 30` to `ExecStart` (then `daemon-reload` + `restart`).

### A5. Connect the clients

On each player laptop (repo cloned, venv with `pip install -r requirements.txt`):

```bash
python -m client_ui.ui --proto tcp --host PUBLIC_IP --port 5050 --name alice --room demo
python -m client_ui.ui --proto udp --host PUBLIC_IP --port 5050 --name bob   --room demo
```

All players of one game must use the **same** `--proto` (the TCP and UDP servers are
separate, with separate lobbies). Headless test player: `python -m client_ui.bot --proto tcp --host PUBLIC_IP --port 5050 --name bot1 --room demo --players 3`.

Why UDP works through home routers: each client sends first (LOGIN, then a PING every
second), so its router creates a NAT mapping and lets the server's replies back in.
The 1 s PING also keeps that mapping from expiring. The server only ever replies to
the address a datagram came from, and never needs to reach a client first.

After the demo: stop the services and delete the two ingress rules (or terminate the VM).

---

## B. Alternative: Tailscale

1. Install Tailscale on **every** machine that plays or hosts:
   - macOS / Windows: installer from <https://tailscale.com/download>
   - Linux / the VM: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`
2. Log in with the **same account** on all of them (or share the server machine with
   teammates from the admin console).
3. On the server machine: `tailscale ip -4` gives an address like `100.101.102.103`.
4. Run the server as usual (`python -m tcp.server --port 5050`); clients use
   `--host 100.101.102.103` (or the MagicDNS name shown in `tailscale status`).

No cloud security list, no port forwarding. The server's **host** firewall still applies
(the macOS "allow incoming connections" prompt, Windows Defender).

### What Tailscale really is (we must say this in the demo)

Tailscale is a **VPN overlay network** built on WireGuard. Every one of our packets
(our TCP segments *and* our UDP datagrams) is encrypted and **encapsulated inside
WireGuard UDP packets** between `100.x.y.z` addresses. When two machines can't reach
each other directly through their NATs, the traffic is **relayed through Tailscale's
DERP servers over HTTPS, i.e. over TCP**. So with Tailscale we are not measuring "our
protocol over the internet". We're measuring our protocol inside a tunnel, possibly
inside a relayed TCP connection: extra headers, a smaller MTU (1280 bytes; our full
STATE is ~1.2 KB, which still fits), and loss/latency behaviour shaped by the tunnel.
`tailscale status` shows whether each peer is `direct` or uses a `relay`;
`tailscale ping <peer>` tells you which path is used.

Suggested sentence for the demo: *"This run goes through Tailscale, a WireGuard VPN
overlay. Our TCP and UDP traffic is tunnelled inside WireGuard UDP, and may be relayed,
so this shows the game working across networks but not a raw internet path. The cloud
VM run is the raw internet path."*

---

## Troubleshooting checklist

Work from the server outwards; each step isolates one layer.

1. **Is the server running and listening on 0.0.0.0?**
   On the VM: `ss -ltnup | grep 5050` → `tcp LISTEN 0.0.0.0:5050` and `udp UNCONN 0.0.0.0:5050`.
   If it shows `127.0.0.1:5050`, it was started with the wrong `--host`.
2. **Does it answer locally?** On the VM:
   ```bash
   echo '{"type":"PING","t":1}' | nc -w 2 127.0.0.1 5050      # TCP → {"type":"PONG","t":1}
   echo '{"type":"PING","t":1}' | nc -u -w 2 127.0.0.1 5050   # UDP → {"type":"PONG","t":1}
   ```
3. **Does it answer from a laptop?** Same two commands with `PUBLIC_IP` instead of
   `127.0.0.1`. A PONG over UDP is the **only** real UDP test:
   - `nc -zv PUBLIC_IP 5050` is a valid TCP test ("succeeded" = TCP handshake done).
   - `nc -zvu PUBLIC_IP 5050` proves **nothing**: UDP has no handshake, and it prints
     "succeeded" even for a closed port (we checked).
   - Windows PowerShell (TCP only): `Test-NetConnection PUBLIC_IP -Port 5050`.
4. **Nothing comes back? Find which firewall eats it.** On the VM run
   `sudo tcpdump -ni any port 5050` and repeat step 3:
   - packets **don't show up** → cloud Security List (A3-1), the wrong IP, or the client's network blocks the port;
   - packets **show up but no reply** → VM iptables/ufw (A3-2) or the server isn't running.
5. **`ping PUBLIC_IP` fails?** Normal on Oracle unless you added the ICMP type 8 rule.
   Ping is a reachability hint only; it says nothing about TCP/UDP 5050.
6. **Right address?** Use the *public* IP from the console, never the VM's private
   `10.0.x.x` (that's what `ip addr` shows on the VM; Oracle NATs public → private).
7. **The player's network blocks it** (campus Wi-Fi/eduroam often blocks unusual ports or
   all UDP): try the same laptop on a phone hotspot. Workaround: also accept port 443
   and redirect it to 5050 on the VM (open 443 TCP+UDP in the Security List and in iptables too):
   ```bash
   sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 5050
   sudo iptables -t nat -A PREROUTING -p udp --dport 443 -j REDIRECT --to-port 5050
   sudo netfilter-persistent save
   ```
   Clients then use `--port 443`.
8. **Firewall on the demo laptops.**
   - *Clients* only make outgoing connections; replies are allowed back automatically, so
     normally nothing to change.
   - A laptop that **runs the server** (Tailscale or LAN demo): macOS shows *"Do you want
     the application Python to accept incoming network connections?"* → **Allow**. If you
     clicked Deny: System Settings → Network → Firewall → Options → set Python to
     "Allow incoming connections" (and keep "Block all incoming connections" and
     "stealth mode" off). Windows: allow Python on **Private** networks in the Defender
     prompt, or Windows Security → Firewall → Allow an app.
9. **Client starts but nothing happens.**
   - Is it the same `--proto` as the server you meant?
   - "Disconnected: server silent for 5 s / 10 s" → path blocked (go back to step 3).
   - Run from the repo root with `python -m client_ui.ui`, not `python client_ui/ui.py`.
10. **"name already taken" right after a crash/reconnect.** The server frees the name when
    it notices the old client is gone: instantly on TCP when the process dies, else after
    the heartbeat timeout (TCP 5 s, UDP 4 s). Wait a few seconds or use another name.
11. **Check where the latency comes from.** The RTT in the UI's corner (`RTT xx ms`) is
    PING→PONG over the real path. Tens of ms are normal across networks; compare with
    `ping` (if enabled) to see what the network itself adds.
