"""Draws a STATE (as sent by the server) with pygame. Used by ui.py and local_demo.py."""

import pygame

CELL = 32
HUD = 40

RGB = {
    "yellow": (255, 220, 0),
    "cyan": (0, 220, 255),
    "magenta": (255, 80, 220),
}
WALL = (30, 60, 200)
BG = (5, 5, 15)
PELLET = (250, 200, 170)
TEXT = (230, 230, 230)
DIM = (140, 140, 160)


def window_size(setup_maze):
    return len(setup_maze[0]) * CELL, HUD + len(setup_maze) * CELL


def draw_game(screen, font, setup, state, hud_extra=""):
    """setup = GAME_START body, state = STATE body (or None before the first tick)."""
    screen.fill(BG)
    for y, row in enumerate(setup["maze"]):
        for x, ch in enumerate(row):
            if ch == "#":
                pygame.draw.rect(screen, WALL, (x * CELL, HUD + y * CELL, CELL, CELL), border_radius=6)
    if state is None:
        return

    def center(x, y):
        return x * CELL + CELL // 2, HUD + y * CELL + CELL // 2

    blink = (pygame.time.get_ticks() // 250) % 2
    for x, y in state["pellets"]:
        pygame.draw.circle(screen, PELLET, center(x, y), 3)
    for x, y in state.get("power_pellets", []):
        pygame.draw.circle(screen, PELLET, center(x, y), 8 if blink else 6)
    powered = state.get("powered", {})
    for name, (x, y) in state["positions"].items():
        color = RGB.get(setup["colors"].get(name), TEXT)
        radius = CELL // 2 - 2
        left = powered.get(name, 0)
        if left and (left > 15 or blink):          # blink in the last 1.5 s
            pygame.draw.circle(screen, (255, 255, 255), center(x, y), radius + 3)
        pygame.draw.circle(screen, color, center(x, y), radius)

    hud = "   ".join(f"{n}: {s}" for n, s in state["scores"].items())
    secs = max(0, setup.get("max_ticks", 1200) - state["tick"]) // setup["tick_rate"]
    hud += f"   {secs // 60}:{secs % 60:02d}"
    if hud_extra:
        hud += "   " + hud_extra
    screen.blit(font.render(hud, True, TEXT), (10, 10))


def draw_lines(screen, font, lines, top=120, color=TEXT):
    """Centered text lines; a line can be (text, color)."""
    for i, line in enumerate(lines):
        text, c = line if isinstance(line, tuple) else (line, color)
        img = font.render(text, True, c)
        screen.blit(img, img.get_rect(center=(screen.get_width() // 2, top + i * 34)))
