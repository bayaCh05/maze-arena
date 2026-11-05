"""The only place that picks a concrete transport; everything else uses the Transport interface."""


def make_transport(proto, host, port, drop=0.0):
    """Connected TcpTransport or UdpTransport for --proto; the UI never sees the difference."""
    if proto == "tcp":
        if drop:
            raise ValueError("--drop only applies to UDP (TCP never loses data); "
                             "use OS-level loss (netem/dnctl) to stress TCP")
        from tcp.client import TcpTransport
        return TcpTransport(host, port).connect()
    if proto == "udp":
        from udp.client import UdpTransport
        return UdpTransport(host, port, drop=drop).connect()
    raise ValueError(f"unknown protocol {proto!r}")
