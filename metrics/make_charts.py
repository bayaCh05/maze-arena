"""Charts from metrics/results.csv (+ raw samples) -> metrics/charts/*.png

    python metrics/make_charts.py            # loss_method "app" (and "os" if present)

Palette: dataviz reference categorical slots 1-2 (validated light mode):
TCP = blue #2a78d6, UDP = orange #eb6834. One y-axis per chart, legend for
2 series plus direct value labels, recessive grid, text in ink colors.
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

METRICS = Path(__file__).resolve().parent
RAW = METRICS / "raw"
OUT = METRICS / "charts"

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
COLOR = {"tcp": "#2a78d6", "udp": "#eb6834"}
LABEL = {"tcp": "TCP", "udp": "UDP"}
WIDTH = 0.36

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "legend.frameon": False,
})


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


NETWORK_ORDER = ["loopback", "lan", "cloudflare", "playit"]


def network(row):
    return row.get("network") or "loopback"     # rows written before the network column


def load(method):
    """Loss experiments: loopback rows only (other networks go to chart_networks)."""
    with open(METRICS / "results.csv") as f:
        rows = [r for r in csv.DictReader(f) if r["loss_method"] == method and network(r) == "loopback"]
    losses = sorted({int(r["loss_pct"]) for r in rows})
    by = {(r["proto"], int(r["loss_pct"])): r for r in rows}
    return losses, by


def measured(row):
    return row is not None and row["status"] == "ok"


def finish(fig, ax, title, subtitle, name):
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=22)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print("wrote", (OUT / name).relative_to(METRICS.parent))


def loss_axis(ax, losses):
    ax.set_xticks(range(len(losses)), [f"{l} % loss" for l in losses])
    ax.tick_params(axis="x", length=0)


def not_measured(ax, x, y, proto):
    ax.text(x, y, f"{LABEL[proto]}\nnot measured", ha="center", va="bottom", fontsize=8, color=INK2)


def bars(ax, x, value, proto, label_text):
    ax.bar(x, value, WIDTH, color=COLOR[proto], edgecolor=SURFACE, linewidth=2, label=LABEL[proto])
    ax.annotate(label_text, (x, value), xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=8, color=INK)


def legend(ax, protos):
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=COLOR[p], label=LABEL[p]) for p in protos],
              loc="upper left", ncols=2, fontsize=9)


# ---------------------------------------------------------------- charts

def chart_rtt(losses, by, suffix):
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    top = max([num(r["rtt_p95_ms"]) or 0 for r in by.values() if measured(r)] or [1])
    for i, loss in enumerate(losses):
        for j, proto in enumerate(("tcp", "udp")):
            x = i + (j - 0.5) * WIDTH
            r = by.get((proto, loss))
            if not measured(r):
                not_measured(ax, x, top * 0.05, proto)
                continue
            mean, p95 = num(r["rtt_mean_ms"]), num(r["rtt_p95_ms"])
            ax.bar(x, mean, WIDTH, color=COLOR[proto], edgecolor=SURFACE, linewidth=2)
            ax.plot([x, x], [mean, p95], color=INK2, linewidth=1)
            ax.plot([x - WIDTH / 5, x + WIDTH / 5], [p95, p95], color=INK2, linewidth=1.5)
            ax.annotate(f"{mean:.2f}\np95 {p95:.2f}", (x, p95), xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, color=INK)
    loss_axis(ax, losses)
    ax.set_ylabel("round-trip time (ms)")
    ax.set_ylim(0, top * 1.45)
    legend(ax, ("tcp", "udp"))
    finish(fig, ax, "Round-trip time by protocol",
           "bar = mean, tick = p95 · PING→PONG measured at alice and bob", f"rtt{suffix}.png")


def inter_update_samples(proto, method, loss):
    samples = []
    for name in ("alice", "bob"):
        path = RAW / f"{proto}_{method}_loss{loss:02d}_{name}.csv"
        if path.exists():
            with open(path) as f:
                samples += [float(r["value"]) for r in csv.DictReader(f) if r["metric"] == "inter_update"]
    return samples


def chart_inter_update(losses, by, method, suffix):
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    top = 0
    for i, loss in enumerate(losses):
        for j, proto in enumerate(("tcp", "udp")):
            x = i + (j - 0.5) * WIDTH
            r = by.get((proto, loss))
            s = inter_update_samples(proto, method, loss) if measured(r) else []
            if not s:
                not_measured(ax, x, 105, proto)
                continue
            bp = ax.boxplot([s], positions=[x], widths=WIDTH * 0.8, whis=(1, 99), showfliers=False,
                            patch_artist=True, manage_ticks=False)
            for box in bp["boxes"]:
                box.set(facecolor=COLOR[proto], alpha=0.35, edgecolor=COLOR[proto], linewidth=1.5)
            for part in ("whiskers", "caps"):
                for line in bp[part]:
                    line.set(color=COLOR[proto], linewidth=1.2)
            for line in bp["medians"]:
                line.set(color=INK, linewidth=1.5)
            mx = max(s)
            top = max(top, mx)
            ax.plot(x, mx, marker="D", markersize=6, color=COLOR[proto],
                    markeredgecolor=SURFACE, markeredgewidth=1.5)
            ax.annotate(f"max {mx:.0f}\nσ {num(r['inter_update_std_ms']):.0f}", (x, mx), xytext=(0, 6),
                        textcoords="offset points", ha="center", fontsize=8, color=INK)
    ax.axhline(100, color=INK2, linewidth=1, linestyle=(0, (4, 3)))
    loss_axis(ax, losses)
    ax.set_ylabel("time between STATE updates (ms)")
    ax.set_xlim(-0.55, len(losses) - 0.45)
    ax.set_ylim(0, max(top, 150) * 1.25)
    legend(ax, ("tcp", "udp"))
    finish(fig, ax, "Inter-update time between STATE messages",
           "box = 25–75 %, whiskers = p1–p99, line = median, ◆ = max · dashed = server tick (100 ms)",
           f"inter_update{suffix}.png")


def chart_udp(losses, by, suffix):
    rows = [(l, by.get(("udp", l))) for l in losses]
    rows = [(l, r) for l, r in rows if measured(r)]
    if not rows:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.5, 4.0))
    xs = range(len(rows))
    for x, (loss, r) in zip(xs, rows):
        miss = num(r["states_missing_pct"])
        a1.bar(x, miss, 0.55, color=COLOR["udp"], edgecolor=SURFACE, linewidth=2)
        a1.annotate(f"{miss:.1f} %\n({r['states_missing']} ticks)", (x, max(miss, loss)), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8)
        a1.plot([x - 0.3, x + 0.3], [loss, loss], color=INK2, linewidth=1, linestyle=(0, (3, 2)))
        retx_c, retx_s = int(num(r["client_retransmissions"]) or 0), int(num(r["server_retransmissions"]) or 0)
        a2.bar(x, retx_c + retx_s, 0.55, color=COLOR["udp"], edgecolor=SURFACE, linewidth=2)
        a2.annotate(f"{retx_c + retx_s}\n(server {retx_s}, clients {retx_c})", (x, retx_c + retx_s),
                    xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
    for ax in (a1, a2):
        ax.set_xticks(list(xs), [f"{l} % loss" for l, _ in rows])
        ax.tick_params(axis="x", length=0)
    a1.set_ylabel("STATE ticks never received (%)")
    a1.set_ylim(0, max(num(r["states_missing_pct"]) for _, r in rows) * 1.4 + 1)
    a1.text(0.02, 0.97, "dashed = configured loss rate", transform=a1.transAxes, fontsize=8,
            color=INK2, va="top")
    a2.set_ylabel("reliable-message retransmissions (per game)")
    tops = [int(num(r["client_retransmissions"]) or 0) + int(num(r["server_retransmissions"]) or 0) for _, r in rows]
    a2.set_ylim(0, max(tops + [1]) * 1.45)
    a1.set_title("Missing STATE ticks", loc="left", fontsize=11, color=INK)
    a2.set_title("Retransmissions (lobby/game events only)", loc="left", fontsize=11, color=INK)
    fig.suptitle("UDP under loss: snapshots are skipped, events are repaired", x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / f"udp_loss{suffix}.png", dpi=150)
    plt.close(fig)
    print("wrote", (OUT / f"udp_loss{suffix}.png").relative_to(METRICS.parent))


def chart_detection(losses, by, suffix):
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    top = 5
    for i, loss in enumerate(losses):
        for j, proto in enumerate(("tcp", "udp")):
            x = i + (j - 0.5) * WIDTH
            r = by.get((proto, loss))
            if not measured(r) or num(r["detect_ms"]) is None:      # 0 ms is a real value
                not_measured(ax, x, 0.2, proto)
                continue
            secs = num(r["detect_ms"]) / 1000
            top = max(top, secs)
            how = "FIN" if r["detect_how"] == "FIN" else "heartbeat" if "heartbeat" in r["detect_how"] else r["detect_how"]
            text = f"{secs:.2f} s" if secs >= 0.1 else ("< 1 ms" if secs < 0.001 else f"{secs * 1000:.0f} ms")
            bars(ax, x, max(secs, 0.03), proto, f"{text}\n{how}")
    ax.axhline(4, color=INK2, linewidth=1, linestyle=(0, (4, 3)))
    ax.set_xlim(-0.55, len(losses) - 0.45)
    loss_axis(ax, losses)
    ax.set_ylabel("SIGKILL → server logs PLAYER_LEFT (s)")
    ax.set_ylim(0, top * 1.35)
    legend(ax, ("tcp", "udp"))
    finish(fig, ax, "Disconnection detection time",
           "one client killed with SIGKILL (no goodbye) mid-game · dashed line = UDP heartbeat timeout (4 s)", f"detection{suffix}.png")


def chart_rtt_paths():
    """metrics/rtt_paths.csv (run_benchmark.py --rtt-host): one bar per measured path."""
    path = METRICS / "rtt_paths.csv"
    if not path.exists():
        return
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(max(5.0, 1.6 * len(rows) + 2), 4.2))
    top = max(num(r["rtt_p95_ms"]) for r in rows)
    for x, r in enumerate(rows):
        mean, p95 = num(r["rtt_mean_ms"]), num(r["rtt_p95_ms"])
        color = COLOR.get(r["proto"], INK2)
        ax.bar(x, mean, 0.55, color=color, edgecolor=SURFACE, linewidth=2)
        ax.plot([x, x], [mean, p95], color=INK2, linewidth=1)
        ax.plot([x - 0.1, x + 0.1], [p95, p95], color=INK2, linewidth=1.5)
        ax.annotate(f"{mean:.1f} ms\np95 {p95:.1f}", (x, p95), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(len(rows)), [f"{r['network']}\n{LABEL.get(r['proto'], r['proto'])}" for r in rows])
    ax.tick_params(axis="x", length=0)
    ax.set_ylabel("round-trip time (ms)")
    ax.set_ylim(0, top * 1.35)
    finish(fig, ax, "Round-trip time by network path",
           "bar = mean, tick = p95 · PING→PONG to the same server over each path", "rtt_paths.png")


def chart_networks():
    """results.csv rows at 0 % loss, one group per network: RTT, inter-update p99, missing ticks."""
    with open(METRICS / "results.csv") as f:
        rows = [r for r in csv.DictReader(f) if measured(r) and int(r["loss_pct"]) == 0]
    nets = sorted({network(r) for r in rows},
                  key=lambda n: (NETWORK_ORDER.index(n) if n in NETWORK_ORDER else 9, n))
    if len(nets) < 2:
        return                                   # only loopback: nothing to compare yet
    by = {}
    for r in rows:                               # loopback has app and os rows: prefer app
        k = (network(r), r["proto"])
        if k not in by or r["loss_method"] == "app":
            by[k] = r
    panels = [("rtt_mean_ms", "rtt_p95_ms", "round-trip time (ms)", "RTT (mean, tick = p95)"),
              ("inter_update_mean_ms", "inter_update_p99_ms", "time between STATEs (ms)",
               "Inter-update time (mean, tick = p99)"),
              ("states_missing_pct", None, "STATE ticks never received (%)", "Missing ticks")]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.3))
    for ax, (key, tick, ylabel, title) in zip(axes, panels):
        top = 0
        for i, net in enumerate(nets):
            for j, proto in enumerate(("tcp", "udp")):
                r = by.get((net, proto))
                if r is None:
                    continue
                x = i + (j - 0.5) * WIDTH
                v = num(r[key]) or 0
                hi = num(r[tick]) if tick else None
                ax.bar(x, v, WIDTH, color=COLOR[proto], edgecolor=SURFACE, linewidth=2)
                if hi is not None:
                    ax.plot([x, x], [v, hi], color=INK2, linewidth=1)
                    ax.plot([x - WIDTH / 5, x + WIDTH / 5], [hi, hi], color=INK2, linewidth=1.5)
                label = f"{v:.1f}" if key != "states_missing_pct" else f"{v:.1f} %"
                ax.annotate(label, (x, hi if hi is not None else v), xytext=(0, 3), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8, color=INK)
                top = max(top, hi or v)
        ax.set_xticks(range(len(nets)), nets)
        ax.tick_params(axis="x", length=0)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(top, 1) * 1.3)
        ax.set_title(title, loc="left", fontsize=11, color=INK)
    if "loopback" in nets:
        axes[1].axhline(100, color=INK2, linewidth=1, linestyle=(0, (4, 3)))
    legend(axes[0], ("tcp", "udp"))
    fig.suptitle("Same game over different networks (no loss injected)", x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "networks.png", dpi=150)
    plt.close(fig)
    print("wrote", (OUT / "networks.png").relative_to(METRICS.parent))


def main():
    chart_rtt_paths()
    chart_networks()
    with open(METRICS / "results.csv") as f:
        methods = sorted({r["loss_method"] for r in csv.DictReader(f) if network(r) == "loopback"})
    for method in methods:
        suffix = "" if method == "app" else f"_{method}"
        losses, by = load(method)
        chart_rtt(losses, by, suffix)
        chart_inter_update(losses, by, method, suffix)
        chart_udp(losses, by, suffix)
        chart_detection(losses, by, suffix)


if __name__ == "__main__":
    main()
