"""Can this laptop reach the Maze Arena server? Run it on a player laptop before the game.

    python scripts/netcheck.py --host 192.168.1.23 --port 5050
    python scripts/netcheck.py --host 203.0.113.7 --port 5050 --proto udp

Tests the real path to the real server, no game: a TCP connect plus PING/PONG
over that connection, and a UDP PING/PONG exchange (both servers answer PING
before any login). Prints the RTT, or a diagnosis of what is most likely wrong.
Standard library only (copy it anywhere); macOS, Linux and Windows.
Exit code 0 = everything tested works, 1 = something failed.
"""

import argparse
import errno
import json
import socket
import statistics
import sys
import time

NO_ROUTE = {errno.EHOSTUNREACH, errno.ENETUNREACH, 10065, 10051}    # 100xx: Windows WSA codes

TIMEOUT_HELP = [
    "Nothing came back at all. Most likely, in this order:",
    "  1. Wrong IP: use the address printed by the server at startup (it changes when",
    "     the server laptop joins another Wi-Fi/hotspot). Cloud VM: the PUBLIC IP, never 10.x.",
    "  2. A firewall on the server drops it: macOS 'accept incoming connections' -> Allow;",
    "     Windows Defender: allow Python on Private networks; cloud VM: the cloud security",
    "     list AND the VM's own iptables/ufw must both allow the port.",
    "  3. Wi-Fi client isolation (campus/guest Wi-Fi blocks laptop-to-laptop traffic):",
    "     put all laptops on a phone hotspot and run this again.",
]


def hint(lines):
    """Print indented advice lines under a FAIL."""
    for line in lines:
        print("      " + line)


def ping_msg(seq):
    """A PING whose t is a sequence number, so each PONG can be matched to its PING."""
    return {"type": "PING", "t": seq}


def check_tcp(host, port, timeout, count):
    """Connect + PING/PONG over TCP; prints a diagnosis (refused / timeout / no route); True if OK."""
    print(f"[TCP] connecting to {host}:{port} ...")
    t0 = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except socket.gaierror as exc:
        print(f"  FAIL  cannot resolve '{host}' ({exc}). Check the spelling, or use the IP address.")
        return False
    except ConnectionRefusedError:
        print(f"  FAIL  REFUSED: the machine at {host} answered, but nothing listens on TCP port {port}.")
        hint(["The TCP server is not running there, it crashed, or the port is wrong",
              f"(start it with: python -m tcp.server --port {port}). A firewall that rejects",
              "instead of dropping looks the same."])
        return False
    except (socket.timeout, TimeoutError):
        print(f"  FAIL  TIMEOUT: no answer from {host}:{port} within {timeout:.0f} s.")
        hint(TIMEOUT_HELP)
        return False
    except OSError as exc:
        if exc.errno in NO_ROUTE or getattr(exc, "winerror", None) in NO_ROUTE:
            print(f"  FAIL  NO ROUTE to {host} ('no route to host' / 'host unreachable').")
            hint(["Either a firewall on the server REJECTS the port: Oracle Ubuntu VMs do this until",
                  "the iptables rule is added (deploy/setup_vm.sh does it), or this laptop has no",
                  "path to that network: not on the same Wi-Fi/hotspot, or a VPN/Tailscale is off."])
        else:
            print(f"  FAIL  {exc}")
        return False
    connect_ms = (time.perf_counter() - t0) * 1000
    local = sock.getsockname()[0]
    print(f"  ok    connected in {connect_ms:.1f} ms (this laptop is {local} on that path)")

    rtts, buf = [], b""
    try:
        sock.settimeout(timeout)
        for seq in range(1, count + 1):
            sent = time.perf_counter()
            sock.sendall((json.dumps(ping_msg(seq)) + "\n").encode())
            while True:
                while b"\n" not in buf:
                    data = sock.recv(4096)
                    if not data:
                        raise ConnectionError("server closed the connection")
                    buf += data
                line, buf = buf.split(b"\n", 1)
                msg = json.loads(line)
                if msg.get("type") == "PONG" and msg.get("t") == seq:
                    rtts.append((time.perf_counter() - sent) * 1000)
                    break
            time.sleep(0.2)
    except (socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as exc:
        print(f"  FAIL  connected, but no PONG ({exc.__class__.__name__}: {exc}).")
        hint([f"Something else is listening on port {port} (not a Maze Arena server?), or a",
              "proxy/firewall on the path accepts connections but blocks the data."])
        return False
    finally:
        sock.close()
    print(f"  ok    PING/PONG x{len(rtts)}: RTT min {min(rtts):.1f} / "
          f"median {statistics.median(rtts):.1f} / max {max(rtts):.1f} ms")
    return True


def check_udp(host, port, timeout, count):
    """PING/PONG datagrams; prints a diagnosis; True if at least one PONG came back."""
    print(f"[UDP] PING x{count} to {host}:{port} ...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((host, port))               # only fixes the peer: UDP sends nothing here
    except socket.gaierror as exc:
        print(f"  FAIL  cannot resolve '{host}' ({exc}).")
        return False
    except OSError as exc:
        print(f"  FAIL  {exc}")
        return False
    sock.settimeout(min(timeout, 1.0))
    rtts, refused = [], False
    for seq in range(1, count + 1):
        sent = time.perf_counter()
        try:
            sock.send(json.dumps(ping_msg(seq)).encode())
            deadline = sent + min(timeout, 1.0)
            while time.perf_counter() < deadline:
                msg = json.loads(sock.recv(65535))
                if msg.get("type") == "PONG" and msg.get("t") == seq:
                    rtts.append((time.perf_counter() - sent) * 1000)
                    break
        except (ConnectionRefusedError, ConnectionResetError):
            refused = True                       # ICMP port unreachable (Windows: WinError 10054)
        except (socket.timeout, TimeoutError, ValueError):
            pass
        except OSError as exc:
            if exc.errno in NO_ROUTE or getattr(exc, "winerror", None) in NO_ROUTE:
                print(f"  FAIL  NO ROUTE to {host}: a server firewall rejecting UDP (Oracle iptables), or no path (other network, VPN off).")
                sock.close()
                return False
            print(f"  FAIL  {exc}")
            sock.close()
            return False
        time.sleep(0.2)
    local = sock.getsockname()[0]
    sock.close()
    if rtts:
        lost = count - len(rtts)
        print(f"  ok    PONG {len(rtts)}/{count} (this laptop is {local}): RTT min {min(rtts):.1f} / "
              f"median {statistics.median(rtts):.1f} / max {max(rtts):.1f} ms"
              + (f", {100 * lost / count:.0f} % lost" if lost else ""))
        if lost:
            hint(["Some loss is normal on Wi-Fi; the game copes (lobby messages are re-sent)."])
        return True
    if refused:
        print(f"  FAIL  REFUSED: {host} answered 'port unreachable' for UDP {port}.")
        hint(["The machine is reachable but no UDP server listens there: start it with",
              f"python -m udp.server --port {port}, or fix the port."])
        return False
    print(f"  FAIL  no PONG at all for {count} PINGs.")
    hint(["UDP has no handshake, so 'no server' and 'dropped on the way' look the same.",
          "If TCP above works, the path is fine and it is almost always: the UDP server is",
          "not running, or the UDP rule is missing (cloud security list AND VM iptables/ufw",
          "need UDP, not only TCP), or this network blocks UDP (try a phone hotspot)."]
         + TIMEOUT_HELP[1:])
    return False


def main():
    """Resolve --host once, run the checks, exit 0 only if every requested protocol works."""
    parser = argparse.ArgumentParser(description="Check the network path to a Maze Arena server")
    parser.add_argument("--host", required=True,
                        help="server IP or hostname (e.g. the playit.gg address), resolved once")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--proto", choices=["both", "tcp", "udp"], default="both")
    parser.add_argument("--timeout", type=float, default=3.0, help="seconds to wait for the TCP connect")
    parser.add_argument("--count", type=int, default=5, help="PINGs per protocol")
    args = parser.parse_args()

    # Resolve ONCE (IPv4), like the game client: both checks then use the same address.
    try:
        ip = socket.getaddrinfo(args.host, args.port, socket.AF_INET)[0][4][0]
    except socket.gaierror as exc:
        print(f"FAIL  cannot resolve '{args.host}' ({exc}). Check the spelling, or use the IP address.")
        sys.exit(1)
    if ip != args.host:
        print(f"{args.host} resolved to {ip}\n")

    results = {}
    if args.proto in ("both", "tcp"):
        results["TCP"] = check_tcp(ip, args.port, args.timeout, args.count)
    if args.proto in ("both", "udp"):
        results["UDP"] = check_udp(ip, args.port, args.timeout, args.count)
    print()
    for proto, ok in results.items():
        print(f"{proto}: {'OK, ready to play' if ok else 'NOT reachable (see above)'}")
    if results.get("TCP") and results.get("UDP") is False:
        print("TCP works but UDP does not: the IP and the path are right; look at the UDP server/rule.")
    if results.get("UDP") and results.get("TCP") is False:
        print("UDP works but TCP does not: the IP is right; is the TCP server running, is TCP allowed?")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
