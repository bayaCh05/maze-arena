import json
from collections import deque

import pytest

from common import game as g
from common.protocol import STATE, encode_udp, make_msg, UDP_SAFE_SIZE

#   x: 0123456
TINY = [
    "#######",   # y=0
    "#1..o2#",   # y=1
    "#.###.#",   # y=2
    "#.....#",   # y=3
    "#######",   # y=4
]


def tiny(*names):
    return g.new_game(names or ("a", "b"), maze=TINY)


def pos(game, name):
    p = game["players"][name]
    return (p["x"], p["y"])


def place(game, name, x, y):
    game["players"][name]["x"], game["players"][name]["y"] = x, y


# ---------------------------------------------------------------- maze

def test_maze_shape():
    walls, pellets, power, spawns = g.parse_maze(g.MAZE_MAP)
    assert (g.WIDTH, g.HEIGHT) == (20, 15)
    assert all(len(row) == 20 for row in g.MAZE_MAP)
    assert len(power) == 4
    assert len(spawns) == 3


def test_every_floor_cell_reachable():
    walls, pellets, power, spawns = g.parse_maze(g.MAZE_MAP)
    floor = {(x, y) for y in range(g.HEIGHT) for x in range(g.WIDTH)} - walls
    seen, todo = {spawns[0]}, deque([spawns[0]])
    while todo:
        x, y = todo.popleft()
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            n = (x + dx, y + dy)
            if n in floor and n not in seen:
                seen.add(n)
                todo.append(n)
    assert seen == floor


def test_new_game_validation():
    with pytest.raises(ValueError):
        g.new_game([])
    with pytest.raises(ValueError):
        g.new_game(["a", "b", "c", "d"])
    with pytest.raises(ValueError):
        g.new_game(["a", "a"])


def test_players_get_spawn_and_color():
    game = g.new_game(["a", "b", "c"])
    _, _, _, spawns = g.parse_maze(g.MAZE_MAP)
    assert [pos(game, n) for n in "abc"] == spawns
    assert len({game["players"][n]["color"] for n in "abc"}) == 3


# ---------------------------------------------------------------- movement

def test_moves_one_cell_per_tick():
    game = tiny()
    g.set_direction(game, "a", "RIGHT")
    g.tick(game)
    assert pos(game, "a") == (2, 1)
    g.tick(game)
    assert pos(game, "a") == (3, 1)


def test_direction_persists_and_none_stops():
    game = tiny()
    g.set_direction(game, "a", "DOWN")
    g.tick(game)
    g.tick(game)
    assert pos(game, "a") == (1, 3)
    g.set_direction(game, "a", "NONE")
    g.tick(game)
    assert pos(game, "a") == (1, 3)


def test_invalid_direction_and_unknown_player_ignored():
    game = tiny()
    g.set_direction(game, "a", "DIAGONAL")
    g.set_direction(game, "ghost", "UP")
    g.tick(game)
    assert pos(game, "a") == (1, 1)


def test_walls_block():
    game = tiny()
    g.set_direction(game, "a", "UP")       # (1,0) is a wall
    g.tick(game)
    assert pos(game, "a") == (1, 1)
    g.set_direction(game, "a", "LEFT")     # (0,1) is a wall
    g.tick(game)
    assert pos(game, "a") == (1, 1)


def test_blocked_then_turn():
    game = tiny()
    place(game, "a", 1, 3)
    g.set_direction(game, "a", "DOWN")     # wall below
    g.tick(game)
    assert pos(game, "a") == (1, 3)
    g.set_direction(game, "a", "RIGHT")
    g.tick(game)
    assert pos(game, "a") == (2, 3)


# ---------------------------------------------------------------- scoring

def test_pellet_scores_10_and_disappears():
    game = tiny()
    g.set_direction(game, "a", "RIGHT")
    g.tick(game)
    assert game["players"]["a"]["score"] == 10
    assert (2, 1) not in game["pellets"]
    g.set_direction(game, "a", "LEFT")     # back to spawn: nothing to eat
    g.tick(game)
    g.set_direction(game, "a", "RIGHT")    # pellet already gone
    g.tick(game)
    assert game["players"]["a"]["score"] == 10


def test_power_pellet_scores_50_and_powers_for_50_ticks():
    game = tiny()
    g.set_direction(game, "b", "LEFT")     # b: (5,1) -> (4,1) power pellet
    g.tick(game)
    b = game["players"]["b"]
    assert b["score"] == 50
    assert b["powered"] == g.POWER_TICKS == 50
    assert (4, 1) not in game["power_pellets"]
    g.set_direction(game, "b", "NONE")
    for _ in range(49):
        g.tick(game)
    assert b["powered"] == 1
    g.tick(game)
    assert b["powered"] == 0


# ---------------------------------------------------------------- eating

def test_powered_player_eats_opponent_on_same_cell():
    game = tiny()
    a = game["players"]["a"]
    a["score"] = 120
    game["players"]["b"]["powered"] = 10
    place(game, "a", 2, 1)
    place(game, "b", 4, 1)
    game["pellets"].clear()                # keep scores easy to read
    game["power_pellets"].clear()
    game["pellets"].add((1, 3))            # so the game is not over
    g.set_direction(game, "a", "RIGHT")    # both step into (3,1)
    g.set_direction(game, "b", "LEFT")
    g.tick(game)
    assert a["score"] == 70
    assert pos(game, "a") == (1, 1)        # respawned
    assert a["dir"] == "RIGHT"             # keeps going: same on TCP and UDP
    assert pos(game, "b") == (3, 1)
    assert game["players"]["b"]["score"] == 0


def test_eating_when_players_swap_cells():
    game = tiny()
    game["players"]["b"]["powered"] = 10
    place(game, "a", 2, 1)
    place(game, "b", 3, 1)
    g.set_direction(game, "a", "RIGHT")
    g.set_direction(game, "b", "LEFT")
    g.tick(game)
    assert pos(game, "a") == (1, 1)


def test_eaten_score_never_negative():
    game = tiny()
    game["players"]["b"]["powered"] = 10
    place(game, "a", 3, 3)
    place(game, "b", 3, 3)
    game["players"]["a"]["score"] = 20
    g.tick(game)
    assert game["players"]["a"]["score"] == 0


def test_victim_loses_power_on_respawn():
    game = tiny()
    a, b = game["players"]["a"], game["players"]["b"]
    b["powered"] = 10
    a["powered"] = 0
    place(game, "a", 3, 3)
    place(game, "b", 3, 3)
    g.tick(game)
    assert a["powered"] == 0 and pos(game, "a") == (1, 1)


def test_no_eating_when_both_or_neither_powered():
    for power_a, power_b in [(0, 0), (10, 10)]:
        game = tiny()
        game["players"]["a"]["powered"] = power_a
        game["players"]["b"]["powered"] = power_b
        place(game, "a", 3, 3)
        place(game, "b", 3, 3)
        g.tick(game)
        assert pos(game, "a") == pos(game, "b") == (3, 3)


# ---------------------------------------------------------------- end of game

def test_timer_ends_game_after_1200_ticks():
    game = g.new_game(["a", "b"])
    for _ in range(g.GAME_TICKS - 1):
        g.tick(game)
    assert not g.is_over(game)
    g.tick(game)
    assert g.is_over(game)
    assert game["tick"] == 1200
    g.tick(game)                           # ticking a finished game is a no-op
    assert game["tick"] == 1200


def test_game_ends_when_all_pellets_eaten():
    one_pellet = ["#####", "#1.2#", "#####"]
    game = g.new_game(["a", "b"], maze=one_pellet)
    g.set_direction(game, "a", "RIGHT")
    g.tick(game)
    assert g.is_over(game)
    assert g.get_winner(game) == "a"


def test_power_pellets_count_as_pellets_for_end():
    maze = ["#####", "#1o2#", "#####"]
    game = g.new_game(["a", "b"], maze=maze)
    assert not g.is_over(game)
    g.set_direction(game, "a", "RIGHT")
    g.tick(game)
    assert g.is_over(game)


def test_ranking_and_winner():
    game = g.new_game(["a", "b", "c"])
    for name, score in [("a", 30), ("b", 70), ("c", 30)]:
        game["players"][name]["score"] = score
    assert g.get_ranking(game) == [
        {"name": "b", "score": 70},
        {"name": "a", "score": 30},
        {"name": "c", "score": 30},
    ]
    assert g.get_winner(game) == "b"


def test_tie_for_first_place_has_no_winner():
    game = g.new_game(["a", "b", "c"])
    for name, score in [("a", 50), ("b", 50), ("c", 10)]:
        game["players"][name]["score"] = score
    assert g.get_winner(game) is None
    assert [r["name"] for r in g.get_ranking(game)] == ["a", "b", "c"]


# ---------------------------------------------------------------- removal

def test_remove_player():
    game = g.new_game(["a", "b", "c"])
    g.remove_player(game, "b")
    assert "b" not in game["players"]
    assert not g.is_over(game)
    assert [r["name"] for r in g.get_ranking(game)] == ["a", "c"]
    g.remove_player(game, "nobody")        # harmless
    g.tick(game)                           # still ticks fine


def test_last_player_standing_ends_game():
    game = g.new_game(["a", "b"])
    g.remove_player(game, "a")
    assert g.is_over(game)
    assert g.get_winner(game) == "b"


def test_single_player_game_is_not_over_at_start():
    game = g.new_game(["solo"])
    g.tick(game)
    assert not g.is_over(game)


# ---------------------------------------------------------------- state

def test_state_is_json_and_matches_contract():
    game = g.new_game(["alice", "bob", "carol"])
    g.tick(game)
    state = g.get_state(game)
    assert json.loads(json.dumps(state)) == state
    assert {"tick", "positions", "pellets", "scores"} <= set(state)
    assert state["positions"]["alice"] == list(pos(game, "alice"))


def test_full_state_fits_in_one_safe_datagram():
    game = g.new_game(["alice123456", "bob12345678", "carol123456"])
    msg = make_msg(STATE, **g.get_state(game))
    assert len(encode_udp(msg, seq=999999, ack=999999)) < UDP_SAFE_SIZE


def test_setup_is_json():
    setup = g.get_setup(g.new_game(["a", "b"]))
    assert json.loads(json.dumps(setup)) == setup
    assert setup["tick_rate"] == 10


def test_unhashable_direction_ignored():
    game = tiny()
    for bad in (["UP"], {"d": 1}, None, 3):
        g.set_direction(game, "a", bad)
    assert game["players"]["a"]["dir"] == "NONE"
