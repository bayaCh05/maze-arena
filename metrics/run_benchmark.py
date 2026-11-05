"""Benchmark TCP vs UDP under packet loss; writes metrics/results.csv and charts.

    python metrics/run_benchmark.py                       # tcp+udp x 0/10/30 %, 120 s games (~9 min)
    python metrics/run_benchmark.py --protos udp --loss 0.1 --game-seconds 30
    sudo -v && python metrics/run_benchmark.py --loss-method os   # kernel loss, TCP included

Each run: server + 3 bots (alice, bob, carol) as separate processes, one full
game; carol is SIGKILLed --kill-after seconds into it (no goodbye).

Loss methods:
  app  UDP --drop on the server and every client (outgoing datagrams).
       TCP cannot be tested this way (TCP never loses data), so TCP rows with
       loss > 0 are written as "not measured".
  os   kernel-level loss on lo0 via metrics/netloss_mac.sh (dummynet), same
       for TCP and UDP. Needs sudo: run `sudo -v` first.

Measured (network-metrics skill), pooled over alice and bob:
  rtt            PING {t} -> PONG on the client (mean, p95)
  inter_update   time between accepted STATEs at the client (mean, std, p99, max)
  missing ticks  STATE ticks never received (UDP; always 0 on TCP)
  retransmissions  UDP reliable-message retransmissions (clients, server)
  detect         SIGKILL of carol -> server logs PLAYER_LEFT carol
Raw samples: metrics/raw/<proto>_<method>_loss<NN>_<node>.csv (git-ignored).

Through a real network, against a server that is ALREADY running (on the Mac):
    python metrics/run_benchmark.py --host 192.168.1.20 --port 5050 --network lan
    python metrics/run_benchmark.py --host 127.0.0.1 --port 15050 --network cloudflare --protos tcp
    python metrics/run_benchmark.py --host xxx.at.ply.gg --port 12345 --network playit --protos udp
3 bots here play one full game there (its length is the server's --game-seconds): RTT,
inter-update time and missing ticks, no loss injected, no kill (the server log is
not here). Rows go to results.csv with that "network" (local runs are "loopback");
chart metrics/charts/networks.png compares them.

Only RTT (PING before login, no game, no player name used), add --rtt-only:
    python metrics/run_benchmark.py --host 127.0.0.1 --port 15050 --network cloudflare --rtt-only
-> metrics/rtt_paths.csv (one row per network+proto, re-runs replace) and charts/rtt_paths.png.
"""

import argparse
import ast
import csv
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
METRICS = ROOT / "metrics"
RAW = METRICS / "raw"
RESULTS = METRICS / "results.csv"
RTT_PATHS = METRICS / "rtt_paths.csv"
NETWORK_ORDER = {"loopback": 0, "lan": 1, "cloudflare": 2, "playit": 3}
NETLOSS = METRICS / "netloss_mac.sh"
OS_PORT = 5061

FIELDS = [
    "network", "proto", "loss_pct", "loss_method", "status", "game_seconds",
    "rtt_samples", "rtt_mean_ms", "rtt_p95_ms",
    "inter_update_mean_ms", "inter_update_std_ms", "inter_update_p99_ms", "inter_update_max_ms",
    "freezes_over_250ms",
    "states_received", "states_missing", "states_missing_pct", "states_late",
    "client_retransmissions", "server_retransmissions", "reliable_gave_up",
    "detect_ms", "detect_how",
]


# ---------------------------------------------------------------- helpers

def pct(values, q):
    """q-th percentile (0-100), linear interpolation."""
    s = sorted(values)
    if not s:
        return None
    k = (len(s) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def free_port():
    while True:
        with socket.socket() as t:
            t.bind(("", 0))
            port = t.getsockname()[1]
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.bind(("", port))
            return port
        except OSError:
            continue


def start(args, log_path):
    f = open(log_path, "w")
    return subprocess.Popen([PY, "-u", "-m", *args], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT), f


def wait_text(path, needle, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in path.read_text(errors="replace"):
            return True
        time.sleep(0.1)
    return False


def log_time(line):
    """'2026-11-04 18:19:19.738 INFO ...' -> epoch seconds."""
    return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S.%f").timestamp()


def read_raw(path):
    rows = {}
    if path.exists():
        with open(path) as f:
            for r in csv.DictReader(f):
                rows.setdefault(r["metric"], []).append(float(r["value"]))
    return rows


def netloss(*args):
    cmd = ["sudo", "-n", "sh", str(NETLOSS), *map(str, args)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"netloss {' '.join(map(str, args))} failed: {res.stderr.strip() or res.stdout.strip()}\n"
                 "Run `sudo -v` first (the benchmark uses sudo -n).")
    print("   ", res.stdout.strip())


# ---------------------------------------------------------------- one run

def run_one(proto, loss, method, game_seconds, kill_after, port, host=None, network="loopback"):
    """One game. host=None: start our own server here (loopback), inject loss, kill carol.
    host given: the server already runs there; only the bots run here, nobody is killed."""
    remote = host is not None
    tag = f"{proto}_{method}_loss{round(loss * 100):02d}"
    if remote:
        tag = f"{network}_{proto}"
        print(f"\n== {tag}: 3 bots -> {host}:{port}, game length set by that server")
    else:
        print(f"\n== {tag}: {game_seconds:.0f} s game, kill carol after {kill_after:.0f} s")
    row = {"network": network, "proto": proto, "loss_pct": round(loss * 100),
           "loss_method": method if not remote else "none", "game_seconds": game_seconds}
    if proto == "tcp" and loss > 0 and method == "app":
        row["status"] = "not measured: TCP needs OS-level loss (--loss-method os)"
        print("   skipped:", row["status"])
        return row

    drop = ["--drop", str(loss)] if (proto == "udp" and method == "app" and loss > 0) else []
    server_log = RAW / f"{tag}_server.log"
    server, procs, files = None, {}, []
    if remote:
        names = [f"{n}{os.getpid() % 1000}" for n in ("alice", "bob", "carol")]   # don't clash with players
        room = f"bench{os.getpid() % 10000}"
    else:
        names, room = ["alice", "bob", "carol"], "bench"
        server, server_f = start([f"{proto}.server", "--port", str(port),
                                  "--game-seconds", str(game_seconds), *drop], server_log)
        files.append(server_f)
    try:
        if not remote and not wait_text(server_log, "listening on", 10):
            row["status"] = "server did not start"
            return row
        for name in names:
            p, f = start(["client_ui.bot", "--proto", proto, "--host", host or "127.0.0.1",
                          "--port", str(port), "--name", name,
                          "--room", room, "--players", "3", *drop,
                          "--metrics-csv", str(RAW / f"{tag}_{name}.csv")], RAW / f"{tag}_{name}.log")
            procs[name] = p
            files.append(f)
            time.sleep(0.2)
        if not all(wait_text(RAW / f"{tag}_{n}.log", "GAME_START", 30) for n in procs):
            row["status"] = "game did not start" + (f" (see {RAW.relative_to(ROOT)}/{tag}_*.log)" if remote else "")
            return row
        if remote:
            for p in procs.values():
                try:
                    p.wait(game_seconds + 30)
                except subprocess.TimeoutExpired:
                    pass
        else:
            time.sleep(kill_after)
            kill_ts = time.time()
            procs[names[2]].kill()                  # SIGKILL carol (Windows: TerminateProcess)
            for name in names[:2]:
                try:
                    procs[name].wait(game_seconds + 30)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.kill()
        if server:
            server.terminate()                      # SIGTERM: prints reliability stats on the way out
            try:
                server.wait(5)
            except subprocess.TimeoutExpired:
                server.kill()
        for f in files:
            f.close()

    if remote:
        return client_samples(row, tag, proto, names, procs, left=True)

    # --- detection time: kill -> server log line
    log = server_log.read_text(errors="replace").splitlines()
    left = next((l for l in log if "PLAYER_LEFT carol" in l), None)
    disc = next((l for l in log if "DISCONNECT carol" in l), "")
    if left:
        row["detect_ms"] = round((log_time(left) - kill_ts) * 1000)
        row["detect_how"] = ("FIN" if "FIN" in disc else "RST" if "RST" in disc
                             else "heartbeat timeout" if "heartbeat" in disc else disc[-60:])
    srv_stats = next((l for l in log if "reliability stats:" in l), None)
    if srv_stats:
        stats = ast.literal_eval(srv_stats.split("reliability stats: ", 1)[1])
        row["server_retransmissions"] = stats["retransmissions"]
        row["reliable_gave_up"] = stats["gave_up"]

    return client_samples(row, tag, proto, ["alice", "bob"], procs, left)


def client_samples(row, tag, proto, names, procs, left):
    """Pool the bots' raw samples into the row (carol is left out when she was killed)."""
    rtt, inter, received, missing, late, retx, codes = [], [], 0, 0, 0, 0, []
    for name in names:
        raw = read_raw(RAW / f"{tag}_{name}.csv")
        rtt += raw.get("rtt", [])
        inter += raw.get("inter_update", [])
        received += int(raw.get("total_states_received", [len(raw.get("inter_update", [])) + 1])[0])
        missing += int(sum(g for g in raw.get("tick_gap", []) if g > 0))
        late += int(raw.get("total_states_late", [0])[0])
        retx += int(raw.get("total_retransmissions", [0])[0])
        codes.append(procs[name].returncode)
    row.update(
        status="ok" if all(c == 0 for c in codes) and left else f"incomplete (bot exit codes {codes})",
        rtt_samples=len(rtt),
        rtt_mean_ms=round(statistics.mean(rtt), 3) if rtt else None,
        rtt_p95_ms=round(pct(rtt, 95), 3) if rtt else None,
        inter_update_mean_ms=round(statistics.mean(inter), 1) if inter else None,
        inter_update_std_ms=round(statistics.pstdev(inter), 1) if inter else None,
        inter_update_p99_ms=round(pct(inter, 99), 1) if inter else None,
        inter_update_max_ms=round(max(inter), 1) if inter else None,
        freezes_over_250ms=sum(1 for v in inter if v > 250),
        states_received=received,
        states_missing=missing,
        states_missing_pct=round(100 * missing / (received + missing), 1) if received else None,
        states_late=late,
        client_retransmissions=retx if proto == "udp" else None,
    )
    print(f"   {row['status']}: rtt {row['rtt_mean_ms']} ms, inter-update mean {row['inter_update_mean_ms']}"
          f" / max {row['inter_update_max_ms']} ms, missing {row['states_missing_pct']} %"
          + (f" detect {row.get('detect_ms')} ms ({row.get('detect_how')})" if row.get("detect_how") else ""))
    return row


# ---------------------------------------------------------------- RTT of one path

RTT_FIELDS = ["network", "proto", "host", "port", "sent", "samples", "lost_pct",
              "rtt_mean_ms", "rtt_p50_ms", "rtt_p95_ms", "rtt_min_ms", "rtt_max_ms", "measured_at"]


def measure_rtt(proto, host, port, count, interval, timeout=2.0):
    """PING {t} -> PONG against a running server; returns the RTTs in ms (lost pings left out)."""
    sys.path.insert(0, str(ROOT))
    from common.protocol import (PING, PONG, ProtocolError, TcpStreamBuffer, decode_udp, encode_tcp,
                                 encode_udp, make_msg)

    if proto == "tcp":
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        buf = TcpStreamBuffer()
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((host, port))
    rtts = []
    try:
        for i in range(count):
            t = time.perf_counter()
            msg = make_msg(PING, t=t)
            sock.sendall(encode_tcp(msg)) if proto == "tcp" else sock.send(encode_udp(msg))
            deadline = t + timeout
            got = False
            while not got and time.perf_counter() < deadline:
                sock.settimeout(max(0.01, deadline - time.perf_counter()))
                try:
                    data = sock.recv(65535)
                except (socket.timeout, TimeoutError):
                    break
                except (ConnectionRefusedError, ConnectionResetError):
                    if proto == "tcp":
                        raise
                    break                                  # UDP: ICMP unreachable, count as lost
                if proto == "tcp":
                    if not data:
                        raise ConnectionError("server closed the connection")
                    msgs = buf.feed(data)
                else:
                    try:
                        msgs = [decode_udp(data)[0]]
                    except ProtocolError:
                        msgs = []
                for m in msgs:
                    if m.get("type") == PONG and m.get("t") == t:
                        rtts.append((time.perf_counter() - t) * 1000)
                        got = True
            print(f"\r   {i + 1}/{count} pings, {len(rtts)} PONGs", end="", flush=True)
            time.sleep(max(0.0, interval - (time.perf_counter() - t)))
    finally:
        sock.close()
        print()
    return rtts


def save_rtt_path(row):
    old = []
    if RTT_PATHS.exists():
        with open(RTT_PATHS) as f:
            old = list(csv.DictReader(f))
    rows = [r for r in old if (r["network"], r["proto"]) != (row["network"], row["proto"])] + [row]
    with open(RTT_PATHS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RTT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {RTT_PATHS.relative_to(ROOT)} ({len(rows)} rows)")


def run_rtt_path(args):
    for proto in args.protos:
        print(f"== RTT {args.network} ({proto}) -> {args.host}:{args.port}, {args.count} pings every {args.interval} s")
        try:
            rtt = measure_rtt(proto, args.host, args.port, args.count, args.interval)
        except OSError as exc:
            sys.exit(f"cannot reach {args.host}:{args.port} over {proto}: {exc}\n"
                     "Is the server (and, for a tunnel, `cloudflared access tcp`) running?")
        if not rtt:
            sys.exit(f"no PONG at all over {proto}: wrong port, or this path does not carry {proto.upper()}.")
        row = {
            "network": args.network, "proto": proto, "host": args.host, "port": args.port,
            "sent": args.count, "samples": len(rtt),
            "lost_pct": round(100 * (args.count - len(rtt)) / args.count, 1),
            "rtt_mean_ms": round(statistics.mean(rtt), 3), "rtt_p50_ms": round(pct(rtt, 50), 3),
            "rtt_p95_ms": round(pct(rtt, 95), 3), "rtt_min_ms": round(min(rtt), 3),
            "rtt_max_ms": round(max(rtt), 3), "measured_at": datetime.now().isoformat(timespec="seconds"),
        }
        print(f"   mean {row['rtt_mean_ms']} ms, p50 {row['rtt_p50_ms']}, p95 {row['rtt_p95_ms']},"
              f" min {row['rtt_min_ms']}, max {row['rtt_max_ms']}, lost {row['lost_pct']} %")
        save_rtt_path(row)


# ---------------------------------------------------------------- results file

def save(rows):
    """Merge into results.csv: re-runs replace the same (proto, loss, method) rows."""
    old = []
    if RESULTS.exists():
        with open(RESULTS) as f:
            old = list(csv.DictReader(f))
    for r in old:
        r["network"] = r.get("network") or "loopback"   # rows from before the network column
    key = lambda r: (r["network"], r["proto"], str(r["loss_pct"]), r["loss_method"])
    merged = {key(r): r for r in old}
    merged.update({key(r): r for r in rows})
    order = sorted(merged.values(), key=lambda r: (NETWORK_ORDER.get(r["network"], 9), r["network"],
                                                   r["loss_method"], r["proto"], int(r["loss_pct"])))
    with open(RESULTS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in order:
            w.writerow({k: ("" if r.get(k) is None else r.get(k, "")) for k in FIELDS})
    print(f"\nwrote {RESULTS.relative_to(ROOT)} ({len(order)} rows)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--protos", nargs="+", default=["tcp", "udp"], choices=["tcp", "udp"])
    parser.add_argument("--loss", nargs="+", type=float, default=[0.0, 0.1, 0.3])
    parser.add_argument("--loss-method", choices=["app", "os"], default="app")
    parser.add_argument("--game-seconds", type=float, default=120)
    parser.add_argument("--kill-after", type=float, default=20)
    parser.add_argument("--no-charts", action="store_true")
    remote = parser.add_argument_group("through a real network (server already running there)")
    remote.add_argument("--host", help="server IP or hostname as this machine reaches it "
                                       "(LAN IP, 127.0.0.1 for cloudflared, the playit.gg address)")
    remote.add_argument("--rtt-host", help=argparse.SUPPRESS)       # old name of --host --rtt-only
    remote.add_argument("--port", type=int, default=5050, help="server port, cloudflared's local port, or the playit port")
    remote.add_argument("--network", "--label", default=None,
                        help="name of the path in the CSV/charts: lan, cloudflare, playit, ...")
    remote.add_argument("--rtt-only", action="store_true", help="only PING RTT, no game (-> rtt_paths.csv)")
    remote.add_argument("--count", type=int, default=100, help="--rtt-only: PINGs per protocol")
    remote.add_argument("--interval", type=float, default=0.2, help="--rtt-only: seconds between PINGs")
    args = parser.parse_args()

    if args.rtt_host:
        args.host, args.rtt_only = args.rtt_host, True
    if args.host:
        if not args.network:
            parser.error("--host needs --network NAME (lan, cloudflare, playit, ...)")
        if args.rtt_only:
            if "--protos" not in sys.argv:
                args.protos = ["tcp"]
            run_rtt_path(args)
            if not args.no_charts:
                from make_charts import chart_rtt_paths
                chart_rtt_paths()
            return
        RAW.mkdir(parents=True, exist_ok=True)
        rows = []
        try:
            for proto in args.protos:
                rows.append(run_one(proto, 0.0, "none", args.game_seconds, 0, args.port,
                                    host=args.host, network=args.network))
        finally:
            if rows:
                save(rows)
        if not args.no_charts:
            from make_charts import main as make_charts
            make_charts()
        return

    RAW.mkdir(parents=True, exist_ok=True)
    if args.loss_method == "os" and platform.system() != "Darwin":
        sys.exit("--loss-method os uses dummynet (macOS). On Linux: sudo tc qdisc add dev lo root netem loss 10%")

    rows = []
    loss_on = False
    try:
        for loss in args.loss:
            if args.loss_method == "os":
                # "on" once (takes one pf token), then only change the rate.
                netloss("set", loss) if loss_on else netloss("on", OS_PORT, loss)
                loss_on = True
            for proto in args.protos:
                port = OS_PORT if args.loss_method == "os" else free_port()
                rows.append(run_one(proto, loss, args.loss_method, args.game_seconds, args.kill_after, port))  # loopback
    finally:
        if args.loss_method == "os":
            netloss("off")
        if rows:
            save(rows)
    if not args.no_charts:
        from make_charts import main as make_charts
        make_charts()


if __name__ == "__main__":
    sys.path.insert(0, str(METRICS))
    main()
