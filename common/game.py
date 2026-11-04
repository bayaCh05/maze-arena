"""Maze, players, pellets, collisions, tick(). Pure logic: NO networking imports.

The game is a plain dict so it can be inspected, copied and tested easily.
The server owns the only real game; clients just render get_state() output.
"""

TICK_RATE = 10                 # ticks per second
GAME_TICKS = 2 * 60 * TICK_RATE  # 2 minutes
POWER_TICKS = 5 * TICK_RATE    # 5 seconds
PELLET_POINTS = 10
POWER_POINTS = 50
EAT_PENALTY = 50
MAX_PLAYERS = 3

# '#' wall, '.' pellet, 'o' power pellet, '1'-'3' spawn points (empty floor).
MAZE_MAP = [
    "####################",
    "#1.......##.......2#",
    "#o##.###.##.###.##o#",
    "#..................#",
    "#.##.#.######.#.##.#",
    "#....#...##...#....#",
    "####.###.##.###.####",
    "#........3.........#",
    "####.#.######.#.####",
    "#....#....##..#....#",
    "#.##.###.##.###.##.#",
    "#o.#............#.o#",
    "##.#.##.####.##.#.##",
    "#..................#",
    "####################",
]
WIDTH = len(MAZE_MAP[0])
HEIGHT = len(MAZE_MAP)

COLORS = ["yellow", "cyan", "magenta"]

DIRECTIONS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
    "NONE": (0, 0),
}


def parse_maze(rows):
    """Return (walls, pellets, power_pellets, spawns) from a string map."""
    walls, pellets, power = set(), set(), set()
    spawns = {}
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                walls.add((x, y))
            elif ch == ".":
                pellets.add((x, y))
            elif ch == "o":
                power.add((x, y))
            elif ch in "123":
                spawns[int(ch) - 1] = (x, y)
    return walls, pellets, power, [spawns[i] for i in sorted(spawns)]


def new_game(player_names, maze=MAZE_MAP, max_ticks=GAME_TICKS):
    names = list(player_names)
    if not 1 <= len(names) <= MAX_PLAYERS:
        raise ValueError(f"need 1..{MAX_PLAYERS} players, got {len(names)}")
    if len(set(names)) != len(names):
        raise ValueError("duplicate player names")

    walls, pellets, power, spawns = parse_maze(maze)
    players = {}
    for i, name in enumerate(names):
        x, y = spawns[i]
        players[name] = {
            "x": x, "y": y,
            "spawn": (x, y),
            "dir": "NONE",
            "color": COLORS[i],
            "score": 0,
            "powered": 0,   # ticks of power left
        }
    return {
        "maze": list(maze),
        "width": len(maze[0]),
        "height": len(maze),
        "walls": walls,
        "pellets": pellets,
        "power_pellets": power,
        "players": players,
        "tick": 0,
        "max_ticks": max_ticks,
        "started_with": len(names),
        "over": False,
    }


def set_direction(game, name, direction):
    """Remember the player's direction; applied at the next tick. Bad input is ignored."""
    player = game["players"].get(name)
    if player is not None and isinstance(direction, str) and direction in DIRECTIONS:
        player["dir"] = direction


def _respawn(player):
    player["x"], player["y"] = player["spawn"]
    player["dir"] = "NONE"
    player["powered"] = 0


def _eat(eater, victim):
    victim["score"] = max(0, victim["score"] - EAT_PENALTY)
    _respawn(victim)


def tick(game):
    """Advance the game by one tick. Does nothing once the game is over."""
    if game["over"]:
        return
    game["tick"] += 1
    players = game["players"]
    order = sorted(players)

    for name in order:
        p = players[name]
        if p["powered"] > 0:
            p["powered"] -= 1

    # Move: one cell per tick, a wall means stay in place.
    previous = {}
    for name in order:
        p = players[name]
        previous[name] = (p["x"], p["y"])
        dx, dy = DIRECTIONS[p["dir"]]
        nx, ny = p["x"] + dx, p["y"] + dy
        if (nx, ny) not in game["walls"]:
            p["x"], p["y"] = nx, ny

    # Pellets.
    for name in order:
        p = players[name]
        pos = (p["x"], p["y"])
        if pos in game["pellets"]:
            game["pellets"].discard(pos)
            p["score"] += PELLET_POINTS
        elif pos in game["power_pellets"]:
            game["power_pellets"].discard(pos)
            p["score"] += POWER_POINTS
            p["powered"] = POWER_TICKS

    # Collisions: same cell, or two players swapping cells (passing through).
    for i, a_name in enumerate(order):
        for b_name in order[i + 1:]:
            a, b = players[a_name], players[b_name]
            a_pos, b_pos = (a["x"], a["y"]), (b["x"], b["y"])
            same_cell = a_pos == b_pos
            swapped = a_pos == previous[b_name] and b_pos == previous[a_name]
            if not (same_cell or swapped):
                continue
            if a["powered"] and not b["powered"]:
                _eat(a, b)
            elif b["powered"] and not a["powered"]:
                _eat(b, a)

    _check_over(game)


def _check_over(game):
    no_pellets = not game["pellets"] and not game["power_pellets"]
    time_up = game["tick"] >= game["max_ticks"]
    alone = game["started_with"] >= 2 and len(game["players"]) <= 1
    if no_pellets or time_up or alone or not game["players"]:
        game["over"] = True


def remove_player(game, name):
    """Remove a player (left or disconnected). Unknown names are ignored."""
    game["players"].pop(name, None)
    _check_over(game)


def is_over(game):
    return game["over"]


def ticks_left(game):
    return max(0, game["max_ticks"] - game["tick"])


def get_state(game):
    """JSON-serializable snapshot, the body of a STATE message."""
    players = game["players"]
    return {
        "tick": game["tick"],
        "positions": {n: [p["x"], p["y"]] for n, p in players.items()},
        "pellets": sorted([x, y] for x, y in game["pellets"]),
        "power_pellets": sorted([x, y] for x, y in game["power_pellets"]),
        "scores": {n: p["score"] for n, p in players.items()},
        "powered": {n: p["powered"] for n, p in players.items()},
    }


def get_setup(game):
    """Static info sent once in GAME_START: maze, players, colors."""
    players = game["players"]
    return {
        "tick_rate": TICK_RATE,
        "max_ticks": game["max_ticks"],
        "maze": list(game["maze"]),
        "players": list(players),
        "colors": {n: p["color"] for n, p in players.items()},
    }


def get_ranking(game):
    """Players still in the game, best score first (ties: alphabetical)."""
    ranking = [{"name": n, "score": p["score"]} for n, p in game["players"].items()]
    ranking.sort(key=lambda r: (-r["score"], r["name"]))
    return ranking


def get_winner(game):
    ranking = get_ranking(game)
    return ranking[0]["name"] if ranking else None
