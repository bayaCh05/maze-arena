"""Build the 7-slide demo deck slides/maze_arena_tcp_vs_udp.pptx.

Every number on the slides is read from metrics/results.csv (and metrics/rtt_paths.csv
when it exists), so after new measurements just run:

    .venv/bin/python slides/build_slides.py

A value that was never measured is shown as "measured live in the demo", never guessed.
The charts are native PowerPoint charts drawn from the same rows as metrics/charts/*.png,
in the same colors (TCP blue, UDP orange, see metrics/make_charts.py).
Edit TEAM and BONUS_STATUS below before the demo.
"""

import csv
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "metrics" / "results.csv"
RTT_PATHS = ROOT / "metrics" / "rtt_paths.csv"
CHARTS = ROOT / "metrics" / "charts"
OUT = ROOT / "slides" / "maze_arena_tcp_vs_udp.pptx"
SCRIPT = ROOT / "docs" / "presentation_script.md"
WPM = 140  # calm speaking speed, words per minute

TEAM = ["[Name 1]", "[Name 2]", "[Name 3]", "[Name 4]"]
BONUS_STATUS = {
    "tcp": "TCP path: works through the public tunnel [update after the remote test]",
    "udp": "UDP path: [update after the playit test]",
}
LIVE = "measured live in the demo"
LOSSES = (0, 10, 30)

# Colors: TCP and UDP are the only saturated colors, the same on every slide and chart.
TCP = RGBColor(0x2A, 0x78, 0xD6)
UDP = RGBColor(0xEB, 0x68, 0x34)
TCP_LIGHT = RGBColor(0xE2, 0xEC, 0xFA)
UDP_LIGHT = RGBColor(0xFC, 0xE8, 0xDF)
INK = RGBColor(0x17, 0x1C, 0x2E)
MUTED = RGBColor(0x55, 0x5D, 0x73)
LINE = RGBColor(0xC9, 0xCE, 0xDB)
PAPER = RGBColor(0xF6, 0xF7, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
NIGHT = RGBColor(0x10, 0x16, 0x2B)
NIGHT_2 = RGBColor(0x1D, 0x26, 0x44)
NIGHT_TEXT = RGBColor(0xB8, 0xC0, 0xD8)
LOST = RGBColor(0xB4, 0x23, 0x2B)

HEAD = "Cambria"
BODY = "Calibri"
MONO = "Courier New"
W, H = Inches(13.333), Inches(7.5)


# ---------------------------------------------------------------- data

def load_results():
    """{(proto, loss): row} for the loopback runs that finished ("ok").

    TCP loss only works through the kernel (loss_method os); a later row replaces an
    earlier one, so a re-run benchmark wins.
    """
    rows = {}
    if not RESULTS.exists():
        sys.exit(f"missing {RESULTS}: run metrics/run_benchmark.py first")
    with open(RESULTS) as f:
        for r in csv.DictReader(f):
            if r["status"] != "ok" or r["network"] != "loopback":
                continue
            rows[(r["proto"], int(float(r["loss_pct"])))] = r
    return rows


def load_rtt_paths():
    """{network: {proto: rtt_mean_ms}} from rtt_paths.csv (LAN / tunnel RTT), if measured."""
    paths = {}
    if RTT_PATHS.exists():
        with open(RTT_PATHS) as f:
            for r in csv.DictReader(f):
                if r.get("rtt_mean_ms"):
                    paths.setdefault(r["network"], {})[r["proto"]] = float(r["rtt_mean_ms"])
    return paths


def num(rows, proto, loss, field):
    r = rows.get((proto, loss))
    if r is None or r.get(field, "") in ("", "nan"):
        return None
    return float(r[field])


def ms(v, digits=0):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.1f} s"
    return f"{v:.{digits}f} ms"


# ---------------------------------------------------------------- drawing helpers

def text(slide, x, y, w, h, paras, size=20, color=INK, font=BODY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, space_after=4, name=None):
    """A text box. paras: list of str or list of (text, {opts}) runs."""
    box = slide.shapes.add_textbox(x, y, w, h)
    if name:
        box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    _fill(tf, paras, size, color, font, bold, align, space_after)
    return box


def _fill(tf, paras, size, color, font, bold, align, space_after):
    if isinstance(paras, str):
        paras = [paras]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        runs = [(para, {})] if isinstance(para, str) else para
        for t, o in runs:
            r = p.add_run()
            r.text = t
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.italic = o.get("italic", False)
            r.font.name = o.get("font", font)
            r.font.color.rgb = o.get("color", color)


def box(slide, x, y, w, h, paras="", fill=WHITE, line=None, size=18, color=INK,
        font=BODY, bold=False, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, margin=0.08, line_w=1.5, name=None):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    if name:
        s.name = name
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.12
    s.shadow.inherit = False
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_w)
    tf = s.text_frame
    tf.word_wrap = True
    m = Inches(margin)
    tf.margin_left = tf.margin_right = m
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    tf.vertical_anchor = anchor
    _fill(tf, paras, size, color, font, bold, align, 0)
    return s


def arrow(slide, x1, y1, x2, y2, color=MUTED, width=2.0, dash=False, head=True):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
    c.line.color.rgb = color
    c.line.width = Pt(width)
    ln = c.line._get_or_add_ln()
    if dash:
        d = etree.SubElement(ln, qn("a:prstDash"))
        d.set("val", "dash")
    if head:
        t = etree.SubElement(ln, qn("a:tailEnd"))
        t.set("type", "triangle")
        t.set("w", "med")
        t.set("len", "med")
    return c


def pill(slide, x, y, label, color):
    """The TCP / UDP tag in the top right corner: the deck's recurring motif."""
    return box(slide, x, y, Inches(0.95), Inches(0.42), label, fill=color, size=16,
               color=WHITE, bold=True, name=f"tag {label}")


def frame(prs, n, title, tags=(), dark=False, gloss=None, source=None):
    """A slide with background, title, protocol tags, a 'words' line and a footer."""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = NIGHT if dark else PAPER
    fg = WHITE if dark else INK
    sub = NIGHT_TEXT if dark else MUTED
    if title:
        text(s, Inches(0.6), Inches(0.38), Inches(10.4), Inches(0.9), title, size=34,
             color=fg, font=HEAD, bold=True, anchor=MSO_ANCHOR.MIDDLE, name="title")
    x = W - Inches(0.6)
    for label in reversed(tags):
        x -= Inches(0.95)
        pill(s, x, Inches(0.6), label, TCP if label == "TCP" else UDP)
        x -= Inches(0.12)
    if gloss:
        text(s, Inches(0.6), Inches(6.62), Inches(12.1), Inches(0.42),
             [[("Words  ", {"bold": True, "color": fg}), (gloss, {})]],
             size=14, color=sub, anchor=MSO_ANCHOR.BOTTOM, name="words")
    foot = f"Maze Arena · TCP vs UDP · {n}/7"
    if source:
        foot += f"   ·   {source}"
    text(s, Inches(0.6), Inches(7.08), Inches(12.1), Inches(0.3), foot, size=11,
         color=sub, name="footer")
    return s


def notes(slide, body, qa):
    lines = [body.strip(), ""]
    for q, a in qa:
        lines += [f"Likely question: {q}", f"Answer: {a}", ""]
    slide.notes_slide.notes_text_frame.text = "\n".join(lines).strip()


def cell(c, paras, size=16, color=INK, bold=False, fill=None, align=PP_ALIGN.LEFT):
    c.text_frame.word_wrap = True
    c.margin_left = c.margin_right = Inches(0.1)
    c.margin_top = c.margin_bottom = Inches(0.04)
    c.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf = c.text_frame
    tf.paragraphs[0].text = ""
    _fill(tf, paras, size, color, BODY, bold, align, 0)
    if fill is None:
        c.fill.background()
    else:
        c.fill.solid()
        c.fill.fore_color.rgb = fill


def table(slide, x, y, w, col_w, row_h, name):
    t = slide.shapes.add_table(len(row_h), len(col_w), x, y, w, sum(row_h, Emu(0)))
    t.name = name
    tbl = t.table
    # drop the built-in banded style so only our fills show
    tbl_pr = tbl._tbl.tblPr
    tbl_pr.set("firstRow", "0")
    tbl_pr.set("bandRow", "0")
    style = tbl_pr.find(qn("a:tableStyleId"))
    if style is None:
        style = etree.SubElement(tbl_pr, qn("a:tableStyleId"))
    style.text = "{5940675A-B579-460E-94D1-54222C63F5DA}"  # "No Style, Table Grid"
    for i, cw in enumerate(col_w):
        tbl.columns[i].width = cw
    for i, rh in enumerate(row_h):
        tbl.rows[i].height = rh
    return tbl


def bar_chart(slide, x, y, w, h, title, tcp_vals, udp_vals, fmt, name):
    data = CategoryChartData(number_format=fmt)
    data.categories = [f"{l} % loss" for l in LOSSES]
    data.add_series("TCP", tcp_vals)
    data.add_series("UDP", udp_vals)
    gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, x, y, w, h, data)
    gf.name = name
    ch = gf.chart
    ch.has_title = True
    ch.chart_title.text_frame.text = title
    tp = ch.chart_title.text_frame.paragraphs[0]
    tp.runs[0].font.size = Pt(18)
    tp.runs[0].font.bold = True
    tp.runs[0].font.name = BODY
    tp.runs[0].font.color.rgb = INK
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(14)
    ch.legend.font.name = BODY
    ch.font.name = BODY
    ch.font.size = Pt(14)
    ch.font.color.rgb = MUTED
    plot = ch.plots[0]
    plot.gap_width = 60
    plot.overlap = -10
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format = fmt
    dl.number_format_is_linked = False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size = Pt(14)
    dl.font.bold = True
    dl.font.color.rgb = INK
    for series, color in zip(plot.series, (TCP, UDP)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = color
    va = ch.value_axis
    va.visible = False
    va.has_major_gridlines = False
    va.minimum_scale = 0
    ca = ch.category_axis
    ca.format.line.color.rgb = LINE
    ca.tick_labels.font.size = Pt(14)
    ca.tick_labels.font.color.rgb = MUTED
    return gf


# ---------------------------------------------------------------- slides

def slide_intro(prs):
    s = frame(prs, 1, None, dark=True,
              gloss="authoritative server = only the server changes the game  ·  "
                    "tick = one game step (every 100 ms)  ·  STATE = full picture of the game")
    text(s, Inches(0.6), Inches(0.7), Inches(6), Inches(1.0), "Maze Arena", size=54,
         color=WHITE, font=HEAD, bold=True, name="title")
    text(s, Inches(0.6), Inches(1.75), Inches(5.6), Inches(1.0),
         "One maze game, built twice: over TCP and over UDP", size=24, color=NIGHT_TEXT)
    text(s, Inches(0.6), Inches(3.05), Inches(5.4), Inches(2.6), [
        "Up to 3 players race for pellets in a maze.",
        "The server runs the game: 10 ticks per second.",
        "Clients only send a direction.",
        [("Rules written once in ", {}), ("common/", {"font": MONO, "bold": True}),
         (" → the same game on both.", {})],
    ], size=20, color=WHITE, space_after=10)
    text(s, Inches(0.6), Inches(5.75), Inches(5.6), Inches(0.4),
         "Team: " + " · ".join(TEAM), size=16, color=NIGHT_TEXT)

    # diagram: 4 computers
    sx, sy, sw, sh = Inches(7.0), Inches(0.75), Inches(5.6), Inches(2.0)
    box(s, sx, sy, sw, sh, "", fill=NIGHT_2, line=NIGHT_TEXT, name="server pc")
    text(s, sx + Inches(0.25), sy + Inches(0.12), sw - Inches(0.5), Inches(0.4),
         [[("PC 1 · server", {"bold": True, "color": WHITE}),
           ("   runs the game, 10 ticks/s · + 3 player PCs", {})]], size=16, color=NIGHT_TEXT)
    box(s, sx + Inches(0.25), sy + Inches(0.62), Inches(2.4), Inches(0.5), "tcp/server.py",
        fill=TCP, size=15, color=WHITE, bold=True, font=BODY)
    box(s, sx + Inches(2.95), sy + Inches(0.62), Inches(2.4), Inches(0.5), "udp/server.py",
        fill=UDP, size=15, color=WHITE, bold=True, font=BODY)
    box(s, sx + Inches(0.25), sy + Inches(1.3), Inches(5.1), Inches(0.5),
        [[("common/ ", {"font": MONO, "bold": True}), ("game rules + message format, shared", {})]],
        fill=None, line=NIGHT_TEXT, size=15, color=WHITE, line_w=1)
    cw, cy = Inches(1.65), Inches(4.35)
    for i in range(3):
        cx = Inches(7.0) + i * (cw + Inches(0.325))
        box(s, cx, cy, cw, Inches(1.15),
            [[(f"PC {i + 2}", {"bold": True})], "client"],
            fill=NIGHT_2, line=NIGHT_TEXT, size=16, color=WHITE)
        mid = cx + cw // 2
        arrow(s, mid - Inches(0.25), cy, mid - Inches(0.25), sy + sh, color=WHITE, width=1.75)
        arrow(s, mid + Inches(0.25), sy + sh, mid + Inches(0.25), cy, color=NIGHT_TEXT,
              width=1.75)
    text(s, Inches(7.0), Inches(5.65), Inches(5.6), Inches(0.8), [
        [("↑ INPUT ", {"bold": True, "color": WHITE}), ("only a direction: UP, LEFT…", {})],
        [("↓ STATE ", {"bold": True, "color": WHITE}), ("10 times per second, to everyone", {})],
    ], size=15, color=NIGHT_TEXT, space_after=2)
    notes(s, """
[Presenter 1] Hello, we are [team]. Our project is Maze Arena, a small multiplayer maze game
where up to three players race to eat pellets. We built the same game twice: once over TCP and
once over UDP, so we can compare the two protocols on the same workload.
The design is simple. One computer runs the server, three computers run a client. The server
is authoritative: it alone moves the players and decides who scores, ten times per second.
A client sends only a direction, and the server sends the full game state, called STATE,
to everyone after each step. The rules live once in the common folder, and both servers use
the same code, so any difference we measure comes from the network, not from the game.
""", [("Why an authoritative server?",
       "Clients cannot cheat or disagree: only the server changes the game, and every client "
       "draws the same STATE."),
      ("Why send the full STATE instead of changes?",
       "If one STATE is lost, the next one is complete again, so UDP can simply skip a lost one.")])


def slide_tcp(prs):
    s = frame(prs, 2, "TCP version: one connection per player", tags=("TCP",),
              gloss="socket = a program's network endpoint  ·  byte stream = bytes arrive in "
                    "order, with no message edges  ·  thread = a task that runs alongside others")
    # left: socket diagram
    lx = Inches(0.6)
    box(s, lx, Inches(1.55), Inches(2.6), Inches(0.75),
        [[("listening socket", {"bold": True})], "port 5050"], fill=TCP, color=WHITE, size=16)
    arrow(s, lx + Inches(2.6), Inches(1.92), lx + Inches(3.2), Inches(1.92), color=TCP)
    box(s, lx + Inches(3.2), Inches(1.55), Inches(1.6), Inches(0.75),
        [[("accept()", {"font": MONO, "bold": True})], "per player"],
        fill=TCP_LIGHT, line=TCP, size=15)
    arrow(s, lx + Inches(4.0), Inches(2.3), lx + Inches(4.0), Inches(2.65), color=TCP)
    for i in range(3):
        y = Inches(2.65) + i * Inches(0.72)
        box(s, lx, y, Inches(2.1), Inches(0.58), f"connection P{i + 1}",
            fill=WHITE, line=TCP, size=15)
        box(s, lx + Inches(2.2), y, Inches(1.25), Inches(0.58), "reader", fill=TCP_LIGHT, size=15)
        box(s, lx + Inches(3.55), y, Inches(1.25), Inches(0.58), "writer", fill=TCP_LIGHT, size=15)
    text(s, lx, Inches(4.85), Inches(6.2), Inches(0.4),
         "+ one game thread per room  ·  + a 5 s watchdog", size=16, color=MUTED)

    # right: framing
    rx, rw = Inches(6.8), Inches(5.9)
    text(s, rx, Inches(1.55), rw, Inches(0.5),
         [[("One recv() is not one message.", {"bold": True})]], size=22)
    text(s, rx, Inches(2.05), rw, Inches(0.45),
         "So each message is one JSON line ending in \\n.", size=18, color=MUTED)
    code = box(s, rx, Inches(2.6), rw, Inches(2.15), "", fill=INK, name="framing example",
               anchor=MSO_ANCHOR.TOP)
    tf = code.text_frame
    tf.margin_left = tf.margin_right = Inches(0.25)
    tf.margin_top = Inches(0.15)
    nl = {"color": RGBColor(0xFF, 0xC5, 0x3D), "bold": True}
    _fill(tf, [
        [("recv #1", {"color": NIGHT_TEXT, "font": BODY, "size": 14})],
        [('{"type":"INPUT","dir":"UP"}', {}), ("\\n", nl), ('{"type":"PI', {})],
        [("recv #2", {"color": NIGHT_TEXT, "font": BODY, "size": 14})],
        [('NG","t":12.5}', {}), ("\\n", nl)],
        [("→ cut at each \\n: INPUT, then PING", {"color": RGBColor(0x8F, 0xBA, 0xF0),
                                                  "font": BODY, "bold": True})],
    ], 16, WHITE, MONO, False, PP_ALIGN.LEFT, 4)

    # bottom: message flow
    steps = ["LOGIN", "LOBBY / ROOMS", "GAME_START", "INPUT ⇄ STATE", "GAME_OVER"]
    cw, gap, y = Inches(2.35), Inches(0.08), Inches(5.45)
    for i, st in enumerate(steps):
        box(s, lx + i * (cw + gap), y, cw, Inches(0.7), st, fill=TCP if i == 3 else TCP_LIGHT,
            color=WHITE if i == 3 else INK, size=14, bold=True, shape=MSO_SHAPE.CHEVRON,
            margin=0.02)
    notes(s, """
[Presenter 2] Here is the TCP version. The server opens one listening socket on port 5050.
Each time a player connects, accept gives us a new socket just for that player, and we start
two threads for it: a reader that receives, and a writer that sends from a queue, so one slow
player never blocks the others. TCP is reliable and ordered, but it is a byte stream: it has no message edges. One recv can
return half a message or three messages. So we end every JSON message with a newline and keep
a buffer until we see one.
The message flow is: LOGIN, then the lobby and rooms, GAME_START, then INPUT and STATE ten
times per second, and GAME_OVER.
""", [("Why a writer thread and not just send()?",
       "send() can block if a client is slow; with a queue per client the game thread never waits."),
      ("Why TCP_NODELAY?",
       "Without it TCP may hold small messages to batch them, which adds delay to our 10 STATEs per second.")])


def slide_udp(prs):
    s = frame(prs, 3, "UDP version: one socket, our own reliability", tags=("UDP",),
              gloss="datagram = one UDP packet = one message  ·  seq = message number  ·  "
                    "ACK = \"I got number 7\"")
    lx = Inches(0.6)
    box(s, lx, Inches(1.55), Inches(5.5), Inches(0.75),
        [[("one socket for everyone", {"bold": True})], "port 5050, recvfrom() in one loop"],
        fill=UDP, color=WHITE, size=16)
    text(s, lx, Inches(2.5), Inches(5.5), Inches(0.4),
         "the sender's (ip, port) tells us who it is:", size=16, color=MUTED)
    tbl = table(s, lx, Inches(2.9), Inches(5.5), [Inches(3.0), Inches(2.5)],
                [Inches(0.42)] * 4, "session map")
    cell(tbl.cell(0, 0), "(ip, port)  — example", 15, WHITE, True, UDP)
    cell(tbl.cell(0, 1), "session", 15, WHITE, True, UDP)
    for i, (addr, who) in enumerate([("192.168.1.12 : 50311", "player Ana"),
                                     ("192.168.1.20 : 61002", "player Ben"),
                                     ("192.168.1.31 : 53877", "player Chloé")], start=1):
        cell(tbl.cell(i, 0), addr, 15, INK, False, WHITE)
        cell(tbl.cell(i, 1), who, 15, INK, False, WHITE)

    # right: timeline, JOIN lost then resent
    rx = Inches(6.9)
    cx, sx = rx + Inches(0.8), rx + Inches(4.9)
    top, bot = Inches(1.95), Inches(4.75)
    text(s, cx - Inches(0.8), Inches(1.5), Inches(1.6), Inches(0.4), "client", size=16,
         bold=True, align=PP_ALIGN.CENTER)
    text(s, sx - Inches(0.8), Inches(1.5), Inches(1.6), Inches(0.4), "server", size=16,
         bold=True, align=PP_ALIGN.CENTER)
    arrow(s, cx, top, cx, bot, color=LINE, width=2, head=False)
    arrow(s, sx, top, sx, bot, color=LINE, width=2, head=False)
    # 1. JOIN lost
    y0 = Inches(2.15)
    arrow(s, cx, y0, cx + Inches(2.1), y0 + Inches(0.3), color=UDP, width=2.25, head=False)
    text(s, cx + Inches(1.95), y0 + Inches(0.06), Inches(0.5), Inches(0.5), "✕", size=26,
         color=LOST, bold=True)
    text(s, cx + Inches(0.15), y0 - Inches(0.36), Inches(3.0), Inches(0.35),
         "JOIN seq 7  (lost)", size=15, color=INK)
    # 2. 200 ms later: resent, arrives
    y1 = Inches(3.05)
    text(s, cx - Inches(1.6), y1 - Inches(0.15), Inches(1.45), Inches(0.35), "+200 ms",
         size=15, color=MUTED, bold=True, align=PP_ALIGN.RIGHT)
    arrow(s, cx, y1, sx, y1 + Inches(0.5), color=UDP, width=2.25)
    text(s, cx + Inches(0.15), y1 - Inches(0.36), Inches(3.6), Inches(0.35),
         "JOIN seq 7  (sent again)", size=15)
    # 3. ACK
    y2 = Inches(3.95)
    arrow(s, sx, y2, cx, y2 + Inches(0.5), color=UDP, width=2.25)
    text(s, cx + Inches(1.6), y2 - Inches(0.1), Inches(2.2), Inches(0.35), "ACK 7",
         size=15, bold=True)
    text(s, sx + Inches(0.12), y1 + Inches(0.35), Inches(1.0), Inches(0.9),
         "a 2nd copy is dropped", size=12, color=MUTED)

    # bottom: the two message classes
    by, bh = Inches(5.0), Inches(1.45)
    box(s, lx, by, Inches(6.0), bh, [
        [("Reliable: ", {"bold": True, "color": UDP}),
         ("seq + ACK, resent every 200 ms, in order, no duplicates", {})],
        [("LOGIN · JOIN · READY · GAME_START · GAME_OVER · PLAYER_LEFT",
          {"font": MONO, "size": 13, "color": MUTED})],
    ], fill=WHITE, line=UDP, size=17, align=PP_ALIGN.LEFT, margin=0.2)
    box(s, Inches(6.8), by, Inches(5.9), bh, [
        [("Unreliable on purpose: ", {"bold": True, "color": UDP}),
         ("a lost STATE is replaced 100 ms later; older ticks are dropped", {})],
        [("STATE · INPUT · PING", {"font": MONO, "size": 13, "color": MUTED})],
    ], fill=WHITE, line=UDP, size=17, align=PP_ALIGN.LEFT, margin=0.2)
    notes(s, """
[Presenter 2] Now UDP. There is no connection: the server has one socket for all players and
reads it in one loop. Each datagram comes with the sender's IP and port, so we
keep a map from (ip, port) to the player's session.
One datagram is one message, but UDP may lose, duplicate or reorder it.
Important ones, like JOIN or GAME_OVER, get
a sequence number; the receiver answers with an ACK, and the sender resends every 200
milliseconds until it gets it, up to 15 times. Look at the timeline: the first JOIN is lost,
it is sent again 200 milliseconds later, and the ACK comes back. Duplicates are dropped by seq. STATE, INPUT and PING are never resent: a new STATE comes
100 milliseconds later anyway, and old ticks are thrown away.
""", [("What if the ACK is lost instead?",
       "The sender resends; the receiver sees seq 7 again, drops the duplicate, and ACKs again."),
      ("What if all 15 resends fail?",
       "The message is given up and the 4 s heartbeat removes that player. In our 30 % loss test, 0 messages were given up.")])


def slide_players(prs, rows):
    tcp_d = [num(rows, "tcp", l, "detect_ms") for l in LOSSES]
    udp_d = [num(rows, "udp", l, "detect_ms") for l in LOSSES]

    def span(vals, unit_s=False):
        vals = [v for v in vals if v is not None]
        if not vals:
            return LIVE
        lo, hi = min(vals), max(vals)
        if unit_s:
            return f"{lo / 1000:.1f}–{hi / 1000:.1f} s"
        return f"{lo:.0f}–{hi:.0f} ms"

    s = frame(prs, 4, "Many players at once, and players who vanish", tags=("TCP", "UDP"),
              gloss="lock = only one thread at a time may change the game  ·  heartbeat = an "
                    "\"I'm alive\" PING every second",
              source="times: a bot killed mid-game, loopback, 0/10/30 % loss (metrics/results.csv)")
    rh = [Inches(0.55), Inches(0.82), Inches(0.62), Inches(0.82), Inches(0.82), Inches(0.62)]
    tbl = table(s, Inches(0.6), Inches(1.5), Inches(12.1),
                [Inches(2.7), Inches(4.7), Inches(4.7)], rh, "players and disconnections")
    cell(tbl.cell(0, 0), "", 18, INK, True, None)
    cell(tbl.cell(0, 1), "TCP", 20, WHITE, True, TCP, PP_ALIGN.CENTER)
    cell(tbl.cell(0, 2), "UDP", 20, WHITE, True, UDP, PP_ALIGN.CENTER)
    body = [
        ("Threads", "1 accept loop + a reader and a writer per player + a game thread per room",
         "1 receive loop for everyone + a timer thread (resends, timeouts) + the game thread"),
        ("Shared game", "one lock around the game state: one thread changes it at a time", None),
        ("Client crashes", [[("its OS closes the connection → seen in ", {}),
                             (span(tcp_d), {"bold": True})]],
         [[("no signal at all → 4 s heartbeat → ", {}), (span(udp_d, True), {"bold": True})]]),
        ("Frozen PC / Wi-Fi off", "no packet at all → the 5 s watchdog drops it",
         "same 4 s heartbeat"),
        ("Mid-game", "the others get PLAYER_LEFT · the game goes on · it ends with 1 player left",
         None),
    ]
    for i, (label, t, u) in enumerate(body, start=1):
        cell(tbl.cell(i, 0), label, 18, INK, True, WHITE)
        cell(tbl.cell(i, 1), t, 17, INK, False, TCP_LIGHT if u else WHITE)
        if u is None:
            tbl.cell(i, 1).merge(tbl.cell(i, 2))
            cell(tbl.cell(i, 1), t, 17, INK, False, WHITE, PP_ALIGN.CENTER)
        else:
            cell(tbl.cell(i, 2), u, 17, INK, False, UDP_LIGHT)
    box(s, Inches(0.6), Inches(5.95), Inches(12.1), Inches(0.55), [[
        ("Chaos test, both servers: ", {"bold": True}),
        ("kill -9 a client, send garbage, break the lobby rules → the server never crashed.", {}),
    ]], fill=WHITE, line=LINE, size=17, line_w=1)
    notes(s, f"""
[Presenter 3] How do we handle several players at the same time? TCP gives each player a
reader and a writer thread; UDP has one receive loop and a timer thread. In both, the game state is protected by one lock.

Now disconnections. With TCP, if a client program crashes, its operating system closes the
connection, and we saw it in {span(tcp_d)}. But if the Wi-Fi goes off, nothing is sent at
all, so TCP alone would wait for minutes: our watchdog drops a silent player after 5 seconds.
UDP has no connection, so silence is the only signal: after 4 seconds without a datagram the
player is removed; we measured {span(udp_d, True)}. Either way the others get PLAYER_LEFT and keep
playing, and if only one player is left, the game ends. Our chaos test never crashed either server.
""", [("Why not a shorter UDP timeout?",
       "Under 30 % loss several PINGs in a row can be lost; 4 s avoids kicking players who are still there."),
      ("Can two threads move a player at the same time?",
       "No. Every change to the game goes through the same lock.")])


def slide_metrics(prs, rows, paths):
    s = frame(prs, 5, "Our measurements: TCP waits, UDP skips", tags=("TCP", "UDP"),
              gloss="RTT = time for a PING to go and come back  ·  freeze = over 250 ms "
                    "without a new STATE  ·  loss = share of packets dropped on purpose")
    cw, ch, gap = Inches(3.9), Inches(3.05), Inches(0.2)
    specs = [
        ("Round-trip time (ms, mean)", "rtt_mean_ms", '0.0;;0'),
        ("STATEs lost (%)", "states_missing_pct", '0.0;;0'),
        ("Freezes > 250 ms per game", "freezes_over_250ms", '0'),
    ]
    missing = False
    for i, (title, field, fmt) in enumerate(specs):
        tv = [num(rows, "tcp", l, field) for l in LOSSES]
        uv = [num(rows, "udp", l, field) for l in LOSSES]
        missing |= None in tv + uv
        bar_chart(s, Inches(0.6) + i * (cw + gap), Inches(1.35), cw, ch, title, tv, uv, fmt,
                  f"chart {field}")
    # table: what does not fit a chart
    tbl = table(s, Inches(0.6), Inches(4.5), Inches(12.1),
                [Inches(3.1)] + [Inches(1.5)] * 6, [Inches(0.42)] * 3, "resends and detection")
    cell(tbl.cell(0, 0), "loss →", 15, MUTED, True, None)
    for j, (p, l) in enumerate([(p, l) for p in ("tcp", "udp") for l in LOSSES], start=1):
        cell(tbl.cell(0, j), f"{p.upper()} {l} %", 15, WHITE, True, TCP if p == "tcp" else UDP,
             PP_ALIGN.CENTER)
    cell(tbl.cell(1, 0), "Messages resent", 15, INK, True, WHITE)
    cell(tbl.cell(2, 0), "Killed client detected after", 15, INK, True, WHITE)
    for j, (p, l) in enumerate([(p, l) for p in ("tcp", "udp") for l in LOSSES], start=1):
        if p == "tcp":
            resent = "by the OS" if (p, l) in rows else "—"
        else:
            c = num(rows, p, l, "client_retransmissions")
            sv = num(rows, p, l, "server_retransmissions")
            resent = "—" if c is None or sv is None else f"{c + sv:.0f}"
        d = num(rows, p, l, "detect_ms")
        cell(tbl.cell(1, j), resent, 15, INK, False, WHITE, PP_ALIGN.CENTER)
        cell(tbl.cell(2, j), ms(d), 15, INK, False, WHITE, PP_ALIGN.CENTER)
    missing |= any((p, l) not in rows for p in ("tcp", "udp") for l in LOSSES)

    t30, u30 = num(rows, "tcp", 30, "rtt_mean_ms"), num(rows, "udp", 30, "rtt_mean_ms")
    tm, um = num(rows, "tcp", 30, "states_missing_pct"), num(rows, "udp", 30, "states_missing_pct")
    if None in (t30, u30, tm, um):
        take = f"Takeaway at 30 % loss: {LIVE}."
    else:
        take = (f"At 30 % loss: TCP loses {tm:.0f} % of STATEs but its RTT grows to {t30:.0f} ms; "
                f"UDP stays at {u30:.1f} ms and skips {um:.0f} %.")
    text(s, Inches(0.6), Inches(5.9), Inches(12.1), Inches(0.4), [[(take, {"bold": True})]],
         size=19)
    where = "loopback (one Mac), 3 bots, 120 s games · TCP loss: kernel · UDP loss: our --drop"
    lan = paths.get("lan", {}).get("tcp") or paths.get("lan", {}).get("udp")
    net = paths.get("cloudflare", {}).get("tcp")
    extra = (f"LAN RTT {ms(lan, 1)}" if lan else f"LAN: {LIVE}") + " · " + \
            (f"internet (Cloudflare) RTT {ms(net, 1)}" if net else f"internet: {LIVE}")
    text(s, Inches(0.6), Inches(6.28), Inches(12.1), Inches(0.35),
         [[("Network: ", {"bold": True}), (f"{where} · {extra}", {})]], size=13, color=MUTED)
    if missing:
        text(s, Inches(0.6), Inches(1.0), Inches(9), Inches(0.3),
             f"empty bars / — : {LIVE}", size=12, color=LOST)

    r = lambda p, l, f, d=0: ms(num(rows, p, l, f), d)
    notes(s, f"""
[Presenter 3] These are our own numbers, from metrics slash results dot csv. Three bots, 120-second games
on one Mac, at 0, 10 and 30 percent loss.
Left chart: round-trip time. Without loss both are under 1 millisecond. With loss, TCP waits
for every lost packet to be resent, and all later data waits behind it: that is head-of-line
blocking. Its RTT grows to {r('tcp', 10, 'rtt_mean_ms')} and then {r('tcp', 30, 'rtt_mean_ms')}.
UDP stays at about {r('udp', 30, 'rtt_mean_ms', 1)}, because nothing waits.
Middle: TCP never loses a STATE; UDP simply skips the lost ones. Right: TCP freezes for more
than a quarter second much more often. One honest caveat: TCP loss is applied by the kernel, UDP loss by our drop
option, at the same rates. LAN and internet numbers we measure live today.
""", [("Why is TCP loss done differently?",
       "TCP must see real lost segments to resend them, so the kernel drops them; our --drop "
       "option only exists in the UDP code. Same rates, different method."),
      ("Why measure on loopback?",
       "It removes Wi-Fi noise, so the only difference is the loss we add on purpose.")])


def slide_differences(prs, rows):
    u30 = num(rows, "udp", 30, "rtt_mean_ms")
    t30 = num(rows, "tcp", 30, "rtt_mean_ms")
    s = frame(prs, 6, "What differs, what hurt, who wins", tags=("TCP", "UDP"),
              gloss="head-of-line blocking = one lost TCP segment makes all later data wait  ·  "
                    "client isolation = Wi-Fi that blocks traffic between laptops")
    rh = [Inches(0.5)] + [Inches(0.62)] * 5
    tbl = table(s, Inches(0.6), Inches(1.45), Inches(7.4),
                [Inches(1.8), Inches(2.8), Inches(2.8)], rh, "differences")
    cell(tbl.cell(0, 0), "", 16, INK, True, None)
    cell(tbl.cell(0, 1), "TCP", 18, WHITE, True, TCP, PP_ALIGN.CENTER)
    cell(tbl.cell(0, 2), "UDP", 18, WHITE, True, UDP, PP_ALIGN.CENTER)
    diff = [
        ("Connection", "handshake, then a stream", "none: just send"),
        ("Message edges", "we add \\n to each message", "1 datagram = 1 message"),
        ("Lost packet", "OS resends; later data waits", "gone; we resend only key ones"),
        ("Order", "always in order", "seq for key ones; old STATEs dropped"),
        ("Leaver seen by", "FIN/RST + 5 s watchdog", "4 s heartbeat"),
    ]
    for i, (a, b, c) in enumerate(diff, start=1):
        cell(tbl.cell(i, 0), a, 16, INK, True, WHITE)
        cell(tbl.cell(i, 1), b, 16, INK, False, TCP_LIGHT)
        cell(tbl.cell(i, 2), c, 16, INK, False, UDP_LIGHT)

    fx = Inches(8.2)
    text(s, fx, Inches(1.45), Inches(4.4), Inches(0.45), [[("Friction points", {"bold": True})]],
         size=20)
    fr = [
        ("TCP", "one recv() ≠ one message → line buffer"),
        ("UDP", "we built seq / ACK / resend ourselves"),
        ("UDP", "heartbeat: short = false kicks, long = slow"),
        ("UDP", "STATE 1228 B, near the ~1472 B safe size"),
        ("both", "firewalls and Wi-Fi client isolation"),
        ("both", "tunnels: Cloudflare is TCP-only"),
    ]
    for i, (who, t) in enumerate(fr):
        y = Inches(1.98) + i * Inches(0.52)
        col = TCP if who == "TCP" else UDP if who == "UDP" else MUTED
        box(s, fx, y + Inches(0.06), Inches(0.68), Inches(0.34), who, fill=col, size=12,
            color=WHITE, bold=True)
        text(s, fx + Inches(0.8), y, Inches(3.75), Inches(0.48), t, size=15,
             anchor=MSO_ANCHOR.MIDDLE)

    by, bh, bw = Inches(5.25), Inches(1.15), Inches(5.95)
    box(s, Inches(0.6), by, bw, bh, [
        [("TCP was best for ", {"bold": True, "color": TCP}), ("the lobby, rooms and results:", {})],
        "everything must arrive; works through firewalls and tunnels.",
    ], fill=WHITE, line=TCP, size=17, align=PP_ALIGN.LEFT, margin=0.2, line_w=2)
    udp_line = (f"RTT stayed {u30:.1f} ms at 30 % loss (TCP: {t30:.0f} ms)."
                if None not in (u30, t30) else f"RTT under loss: {LIVE}.")
    box(s, Inches(0.6) + bw + Inches(0.2), by, bw, bh, [
        [("UDP was best for ", {"bold": True, "color": UDP}), ("live play when packets are lost:", {})],
        udp_line,
    ], fill=WHITE, line=UDP, size=17, align=PP_ALIGN.LEFT, margin=0.2, line_w=2)
    notes(s, """
[Presenter 4] To sum up the differences: TCP opens a connection and gives us an ordered
stream; UDP just sends separate datagrams. With TCP we add the message edges ourselves; with
UDP we add reliability ourselves, only for the messages that need it.
Friction points: TCP framing; building seq, ACK and resend for UDP; tuning the heartbeat;
a 1228-byte STATE close to the safe UDP size; firewalls and Wi-Fi that isolates laptops; and
Cloudflare carrying only TCP.
So where did each protocol win? TCP for the lobby and results, where everything must arrive,
and it passes firewalls easily. UDP for live play under loss: its round-trip time stayed flat.
""", [("If you started again, which one would you choose?",
       "UDP for the game data and our reliable layer for the lobby, like we did, because the game "
       "only needs the newest STATE."),
      ("What happens if STATE grows past the safe size?",
       "IP would split the datagram; losing one piece loses the whole STATE. We warn above 1200 "
       "bytes; a fix would be sending only changes.")])


def slide_bonus(prs, paths):
    s = frame(prs, 7, "Bonus: players on different networks", tags=("TCP", "UDP"), dark=True,
              gloss="NAT = a router sharing one public IP; it blocks unasked incoming traffic  ·  "
                    "tunnel = a link that carries our traffic through a relay")

    def lane(y, color, label, steps):
        text(s, Inches(0.6), y - Inches(0.48), Inches(8), Inches(0.4),
             [[(label, {"bold": True, "color": color})]], size=18)
        n = len(steps)
        gap = Inches(0.42)
        bw = (Inches(12.1) - gap * (n - 1)) // n
        for i, st in enumerate(steps):
            x = Inches(0.6) + i * (bw + gap)
            last = i == n - 1
            box(s, x, y, bw, Inches(1.0), st, fill=color if last else NIGHT_2,
                line=color, size=14, color=WHITE, line_w=1.75)
            if not last:
                arrow(s, x + bw, y + Inches(0.5), x + bw + gap, y + Inches(0.5), color=color,
                      width=2.25)

    lane(Inches(1.9), TCP, "TCP · Cloudflare Tunnel", [
        [[("player PC", {"bold": True})], "client → localhost:15050"],
        [[("cloudflared", {"bold": True})], "access tcp"],
        [[("Cloudflare edge", {"bold": True})], "on the internet"],
        [[("tunnel", {"bold": True})], "opened outward by the server"],
        [[("tcp/server.py :5050", {"bold": True})], "sees 127.0.0.1"],
    ])
    lane(Inches(3.55), UDP, "UDP · playit.gg", [
        [[("player PC", {"bold": True})], "client, no extra app"],
        [[("xxx.ply.gg : port", {"bold": True})], "public UDP address"],
        [[("playit relay", {"bold": True})], "on the internet"],
        [[("playit agent", {"bold": True})], "reverse tunnel, opened outward"],
        [[("udp/server.py :5050", {"bold": True})], "sees the agent's address"],
    ])
    lan = paths.get("lan", {})
    net = {k: v for k, v in paths.items() if k in ("cloudflare", "playit")}
    if lan or net:
        parts = [f"{k} {p.upper()} {ms(v, 1)}" for k, d in list(lan and {"lan": lan}.items()) +
                 list(net.items()) for p, v in d.items()]
        rtt = "RTT: " + " · ".join(parts)
    else:
        rtt = f"RTT internet vs LAN: {LIVE}."
    text(s, Inches(0.6), Inches(4.75), Inches(12.1), Inches(1.6), [
        [("No port forwarding: ", {"bold": True, "color": WHITE}),
         ("both tunnels are dialed out from the server, so the router (NAT) needs no change.", {})],
        [("Two services: ", {"bold": True, "color": WHITE}),
         ("Cloudflare quick tunnels carry TCP only; playit relays UDP.", {})],
        [("Proof: ", {"bold": True, "color": WHITE}),
         ("each player runs ", {}), ("curl -4 ifconfig.me", {"font": MONO, "color": WHITE}),
         (" → 3 different public IPs.  ", {}), (rtt, {})],
    ], size=17, color=NIGHT_TEXT, space_after=6)
    text(s, Inches(0.6), Inches(6.25), Inches(12.1), Inches(0.35),
         f"Status: {BONUS_STATUS['tcp']}  ·  {BONUS_STATUS['udp']}", size=13,
         color=RGBColor(0xFF, 0xC5, 0x3D))
    notes(s, """
[Presenter 4] The bonus is to play from different networks, like campus Wi-Fi and two hotspots. Our server sits behind a router with NAT, which blocks connections that come
in from outside, and we did not open any port. Instead, the server dials out.
For TCP, cloudflared on the server opens a tunnel to Cloudflare. A remote player runs
cloudflared access tcp, which gives them a local port; their client connects there, and the
traffic goes through Cloudflare's edge to our port 5050. The server sees 127.0.0.1, where the tunnel ends.
Cloudflare quick tunnels do not carry UDP, so for UDP we use playit: the player sends
datagrams to a public playit address, and the playit agent on our server, through its reverse
tunnel, delivers them to the UDP server.
Proof: each player shows a different public IP with curl ifconfig.me.
""", [("Why not just forward port 5050 on the router?",
       "We do not control campus or hotspot routers, and many use carrier NAT; an outgoing tunnel "
       "works everywhere."),
      ("Does the tunnel change the protocol comparison?",
       "It adds delay, and playit still carries UDP datagrams, so the TCP vs UDP behaviour stays; we "
       "show the internet RTT next to the LAN one.")])


def write_script(prs):
    """docs/presentation_script.md: the notes in order, with timings from their length."""
    out = ["# Presentation script", "",
           f"Generated by `slides/build_slides.py` from the speaker notes of "
           f"`{OUT.relative_to(ROOT)}`; edit the notes there, then re-run. Timings assume "
           f"{WPM} words per minute.", "",
           "Presenters: " + ", ".join(f"Presenter {i + 1} = {n}" for i, n in enumerate(TEAM)), ""]
    total = 0
    rows, parts = [], []
    for i, slide in enumerate(prs.slides, start=1):
        title = next((sh.text_frame.text for sh in slide.shapes if sh.name == "title"), "")
        body, _, qa = slide.notes_slide.notes_text_frame.text.partition("Likely question")
        secs = round(len(body.split()) / WPM * 60 / 5) * 5
        start = total
        total += secs
        presenter = body.strip().split("]")[0].lstrip("[")
        rows.append(f"| {i} | {title} | {presenter} | {start // 60}:{start % 60:02d} | {secs} s |")
        qa = ("Likely question" + qa).strip() if qa else ""
        parts += [f"## Slide {i}: {title} ({secs} s)", "",
                  " ".join(body.split()), "", *(f"> {l}" if l else ">" for l in qa.splitlines()), ""]
    out += ["| Slide | Title | Who | Starts at | Length |", "|---|---|---|---|---|", *rows,
            f"| | **Total** | | | **{total // 60} min {total % 60:02d} s** |", ""]
    out += parts
    SCRIPT.write_text("\n".join(out))
    return total


def build():
    rows = load_results()
    paths = load_rtt_paths()
    if not CHARTS.exists():
        print(f"note: {CHARTS} is missing; run metrics/make_charts.py for the PNG charts")
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    prs.core_properties.title = "Maze Arena: TCP vs UDP"
    slide_intro(prs)
    slide_tcp(prs)
    slide_udp(prs)
    slide_players(prs, rows)
    slide_metrics(prs, rows, paths)
    slide_differences(prs, rows)
    slide_bonus(prs, paths)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    total = write_script(prs)
    have = sorted(f"{p}{l}" for p, l in rows)
    print(f"wrote {OUT.relative_to(ROOT)} (7 slides; loopback rows: {', '.join(have)}; "
          f"rtt paths: {', '.join(paths) or 'none'}); "
          f"wrote {SCRIPT.relative_to(ROOT)} ({total // 60} min {total % 60:02d} s)")


if __name__ == "__main__":
    build()
