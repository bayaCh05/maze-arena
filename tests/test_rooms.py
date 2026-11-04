import pytest

from common import rooms as r


@pytest.fixture
def lobby():
    lobby = r.new_lobby()
    r.create_room(lobby, "arena1")
    return lobby


def test_create_and_list(lobby):
    assert r.list_rooms(lobby) == [
        {"room": "arena1", "players": 0, "max_players": 3, "in_game": False}]
    with pytest.raises(r.RoomError):
        r.create_room(lobby, "arena1")
    with pytest.raises(r.RoomError):
        r.create_room(lobby, "")


def test_join_and_update(lobby):
    r.join_room(lobby, "arena1", "alice")
    r.join_room(lobby, "arena1", "bob")
    assert r.room_players(lobby, "arena1") == [
        {"name": "alice", "ready": False}, {"name": "bob", "ready": False}]
    assert r.room_of(lobby, "bob") == "arena1"


def test_join_errors(lobby):
    with pytest.raises(r.RoomError):
        r.join_room(lobby, "nope", "alice")
    r.join_room(lobby, "arena1", "alice")
    with pytest.raises(r.RoomError):
        r.join_room(lobby, "arena1", "alice")
    r.join_room(lobby, "arena1", "bob")
    r.join_room(lobby, "arena1", "carol")
    with pytest.raises(r.RoomError):
        r.join_room(lobby, "arena1", "dave")      # full


def test_start_needs_two_ready_players(lobby):
    r.join_room(lobby, "arena1", "alice")
    r.set_ready(lobby, "alice")
    assert not r.can_start(lobby, "arena1")       # alone
    r.join_room(lobby, "arena1", "bob")
    assert not r.can_start(lobby, "arena1")       # bob not ready
    r.set_ready(lobby, "bob")
    assert r.can_start(lobby, "arena1")
    assert r.start_game(lobby, "arena1") == ["alice", "bob"]
    assert r.list_rooms(lobby)[0]["in_game"]
    with pytest.raises(r.RoomError):
        r.join_room(lobby, "arena1", "carol")     # game running
    with pytest.raises(r.RoomError):
        r.start_game(lobby, "arena1")


def test_unready(lobby):
    r.join_room(lobby, "arena1", "alice")
    r.join_room(lobby, "arena1", "bob")
    r.set_ready(lobby, "alice")
    r.set_ready(lobby, "bob")
    r.set_ready(lobby, "bob", False)
    assert not r.can_start(lobby, "arena1")


def test_ready_without_room():
    with pytest.raises(r.RoomError):
        r.set_ready(r.new_lobby(), "ghost")


def test_leave_and_empty_room_deleted(lobby):
    r.join_room(lobby, "arena1", "alice")
    r.join_room(lobby, "arena1", "bob")
    assert r.leave_room(lobby, "alice") == "arena1"
    assert r.room_players(lobby, "arena1") == [{"name": "bob", "ready": False}]
    assert r.leave_room(lobby, "bob") == "arena1"
    assert r.list_rooms(lobby) == []
    assert r.leave_room(lobby, "bob") is None      # safe on disconnect


def test_leave_makes_remaining_ready_players_startable(lobby):
    for n in ["alice", "bob", "carol"]:
        r.join_room(lobby, "arena1", n)
    r.set_ready(lobby, "alice")
    r.set_ready(lobby, "bob")
    r.leave_room(lobby, "carol")
    assert r.can_start(lobby, "arena1")


def test_end_game_resets_ready(lobby):
    r.join_room(lobby, "arena1", "alice")
    r.join_room(lobby, "arena1", "bob")
    r.set_ready(lobby, "alice")
    r.set_ready(lobby, "bob")
    r.start_game(lobby, "arena1")
    r.end_game(lobby, "arena1")
    assert not r.list_rooms(lobby)[0]["in_game"]
    assert not r.can_start(lobby, "arena1")


@pytest.mark.parametrize("bad", [[1], {"r": 1}, None, 5])
def test_join_with_non_string_room(lobby, bad):
    with pytest.raises(r.RoomError):
        r.join_room(lobby, bad, "alice")
