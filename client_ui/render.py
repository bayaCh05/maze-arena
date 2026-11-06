"""Drawing with pygame: the board (from STATE as sent by the server), the sidebar, menus.

Used by ui.py and local_demo.py. Nothing here decides game outcomes: positions,
scores and power come from the server's STATE. The only client-side extras are
cosmetic: players glide between two server positions (100 ms apart) instead of
jumping, and score changes become little popups.
"""

import math
import time

import pygame

CELL = 36
TOP = 64            # top bar
SIDE = 250          # scoreboard on the right

BG = (10, 12, 28)
PANEL = (22, 26, 54)
PANEL_HI = (34, 40, 80)
BORDER = (60, 70, 130)
WALL_FILL = (14, 20, 66)
WALL_EDGE = (80, 120, 255)
PELLET = (255, 205, 165)
TEXT = (238, 240, 255)
DIM = (140, 148, 185)
ACCENT = (255, 214, 0)
GOOD = (90, 230, 140)
BAD = (255, 95, 115)
SCARED = (90, 120, 255)

RGB = {
    "yellow": (255, 214, 0),
    "cyan": (0, 225, 255),
    "magenta": (255, 95, 225),
}
FACING_ANGLE = {"RIGHT": 0, "UP": 90, "LEFT": 180, "DOWN": 270}
STEPS = {"RIGHT": (1, 0), "LEFT": (-1, 0), "UP": (0, -1), "DOWN": (0, 1)}


def window_size(maze):
    """Window (width, height) in pixels for this maze: board + top bar + sidebar."""
    return len(maze[0]) * CELL + SIDE, TOP + len(maze) * CELL


def player_rgb(setup, name):
    """RGB of a player's color name from GAME_START."""
    return RGB.get(setup["colors"].get(name), TEXT)


class Fonts:
    """pygame's bundled font (same look on macOS, Windows and Linux)."""

    def __init__(self):
        f = lambda size: pygame.font.Font(None, size)
        self.title, self.big, self.mid, self.body, self.small = f(84), f(52), f(34), f(26), f(21)


def text(screen, font, msg, color, pos, anchor="topleft", shadow=True):
    """Draw text anchored at pos (with a drop shadow); returns its rect."""
    img = font.render(str(msg), True, color)
    rect = img.get_rect(**{anchor: pos})
    if shadow:
        screen.blit(font.render(str(msg), True, (0, 0, 0)), rect.move(2, 2))
    screen.blit(img, rect)
    return rect


def panel(screen, rect, color=PANEL, border=BORDER, radius=14):
    """Rounded rectangle with a border (cards, dialogs)."""
    pygame.draw.rect(screen, color, rect, border_radius=radius)
    pygame.draw.rect(screen, border, rect, width=2, border_radius=radius)


def button(screen, fonts, rect, label, hovered=False, color=ACCENT, enabled=True):
    """Rounded button; lighter when hovered, greyed out when disabled."""
    rect = pygame.Rect(rect)
    if not enabled:
        fill, fg = PANEL_HI, DIM
    elif hovered:
        fill, fg = tuple(min(255, c + 30) for c in color), BG
    else:
        fill, fg = color, BG
    pygame.draw.rect(screen, (0, 0, 0), rect.move(0, 4), border_radius=12)
    pygame.draw.rect(screen, fill, rect.move(0, -2 if hovered and enabled else 0), border_radius=12)
    text(screen, fonts.body, label, fg, rect.move(0, -2 if hovered and enabled else 0).center, "center", shadow=False)
    return rect


def key_hints(screen, fonts, hints, center_x, y):
    """Row of [KEY] label chips, centered."""
    parts = []
    for key, label in hints:
        k = fonts.small.render(key, True, BG)
        lbl = fonts.small.render(label, True, DIM)
        parts.append((k, lbl))
    width = sum(k.get_width() + 16 + 6 + lbl.get_width() + 22 for k, lbl in parts) - 22
    x = center_x - width // 2
    for k, lbl in parts:
        chip = pygame.Rect(x, y - 2, k.get_width() + 16, k.get_height() + 6)
        pygame.draw.rect(screen, DIM, chip, border_radius=6)
        screen.blit(k, k.get_rect(center=chip.center))
        x = chip.right + 6
        screen.blit(lbl, (x, y + 1))
        x += lbl.get_width() + 22


def draw_pac(screen, color, center, radius, facing="RIGHT", mouth=0.3, eye=True):
    """Pac-Man shape: mouth 0 = closed, 1 = wide open, facing a direction."""
    cx, cy = center
    a0 = FACING_ANGLE.get(facing, 0)
    half = 4 + 38 * mouth
    pts = [(cx, cy)]
    for i in range(25):
        a = math.radians(a0 + half + (360 - 2 * half) * i / 24)
        pts.append((cx + radius * math.cos(a), cy - radius * math.sin(a)))
    pygame.draw.polygon(screen, color, pts)
    if eye:
        ea = math.radians(a0 + (-65 if facing == "LEFT" else 65))
        ex, ey = cx + radius * 0.5 * math.cos(ea), cy - radius * 0.5 * math.sin(ea)
        pygame.draw.circle(screen, (15, 15, 30), (int(ex), int(ey)), max(2, radius // 6))


def glow(screen, color, center, radius, alpha):
    """Translucent circle (halo around power pellets and powered players)."""
    surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    pygame.draw.circle(surf, (*color, alpha), (radius, radius), radius)
    screen.blit(surf, (center[0] - radius, center[1] - radius))


# ---------------------------------------------------------------- menus background

def menu_background(screen, fonts, subtitle=""):
    """Dark backdrop with a pellet field and a Pac-Man chasing dots under the title."""
    w, h = screen.get_size()
    screen.fill(BG)
    t = time.monotonic()
    for i in range(0, w, 48):
        for j in range(140, h, 48):
            if (i // 48 + j // 48) % 3 == 0:
                pygame.draw.circle(screen, (30, 34, 70), (i + 24, j), 3)
    text(screen, fonts.title, "MAZE ARENA", ACCENT, (w // 2, 58), "center")
    lane_y = 112
    x = (t * 180) % (w + 200) - 100
    for d in range(0, w, 40):
        if d > x:
            pygame.draw.circle(screen, PELLET, (d, lane_y), 4)
    draw_pac(screen, ACCENT, (int(x), lane_y), 15, "RIGHT", abs(math.sin(t * 10)))
    for k, c in enumerate(("cyan", "magenta")):
        draw_pac(screen, RGB[c], (int(x) - 60 - 45 * k, lane_y), 13, "RIGHT", abs(math.sin(t * 10 + k)))
    if subtitle:
        text(screen, fonts.small, subtitle, DIM, (w // 2, 140), "center", shadow=False)


# ---------------------------------------------------------------- the board

class GameView:
    """Draws one game: maze, pellets, players, effects, top bar, scoreboard."""

    def __init__(self, setup, me=None, tick_seconds=0.1):
        self.setup, self.me = setup, me
        self.maze = setup["maze"]
        self.rows, self.cols = len(self.maze), len(self.maze[0])
        self.tick_seconds = tick_seconds
        self.walls = self._wall_surface()
        self.state = None
        self.prev_pos = {}
        self.arrived = 0.0
        self.facing = {}
        self.moving = {}
        self.floats = []            # [text, color, x, y, t0]
        self.bursts = []            # [x, y, color, t0]
        self.started = time.monotonic()

    # -------------------------------------------------------- geometry

    def cell_center(self, x, y):
        """Pixel center of grid cell (x, y)."""
        return x * CELL + CELL // 2, TOP + y * CELL + CELL // 2

    def _wall_surface(self):
        """Pre-draw the maze walls once; every frame just blits this surface."""
        w, h = self.cols * CELL, self.rows * CELL
        surf = pygame.Surface((w, h))
        surf.fill(BG)
        walls = {(x, y) for y, row in enumerate(self.maze) for x, ch in enumerate(row) if ch == "#"}
        for x, y in walls:
            pygame.draw.rect(surf, WALL_FILL, (x * CELL, y * CELL, CELL, CELL))
        # Neon outline on every wall side that faces a corridor, like the arcade maze.
        i = 5                                           # inset of the line inside the wall cell
        segs = []
        for x, y in walls:
            x0, y0, x1, y1 = x * CELL, y * CELL, (x + 1) * CELL, (y + 1) * CELL
            free = {d: (x + dx, y + dy) not in walls for d, (dx, dy) in STEPS.items()}
            left, right = (x0 + i if free["LEFT"] else x0), (x1 - i if free["RIGHT"] else x1)
            top, bottom = (y0 + i if free["UP"] else y0), (y1 - i if free["DOWN"] else y1)
            if free["UP"]:
                segs.append(((left, y0 + i), (right, y0 + i)))
            if free["DOWN"]:
                segs.append(((left, y1 - i), (right, y1 - i)))
            if free["LEFT"]:
                segs.append(((x0 + i, top), (x0 + i, bottom)))
            if free["RIGHT"]:
                segs.append(((x1 - i, top), (x1 - i, bottom)))
        edges = pygame.Surface((w, h), pygame.SRCALPHA)
        for a, b in segs:
            pygame.draw.line(edges, (*WALL_EDGE, 70), a, b, 7)      # soft glow
        for a, b in segs:
            pygame.draw.line(edges, WALL_EDGE, a, b, 3)
        surf.blit(edges, (0, 0))
        return surf

    # -------------------------------------------------------- server updates

    def update(self, state):
        """New STATE from the server. Returns cosmetic events: [(kind, name, extra)]."""
        events = []
        old = self.state
        self.prev_pos = {n: tuple(p) for n, p in old["positions"].items()} if old else {}
        self.state, self.arrived = state, time.monotonic()
        for name, pos in state["positions"].items():
            prev = self.prev_pos.get(name)
            if prev and prev != tuple(pos):
                dx, dy = pos[0] - prev[0], pos[1] - prev[1]
                if abs(dx) + abs(dy) == 1:
                    self.facing[name] = {(1, 0): "RIGHT", (-1, 0): "LEFT", (0, -1): "UP", (0, 1): "DOWN"}[(dx, dy)]
                self.moving[name] = True
            elif prev:
                self.moving[name] = False
        if old is None:
            return events
        for name, score in state["scores"].items():
            delta = score - old["scores"].get(name, score)
            pos = state["positions"].get(name)
            if pos is None:
                continue
            cx, cy = self.cell_center(*pos)
            if delta < 0:                                     # eaten: respawned with a penalty
                px, py = self.cell_center(*self.prev_pos.get(name, pos))
                self.bursts.append([px, py, player_rgb(self.setup, name), time.monotonic()])
                self.floats.append([f"{delta}", BAD, px, py - 10, time.monotonic()])
                eater = next((n for n, left in state.get("powered", {}).items() if left and n != name), None)
                events.append(("eaten", name, eater))
            elif delta >= 50:
                self.floats.append([f"+{delta}", ACCENT, cx, cy - 14, time.monotonic()])
            elif delta > 0:
                events.append(("pellet", name, delta))
        for name, left in state.get("powered", {}).items():
            if left and not old.get("powered", {}).get(name):
                events.append(("power", name, None))
        return events

    def _draw_pos(self, name, pos):
        """Pixel position, gliding from the previous cell to the new one during one tick (cosmetic only)."""
        prev = self.prev_pos.get(name)
        if not prev or abs(prev[0] - pos[0]) + abs(prev[1] - pos[1]) != 1:
            return self.cell_center(*pos)                     # first frame or respawn: no glide
        a = min(1.0, (time.monotonic() - self.arrived) / self.tick_seconds)
        (x0, y0), (x1, y1) = self.cell_center(*prev), self.cell_center(*pos)
        return x0 + (x1 - x0) * a, y0 + (y1 - y0) * a

    # -------------------------------------------------------- drawing

    def draw(self, screen, fonts, info=None):
        """info: {"room", "proto", "net": [lines], "hints": [(key, label)]} for the bars."""
        info = info or {}
        screen.fill(BG)
        screen.blit(self.walls, (0, TOP))
        now = time.monotonic()
        state = self.state
        if state:
            self._draw_pellets(screen, now)
            self._draw_players(screen, fonts, now)
        self._draw_effects(screen, fonts, now)
        self._draw_top_bar(screen, fonts, info, now)
        self._draw_sidebar(screen, fonts, info)
        board = pygame.Rect(0, TOP, self.cols * CELL, self.rows * CELL)
        if state is None:
            text(screen, fonts.big, "GET READY...", ACCENT, board.center, "center")
        elif now - self.started < 1.3:
            k = (now - self.started) / 1.3
            img = fonts.title.render("GO!", True, ACCENT)
            img = pygame.transform.rotozoom(img, 0, 1 + k)
            img.set_alpha(int(255 * (1 - k)))
            screen.blit(img, img.get_rect(center=board.center))

    def _draw_pellets(self, screen, now):
        """Pellets and blinking power pellets that are still in the last STATE."""
        for x, y in self.state["pellets"]:
            pygame.draw.circle(screen, PELLET, self.cell_center(x, y), 3)
        pulse = (math.sin(now * 6) + 1) / 2
        for x, y in self.state.get("power_pellets", []):
            c = self.cell_center(x, y)
            glow(screen, (255, 240, 200), c, int(14 + 4 * pulse), 55)
            pygame.draw.circle(screen, (255, 248, 230), c, int(7 + 2 * pulse))

    def _draw_players(self, screen, fonts, now):
        """Every player as a Pac-Man in their color; ours has a ring and a YOU label."""
        powered = self.state.get("powered", {})
        anyone_powered = {n for n, left in powered.items() if left}
        radius = CELL // 2 - 3
        for name, pos in self.state["positions"].items():
            cx, cy = self._draw_pos(name, pos)
            c = (int(cx), int(cy))
            color = player_rgb(self.setup, name)
            left = powered.get(name, 0)
            if left and (left > 15 or int(now * 8) % 2):         # blinks in the last 1.5 s
                glow(screen, color, c, radius + 12, 90)
                glow(screen, (255, 255, 255), c, radius + 6, 70)
            elif anyone_powered - {name}:                         # someone can eat this player
                if int(now * 6) % 2:
                    pygame.draw.circle(screen, SCARED, c, radius + 4, 3)
            if name == self.me:
                pygame.draw.circle(screen, (255, 255, 255), c, radius + 3, 2)
            mouth = abs(math.sin(now * 14)) if self.moving.get(name) else 0.25
            draw_pac(screen, color, c, radius, self.facing.get(name, "RIGHT"), mouth)
            label = "YOU" if name == self.me else name
            text(screen, fonts.small, label, (255, 255, 255) if name == self.me else color,
                 (c[0], c[1] - radius - 4), "midbottom")

    def _draw_effects(self, screen, fonts, now):
        """Short cosmetic effects: floating score pop-ups and a burst where someone was eaten."""
        for f in list(self.floats):
            msg, color, x, y, t0 = f
            k = (now - t0) / 0.9
            if k >= 1:
                self.floats.remove(f)
                continue
            img = fonts.mid.render(msg, True, color)
            img.set_alpha(int(255 * (1 - k)))
            screen.blit(img, img.get_rect(center=(x, y - 30 * k)))
        for b in list(self.bursts):
            x, y, color, t0 = b
            k = (now - t0) / 0.6
            if k >= 1:
                self.bursts.remove(b)
                continue
            for i in range(8):
                a = i * math.pi / 4
                r = 6 + 34 * k
                pygame.draw.circle(screen, color, (int(x + r * math.cos(a)), int(y + r * math.sin(a))),
                                   max(1, int(5 * (1 - k))))

    def _draw_top_bar(self, screen, fonts, info, now):
        """Title, time left, and the room / protocol on the right."""
        w = screen.get_width()
        pygame.draw.rect(screen, PANEL, (0, 0, w, TOP))
        pygame.draw.line(screen, BORDER, (0, TOP - 1), (w, TOP - 1), 2)
        draw_pac(screen, ACCENT, (32, TOP // 2), 15, "RIGHT", abs(math.sin(now * 6)))
        text(screen, fonts.mid, "MAZE ARENA", ACCENT, (58, TOP // 2), "midleft")
        if self.state:
            ticks = max(0, self.setup.get("max_ticks", 600) - self.state["tick"])
            secs = math.ceil(ticks / self.setup.get("tick_rate", 10))
            urgent = secs <= 10
            color = BAD if urgent and int(now * 4) % 2 else (TEXT if not urgent else ACCENT)
            text(screen, fonts.big, f"{secs // 60}:{secs % 60:02d}", color, (self.cols * CELL // 2, TOP // 2 + 2), "center")
        right = " · ".join(p for p in (f"room {info['room']}" if info.get("room") else "",
                                       info.get("proto", "").upper()) if p)
        if right:
            text(screen, fonts.body, right, DIM, (w - 16, TOP // 2), "midright", shadow=False)

    def _draw_sidebar(self, screen, fonts, info):
        """Scoreboard (rank, score, power bar), then the network lines (RTT, loss) and key hints."""
        x0 = self.cols * CELL
        side = pygame.Rect(x0, TOP, screen.get_width() - x0, screen.get_height() - TOP)
        pygame.draw.rect(screen, PANEL, side)
        pygame.draw.line(screen, BORDER, side.topleft, side.bottomleft, 2)
        text(screen, fonts.body, "SCORES", DIM, (x0 + 18, TOP + 16), shadow=False)
        y = TOP + 46
        if self.state:
            powered = self.state.get("powered", {})
            ranking = sorted(self.state["scores"].items(), key=lambda kv: (-kv[1], kv[0]))
            for rank, (name, score) in enumerate(ranking, 1):
                card = pygame.Rect(x0 + 12, y, side.width - 24, 70)
                mine = name == self.me
                panel(screen, card, PANEL_HI if mine else BG, (255, 255, 255) if mine else BORDER, 12)
                color = player_rgb(self.setup, name)
                text(screen, fonts.small, f"#{rank}", DIM, (card.x + 10, card.y + 10), shadow=False)
                draw_pac(screen, color, (card.x + 30, card.y + 44), 13, "RIGHT", 0.35)
                text(screen, fonts.body, name + ("  (you)" if mine else ""), color, (card.x + 52, card.y + 12))
                text(screen, fonts.mid, score, TEXT, (card.right - 12, card.y + 46), "midright")
                left = powered.get(name, 0)
                if left:
                    bar = pygame.Rect(card.x + 52, card.y + 50, 90, 8)
                    pygame.draw.rect(screen, BG, bar, border_radius=4)
                    fill = bar.copy()
                    fill.width = int(bar.width * min(1, left / 50))
                    pygame.draw.rect(screen, ACCENT, fill, border_radius=4)
                    text(screen, fonts.small, "POWER", ACCENT, (bar.x, bar.y - 2), "bottomleft", shadow=False)
                y += 80
        y = side.bottom - 24 * (len(info.get("hints", [])) + len(info.get("net", []))) - 30
        for line in info.get("net", []):
            text(screen, fonts.small, line, GOOD, (x0 + 18, y), shadow=False)
            y += 24
        y += 8
        hints = info.get("hints", [])
        key_w = max([fonts.small.size(k)[0] for k, _ in hints] + [0]) + 14
        for key, label in hints:
            text(screen, fonts.small, key, TEXT, (x0 + 18, y), shadow=False)
            text(screen, fonts.small, label, DIM, (x0 + 18 + key_w, y), shadow=False)
            y += 24
