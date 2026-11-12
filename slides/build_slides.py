"""Build the demo deck slides/maze_arena_tcp_vs_udp.pptx (20-minute talk with a live demo).

Every number on the slides is read from metrics/results.csv (and metrics/rtt_paths.csv
when it exists), so after new measurements just run:

    .venv/bin/python slides/build_slides.py --team "Name 1,Name 2,Name 3,Name 4"

Speaking order: Presenter 1 = the game and the design, Presenter 2 = TCP and UDP,
Presenter 3 = runs the live demo (server laptop), Presenter 4 = results and conclusion.
In the demo, Presenter 1 plays alice, Presenter 2 bob, Presenter 4 carol.
A value that was never measured is shown as "measured live in the demo", never guessed.
Charts are native PowerPoint charts, TCP blue and UDP orange as in metrics/charts/*.png.
Also writes docs/presentation_script.md (speaker notes + timings).
Edit BONUS_STATUS after the remote tests.
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
BONUS_STATUS = {
    "tcp": "TCP: full games through the Cloudflare tunnel, tested from the server Mac",
    "udp": "UDP: playit agent ready, UDP tunnel not set up yet",
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
GOLD = RGBColor(0xFF, 0xC5, 0x3D)       # live demo
LOST = RGBColor(0xB4, 0x23, 0x2B)
PLAYER = {"alice": RGBColor(0xE0, 0xB0, 0x00), "bob": RGBColor(0x00, 0xA5, 0xB8),
          "carol": RGBColor(0xC8, 0x2C, 0xB4)}   # the game's yellow / cyan / magenta, darkened for paper

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
    text(s, I(6.65), I(5.25), I(6.1), I(0.4), "A real frame of our game: alice's screen",
         size=14, color=NIGHT_TEXT)
    notes(s, """
[Presenter 1] Hello, we are [team]. This is Maze Arena: a multiplayer maze game for up to three
players. We built the same game twice, once over TCP and once over UDP, so that we could compare
the two protocols on exactly the same game. In the next twenty minutes we explain how both
versions work, we show them live on four laptops, and we show what we measured.
""")


def s_agenda(prs):
    s = frame(prs, "Our 20 minutes", kicker="Plan")
    box(s, I(0.6), I(1.75), I(12.1), I(0.9),
        [[("Our question: ", {"bold": True}),
          ("which transport suits a real-time multiplayer game, and why?", {})]],
        fill=WHITE, line=LINE, size=24, align=PP_ALIGN.LEFT, margin=0.3)
    parts = [("1", "The game and our design", "3 min", first(1), None),
             ("2", "The TCP version", "2 min", first(2), TCP),
             ("3", "The UDP version", "3 min", first(2), UDP),
             ("4", "Live demo on 4 laptops", "8 min", "everyone", GOLD),
             ("5", "Results and lessons", "4 min", first(4), None)]
    bw, gap, y = 2.3, 0.15, 3.05
    for k, (n, label, mins, by, color) in enumerate(parts):
        x = I(0.6 + k * (bw + gap))
        demo = color is GOLD
        box(s, x, I(y), I(bw), I(2.5), "", fill=NIGHT if demo else WHITE,
            line=None if demo else LINE)
        badge(s, x + I(0.25), I(y + 0.3), n, color or INK)
        text(s, x + I(0.25), I(y + 1.0), I(bw - 0.45), I(0.85), label, size=21, bold=True,
             color=WHITE if demo else INK)
        text(s, x + I(0.25), I(y + 1.85), I(bw - 0.45), I(0.6),
             [[(mins, {"bold": True}), ("  ·  " + by, {})]], size=16,
             color=GOLD if demo else MUTED)
    text(s, I(0.6), I(5.95), I(12.1), I(0.5),
         "First how it works, then we show it live, then the numbers that explain what you saw.",
         size=20, color=MUTED)
    notes(s, """
[Presenter 1] Our question is simple: which transport suits a real-time multiplayer game, and
why? First we present the game and our design, then the TCP version and the UDP version.
Then the most important part: a live demo on four laptops, with four short games that each
prove something. We finish with our measurements and what we learned.
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
    for k, name in enumerate(("alice", "bob", "carol")):
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


def s_flow(prs):
    s = frame(prs, "A game, message by message", kicker="Part 1 · Design")
    steps = [("LOGIN", "pick a name"), ("ROOM", "create or join"), ("READY", "everyone presses R"),
             ("GAME_START", "maze, colors, timer"), ("INPUT ⇄ STATE", "600 times in 60 s"),
             ("GAME_OVER", "ranking, winner")]
    cw, y = 2.08, 1.85
    for k, (name, sub) in enumerate(steps):
        x = I(0.6 + k * (cw - 0.03))
        hot = k == 4
        box(s, x, I(y), I(cw), I(0.95), name.replace("_", "_\u200b"),
            shape=MSO_SHAPE.PENTAGON if k == 0 else MSO_SHAPE.CHEVRON,
            fill=NIGHT if hot else WHITE, line=None if hot else LINE, size=14, bold=True,
            color=WHITE if hot else INK)
        text(s, x + I(0.25), I(y + 1.1), I(cw - 0.4), I(0.6), sub, size=17, color=MUTED)
    code_panel(s, I(0.6), I(3.75), I(12.1), I(2.1), [
        [("Examples, one message each:", {"font": BODY, "size": 16, "color": NIGHT_TEXT})],
        '{"type": "LOGIN", "name": "alice"}',
        '{"type": "INPUT", "dir": "UP"}',
        '{"type": "STATE", "tick": 231, "positions": {...}, "scores": {...}}',
    ], size=19)
    text(s, I(0.6), I(6.1), I(12.1), I(0.5),
         "Every message is a small JSON object, exactly the same on TCP and on UDP.", size=20,
         color=INK, bold=True)
    notes(s, """
[Presenter 1] This is one game, message by message. A player logs in with a name, creates or
joins a room, and presses R when ready. When everyone is ready the server sends GAME_START with
the maze and the colors. Then for sixty seconds the players send INPUT and the server sends
STATE, six hundred times. At the end GAME_OVER gives the ranking. Every message is a small
JSON object, and the messages are identical on TCP and UDP.
""")


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
        [[("listening socket", {"bold": True})], "port 5050"], fill=TCP, color=WHITE, size=18)
    arrow(s, I(3.6), I(2.27), I(4.2), I(2.27), color=TCP, width=2.5)
    box(s, I(4.2), I(1.8), I(2.9), I(0.95),
        [[("accept()", {"bold": True, "font": MONO})], "a new socket per player"],
        fill=WHITE, line=TCP, size=18)
    for k, name in enumerate(("alice", "bob", "carol")):
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
    notes(s, """
[Presenter 2] TCP works like a phone call: you connect first, then you talk. The server opens a
listening socket on port 5050. For each player, accept gives a new socket, just for that
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
        [[("one socket", {"bold": True}), ("  ·  port 5050", {})],
         "reads every packet in one loop"], fill=UDP, color=WHITE, size=18)
    tbl = table(s, I(0.6), I(3.0), I(5.9), [I(3.3), I(2.6)], [I(0.55)] * 4, "who is it")
    cell(tbl.cell(0, 0), "sender's address", 18, WHITE, True, UDP)
    cell(tbl.cell(0, 1), "player", 18, WHITE, True, UDP)
    for k, (addr, name) in enumerate((("192.168.1.12 : 50311", "alice"),
                                      ("192.168.1.20 : 61002", "bob"),
                                      ("192.168.1.31 : 53877", "carol")), start=1):
        cell(tbl.cell(k, 0), addr, 18, INK, False, WHITE)
        cell(tbl.cell(k, 1), [[(name, {"bold": True, "color": PLAYER[name]})]], 18, INK, False,
             WHITE)
    text(s, I(0.6), I(5.4), I(5.9), I(0.5), "The address on each packet tells us who sent it.",
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
        ("Then", "the others see “carol left”, the game goes on", None),
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

DEMO_ROLES = None   # filled in build(): who plays which laptop


def s_demo_plan(prs):
    s = frame(prs, "Live demo: 4 games on 4 laptops", kicker="Part 4 · Live demo",
              kicker_color=GOLD, dark=True)
    games = [("GAME 1", "TCP", "Normal game, then a crash", "crash noticed at once"),
             ("GAME 2", "UDP", "Normal game, then a crash", "crash noticed after 4 s"),
             ("GAME 3", "UDP", "30 % of packets thrown away", "the game keeps going"),
             ("GAME 4", "TCP", "Wi-Fi off in the middle", "player dropped after 5 s")]
    cw, gap = 2.9, 0.17
    for k, (g, proto, title, result) in enumerate(games):
        x = I(0.6 + k * (cw + gap))
        color = TCP if proto == "TCP" else UDP
        box(s, x, I(1.8), I(cw), I(2.95), "", fill=NIGHT_2, line=color, line_w=2)
        text(s, x + I(0.25), I(2.0), I(1.5), I(0.4), g, size=16, bold=True, color=GOLD)
        pill(s, x + I(cw - 1.2), I(1.97), proto, color)
        text(s, x + I(0.25), I(2.6), I(cw - 0.5), I(1.2), title, size=22, bold=True, color=WHITE)
        text(s, x + I(0.25), I(3.85), I(cw - 0.5), I(0.8), result, size=18, color=NIGHT_TEXT)
    text(s, I(0.6), I(5.05), I(12.1), I(1.0), [
        [("Server laptop: ", {"bold": True, "color": GOLD}), (who(3) + ", its log on the projector", {})],
        [("Players: ", {"bold": True, "color": GOLD}),
         (f"alice = {who(1)}  ·  bob = {who(2)}  ·  carol = {who(4)}", {})],
    ], size=20, color=WHITE, space_after=6)
    text(s, I(0.6), I(6.2), I(12.1), I(0.5),
         "If we have time: TCP with 30 % loss, and a player on another network.", size=18,
         color=NIGHT_TEXT)
    notes(s, """
[Presenter 3] Now the live demo. We play four short games, and each one proves something.
Games 1 and 2: a normal game on TCP and on UDP, and in each one we crash a player on purpose.
Game 3: UDP with 30 percent of the packets thrown away. Game 4: a player's Wi-Fi goes off.
I run the server; its log is on the projector so you can see every event with its time.
""", secs=40)


def demo_slide(prs, n, proto, title, do, watch, proves, command, note, secs):
    color = TCP if proto == "TCP" else UDP
    s = frame(prs, title, kicker=f"Live demo · Game {n}", kicker_color=GOLD, tags=(proto,),
              dark=True)
    cols = [("We do", do, True), ("Watch for", watch, False), ("This proves", proves, False)]
    cw, gap = 3.85, 0.27
    for k, (head, items, numbered) in enumerate(cols):
        x = I(0.6 + k * (cw + gap))
        box(s, x, I(1.8), I(cw), I(4.25), "", fill=NIGHT_2,
            line=GOLD if k == 2 else None, line_w=2)
        text(s, x + I(0.3), I(1.98), I(cw - 0.6), I(0.5), head, size=22, bold=True,
             color=GOLD if k == 2 else color if k == 0 else WHITE)
        paras = [[(f"{i + 1}.  " if numbered else "• ", {"bold": True, "color": GOLD}),
                  (t, {})] for i, t in enumerate(items)]
        text(s, x + I(0.3), I(2.6), I(cw - 0.6), I(3.35), paras, size=19, color=WHITE,
             space_after=10)
    text(s, I(0.6), I(6.25), I(12.1), I(0.55), command, size=13, color=NIGHT_TEXT, font=MONO)
    notes(s, note, secs=secs)
    return s


def s_demos(prs):
    demo_slide(
        prs, 1, "TCP", "TCP: a normal game, then a crash",
        ["Start the TCP server", "bob first tries the name “alice” → refused",
         "All three join room demo and press R", "At 0:40 left, carol's game is killed"],
        ["Same maze and scores on 3 screens", "RTT in the corner: a few ms",
         "Server log: 3 different IP addresses", "“carol left” in the same second"],
        ["Login, rooms and the 10 ticks/s game work over TCP",
         "A crash is seen at once: carol's OS closes the connection (FIN)"],
        "server: python -m tcp.server · players: python -m client_ui.ui --proto tcp "
        "--host S_IP --name alice --room demo · crash: pkill -9 -f client_ui.ui",
        """[Presenter 3] Game 1, TCP. I start the TCP server. bob first tries to log in as alice:
        refused, the name is taken. Then the three players join room demo and press R. Look at
        the log: three connections from three different addresses. Watch the RTT in the corner of
        each screen. At forty seconds left, carol's game is killed, with no goodbye. The log shows
        carol left in the same second, because carol's operating system closes the TCP connection.
        alice and bob keep playing to the end and get the same ranking.""", 120)
    demo_slide(
        prs, 2, "UDP", "UDP: the same game, then a crash",
        ["Start the UDP server", "The same three players join and press R",
         "At 0:40 left, carol's game is killed"],
        ["Server log: “NEW PEER”, not “CONNECT”", "Corner: lost 0 % of updates",
         "“carol left” only after about 4 s"],
        ["The same game works over UDP", "UDP has nothing to close: silence is the only signal"],
        "server: python -m udp.server · players: python -m client_ui.ui --proto udp "
        "--host S_IP --name alice --room demo",
        """[Presenter 3] Game 2, the same game over UDP. The log now says NEW PEER instead of
        CONNECT: there is no connection, the server just sees packets from a new address. The
        corner shows lost zero percent of updates on our network. At forty seconds left we kill
        carol again. This time nothing happens at first: carol's laptop has nothing to close. Count
        with me: after about four seconds of silence the server removes carol.""", 100)
    demo_slide(
        prs, 3, "UDP", "UDP with 30 % packet loss",
        ["Restart server and players with --drop 0.3",
         "Each side throws away 30 % of what it sends", "Log in, join, press R, play"],
        ["Login and rooms still work", "Corner: lost about 30 % of updates",
         "Moves are jumpier, but never stop", "After: the log shows resends, 0 given up"],
        ["Our safety net saves the important messages",
         "Skipping old STATEs keeps the game live"],
        "server: python -m udp.server --drop 0.3 · players: python -m client_ui.ui --proto udp "
        "--host S_IP --drop 0.3 --name alice --room demo",
        """[Presenter 3] Game 3: we now throw away thirty percent of all packets on purpose, on the
        server and on every player. Login, joining the room and ready still work: these messages
        use our safety net and are resent. In the corner you see about thirty percent of updates
        lost. The players jump a bit, but the game never stops, because we never wait for an old
        picture. When the game ends I stop the server: its statistics show the resends, and zero
        messages given up.""", 110)
    demo_slide(
        prs, 4, "TCP", "TCP: Wi-Fi off in the middle of a game",
        ["Back to TCP, all three press R", "At 0:40 left, bob's laptop turns Wi-Fi off",
         "bob's game stays open"],
        ["bob stops moving on the other screens", "After about 5 s: “bob left”",
         "bob's window: “server silent”", "alice and carol keep playing"],
        ["With no network there is no FIN: TCP alone would wait for minutes",
         "Our heartbeat (a PING every second) catches it in 5 s"],
        "server: python -m tcp.server · players: python -m client_ui.ui --proto tcp "
        "--host S_IP --name bob --room demo · Wi-Fi off from the menu bar",
        """[Presenter 3] Game 4, back to TCP. At forty seconds left, bob turns the Wi-Fi off but
        keeps the game open. Now there is no crash, so no operating system closes anything: TCP
        alone would wait for minutes. On the other screens bob stops moving, and about five
        seconds later the server says bob left, thanks to our heartbeat. bob's own window says the
        server is silent. The game goes on for alice and carol.""", 100)
    s = frame(prs, "If we have time", kicker="Live demo · Extra", kicker_color=GOLD, dark=True)
    extras = [("TCP with 30 % loss", TCP,
               "The server Mac drops 30 % of packets in the kernel (needs sudo).",
               "Watch: the game freezes, then jumps. One lost packet holds back everything behind "
               "it: head-of-line blocking."),
              ("A player on another network", GOLD,
               "One player on a phone hotspot joins through the Cloudflare tunnel.",
               "Watch: a different public IP (curl -4 ifconfig.me) and a higher RTT.")]
    for k, (head, color, do, watch) in enumerate(extras):
        x = I(0.6 + k * 6.2)
        box(s, x, I(1.8), I(5.9), I(4.0), "", fill=NIGHT_2, line=color, line_w=2)
        text(s, x + I(0.35), I(2.0), I(5.2), I(0.5), head, size=24, bold=True, color=color)
        text(s, x + I(0.35), I(2.75), I(5.2), I(3.0), [do, watch], size=20, color=WHITE,
             space_after=14)
    text(s, I(0.6), I(6.1), I(12.1), I(0.6),
         "sudo sh metrics/netloss_mac.sh on 5050 0.3 0 en0   ·   off: sudo sh metrics/netloss_mac.sh off",
         size=13, color=NIGHT_TEXT, font=MONO)
    notes(s, """
[Presenter 3] Only if we are ahead of time. First, TCP with thirty percent loss, made by the
operating system: the game freezes and then jumps, because one lost packet holds back
everything behind it. Second, a player on a phone hotspot joins through our Cloudflare tunnel.
Otherwise we skip this slide.
""", secs=0)


# ---------------------------------------------------------------- part 5: results

HOW = ("How we measured: 3 bots, 120 s games on one Mac, loss added on purpose "
       "(TCP: by the kernel, UDP: by our --drop option).")


def s_rtt(prs, rows):
    s = frame(prs, "Under loss, TCP waits and UDP doesn't", kicker="Part 5 · Results",
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
    s = frame(prs, "UDP skips lost updates, TCP freezes", kicker="Part 5 · Results",
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
    s = frame(prs, "How fast a crashed player is noticed", kicker="Part 5 · Results",
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
    s = frame(prs, "Who wins? It depends on the message", kicker="Part 5 · Lessons",
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


def s_hard(prs):
    s = frame(prs, "What was hard", kicker="Part 5 · Lessons")
    cards = [("TCP", TCP, "One recv() is not one message",
              "We added line framing and tested split and merged messages."),
             ("UDP", UDP, "Building seq, ACK and resend",
              "Tested at 30 % loss: everything important arrives once, in order."),
             ("both", MUTED, "Choosing the timeout",
              "Too short kicks players on bad Wi-Fi, too long is slow: we chose 4–5 s."),
             ("both", MUTED, "Real networks",
              "Firewalls and Wi-Fi that blocks laptops from each other: we check with netcheck first.")]
    for k, (tag, color, head, body) in enumerate(cards):
        x = I(0.6 + (k % 2) * 6.2)
        y = I(1.8 + (k // 2) * 2.35)
        box(s, x, y, I(5.9), I(2.1), "", fill=WHITE, line=LINE)
        box(s, x + I(0.3), y + I(0.3), I(0.95), I(0.42), tag, fill=color, size=16, color=WHITE,
            bold=True)
        text(s, x + I(1.45), y + I(0.27), I(4.2), I(0.5), head, size=21, bold=True)
        text(s, x + I(0.3), y + I(0.95), I(5.3), I(1.1), body, size=18, color=MUTED)
    notes(s, """
[Presenter 4] What was hard? With TCP, understanding that one recv is not one message. With UDP,
building sequence numbers, ACKs and resends ourselves, and testing them under loss. For both,
choosing the timeout: too short and players on bad Wi-Fi get kicked, too long and a dead player
stays in the game. And real networks: firewalls, and campus Wi-Fi that blocks laptops from
talking to each other. That is why we check the network with a small tool before playing.
""", [("What happens if STATE grows past the safe UDP size?",
       "IP would split the packet and losing one piece loses the whole STATE. Ours is 1228 bytes, "
       "under the ~1472-byte limit; we warn above 1200.")])


def s_bonus(prs, paths):
    s = frame(prs, "Bonus: players on different networks", kicker="Part 5 · Bonus",
              tags=("TCP", "UDP"))
    rows = [("TCP", TCP, ["player", "Cloudflare\n(internet)", "tunnel opened\nby the server",
                          "TCP server\n:5050"]),
            ("UDP", UDP, ["player", "playit.gg relay\n(internet)", "playit agent\non the server",
                          "UDP server\n:5050"])]
    for r, (proto, color, steps) in enumerate(rows):
        y = I(1.8 + r * 1.65)
        pill(s, I(0.6), y + I(0.3), proto, color)
        for k, label in enumerate(steps):
            x = I(1.85 + k * 2.75)
            last = k == len(steps) - 1
            box(s, x, y, I(2.3), I(1.05), label.split("\n"), fill=color if last else WHITE,
                line=color, size=17, color=WHITE if last else INK, line_w=2)
            if not last:
                arrow(s, x + I(2.3), y + I(0.52), x + I(2.75), y + I(0.52), color=color, width=2.5)
    text(s, I(0.6), I(5.2), I(12.1), I(0.5),
         "No change on any router: the server dials out to the relay.", size=21, bold=True)
    text(s, I(0.6), I(5.8), I(12.1), I(0.9), [
        [("Status  ", {"bold": True, "color": INK}), (BONUS_STATUS["tcp"], {})],
        [("", {}), (BONUS_STATUS["udp"], {})]], size=17, color=MUTED, space_after=2)
    notes(s, """
[Presenter 4] The bonus: players on different networks. Routers block connections that come in
from outside, and we cannot change campus or hotspot routers. So the server dials out. For TCP a
Cloudflare tunnel carries the traffic from a remote player to our server. Cloudflare does not
carry UDP, so for UDP we use a relay called playit. The TCP path works; the UDP tunnel is not
set up yet.
""", [("Why not just open port 5050 on the router?",
       "We do not control campus or hotspot routers, and many use carrier NAT; an outgoing tunnel "
       "works everywhere.")])


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
        secs = SECS.get(slide.slide_id)
        if secs is None:
            secs = round(len(body.split()) / WPM * 60 / 5) * 5
        start = total
        total += secs
        presenter = body.strip().split("]")[0].lstrip("[")
        length = f"{secs} s" if secs else "skip if late"
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
    paths = load_rtt_paths()
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    prs.core_properties.title = "Maze Arena: TCP vs UDP"
    s_title(prs)
    s_agenda(prs)
    s_game(prs)
    s_arch(prs)
    s_flow(prs)
    s_shared(prs)
    s_tcp(prs)
    s_stream(prs)
    s_udp(prs)
    s_reliable(prs)
    s_split(prs)
    s_vanish(prs, rows)
    s_demo_plan(prs)
    s_demos(prs)
    s_rtt(prs, rows)
    s_lost(prs, rows)
    s_detect(prs, rows)
    s_wins(prs)
    s_hard(prs)
    s_bonus(prs, paths)
    s_end(prs)
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
