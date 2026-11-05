"""scripts/netcheck.py against real servers, and the server startup banner."""

import socket
import subprocess
import sys
import threading
from pathlib import Path

from netutil.addresses import local_ipv4_addresses, startup_banner
from tcp.server import Server as TcpServer
from udp.server import Server as UdpServer

NETCHECK = Path(__file__).resolve().parent.parent / "scripts" / "netcheck.py"


def netcheck(*args):
    out = subprocess.run([sys.executable, str(NETCHECK), *args], capture_output=True, text=True, timeout=30)
    return out.returncode, out.stdout


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_netcheck_ok_against_both_servers():
    tcp = TcpServer("127.0.0.1", 0)
    port = tcp.start()
    udp = UdpServer("127.0.0.1", port)              # same number: TCP and UDP ports are separate
    udp.start()
    for srv in (tcp, udp):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, out = netcheck("--host", "127.0.0.1", "--port", str(port), "--count", "2")
    finally:
        tcp.stop()
        udp.stop()
    assert code == 0, out
    assert "TCP: OK" in out and "UDP: OK" in out
    assert "RTT" in out


def test_netcheck_reports_refused_when_no_server():
    code, out = netcheck("--host", "127.0.0.1", "--port", str(free_port()), "--count", "1")
    assert code == 1
    assert out.count("REFUSED") == 2                 # TCP RST and UDP ICMP port unreachable


def test_banner_has_the_command_to_copy():
    lines = startup_banner("udp", "0.0.0.0", 5050, public_ip="203.0.113.7")
    assert "  python -m client_ui.ui --proto udp --host 203.0.113.7 --port 5050 --name alice --room demo" in lines
    assert "  python scripts/netcheck.py --host 203.0.113.7 --port 5050" in lines


def test_banner_for_a_specific_bind_address():
    lines = startup_banner("tcp", "10.1.2.3", 6000)
    assert any("--proto tcp --host 10.1.2.3 --port 6000" in line for line in lines)
    assert any("public IP" in line for line in lines)        # private only: hint for other networks


def test_local_addresses_never_include_loopback():
    for ip, _desc in local_ipv4_addresses():
        assert not ip.startswith("127.")


def test_netcheck_resolves_a_hostname_once():
    udp = UdpServer("127.0.0.1", 0)
    port = udp.start()
    threading.Thread(target=udp.serve_forever, daemon=True).start()
    try:
        code, out = netcheck("--host", "localhost", "--port", str(port), "--proto", "udp", "--count", "2")
    finally:
        udp.stop()
    assert code == 0, out
    assert "localhost resolved to 127.0.0.1" in out


def test_netcheck_unknown_hostname():
    code, out = netcheck("--host", "no-such-host.invalid", "--port", "5050")
    assert code == 1 and "cannot resolve" in out
