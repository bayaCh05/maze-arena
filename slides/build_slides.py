"""Build the demo deck slides/maze_arena_tcp_vs_udp.pptx (20-minute talk with a live demo).

Every number on the slides is read from metrics/results.csv, so after new measurements just run:

    .venv/bin/python slides/build_slides.py --team "Name 1,Name 2,Name 3,Name 4"

Speaking order: Presenter 1 = the game and the design, then TCP vs UDP after the demo;
Presenter 2 = TCP and UDP; Presenter 3 = tells the live demo; Presenter 4 = conclusion
and runs the server (SERVER_IP over Tailscale, TCP on TCP_PORT, UDP on UDP_PORT).
In the demo the players use their own names (PLAYERS); CRASHED's game is the one killed.
The demo follows docs/demo_scenarios.md (3 tests: TCP, UDP, UDP with 30 % loss).
The measured charts are backup slides after "Questions?", for the Q&A.
A value that was never measured is shown as "measured live in the demo", never guessed.
Charts are native PowerPoint charts, TCP blue and UDP orange as in metrics/charts/*.png.
Also writes docs/presentation_script.md (speaker notes + timings).
"""

import argparse
import csv
import re
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
GAME_PNG = ROOT / "slides" / "img" / "game.png"
OUT = ROOT / "slides" / "maze_arena_tcp_vs_udp.pptx"
SCRIPT = ROOT / "docs" / "presentation_script.md"
WPM = 140  # calm speaking speed, words per minute

TEAM = ["Baya Chaabene", "Mohamed Aziz Souissi", "Yahia Mahfoudh", "Yassine Friaa"]
SERVER_IP = "100.66.86.49"      # the server PC's Tailscale address
TCP_PORT, UDP_PORT = 5050, 5051
PLAYERS = ("Baya", "Yahia", "Aziz")   # in-game names = players 1, 2, 3
CRASHED = "Aziz"                      # the player whose game is killed in tests 1 and 2
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
GOLD = RGBColor(0xFF, 0xC5, 0x3D)       # live demo
LOST = RGBColor(0xB4, 0x23, 0x2B)
PLAYER = dict(zip(PLAYERS, (RGBColor(0xE0, 0xB0, 0x00), RGBColor(0x00, 0xA5, 0xB8),
                             RGBColor(0xC8, 0x2C, 0xB4))))   # the game's yellow / cyan / magenta, darkened for paper

HEAD = "Cambria"
BODY = "Calibri"
MONO = "Courier New"
W, H = Inches(13.333), Inches(7.5)
I = Inches

SECS = {}   # slide_id -> fixed duration (demo slides); others are timed from their notes


# ---------------------------------------------------------------- data

def load_results():
    """{(proto, loss): row} for the loopback runs that finished ("ok"); a later row wins."""
    rows = {}
    if not RESULTS.exists():
        sys.exit(f"missing {RESULTS}: run metrics/run_benchmark.py first")
    with open(RESULTS) as f:
        for r in csv.DictReader(f):
            if r["status"] != "ok" or r["network"] != "loopback":
                continue
            rows[(r["proto"], int(float(r["loss_pct"])))] = r
    return rows


def num(rows, proto, loss, field):
    r = rows.get((proto, loss))
    if r is None or r.get(field, "") in ("", "nan"):
        return None
    return float(r[field])


def ms(v, digits=0):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.1f} s"
    return f"{v:.{digits}f} ms"


def span(vals, seconds=False):
    """'0–95 ms' / '4.0–4.5 s' over the measured values, kept on one line."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return LIVE
    lo, hi = min(vals), max(vals)
    if seconds:
        return f"{lo / 1000:.1f}⁠–⁠{hi / 1000:.1f} s"
    return f"{lo:.0f}⁠–⁠{hi:.0f} ms"


def who(i):
    """Presenter i's name, or 'Presenter i' while TEAM still has placeholders."""
    n = TEAM[i - 1] if i <= len(TEAM) else f"[Name {i}]"
    return f"Presenter {i}" if n.startswith("[") else n


def first(i):
    """Name without the family name ('Mohamed Aziz'), for small spaces."""
    n = who(i)
    return n if n.startswith("Presenter") or " " not in n else n.rsplit(" ", 1)[0]


def team_names():
    """'A, B, C and D' for the spoken intro."""
    return TEAM[0] if len(TEAM) == 1 else ", ".join(TEAM[:-1]) + " and " + TEAM[-1]


# ---------------------------------------------------------------- drawing helpers

def keep_together(t):
    """No line break between a number and its unit ('30 %', '4 s', '95 ms'), or in 'press R'."""
    t = re.sub(r"(\d) (%|s\b|ms\b|min\b)", "\\1\u00a0\\2", t)
    return re.sub(r"(press|presses) R\b", "\\1\u00a0R", t)


def text(slide, x, y, w, h, paras, size=20, color=INK, font=BODY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, space_after=4, name=None):
    """A text box. paras: str, or list of str / list of (text, {opts}) runs."""
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
            r.text = keep_together(t)
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.italic = o.get("italic", False)
            r.font.name = o.get("font", font)
            r.font.color.rgb = o.get("color", color)


def box(slide, x, y, w, h, paras="", fill=WHITE, line=None, size=18, color=INK,
        font=BODY, bold=False, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, margin=0.08, line_w=1.5, space_after=0, name=None):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    if name:
        s.name = name
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.10
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
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.05)
    tf.vertical_anchor = anchor
    _fill(tf, paras, size, color, font, bold, align, space_after)
    return s


def arrow(slide, x1, y1, x2, y2, color=MUTED, width=2.0, head=True):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
    c.line.color.rgb = color
    c.line.width = Pt(width)
    if head:
        t = etree.SubElement(c.line._get_or_add_ln(), qn("a:tailEnd"))
        t.set("type", "triangle")
        t.set("w", "med")
        t.set("len", "med")
    return c


def badge(slide, x, y, label, fill, d=0.55, size=20, color=WHITE):
    """A numbered circle: the deck's recurring marker for steps and points."""
    return box(slide, x, y, I(d), I(d), label, fill=fill, size=size, color=color, bold=True,
               shape=MSO_SHAPE.OVAL, margin=0)


def points(slide, x, y, w, items, accent, gap=1.15, size=22, dark=False):
    """Numbered statements: a badge, then a bold lead and an optional plain follow-up."""
    for i, item in enumerate(items):
        lead, rest = item if isinstance(item, tuple) else (item, "")
        yy = y + I(gap * i)
        badge(slide, x, yy, str(i + 1), accent)
        runs = [(lead, {"bold": True})]
        if rest:
            runs.append((" " + rest, {"bold": False, "color": NIGHT_TEXT if dark else MUTED}))
        text(slide, x + I(0.8), yy - I(0.02), w - I(0.8), I(gap), [runs], size=size,
             color=WHITE if dark else INK)


def pill(slide, x, y, label, color):
    return box(slide, x, y, I(0.95), I(0.42), label, fill=color, size=16, color=WHITE, bold=True,
               name=f"tag {label}")


def frame(prs, title, kicker=None, kicker_color=MUTED, tags=(), dark=False):
    """Background, small section label (kicker), title and the TCP / UDP tags."""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = NIGHT if dark else PAPER
    if kicker:
        text(s, I(0.6), I(0.32), I(10), I(0.35), kicker.upper(), size=14, bold=True,
             color=kicker_color, name="kicker")
    if title:
        tw = 12.1 - (1.07 * len(tags) + 0.2 if tags else 0)
        text(s, I(0.6), I(0.62), I(tw), I(0.9), title, size=36, color=WHITE if dark else INK,
             font=HEAD, bold=True, anchor=MSO_ANCHOR.MIDDLE, name="title")
    x = W - I(0.6)
    for label in reversed(tags):
        x -= I(0.95)
        pill(s, x, I(0.62), label, TCP if label == "TCP" else UDP)
        x -= I(0.12)
    return s


def footers(prs):
    """'Maze Arena · TCP vs UDP' and 'n / N' on every slide but the first."""
    total = len(prs.slides)
    for n, s in enumerate(prs.slides, start=1):
        if n == 1:
            continue
        dark = s.background.fill.fore_color.rgb == NIGHT
        c = NIGHT_TEXT if dark else MUTED
        text(s, I(0.6), I(7.0), I(6), I(0.3), "Maze Arena · TCP vs UDP", size=12, color=c,
             name="footer")
        text(s, I(10.7), I(7.0), I(2.0), I(0.3), f"{n} / {total}", size=12, color=c,
             align=PP_ALIGN.RIGHT, name="page")


def notes(slide, body, qa=(), secs=None):
    body = body.strip().replace("[team]", team_names())
    for i, name in enumerate(TEAM, start=1):
        if not name.startswith("["):
            body = body.replace(f"[Presenter {i}]", f"[{name}]")
    lines = [" ".join(body.split()), ""]
    for q, a in qa:
        lines += [f"Likely question: {q}", f"Answer: {a}", ""]
    slide.notes_slide.notes_text_frame.text = "\n".join(lines).strip()
    if secs is not None:
        SECS[slide.slide_id] = secs


def cell(c, paras, size=20, color=INK, bold=False, fill=None, align=PP_ALIGN.LEFT):
    c.text_frame.word_wrap = True
    c.margin_left = c.margin_right = Inches(0.15)
    c.margin_top = c.margin_bottom = Inches(0.06)
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
    run = ch.chart_title.text_frame.paragraphs[0].runs[0]
    run.font.size = Pt(20)
    run.font.bold = True
    run.font.name = BODY
    run.font.color.rgb = INK
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(16)
    ch.legend.font.name = BODY
    ch.font.name = BODY
    ch.font.size = Pt(16)
    ch.font.color.rgb = MUTED
    plot = ch.plots[0]
    plot.gap_width = 60
    plot.overlap = -10
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format = fmt
    dl.number_format_is_linked = False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size = Pt(16)
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
    ca.tick_labels.font.size = Pt(16)
    ca.tick_labels.font.color.rgb = MUTED
    return gf


def game_picture(slide, x, y, w):
    """A real frame of the game, drawn by client_ui/render.py (slides/img/game.png)."""
    if GAME_PNG.exists():
        pic = slide.shapes.add_picture(str(GAME_PNG), x, y, width=w)
        pic.name = "game screenshot"
        return pic
    return box(slide, x, y, w, int(w / 1.6), "game screenshot missing", fill=NIGHT_2,
               color=WHITE)


def code_panel(slide, x, y, w, h, lines, size=20):
    """Dark panel with monospace lines; '\\n' is shown in gold."""
    paras = []
    for ln in lines:
        if isinstance(ln, list):
            paras.append(ln)
            continue
        runs = []
        for k, part in enumerate(ln.split("\\n")):
            if k:
                runs.append(("\\n", {"color": GOLD, "bold": True}))
            if part:
                runs.append((part, {}))
        paras.append(runs)
    return box(slide, x, y, w, h, paras, fill=NIGHT, size=size, color=WHITE, font=MONO,
               align=PP_ALIGN.LEFT, margin=0.3, space_after=6, name="code")


# ---------------------------------------------------------------- part 1: the game

def s_title(prs):
    s = frame(prs, None, dark=True)
    text(s, I(0.6), I(1.2), I(5.8), I(1.2), "Maze Arena", size=60, color=WHITE, font=HEAD,
         bold=True, name="title")
    text(s, I(0.6), I(2.45), I(5.6), I(1.3),
         "One multiplayer game, built twice: over TCP and over UDP", size=26, color=NIGHT_TEXT)
    text(s, I(0.6), I(4.2), I(5.6), I(0.9),
         [[("Team  ", {"bold": True, "color": GOLD}), (" · ".join(TEAM), {})]], size=20,
         color=WHITE)
    text(s, I(0.6), I(5.0), I(5.6), I(0.5), "Computer Networks project · live demo on 4 laptops",
         size=18, color=NIGHT_TEXT)
    game_picture(s, I(6.65), I(1.3), I(6.1))
    text(s, I(6.65), I(5.25), I(6.1), I(0.4), "A real frame of our game",
         size=14, color=NIGHT_TEXT)
    notes(s, """
[Presenter 1] Hello, we are [team]. This is Maze Arena: a multiplayer maze game for up to three
players. We built the same game twice, once over TCP and once over UDP, so that we could compare
the two protocols on exactly the same game. In the next twenty minutes we explain how both
versions work, we show them live on four laptops, and we show what we measured.
""")


def s_game(prs):
    s = frame(prs, "The game in 30 seconds", kicker="Part 1 · The game")
    game_picture(s, I(0.6), I(1.75), I(6.5))
    rules = [("Eat a dot", "+10 points"),
             ("Eat a power pellet (big dot)", "+50 points and 5 s of power"),
             ("Powered? Catch a rival", "they lose 50 points and restart"),
             ("60 seconds, up to 3 players", "the highest score wins")]
    points(s, I(7.55), I(1.85), I(5.2), rules, INK, gap=1.0, size=21)
    text(s, I(7.55), I(5.95), I(5.2), I(0.9),
         "Players only use the arrow keys. Everything else is decided by the server.",
         size=18, color=MUTED)
    notes(s, """
[Presenter 1] The game in thirty seconds. Each player is a Pac-Man. A small dot gives ten
points. A big power pellet gives fifty points and five seconds of power. While you have power,
touching another player sends them back to their start and costs them fifty points. A game lasts
sixty seconds and the highest score wins. On the right of the screen you see the scores, and
in the corner the network numbers we will talk about later.
""")


def s_arch(prs):
    s = frame(prs, "One server, three players", kicker="Part 1 · Design")
    box(s, I(0.6), I(1.75), I(7.4), I(1.15),
        [[("Server laptop", {"bold": True, "size": 24})], "runs the game, 10 times per second"],
        fill=NIGHT, color=WHITE, size=18)
    for k, name in enumerate(PLAYERS):
        x = 0.6 + k * 2.6
        cx = x + 1.1
        arrow(s, I(cx - 0.35), I(4.95), I(cx - 0.35), I(2.95), color=INK, width=2.5)
        arrow(s, I(cx + 0.35), I(2.95), I(cx + 0.35), I(4.95), color=MUTED, width=2.5)
        box(s, I(x), I(4.95), I(2.2), I(0.95),
            [[(name, {"bold": True, "color": PLAYER[name], "size": 22})], "laptop"],
            fill=WHITE, line=LINE, size=16, color=MUTED)
    text(s, I(0.6), I(6.1), I(7.6), I(0.8), [
        [("↑ INPUT  ", {"bold": True}), ("only a direction: UP, LEFT…", {})],
        [("↓ STATE  ", {"bold": True}), ("the whole game, 10 times per second", {})]],
        size=17, color=INK, space_after=2)
    text(s, I(8.6), I(1.8), I(4.1), I(0.5), "The golden rule", size=22, bold=True, color=INK)
    text(s, I(8.6), I(2.45), I(4.1), I(3.6), [
        "Players only send a key press.",
        "Only the server moves players and counts points.",
        "Everyone draws the same picture: nobody can cheat.",
    ], size=22, color=INK, space_after=18)
    notes(s, """
[Presenter 1] One laptop runs the server, three laptops are players. The golden rule: the
server decides everything. A player only sends a direction, called INPUT. Ten times per second
the server moves everybody, counts the points and sends the whole game, called STATE, to all
players. Players only draw what they receive. So all screens show the same game, and nobody
can cheat by changing the score on their own laptop.
""", [("Why send the whole game instead of only the changes?",
       "If one STATE is lost, the next one is complete again, so UDP can simply skip a lost one.")])


def s_shared(prs):
    s = frame(prs, "Same game, only the transport changes", kicker="Part 1 · Design")
    box(s, I(0.6), I(1.8), I(12.1), I(1.45), [
        [("common/", {"bold": True, "font": MONO, "size": 24}),
         ("   written once, used by both versions", {"bold": True})],
        "game rules  ·  lobby and rooms  ·  game loop at 10 ticks/s  ·  message format"],
        fill=WHITE, line=INK, size=21, line_w=2)
    for k, (name, color, line) in enumerate((
            ("tcp/", TCP, "connections and a byte stream; 2 threads per player"),
            ("udp/", UDP, "one socket, separate packets, our own resend layer"))):
        x = 0.6 + k * 6.2
        arrow(s, I(x + 2.95), I(3.25), I(x + 2.95), I(3.95), color=MUTED, width=2.5)
        box(s, I(x), I(3.95), I(5.9), I(1.5),
            [[(name, {"bold": True, "font": MONO, "size": 26})], line],
            fill=color, color=WHITE, size=19)
    text(s, I(0.6), I(5.85), I(12.1), I(0.9),
         "So any difference we measure comes from the network, not from the game.",
         size=24, bold=True, color=INK)
    notes(s, """
[Presenter 1] To compare fairly, everything that is not networking is written once, in the
common folder: the rules, the lobby and rooms, the game loop and the message format. The TCP
folder and the UDP folder only move bytes. One test even checks that both versions deliver
exactly the same messages. So any difference you see today comes from the network, not from the
game. Now [Presenter 2] presents the TCP version.
""", [("How do you know both versions behave the same?",
       "A parity test plays the same session on TCP and UDP and checks that the messages are "
       "identical; 118 automated tests in total.")])


# ---------------------------------------------------------------- part 2 and 3: TCP, UDP

def s_tcp(prs):
    s = frame(prs, "TCP: one connection per player", kicker="Part 2 · TCP", kicker_color=TCP,
              tags=("TCP",))
    box(s, I(0.6), I(1.8), I(3.0), I(0.95),
        [[("listening socket", {"bold": True})], f"port {TCP_PORT}"], fill=TCP, color=WHITE, size=18)
    arrow(s, I(3.6), I(2.27), I(4.2), I(2.27), color=TCP, width=2.5)
    box(s, I(4.2), I(1.8), I(2.9), I(0.95),
        [[("accept()", {"bold": True, "font": MONO})], "a new socket per player"],
        fill=WHITE, line=TCP, size=18)
    for k, name in enumerate(PLAYERS):
        y = I(3.15 + k * 0.85)
        box(s, I(0.6), y, I(2.6), I(0.7), [[(name, {"bold": True, "color": PLAYER[name]}),
                                            (" connection", {})]],
            fill=WHITE, line=TCP, size=18)
        box(s, I(3.35), y, I(1.8), I(0.7), "reader", fill=TCP_LIGHT, size=18)
        box(s, I(5.3), y, I(1.8), I(0.7), "writer", fill=TCP_LIGHT, size=18)
    text(s, I(0.6), I(5.8), I(6.5), I(0.5), "+ one game thread per room", size=18, color=MUTED)
    points(s, I(7.75), I(1.85), I(5.0), [
        ("Like a phone call:", "connect first, then talk."),
        ("TCP resends lost data", "and keeps everything in order for us."),
        ("Each player has a reader and a writer,", "so one slow player never blocks the others."),
    ], TCP, gap=1.35, size=21)
    notes(s, f"""
[Presenter 2] TCP works like a phone call: you connect first, then you talk. The server opens a
listening socket on port {TCP_PORT}. For each player, accept gives a new socket, just for that
player, and we start two threads: a reader that receives and a writer that sends from a queue.
So one slow player never blocks the others. TCP does a lot for us: it resends lost data and
keeps everything in order.
""", [("Why a writer thread and not just send()?",
       "send() can block if a client is slow; with a queue per client the game thread never waits."),
      ("Why TCP_NODELAY?",
       "Without it TCP may hold small messages to group them, which delays our 10 STATEs per second.")])


def s_stream(prs):
    s = frame(prs, "TCP delivers bytes, not messages", kicker="Part 2 · TCP", kicker_color=TCP,
              tags=("TCP",))
    code_panel(s, I(0.6), I(1.8), I(6.9), I(3.6), [
        [("What one recv() can return:", {"font": BODY, "size": 17, "color": NIGHT_TEXT})],
        [("recv #1", {"font": BODY, "size": 15, "color": NIGHT_TEXT})],
        '{"type":"INPUT","dir":"UP"}\\n{"type":"PI',
        [("recv #2", {"font": BODY, "size": 15, "color": NIGHT_TEXT})],
        'NG","t":12.5}\\n',
        [("→ cut at each \\n:  INPUT, then PING", {"font": BODY, "bold": True, "color": GOLD})],
    ], size=20)
    text(s, I(8.0), I(1.8), I(4.7), I(4.6), [
        [("The problem", {"bold": True, "color": TCP})],
        "One recv() can give half a message, or three messages at once.",
        [("Our fix", {"bold": True, "color": TCP})],
        "One JSON message per line, ending in \\n. We keep a buffer and cut at each \\n.",
        [("Tested", {"bold": True, "color": TCP})],
        "split messages, merged messages, one byte at a time.",
    ], size=21, space_after=8)
    notes(s, """
[Presenter 2] The tricky part of TCP: it delivers a stream of bytes, not messages. One recv can
return half a message, or three messages glued together. Here the first recv ends in the middle
of the word PING. Our fix: every message is one line of JSON ending with a newline. We keep a
buffer and only cut at newlines. We tested messages split in two, merged, and even one byte at
a time.
""")


def s_udp(prs):
    s = frame(prs, "UDP: one socket for everyone", kicker="Part 3 · UDP", kicker_color=UDP,
              tags=("UDP",))
    box(s, I(0.6), I(1.8), I(5.9), I(0.95),
        [[("one socket", {"bold": True}), (f"  ·  port {UDP_PORT}", {})],
         "reads every packet in one loop"], fill=UDP, color=WHITE, size=18)
    tbl = table(s, I(0.6), I(3.0), I(5.9), [I(3.3), I(2.6)], [I(0.55)] * 4, "who is it")
    cell(tbl.cell(0, 0), "sender's address", 18, WHITE, True, UDP)
    cell(tbl.cell(0, 1), "player", 18, WHITE, True, UDP)
    for k, (addr, name) in enumerate(zip(("100.109.204.11 : 50311", "100.92.17.40 : 61002",
                                          "100.71.8.25 : 53877"), PLAYERS), start=1):
        cell(tbl.cell(k, 0), addr, 18, INK, False, WHITE)
        cell(tbl.cell(k, 1), [[(name, {"bold": True, "color": PLAYER[name]})]], 18, INK, False,
             WHITE)
    text(s, I(0.6), I(5.4), I(5.9), I(0.5), "The address on each packet tells us who sent it (here Tailscale addresses).",
         size=18, color=MUTED)
    points(s, I(7.2), I(1.85), I(5.5), [
        ("Like postcards:", "no connection, each packet travels alone."),
        ("One packet = one message,", "so no cutting is needed."),
        ("But packets can be lost,", "arrive twice, or arrive out of order."),
    ], UDP, gap=1.35, size=21)
    notes(s, """
[Presenter 2] UDP works like sending postcards: there is no connection, every packet travels
alone. The server has one single socket for all players and reads it in one loop. Each packet
carries the sender's address, so we keep a table from address to player. One packet is one
message, so no cutting is needed. But nothing is guaranteed: a packet can be lost, arrive twice,
or arrive out of order. That is our job now.
""")


def s_reliable(prs):
    s = frame(prs, "Lost packets: we built our own safety net", kicker="Part 3 · UDP",
              kicker_color=UDP, tags=("UDP",))
    cx, sx = 1.6, 6.0
    text(s, I(cx - 0.8), I(1.75), I(1.6), I(0.4), "player", size=18, bold=True,
         align=PP_ALIGN.CENTER)
    text(s, I(sx - 0.8), I(1.75), I(1.6), I(0.4), "server", size=18, bold=True,
         align=PP_ALIGN.CENTER)
    arrow(s, I(cx), I(2.2), I(cx), I(5.6), color=LINE, width=2, head=False)
    arrow(s, I(sx), I(2.2), I(sx), I(5.6), color=LINE, width=2, head=False)
    arrow(s, I(cx), I(2.75), I(cx + 2.4), I(3.05), color=UDP, width=2.5, head=False)
    text(s, I(cx + 2.3), I(2.72), I(0.5), I(0.5), "✕", size=28, color=LOST, bold=True)
    text(s, I(cx + 0.15), I(2.3), I(4), I(0.4), "JOIN #7   lost", size=18)
    text(s, I(0.2), I(3.7), I(1.25), I(0.4), "+200 ms", size=17, bold=True, color=MUTED,
         align=PP_ALIGN.RIGHT)
    arrow(s, I(cx), I(3.85), I(sx), I(4.35), color=UDP, width=2.5)
    text(s, I(cx + 0.15), I(3.4), I(4), I(0.4), "JOIN #7   sent again", size=18)
    arrow(s, I(sx), I(4.85), I(cx), I(5.35), color=UDP, width=2.5)
    text(s, I(cx + 1.5), I(4.6), I(2.5), I(0.4), "ACK 7 = got it", size=18, bold=True)
    points(s, I(7.0), I(1.85), I(5.7), [
        ("Number", "each important message (#7)."),
        ("The receiver answers", "ACK 7."),
        ("No ACK after 200 ms?", "Send it again, up to 15 times."),
        ("Arrived twice?", "The copy is ignored. Order is kept."),
    ], UDP, gap=1.05, size=20)
    text(s, I(0.6), I(6.05), I(12.1), I(0.5),
         "Tested at 30 % loss: every important message arrived exactly once, in order.",
         size=18, color=MUTED)
    notes(s, """
[Presenter 2] So we built our own safety net. Every important message gets a number, here
JOIN number 7. The receiver answers ACK 7: got it. If no ACK comes back within 200
milliseconds, the sender sends it again, up to fifteen times. If a copy arrives twice, the
receiver sees the same number and ignores it, and messages are delivered in order. Our tests
at 30 percent loss check that every important message arrives exactly once and in order.
""", [("What if the ACK is lost instead?",
       "The sender resends; the receiver sees #7 again, ignores the copy and ACKs again."),
      ("What if all 15 resends fail?",
       "The message is given up and the 4 s heartbeat removes that player. At 30 % loss, 0 were "
       "given up.")])


def s_split(prs):
    s = frame(prs, "Not every message has to arrive", kicker="Part 3 · UDP", kicker_color=UDP,
              tags=("UDP",))
    cards = [("Must arrive → sent reliably",
              ["LOGIN, rooms, READY", "GAME_START, GAME_OVER", "PLAYER_LEFT"],
              "Missing one would break the game."),
             ("Can be skipped → sent once",
              ["STATE: the picture, 10× per second", "INPUT: your direction", "PING: are you there?"],
              "A new STATE comes 100 ms later. Resending an old one only adds delay.")]
    for k, (head, items, foot) in enumerate(cards):
        x = I(0.6 + k * 6.2)
        box(s, x, I(1.8), I(5.9), I(3.85), "", fill=WHITE if k == 0 else UDP_LIGHT, line=UDP,
            line_w=2)
        text(s, x + I(0.35), I(2.0), I(5.3), I(0.5), head, size=24, bold=True, color=UDP)
        text(s, x + I(0.35), I(2.75), I(5.3), I(1.8), items, size=21, color=INK, space_after=8)
        text(s, x + I(0.35), I(4.55), I(5.3), I(1.0), foot, size=18, color=MUTED)
    text(s, I(0.6), I(5.95), I(12.1), I(0.6),
         "This is the key difference with TCP, which resends everything.", size=22, bold=True)
    notes(s, """
[Presenter 2] The key idea of our UDP version: not every message has to arrive. Lobby messages
and game events must arrive, so they use our safety net. But STATE, the picture of the game, is
sent ten times per second. If one is lost, the next one arrives 100 milliseconds later and is
complete. Resending the old one would only add delay. So STATE, INPUT and PING are sent once
and never resent. TCP cannot make this choice: it resends everything.
""")


def s_vanish(prs, rows):
    tcp_d = span([num(rows, "tcp", l, "detect_ms") for l in LOSSES])
    udp_d = span([num(rows, "udp", l, "detect_ms") for l in LOSSES], seconds=True)
    s = frame(prs, "When a player disappears", kicker="Part 3 · TCP vs UDP", tags=("TCP", "UDP"))
    rh = [I(0.6), I(1.15), I(1.15), I(0.85)]
    tbl = table(s, I(0.6), I(1.8), I(12.1), [I(2.9), I(4.6), I(4.6)], rh, "disconnections")
    cell(tbl.cell(0, 0), "", 20, INK, True, None)
    cell(tbl.cell(0, 1), "TCP", 22, WHITE, True, TCP, PP_ALIGN.CENTER)
    cell(tbl.cell(0, 2), "UDP", 22, WHITE, True, UDP, PP_ALIGN.CENTER)
    body = [
        ("The program crashes",
         [[("Its OS closes the connection → noticed in ", {}), (tcp_d, {"bold": True})]],
         [[("Nothing is sent → noticed after 4 s of silence: ", {}), (udp_d, {"bold": True})]]),
        ("Wi-Fi off or frozen laptop",
         "Nothing arrives → our heartbeat drops the player after 5 s",
         "Same: 4 s of silence"),
        ("Then", f"the others see “{CRASHED} left”, the game goes on", None),
    ]
    for k, (label, t, u) in enumerate(body, start=1):
        cell(tbl.cell(k, 0), label, 20, INK, True, WHITE)
        cell(tbl.cell(k, 1), t, 20, INK, False, TCP_LIGHT if u else WHITE,
             PP_ALIGN.LEFT if u else PP_ALIGN.CENTER)
        if u is None:
            tbl.cell(k, 1).merge(tbl.cell(k, 2))
        else:
            cell(tbl.cell(k, 2), u, 20, INK, False, UDP_LIGHT)
    text(s, I(0.6), I(5.85), I(12.1), I(0.9), [
        [("Heartbeat: ", {"bold": True}), ("every player sends a PING each second. ", {}),
         ("No message for 5 s (TCP) or 4 s (UDP) = gone.", {})]], size=19, color=MUTED)
    notes(s, f"""
[Presenter 2] Last design question: what if a player disappears? If the game program crashes on
a TCP laptop, its operating system closes the connection for it, so the server knows almost
immediately: we measured {tcp_d}. With UDP there is no connection to close, so the only signal
is silence: after 4 seconds without any packet, the player is removed. If the Wi-Fi goes off,
even TCP gets nothing, so we added a heartbeat: every player sends a PING each second. In every
case the others see that the player left, and the game goes on. Now [Presenter 3] shows all of
this live.
""", [("Why not a shorter UDP timeout?",
       "At 30 % loss several PINGs in a row can be lost; 4 s avoids kicking players who are still "
       "there.")])


# ---------------------------------------------------------------- part 4: live demo

DEMO_SECS = (150, 150, 140)


def client_cmd(proto, name, port):
    return (f"python -m client_ui.ui --proto {proto} --host {SERVER_IP} --port {port} "
            f"--name {name} --room demo")


def s_demo_plan(prs):
    s = frame(prs, "Live demo: 3 tests on 4 laptops", kicker="Part 4 · Live demo",
              kicker_color=GOLD, dark=True)
    games = [("TEST 1", "TCP", "A normal game, then a crash", "crash noticed at once"),
             ("TEST 2", "UDP", "The same game, then a crash", "crash noticed after 4 s"),
             ("TEST 3", "UDP", "30 % of packets thrown away", "the game keeps going")]
    cw, gap = 3.9, 0.2
    for k, (g, proto, title, result) in enumerate(games):
        x = I(0.6 + k * (cw + gap))
        color = TCP if proto == "TCP" else UDP
        box(s, x, I(1.8), I(cw), I(2.2), "", fill=NIGHT_2, line=color, line_w=2)
        text(s, x + I(0.25), I(1.98), I(1.4), I(0.4), g, size=16, bold=True, color=GOLD)
        box(s, x + I(cw - 1.05), I(1.95), I(0.8), I(0.38), proto, fill=color, size=14,
            color=WHITE, bold=True)
        text(s, x + I(0.25), I(2.5), I(cw - 0.5), I(0.9), title, size=22, bold=True, color=WHITE)
        text(s, x + I(0.25), I(3.4), I(cw - 0.5), I(0.5), result, size=18, color=NIGHT_TEXT)
    text(s, I(0.6), I(4.3), I(12.1), I(1.7), [
        [("Server: ", {"bold": True, "color": GOLD}),
         (f"{first(4)}'s PC, Tailscale address {SERVER_IP} · TCP port {TCP_PORT}, "
          f"UDP port {UDP_PORT} · server log and Wireshark on the projector", {})],
        [("Players: ", {"bold": True, "color": GOLD}), ("  ·  ".join(PLAYERS), {}),
         ("  (one laptop each, logged in with their own name)", {})],
        [("Network: ", {"bold": True, "color": GOLD}),
         ("all 4 laptops in one Tailscale network, so it works even if the Wi-Fi isolates laptops",
          {})],
    ], size=19, color=WHITE, space_after=8)
    text(s, I(0.6), I(6.2), I(12.1), I(0.5),
         "Each test: what we do → what you should see. One protocol at a time; the previous "
         "server is stopped first.", size=17, color=NIGHT_TEXT)
    notes(s, f"""
[Presenter 3] Now the live demo: three short tests. For each one the slide says what we do and
what you should see, so you can check it with us. Test 1 is a normal TCP game where we crash a
player. Test 2 is the same over UDP. Test 3 throws away thirty percent of the packets.
[Presenter 4] runs the server PC; its log and Wireshark are on the projector, so you see every
event with its time. The four laptops are in one Tailscale network: a private network on top of
the Wi-Fi, so it works even when the Wi-Fi blocks laptops from talking to each other.
""", [("Does Tailscale change the results?",
       "It wraps every packet, TCP or UDP, in an encrypted WireGuard UDP packet, so the path adds "
       "a few ms. Inside, our TCP is still TCP and our UDP is still UDP; our 1.2 KB STATE fits "
       "Tailscale's 1280-byte MTU.")], secs=45)


def s_wireshark(prs):
    s = frame(prs, "What Wireshark shows", kicker="Live demo · Wireshark", kicker_color=GOLD,
              tags=("TCP", "UDP"), dark=True)
    cols = [("TCP", TCP, f"tcp.port == {TCP_PORT}", [
                ("SYN, SYN-ACK, ACK", "when a player connects: the handshake"),
                ("Our JSON lines", "inside the segments (Follow → TCP Stream)"),
                ("FIN (or RST)", f"when {CRASHED}'s game is killed"),
                ("TCP's own ACKs", "added by the OS: tcp.analysis.ack_rtt")]),
            ("UDP", UDP, f"udp.port == {UDP_PORT}", [
                ("No handshake", "the first packet is already LOGIN"),
                ("1 datagram = 1 message", "one JSON object per packet"),
                ("Our own ACKs", '{"type":"ACK","ack":7}: written by us, not the OS'),
                ('udp contains "rel"', "the important messages; a resend repeats its seq")])]
    for k, (proto, color, flt, items) in enumerate(cols):
        x = I(0.6 + k * 6.2)
        box(s, x, I(1.8), I(5.9), I(4.15), "", fill=NIGHT_2, line=color, line_w=2)
        text(s, x + I(0.3), I(1.95), I(1.2), I(0.5), proto, size=24, bold=True, color=color)
        text(s, x + I(1.5), I(2.02), I(4.2), I(0.45), flt, size=17, color=GOLD, font=MONO)
        text(s, x + I(0.3), I(2.65), I(5.3), I(3.2),
             [[(head + "  ", {"bold": True}), (body, {"color": NIGHT_TEXT})] for head, body in items],
             size=18, color=WHITE, space_after=12)
    text(s, I(0.6), I(6.2), I(12.1), I(0.5),
         "Capture on the server's Tailscale interface: on the Wi-Fi interface you would only see "
         "encrypted WireGuard packets.", size=16, color=NIGHT_TEXT)
    notes(s, f"""
[Presenter 3] During the tests Wireshark runs on the server. With TCP you will see the
handshake, SYN, SYN-ACK, ACK, when a player connects, our JSON lines inside the stream, and a FIN
when we crash {CRASHED}'s game. TCP's acknowledgements are added by the operating system. With UDP
there is no handshake at all: the very first packet is already the LOGIN. Each datagram is one
message, and the ACKs you see are our own messages, written by our code. We capture on the
Tailscale interface, because on the Wi-Fi everything is encrypted.
""", [("Why do you see FIN and not RST, or the other way round?",
       "When a program dies the OS closes its socket: FIN if nothing was left unread, RST if data "
       "was still waiting. Our server treats both as 'player left'.")], secs=50)


def demo_slide(prs, n, proto, title, rows, proves, command, note, secs):
    """One live test: a table 'what we do → what you should see', what it proves, the commands."""
    color = TCP if proto == "TCP" else UDP
    s = frame(prs, title, kicker=f"Live demo · Test {n} · {proto}", kicker_color=GOLD,
              tags=(proto,), dark=True)
    rh = [I(0.5)] + [I(0.78)] * len(rows)
    tbl = table(s, I(0.6), I(1.75), I(12.1), [I(0.6), I(5.3), I(6.2)], rh, f"test {n}")
    cell(tbl.cell(0, 0), "#", 17, WHITE, True, color, PP_ALIGN.CENTER)
    cell(tbl.cell(0, 1), "What we do", 17, WHITE, True, color)
    cell(tbl.cell(0, 2), "What you should see", 17, WHITE, True, color)
    for k, (try_, expect) in enumerate(rows, start=1):
        cell(tbl.cell(k, 0), str(k), 19, GOLD, True, NIGHT_2, PP_ALIGN.CENTER)
        cell(tbl.cell(k, 1), try_, 18, WHITE, False, NIGHT_2)
        cell(tbl.cell(k, 2), expect, 18, WHITE, False, NIGHT)
    y = 1.75 + 0.5 + 0.78 * len(rows) + 0.2
    box(s, I(0.6), I(y), I(12.1), I(0.6),
        [[("This proves: ", {"bold": True, "color": GOLD}), (proves, {})]],
        fill=NIGHT_2, line=GOLD, size=19, color=WHITE, align=PP_ALIGN.LEFT, margin=0.25,
        line_w=1.5)
    text(s, I(0.6), I(6.3), I(12.1), I(0.6), command.split("\n"), size=12, color=NIGHT_TEXT,
         font=MONO, space_after=0)
    notes(s, note, secs=secs)
    return s


def s_demos(prs):
    p1, p2 = PLAYERS[0], PLAYERS[1]
    crash = f"At 0:40 left, {CRASHED} closes the terminal that runs the game (no goodbye)"
    demo_slide(
        prs, 1, "TCP", "TCP: a normal game, then a crash",
        [(f"{CRASHED} first logs in as “{p1}” while {p1} is already in",
          f"Refused: “name already taken”. {CRASHED} starts again with the right name"),
         (f"All three join room demo and press R",
          f"Same maze and scores on 3 screens; RTT of a few ms; log: 3 CONNECT lines, 3 addresses"),
         (crash, f"Log, same second: PLAYER_LEFT {CRASHED} (FIN); Wireshark: FIN"),
         (f"{p1} and {p2} play to 0:00", "Same ranking on both screens; GAME_OVER in the log")],
        f"TCP works across laptops, and a crash is seen at once: {CRASHED}'s OS closes the connection.",
        f"server: python -m tcp.server --host {SERVER_IP} --port {TCP_PORT}\n"
        f"players: {client_cmd('tcp', p1, TCP_PORT)}",
        f"""[Presenter 3] Test 1, TCP. [Presenter 4] starts the TCP server. First {CRASHED} tries to log
        in as {p1}, who is already in: refused, the name is taken; the server checks it. Then the
        three of us join room demo and press R. Look at the log: three connections from three
        different addresses, and in Wireshark the handshake for each one. Same maze, same scores on
        every screen, and a round trip of a few milliseconds in the corner. At forty seconds left
        {CRASHED} closes the terminal of the game, with no goodbye. The log shows {CRASHED} left in
        the same second, and Wireshark shows the FIN: {CRASHED}'s operating system closed the TCP
        connection. {p1} and {p2} play on and get the same ranking.""", DEMO_SECS[0])
    demo_slide(
        prs, 2, "UDP", "UDP: the same game, then a crash",
        [(f"Stop the TCP server; start the UDP server on port {UDP_PORT}; all three join, press R",
          "Log: “NEW PEER”, not “CONNECT”; corner: lost 0 % of updates"),
         (f"Wireshark: udp.port == {UDP_PORT}",
          "No handshake: the first packet is LOGIN; our own ACK messages"),
         (crash, f"Nothing at first… about 4 s later: PLAYER_LEFT {CRASHED} (heartbeat timeout)"),
         (f"{p1} and {p2} play to 0:00", "Same ranking on both screens")],
        "UDP has no connection to close: silence is the only signal, so it takes 4 s.",
        f"server: python -m udp.server --host {SERVER_IP} --port {UDP_PORT}\n"
        f"players: {client_cmd('udp', p1, UDP_PORT)}",
        f"""[Presenter 3] Test 2, the same game over UDP, on port {UDP_PORT}. The log now says NEW PEER
        instead of CONNECT: there is no connection, the server just sees packets from a new
        address. In Wireshark there is no handshake: the first packet is already the LOGIN, and the
        ACKs are our own messages. The corner shows zero percent of updates lost. At forty seconds
        left {CRASHED} closes the terminal again. This time nothing happens at first: there is no
        connection to close. Count with me: after about four seconds of silence, the server
        removes {CRASHED}.""", DEMO_SECS[1])
    demo_slide(
        prs, 3, "UDP", "UDP with 30 % of packets lost",
        [("Stop the server; restart it with --drop 0.3; the players restart their game",
          "Log: drop=30%: the server throws away 30 % of what it sends"),
         ("Log in, join, press R",
          "Still works, maybe after a short pause; RETRANSMIT lines in the log"),
         ("Play the whole game",
          "Corner: lost about 30 % of updates. Moves jump but never stop; nobody is kicked"),
         ("At GAME_OVER, before anyone closes, Ctrl-C on the server",
          "reliability stats: dropped ≈ 30 % of sent, retransmissions\u00a0>\u00a00, "
          "gave_up\u00a00")],
        "our safety net saves the important messages, and skipping old pictures keeps the game live.",
        f"server: python -m udp.server --host {SERVER_IP} --port {UDP_PORT} --drop 0.3 "
        f"--log-level DEBUG\nplayers: the same command as test 2",
        f"""[Presenter 3] Test 3: the server now throws away thirty percent of everything it sends, on
        purpose. Logging in, joining and ready still work, maybe after a short pause: these
        messages use our safety net, and you can see the RETRANSMIT lines in the log. During the
        game the corner shows about thirty percent of updates lost. The players jump a bit, but the
        game never stops and nobody is kicked, because we never wait for an old picture. At the
        end [Presenter 4] stops the server: the statistics show about thirty percent dropped, the
        resends, and zero messages given up.""", DEMO_SECS[2])
    extras(prs)


def extras(prs):
    s = frame(prs, "If we have time", kicker="Live demo · Extra", kicker_color=GOLD, dark=True)
    extras = [("Wi-Fi off during a TCP game", TCP,
               f"{CRASHED} turns the Wi-Fi off and leaves the game open.",
               "Watch: no FIN this time, so TCP alone would wait for minutes. Our heartbeat "
               f"drops {CRASHED} after 5 s; {CRASHED}'s window says “server silent”."),
              ("Log in again too fast on UDP", UDP,
               f"{CRASHED} kills the UDP game and starts it again at once (second terminal ready).",
               "Watch: refused, “name already taken”, for about 4 s: the server still thinks the "
               "old player is there.")]
    for k, (head, color, do, watch) in enumerate(extras):
        x = I(0.6 + k * 6.2)
        box(s, x, I(1.8), I(5.9), I(4.0), "", fill=NIGHT_2, line=color, line_w=2)
        text(s, x + I(0.35), I(2.0), I(5.2), I(0.5), head, size=24, bold=True, color=color)
        text(s, x + I(0.35), I(2.75), I(5.2), I(3.0), [do, watch], size=20, color=WHITE,
             space_after=14)
    text(s, I(0.6), I(6.1), I(12.1), I(0.6),
         "Turn the Wi-Fi back on afterwards: Tailscale reconnects by itself.", size=16,
         color=NIGHT_TEXT)
    notes(s, f"""
[Presenter 3] Only if we are ahead of time. First, {CRASHED} turns the Wi-Fi off during a TCP game.
Nothing crashed, so no FIN is sent: TCP alone would wait for minutes, but our heartbeat drops
{CRASHED} after five seconds. Second, on UDP, if {CRASHED} logs in again right after a crash, the name is
still taken for about four seconds. Otherwise we skip this slide.
""", secs=0)


# ---------------------------------------------------------------- part 5: TCP vs UDP

def compare_table(s, rows, name, size=19, row_h=0.66, first_w=2.9):
    """Topic | TCP | UDP table on paper; rows: (topic, tcp, udp), udp None = same on both."""
    rest = (12.1 - first_w) / 2
    tbl = table(s, I(0.6), I(1.75), I(12.1), [I(first_w), I(rest), I(rest)],
                [I(0.55)] + [I(row_h)] * len(rows), name)
    cell(tbl.cell(0, 0), "", size, INK, True, None)
    cell(tbl.cell(0, 1), "TCP", 21, WHITE, True, TCP, PP_ALIGN.CENTER)
    cell(tbl.cell(0, 2), "UDP", 21, WHITE, True, UDP, PP_ALIGN.CENTER)
    for k, (topic, t, u) in enumerate(rows, start=1):
        cell(tbl.cell(k, 0), topic, size, INK, True, WHITE)
        if u is None:       # the same on both: one cell across TCP and UDP
            tbl.cell(k, 1).merge(tbl.cell(k, 2))
            cell(tbl.cell(k, 1), t, size, INK, False, WHITE, PP_ALIGN.CENTER)
            continue
        cell(tbl.cell(k, 1), t, size, INK, False, TCP_LIGHT)
        cell(tbl.cell(k, 2), u, size, INK, False, UDP_LIGHT)
    return tbl


def s_differences(prs):
    s = frame(prs, "TCP vs UDP: how they differ", kicker="Part 5 · TCP vs UDP",
              tags=("TCP", "UDP"))
    compare_table(s, [
        ("Connection", "Handshake first, like a phone call", "None: each packet travels alone"),
        ("Messages", "A stream of bytes: we add \\n to separate them", "1 packet = 1 message"),
        ("Lost packet", "The OS resends it; everything behind it waits",
         "Gone. We resend only the important ones"),
        ("Order", "Always in order", "Not guaranteed: we number the important ones"),
        ("Header", "20 bytes per segment", "8 bytes per packet"),
    ], "how they differ")
    text(s, I(0.6), I(6.1), I(12.1), I(0.6),
         "TCP gives us reliability for free; with UDP we choose what is worth resending.",
         size=21, bold=True)
    notes(s, """
[Presenter 1] Now that you have seen both versions live, let's put the differences side by side.
TCP opens a connection first, like a phone call; UDP just sends packets that travel alone. TCP
delivers a stream of bytes, so we had to separate messages with a newline; with UDP one packet is
one message. When a TCP packet is lost, the operating system resends it and everything behind it
waits. A lost UDP packet is simply gone, so we resend only the important ones. TCP keeps the
order; with UDP we number the important messages ourselves. UDP is also lighter: 8 bytes of
header instead of 20. In short: TCP gives us reliability for free, with UDP we choose what is
worth resending.
""", [("Is UDP faster than TCP?",
       "Without loss, no: both had about 0.9 ms round trip on one machine. The difference appears "
       "when packets are lost: TCP waits, UDP does not.")])


def s_seen(prs, rows):
    tcp_d = span([num(rows, "tcp", l, "detect_ms") for l in LOSSES])
    t30 = num(rows, "tcp", 30, "rtt_mean_ms")
    s = frame(prs, "What the demo showed", kicker="Part 5 · TCP vs UDP", tags=("TCP", "UDP"))
    compare_table(s, [
        ("In Wireshark", "SYN, SYN-ACK, ACK first; a FIN at the crash",
         "No handshake: LOGIN is the first packet; the ACKs are ours"),
        ("A player crashes", f"Noticed in the same second ({tcp_d}): the OS closes the connection",
         "Noticed after 4 s of silence"),
        ("30 % of packets lost", f"Measured: nothing lost, but it freezes (round trip {ms(t30)})",
         "Live: about 30 % of updates skipped, the game never stops"),
        ("Who resends?", "The OS: every byte, in order", "Our code: only the important messages"),
        ("Rules, scores, results", "Identical on both: the same server code", None),
    ], "what the demo showed", size=18, row_h=0.72, first_w=3.0)
    text(s, I(0.6), I(6.2), I(12.1), I(0.6),
         "The game is the same; only the behaviour of the network changes.", size=21, bold=True)
    notes(s, f"""
[Presenter 1] And this is what you just saw. In Wireshark, TCP starts with a handshake and ends
with a FIN; UDP has no handshake, the first packet is already the login, and the ACKs are
messages we wrote ourselves. When a player crashed, TCP knew in the same second, because the
operating system closed the connection; UDP needed four seconds of silence. With thirty percent
loss, UDP skipped about a third of the updates but never stopped. TCP, in our measurements,
loses nothing but freezes, with a round trip of {ms(t30)}, because the operating system resends
every byte in order. Everything else, the rules, the scores, the results, is identical, because
both use the same server code. [Presenter 4] concludes.
""", [("Why didn't you show TCP with 30 % loss live?",
       "TCP needs real lost segments, made by the operating system's firewall with admin rights on "
       "the server PC; we measured it on one Mac instead (backup slides).")])


# ---------------------------------------------------------------- part 6: results

HOW = ("How we measured: 3 bots, 120 s games on one Mac, loss added on purpose "
       "(TCP: by the kernel, UDP: by our --drop option).")
BACKUP = set()   # slide ids of the backup slides: not timed, shown only for questions


def s_rtt(prs, rows):
    s = frame(prs, "Under loss, TCP waits and UDP doesn't", kicker="Backup · Measured",
              tags=("TCP", "UDP"))
    tv = [num(rows, "tcp", l, "rtt_mean_ms") for l in LOSSES]
    uv = [num(rows, "udp", l, "rtt_mean_ms") for l in LOSSES]
    bar_chart(s, I(0.6), I(1.7), I(7.4), I(4.4), "Round-trip time (ms)", tv, uv, '0.0;;0',
              "chart rtt")
    t30, u30 = tv[2], uv[2]
    for k, (val, color, label) in enumerate(((t30, TCP, "TCP round trip at 30 % loss"),
                                             (u30, UDP, "UDP round trip at 30 % loss"))):
        y = I(1.8 + k * 1.55)
        text(s, I(8.5), y, I(4.2), I(0.9), ms(val, 0 if (val or 0) >= 10 else 1), size=54,
             bold=True, color=color, font=HEAD)
        text(s, I(8.5), y + I(0.9), I(4.2), I(0.4), label, size=18, color=MUTED)
    text(s, I(8.5), I(4.95), I(4.2), I(1.3),
         "One lost TCP packet holds back everything behind it: head-of-line blocking.",
         size=19, color=INK)
    text(s, I(0.6), I(6.3), I(12.1), I(0.5), HOW, size=14, color=MUTED)
    notes(s, f"""
[Presenter 4] Now our measurements. We ran three bots for two minutes, with zero, ten and thirty
percent of packets lost on purpose. This chart is the round-trip time. Without loss both are
under one millisecond. With loss, TCP waits: when one packet is lost, everything behind it waits
until it is resent. That is called head-of-line blocking. At thirty percent loss TCP needs
{ms(t30)}; UDP stays at {ms(u30, 1)}, because it never waits.
""", [("Why is the loss made differently for TCP?",
       "TCP must see real lost segments to resend them, so the kernel drops them; our --drop "
       "option only exists in the UDP code. Same rates, different method."),
      ("Why measure on one Mac?",
       "It removes Wi-Fi noise, so the only difference is the loss we add on purpose.")])


def s_lost(prs, rows):
    s = frame(prs, "UDP skips lost updates, TCP freezes", kicker="Backup · Measured",
              tags=("TCP", "UDP"))
    lost_t = [num(rows, "tcp", l, "states_missing_pct") for l in LOSSES]
    lost_u = [num(rows, "udp", l, "states_missing_pct") for l in LOSSES]
    fr_t = [num(rows, "tcp", l, "freezes_over_250ms") for l in LOSSES]
    fr_u = [num(rows, "udp", l, "freezes_over_250ms") for l in LOSSES]
    bar_chart(s, I(0.6), I(1.7), I(5.9), I(3.9), "Updates (STATEs) lost, %", lost_t, lost_u,
              '0.0;;0', "chart lost")
    bar_chart(s, I(6.8), I(1.7), I(5.9), I(3.9), "Freezes over 250 ms, per game", fr_t, fr_u, '0',
              "chart freezes")
    if None in (lost_u[2], fr_t[2], fr_u[2]):
        take = f"At 30 % loss: {LIVE}."
    else:
        take = (f"At 30 % loss UDP skips {lost_u[2]:.0f} % of updates but freezes less: "
                f"{fr_u[2]:.0f} vs {fr_t[2]:.0f} times per game.")
    text(s, I(0.6), I(5.8), I(12.1), I(0.9), take, size=21, bold=True)
    text(s, I(0.6), I(6.45), I(12.1), I(0.4),
         "freeze = more than 250 ms with no new picture of the game", size=14, color=MUTED)
    notes(s, f"""
[Presenter 4] The other side of the story. Left: TCP never loses an update, zero percent at any
loss. UDP skips the lost ones: about ten and thirty percent, exactly the loss we added. Right:
freezes, moments of more than a quarter second without a new picture. TCP freezes much more
often, because it waits for every lost packet. So for a live game, skipping an old picture is
better than waiting for it.
""")


def s_detect(prs, rows):
    s = frame(prs, "How fast a crashed player is noticed", kicker="Backup · Measured",
              tags=("TCP", "UDP"))
    tcp_d = span([num(rows, "tcp", l, "detect_ms") for l in LOSSES])
    udp_d = span([num(rows, "udp", l, "detect_ms") for l in LOSSES], seconds=True)
    for k, (val, color, light, why) in enumerate((
            (tcp_d, TCP, TCP_LIGHT, "The OS closes the connection for the dead program (FIN)."),
            (udp_d, UDP, UDP_LIGHT, "No connection: we wait for 4 s of silence."))):
        x = I(0.6 + k * 6.2)
        box(s, x, I(1.8), I(5.9), I(3.1), "", fill=light)
        text(s, x + I(0.4), I(2.0), I(5.1), I(0.5), "TCP" if k == 0 else "UDP", size=22,
             bold=True, color=color)
        text(s, x + I(0.4), I(2.55), I(5.1), I(1.2), val, size=60, bold=True, color=color,
             font=HEAD)
        text(s, x + I(0.4), I(3.85), I(5.1), I(0.9), why, size=19, color=INK)
    c30 = num(rows, "udp", 30, "client_retransmissions")
    s30 = num(rows, "udp", 30, "server_retransmissions")
    g30 = num(rows, "udp", 30, "reliable_gave_up")
    if None not in (c30, s30, g30):
        line = (f"UDP at 30 % loss: {c30 + s30:.0f} important messages had to be resent, "
                f"{g30:.0f} were given up.")
    else:
        line = f"UDP resends at 30 % loss: {LIVE}."
    text(s, I(0.6), I(5.2), I(12.1), I(0.6), line, size=21, bold=True)
    text(s, I(0.6), I(6.3), I(12.1), I(0.5),
         "A bot killed with kill -9 in the middle of a game, at 0, 10 and 30 % loss.", size=14,
         color=MUTED)
    notes(s, f"""
[Presenter 4] How fast is a crashed player noticed? With TCP, {tcp_d}: the operating system
closes the connection. With UDP, {udp_d}: we have to wait for four seconds of silence. This is
the price of having no connection. And our safety net works: at thirty percent loss, the
important messages that were lost were resent, and none was given up.
""")


def s_wins(prs):
    s = frame(prs, "Who wins? It depends on the message", kicker="Part 6 · Conclusion",
              tags=("TCP", "UDP"))
    cards = [("TCP is best for", TCP, TCP_LIGHT,
              ["Lobby, rooms, results: everything must arrive",
               "Simple: order and resending come for free",
               "Crashes noticed at once; passes firewalls and tunnels easily"]),
             ("UDP is best for", UDP, UDP_LIGHT,
              ["Live game updates when packets are lost",
               "Never waits for an old picture",
               "But: we had to build reliability ourselves"])]
    for k, (head, color, light, items) in enumerate(cards):
        x = I(0.6 + k * 6.2)
        box(s, x, I(1.8), I(5.9), I(3.6), "", fill=light)
        text(s, x + I(0.35), I(2.0), I(5.2), I(0.5), head, size=24, bold=True, color=color)
        text(s, x + I(0.35), I(2.7), I(5.2), I(2.6), [[("• ", {"bold": True, "color": color}),
                                                         (t, {})] for t in items],
             size=20, color=INK, space_after=10)
    box(s, I(0.6), I(5.65), I(12.1), I(0.95),
        "Real games do what we did: UDP for live data + a small reliable layer for the rest.",
        fill=NIGHT, color=WHITE, size=21, bold=True)
    notes(s, """
[Presenter 4] So which one is better? It depends on the message. TCP is best when everything
must arrive: the lobby, the rooms, the results. It is simple, notices crashes immediately and
passes firewalls easily. UDP is best for the live game when packets are lost, because it never
waits for an old picture, but we had to build reliability ourselves. Real online games do what
we did: UDP for live data, plus a small reliable layer for the rest.
""", [("If you started again, which one would you choose?",
       "UDP for the game data and our reliable layer for the lobby, like we did, because the game "
       "only needs the newest STATE.")])


def s_end(prs):
    s = frame(prs, "What we take away", kicker="Conclusion", kicker_color=GOLD, dark=True)
    points(s, I(0.6), I(1.9), I(12.1), [
        ("TCP:", "reliable and simple, but one lost packet makes everything wait."),
        ("UDP:", "never stuck on an old packet, but we decide what to resend."),
        ("For a live game:", "UDP plus a small reliable layer gives the best of both."),
    ], GOLD, gap=1.0, size=24, dark=True)
    text(s, I(0.6), I(4.95), I(12.1), I(0.9), "Thank you! Questions?", size=44, bold=True,
         color=GOLD, font=HEAD)
    text(s, I(0.6), I(5.95), I(12.1), I(0.5), " · ".join(TEAM), size=18, color=NIGHT_TEXT)
    notes(s, """
[Presenter 4] To conclude. TCP is reliable and simple, but one lost packet makes everything
wait. UDP never gets stuck on an old packet, but we have to decide ourselves what to resend.
For a live game, UDP with a small reliable layer gives the best of both. Thank you, we are happy
to answer your questions.
""")


# ---------------------------------------------------------------- script

def backup(s):
    BACKUP.add(s.slide_id)
    return s


def write_script(prs):
    """docs/presentation_script.md: the notes in order, with timings."""
    out = ["# Presentation script (20 minutes, with live demo)", "",
           f"Generated by `slides/build_slides.py` from the speaker notes of "
           f"`{OUT.relative_to(ROOT)}`; edit the notes there, then re-run. Talk slides are timed "
           f"at {WPM} words per minute; demo slides have a fixed time. The demo steps and "
           f"what to check are in [demo_scenarios.md](demo_scenarios.md).", "",
           "Presenters: " + ", ".join(f"Presenter {i + 1} = {n}" for i, n in enumerate(TEAM)), ""]
    total = 0
    rows, parts = [], []
    for i, slide in enumerate(prs.slides, start=1):
        title = next((sh.text_frame.text for sh in slide.shapes if sh.name == "title"), "")
        body, _, qa = slide.notes_slide.notes_text_frame.text.partition("Likely question")
        secs = 0 if slide.slide_id in BACKUP else SECS.get(slide.slide_id)
        if secs is None:
            secs = round(len(body.split()) / WPM * 60 / 5) * 5
        start = total
        total += secs
        presenter = body.strip().split("]")[0].lstrip("[")
        length = ("backup, for questions" if slide.slide_id in BACKUP
                  else f"{secs} s" if secs else "skip if late")
        rows.append(f"| {i} | {title} | {presenter} | {start // 60}:{start % 60:02d} | {length} |")
        qa = ("Likely question" + qa).strip() if qa else ""
        parts += [f"## Slide {i}: {title} ({length})", "",
                  " ".join(body.split()), "", *(f"> {l}" if l else ">" for l in qa.splitlines()), ""]
    out += ["| Slide | Title | Who | Starts at | Length |", "|---|---|---|---|---|", *rows,
            f"| | **Total** | | | **{total // 60} min {total % 60:02d} s** |", ""]
    out += parts
    SCRIPT.write_text("\n".join(out))
    return total


def build():
    rows = load_results()
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    prs.core_properties.title = "Maze Arena: TCP vs UDP"
    s_title(prs)
    s_game(prs)
    s_arch(prs)
    s_shared(prs)
    s_tcp(prs)
    s_stream(prs)
    s_udp(prs)
    s_reliable(prs)
    s_split(prs)
    s_vanish(prs, rows)
    s_demo_plan(prs)
    s_wireshark(prs)
    s_demos(prs)
    s_differences(prs)
    s_seen(prs, rows)
    s_wins(prs)
    s_end(prs)
    for slide_fn in (s_rtt, s_lost, s_detect):
        slide_fn(prs, rows)
        backup(prs.slides[-1])
    footers(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    total = write_script(prs)
    have = sorted(f"{p}{l}" for p, l in rows)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(prs.slides)} slides; loopback rows: "
          f"{', '.join(have)}); wrote {SCRIPT.relative_to(ROOT)} ({total // 60} min "
          f"{total % 60:02d} s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--team", help='comma-separated names in speaking order, e.g. "Ana,Ben,Chloé,Dan"')
    args = ap.parse_args()
    if args.team:
        TEAM = [n.strip() for n in args.team.split(",") if n.strip()]
    build()
