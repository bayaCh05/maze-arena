"""Local single-player demo of common/game.py with pygame. No networking.

    python local_demo.py          # you alone
    python local_demo.py --bot    # + a random-walking bot, to try eating

Arrows/WASD move, R restarts, Esc quits.
"""

import argparse
import random

import pygame

from client_ui import render
from common import game as g

FPS = 60
TICK_MS = 1000 // g.TICK_RATE

KEYS = {
    pygame.K_UP: "UP", pygame.K_w: "UP",
    pygame.K_DOWN: "DOWN", pygame.K_s: "DOWN",
    pygame.K_LEFT: "LEFT", pygame.K_a: "LEFT",
    pygame.K_RIGHT: "RIGHT", pygame.K_d: "RIGHT",
}


def bot_move(game, name):
    """Keep going straight; at walls or occasionally, pick a random open direction."""
    p = game["players"][name]
    open_dirs = [d for d, (dx, dy) in g.DIRECTIONS.items()
                 if d != "NONE" and (p["x"] + dx, p["y"] + dy) not in game["walls"]]
    dx, dy = g.DIRECTIONS[p["dir"]]
    blocked = p["dir"] == "NONE" or (p["x"] + dx, p["y"] + dy) in game["walls"]
    if open_dirs and (blocked or random.random() < 0.2):
        g.set_direction(game, name, random.choice(open_dirs))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bot", action="store_true", help="add a random-walking bot")
    args = parser.parse_args()
    names = ["you", "bot"] if args.bot else ["you"]

    pygame.init()
    screen = pygame.display.set_mode(render.window_size(g.MAZE_MAP))
    pygame.display.set_caption("Maze Arena — local demo")
    font = pygame.font.SysFont(None, 30)
    clock = pygame.time.Clock()

    game = g.new_game(names)
    setup = g.get_setup(game)
    since_tick = 0
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    game = g.new_game(names)
                elif event.key in KEYS:
                    g.set_direction(game, "you", KEYS[event.key])

        # Fixed 10 ticks/s simulation, 60 fps rendering.
        since_tick += clock.tick(FPS)
        while since_tick >= TICK_MS:
            since_tick -= TICK_MS
            if args.bot and "bot" in game["players"]:
                bot_move(game, "bot")
            g.tick(game)

        state = g.get_state(game)
        power = state["powered"].get("you")
        render.draw_game(screen, font, setup, state, f"POWER {power / g.TICK_RATE:.1f}s" if power else "")
        if g.is_over(game):
            ranking = ", ".join(f"{r['name']} {r['score']}" for r in g.get_ranking(game))
            render.draw_lines(screen, font, ["GAME OVER", f"winner: {g.get_winner(game)}",
                                             ranking, "R = restart, Esc = quit"], top=180)
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    main()
