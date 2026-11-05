"""Room/lobby state: create, join, leave, ready, start. Pure logic: NO networking imports.

The lobby is a plain dict. Functions raise RoomError for refused actions;
the server turns that into a reply and keeps going.
"""

from common.game import MAX_PLAYERS

MIN_PLAYERS = 2
ROOM_NAME_MAX = 16


class RoomError(Exception):
    """A refused room request; the message is sent back to the client as ROOM_LIST.error."""


def new_lobby():
    """Empty lobby: rooms by name, and which room each player is in."""
    return {"rooms": {}, "player_room": {}}


def create_room(lobby, room):
    """Add an empty room; RoomError for a bad or existing name."""
    if (not isinstance(room, str) or not 1 <= len(room.strip()) <= ROOM_NAME_MAX
            or room != room.strip() or not room.isprintable()):
        raise RoomError("invalid room name")
    if room in lobby["rooms"]:
        raise RoomError("room already exists")
    lobby["rooms"][room] = {"players": [], "ready": {}, "in_game": False}


def list_rooms(lobby):
    """Body of ROOM_LIST: [{room, players, max_players, in_game}]."""
    return [
        {"room": name, "players": len(r["players"]),
         "max_players": MAX_PLAYERS, "in_game": r["in_game"]}
        for name, r in sorted(lobby["rooms"].items())
    ]


def join_room(lobby, room, name):
    """Put the player in the room; RoomError if unknown, full, playing, or already in a room."""
    r = lobby["rooms"].get(room) if isinstance(room, str) else None
    if r is None:
        raise RoomError("no such room")
    if name in lobby["player_room"]:
        raise RoomError("already in a room")
    if r["in_game"]:
        raise RoomError("game already running")
    if len(r["players"]) >= MAX_PLAYERS:
        raise RoomError("room is full")
    r["players"].append(name)
    r["ready"][name] = False
    lobby["player_room"][name] = room


def leave_room(lobby, name):
    """Remove the player from their room. Returns the room name, or None.

    Empty rooms are deleted. Safe to call for any name (used on disconnect).
    """
    room = lobby["player_room"].pop(name, None)
    if room is None:
        return None
    r = lobby["rooms"][room]
    r["players"].remove(name)
    r["ready"].pop(name, None)
    if not r["players"]:
        del lobby["rooms"][room]
    return room


def set_ready(lobby, name, ready=True):
    """Set the player's ready flag; returns their room. RoomError if not in a room or it's playing."""
    room = room_of(lobby, name)
    if room is None:
        raise RoomError("not in a room")
    r = lobby["rooms"][room]
    if r["in_game"]:
        raise RoomError("game already running")
    r["ready"][name] = bool(ready)
    return room


def room_of(lobby, name):
    """The player's room name, or None."""
    return lobby["player_room"].get(name)


def room_players(lobby, room):
    """Body of ROOM_UPDATE players: [{name, ready}] in join order."""
    r = lobby["rooms"].get(room)
    if r is None:
        return []
    return [{"name": n, "ready": r["ready"][n]} for n in r["players"]]


def can_start(lobby, room):
    """True when the room is idle, has >= 2 players and all of them are ready."""
    r = lobby["rooms"].get(room)
    return (r is not None and not r["in_game"]
            and len(r["players"]) >= MIN_PLAYERS
            and all(r["ready"].values()))


def start_game(lobby, room):
    """Mark the room as playing; returns the player names (join order)."""
    if not can_start(lobby, room):
        raise RoomError("room cannot start")
    r = lobby["rooms"][room]
    r["in_game"] = True
    return list(r["players"])


def end_game(lobby, room):
    """Back to the lobby state: not playing, nobody ready."""
    r = lobby["rooms"].get(room)
    if r is None:
        return
    r["in_game"] = False
    for n in r["ready"]:
        r["ready"][n] = False
