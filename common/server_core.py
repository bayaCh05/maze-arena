"""Transport-independent server logic: login, lobby, rooms, game loop.

Used by tcp/server.py and udp/server.py, which only move bytes. A "session"
is any object with:
    name      None until LOGIN succeeds (set here)
    alive     False once the transport closed it
    send(msg) queue/send one message dict; must never block or raise
No networking imports here. The game thread is a timer, not network I/O.

All shared state is guarded by ONE lock, `GameServer.lock`: every critical
section is microseconds long, and a single lock cannot deadlock.
"""

import logging
import threading
import time

from common import game, rooms
from common.protocol import (
    CREATE_ROOM, GAME_OVER, GAME_START, HEARTBEAT, INPUT, JOIN_ROOM, LEAVE_ROOM,
    LIST_ROOMS, LOGIN, LOGIN_FAIL, LOGIN_OK, PING, PLAYER_LEFT, PONG, READY,
    ROOM_LIST, ROOM_UPDATE, STATE, make_msg, valid_name,
)


class GameRunner(threading.Thread):
    """Runs one room's game at TICK_RATE and broadcasts STATE."""

    def __init__(self, server, room, names, max_ticks):
        super().__init__(name=f"game-{room}", daemon=True)
        self.server = server
        self.room = room
        self.game = game.new_game(names, max_ticks=max_ticks)
        self.stopped = False

    def run(self):
        log = self.server.log
        period = 1 / game.TICK_RATE
        next_t = time.monotonic()
        try:
            while True:
                next_t += period
                delay = next_t - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -period:              # far behind: don't burst-tick
                    log.warning("game %s: tick late by %.0f ms", self.room, -delay * 1000)
                    next_t = time.monotonic()
                with self.server.lock:
                    if self.stopped:
                        return
                    if not game.is_over(self.game):     # a leave can end it between ticks
                        game.tick(self.game)
                        self.server.broadcast_game(self, make_msg(STATE, **game.get_state(self.game)))
                    if game.is_over(self.game):
                        self.server.finish_game(self)
                        return
        except Exception:
            log.exception("game %s crashed; ending it", self.room)
            with self.server.lock:
                self.server.finish_game(self)


class GameServer:
    def __init__(self, game_ticks=game.GAME_TICKS, log=None):
        self.game_ticks = game_ticks
        self.log = log or logging.getLogger("server")
        self.lock = threading.RLock()
        self.clients = {}           # name -> session (logged in)
        self.lobby = rooms.new_lobby()
        self.games = {}             # room -> GameRunner

    def stop(self):
        with self.lock:
            for runner in self.games.values():
                runner.stopped = True

    # ------------------------------------------------------------ messages

    def handle(self, session, msg):
        """Process one message from a session. Never raises for bad input."""
        t = msg["type"]
        if t in (PING, HEARTBEAT):              # no lock needed, answer fast
            session.send(make_msg(PONG, t=msg["t"]) if "t" in msg else make_msg(PONG))
            return
        with self.lock:
            if not session.alive:
                return
            if t == LOGIN:
                self._on_login(session, msg)
            elif session.name is None:
                # e.g. a UDP client the server already timed out: tell it (once) to log in again
                if not getattr(session, "told_to_login", False):
                    session.told_to_login = True
                    session.send(make_msg(LOGIN_FAIL, reason="not logged in"))
                    self.log.warning("%s sent %s before LOGIN", session, t)
            elif t == LIST_ROOMS:
                session.send(self._room_list())
            elif t == CREATE_ROOM:
                self._on_create_room(session, msg)
            elif t == JOIN_ROOM:
                self._on_join_room(session, msg)
            elif t == LEAVE_ROOM:
                self._leave_room(session, "left the room")
                session.send(self._room_list())
            elif t == READY:
                self._on_ready(session, msg)
            elif t == INPUT:
                self._on_input(session, msg)
            else:
                self.log.warning("%s sent unexpected %s, ignored", session, t)

    def _on_login(self, session, msg):
        name = msg.get("name")
        if session.name is not None:
            session.send(make_msg(LOGIN_FAIL, reason="already logged in"))
        elif not valid_name(name):
            session.send(make_msg(LOGIN_FAIL, reason="invalid name (1-12 characters)"))
            self.log.info("LOGIN_FAIL %s invalid name %r", session, name)
        elif name in self.clients:
            session.send(make_msg(LOGIN_FAIL, reason="name already taken"))
            self.log.info("LOGIN_FAIL %s name %r taken", session, name)
        else:
            session.name = name
            self.clients[name] = session
            session.send(make_msg(LOGIN_OK, name=name))
            self.log.info("LOGIN %s", session)

    def _on_create_room(self, session, msg):
        room = msg.get("room")
        try:
            rooms.create_room(self.lobby, room)
        except rooms.RoomError as exc:
            session.send(self._room_list(error=str(exc)))
            return
        self.log.info("ROOM CREATED %r by %s", room, session.name)
        self._broadcast_room_list()
        if rooms.room_of(self.lobby, session.name):   # creator already inside a room
            session.send(self._room_list())

    def _on_join_room(self, session, msg):
        room = msg.get("room")
        try:
            rooms.join_room(self.lobby, room, session.name)
        except rooms.RoomError as exc:
            session.send(self._room_list(error=str(exc)))
            return
        self.log.info("JOIN %s -> %r", session.name, room)
        self._send_room_update(room)
        self._broadcast_room_list()

    def _on_ready(self, session, msg):
        try:
            ready = msg.get("ready", True) is not False      # only a real false un-readies
            room = rooms.set_ready(self.lobby, session.name, ready)
        except rooms.RoomError as exc:
            session.send(self._room_list(error=str(exc)))
            return
        self.log.info("READY %s=%s in %r", session.name, ready, room)
        self._send_room_update(room)
        if rooms.can_start(self.lobby, room):
            self._start_game(room)

    def _on_input(self, session, msg):
        room = rooms.room_of(self.lobby, session.name)
        runner = self.games.get(room)
        if runner is not None:
            game.set_direction(runner.game, session.name, msg.get("dir"))

    # ------------------------------------------------------------ rooms & games

    def _members(self, room):
        names = [p["name"] for p in rooms.room_players(self.lobby, room)]
        return [self.clients[n] for n in names if n in self.clients]

    def _room_list(self, error=None):
        msg = make_msg(ROOM_LIST, rooms=rooms.list_rooms(self.lobby))
        if error:
            msg["error"] = error
        return msg

    def _broadcast_room_list(self):
        """Everyone in the lobby (logged in, not in a room) sees room changes."""
        msg = self._room_list()
        for name, session in self.clients.items():
            if rooms.room_of(self.lobby, name) is None:
                session.send(msg)

    def _send_room_update(self, room):
        msg = make_msg(ROOM_UPDATE, room=room, players=rooms.room_players(self.lobby, room))
        for session in self._members(room):
            session.send(msg)

    def _start_game(self, room):
        names = rooms.start_game(self.lobby, room)
        runner = GameRunner(self, room, names, self.game_ticks)
        self.games[room] = runner
        start = make_msg(GAME_START, room=room, **game.get_setup(runner.game))
        for session in self._members(room):
            session.send(start)
        self.log.info("GAME_START %r players=%s", room, names)
        self._broadcast_room_list()
        runner.start()

    def broadcast_game(self, runner, msg):
        """Send to the players still in this game (lock held)."""
        for name in runner.game["players"]:
            session = self.clients.get(name)
            if session is not None:
                session.send(msg)

    def finish_game(self, runner):
        """Called with the lock held, from the game thread."""
        runner.stopped = True
        if self.games.get(runner.room) is runner:
            del self.games[runner.room]
        ranking = game.get_ranking(runner.game)
        winner = game.get_winner(runner.game)
        self.broadcast_game(runner, make_msg(GAME_OVER, ranking=ranking, winner=winner))
        self.log.info("GAME_OVER %r tick=%d winner=%s ranking=%s",
                      runner.room, runner.game["tick"], winner, ranking)
        rooms.end_game(self.lobby, runner.room)
        if runner.room in self.lobby["rooms"]:
            self._send_room_update(runner.room)
        self._broadcast_room_list()

    def _leave_room(self, session, why):
        """Take a player out of their room (and game). Lock must be held."""
        name = session.name
        room = rooms.room_of(self.lobby, name)
        if room is None:
            return
        rooms.leave_room(self.lobby, name)
        runner = self.games.get(room)
        if runner is not None:
            game.remove_player(runner.game, name)   # game thread sends GAME_OVER if needed
        self.log.info("PLAYER_LEFT %s from %r (%s)%s", name, room, why,
                      " during game" if runner else "")
        left = make_msg(PLAYER_LEFT, name=name)
        for member in self._members(room):
            member.send(left)
        if room in self.lobby["rooms"]:
            self._send_room_update(room)
            if rooms.can_start(self.lobby, room):   # the only unready player left
                self._start_game(room)
        elif runner is not None:                    # room is empty: nobody to play for
            runner.stopped = True
            del self.games[room]
            self.log.info("GAME_ABORTED %r (no players left)", room)
        self._broadcast_room_list()

    def disconnect(self, session, reason):
        """The transport lost this session: free its name, room and game slot."""
        with self.lock:
            if session.name is not None and self.clients.get(session.name) is session:
                self._leave_room(session, reason)
                del self.clients[session.name]
