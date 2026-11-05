"""Which IPv4 addresses can players use to reach this machine? (server startup banner)

Best effort, standard library only, macOS / Linux / Windows. Nothing here sends
a packet: the "default route" address comes from connect() on a UDP socket,
which only asks the OS which interface it would use.
"""

import ipaddress
import platform
import re
import socket
import subprocess

TAILSCALE = ipaddress.IPv4Network("100.64.0.0/10")     # carrier-grade NAT range, used by Tailscale


def _primary_ip():
    """Address of the interface that holds the default route, or None (offline)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _run(cmd):
    """Output of an OS command, or "" if it fails or takes more than 2 s."""
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=2, check=False)
        return out.stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _from_os():
    """[(ip, interface name)] parsed from the OS's own tool."""
    system = platform.system()
    found = []
    if system == "Windows":
        adapter = ""
        for line in _run(["ipconfig"]).splitlines():
            if line and not line[0].isspace() and line.rstrip().endswith(":"):
                adapter = line.rstrip(" :")
                adapter = adapter.split(" adapter ")[-1]       # "Wireless LAN adapter Wi-Fi" -> "Wi-Fi"
            m = re.search(r"IPv4[^:]*:\s*([\d.]+)", line)      # English and e.g. French "Adresse IPv4"
            if m:
                found.append((m.group(1), adapter))
    elif system == "Linux":
        for line in _run(["ip", "-4", "-o", "addr", "show"]).splitlines():
            m = re.match(r"\d+:\s+(\S+)\s+inet\s+([\d.]+)/", line)
            if m:
                found.append((m.group(2), m.group(1)))
        if not found:
            found = [(ip, "") for ip in _run(["hostname", "-I"]).split()]
    else:                                                    # macOS / BSD
        iface = ""
        for line in _run(["ifconfig"]).splitlines():
            m = re.match(r"(\S+?):\s+flags=", line)
            if m:
                iface = m.group(1)
            m = re.match(r"\s+inet\s+([\d.]+)", line)
            if m:
                found.append((m.group(1), iface))
    return found


def _from_hostname():
    """IPv4 addresses the OS resolver gives for our own host name (fallback)."""
    try:
        return [ai[4][0] for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        return []


def _kind(addr):
    """Human label for an address: Tailscale, LAN / private, or public."""
    if addr in TAILSCALE:
        return "Tailscale"
    return "LAN / private" if addr.is_private else "public"


def local_ipv4_addresses():
    """[(ip, description)] usable by other machines, default-route address first. Never raises."""
    primary = _primary_ip()
    names = {}
    for ip, iface in _from_os() + [(ip, "") for ip in _from_hostname()] + [(primary, "")]:
        if ip and not names.get(ip):
            names[ip] = iface
    result = []
    for ip, iface in names.items():
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            continue
        parts = [p for p in (iface, _kind(addr), "default route" if ip == primary else "") if p]
        result.append((ip, ", ".join(parts)))
    result.sort(key=lambda r: (r[0] != primary, r[0]))
    return result


def free_port():
    """A port number that is free for BOTH TCP and UDP right now (tests, benchmark)."""
    while True:
        with socket.socket() as t:
            t.bind(("", 0))
            port = t.getsockname()[1]
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.bind(("", port))
            return port
        except OSError:
            continue                    # the UDP twin is taken: try another number


def resolve_ipv4(host, port, proto="udp"):
    """Hostname (e.g. a playit.gg address) or IPv4 literal -> one IPv4 address string.

    Clients call this ONCE at startup and then only use the IP, so a DNS change or a
    slow resolver can't affect a running game. Raises socket.gaierror if it doesn't resolve.
    """
    socktype = socket.SOCK_DGRAM if proto == "udp" else socket.SOCK_STREAM
    return socket.getaddrinfo(host, port, socket.AF_INET, socktype)[0][4][0]


def startup_banner(proto, host, port, public_ip=None):
    """Lines for the server log: where players connect, and the exact commands to copy."""
    if host in ("0.0.0.0", ""):
        addrs = local_ipv4_addresses()
    else:
        addrs = [(host, "the only address this server is bound to")]
    if public_ip:
        addrs.insert(0, (public_ip, "public IP (--public-ip), for players on other networks"))
    best = addrs[0][0] if addrs else "SERVER_IP"
    width = max([len(ip) for ip, _ in addrs] + [15])

    lines = [f"Maze Arena {proto.upper()} server, port {port} ({proto.upper()}), bound to {host or '0.0.0.0'}",
             "Players connect to ONE of these addresses (the one on their network):"]
    lines += [f"  {ip:<{width}}  {desc}" for ip, desc in addrs] or ["  (no network address found: offline?)"]
    lines += ["Client command to copy (change the name):",
              f"  python -m client_ui.ui --proto {proto} --host {best} --port {port} --name alice --room demo",
              "Check the path first, from a player laptop:",
              f"  python scripts/netcheck.py --host {best} --port {port}"]
    if not public_ip and all(ipaddress.IPv4Address(ip).is_private for ip, _ in addrs):
        lines.append("Players on OTHER networks need this machine's public IP instead (cloud console, "
                     "or `curl -4 ifconfig.me` here) and an open port in every firewall on the way.")
    return lines
