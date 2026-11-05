"""pygame UI. Talks only to a transport exposing send(msg) and on_message(callback).

    python -m client_ui.ui --proto tcp --host 192.168.1.10 --port 5050 [--name alice] [--room arena]

Screens: login -> lobby -> room -> game -> over -> room ...
client_ui/connect.py is the only place that picks a transport class;
everything here uses the Transport interface (send / on_message / poll).
"""

import argparse
import sys
import time

import pygame

from client_ui import render
from client_ui.connect import make_transport
from common.game import MAZE_MAP
from common.protocol import (
    CREATE_ROOM, GAME_OVER, GAME_START, INPUT, JOIN_ROOM, LEAVE_ROOM, LIST_ROOMS,
    LOGIN, LOGIN_FAIL, LOGIN_OK, NAME_MAX, PLAYER_LEFT, READY, ROOM_LIST,
    ROOM_UPDATE, STATE, make_msg,
)

FPS = 60
KEYS = {
    pygame.K_UP: "UP", pygame.K_w: "UP",
    pygame.K_DOWN: "DOWN", pygame.K_s: "DOWN",
    pygame.K_LEFT: "LEFT", pygame.K_a: "LEFT",
    pygame.K_RIGHT: "RIGHT", pygame.K_d: "RIGHT",
}


class App:
    def __init__(self, transport, name=None, room=None):
        self.t = transport
        self.t.on_message(self.on_message)
        self.screen_name = "login"
        self.text = name or ""            # text being typed (name or room)
        self.typing = "name"
        self.me = None
        self.auto_room = room
        self.rooms = []
        self.selected = 0
        self.room = None
        self.players = []
        self.setup = None
        self.state = None
        self.result = None
        self.my_dir = "NONE"
        self.banner, self.banner_until = "", 0
        if name:
            self.t.send(make_msg(LOGIN, name=name))

    def notify(self, text, seconds=3):
        self.banner, self.banner_until = text, time.monotonic() + seconds

    # ------------------------------------------------------------ network

    def on_message(self, msg):
        t = msg["type"]
        if t == LOGIN_OK:
            self.me = msg["name"]
            self.screen_name, self.typing, self.text = "lobby", None, ""
            self.t.send(make_msg(LIST_ROOMS))
            if self.auto_room:
                self.t.send(make_msg(CREATE_ROOM, room=self.auto_room))   # fails if it exists: fine
                self.t.send(make_msg(JOIN_ROOM, room=self.auto_room))
        elif t == LOGIN_FAIL:
            self.notify(f"Login refused: {msg.get('reason')}")
            self.screen_name, self.typing = "login", "name"
        elif t == ROOM_LIST:
            self.rooms = msg.get("rooms", [])
            self.selected = min(self.selected, max(0, len(self.rooms) - 1))
            if msg.get("error") and not (self.auto_room and msg["error"] == "room already exists"):
                self.notify(msg["error"])
        elif t == ROOM_UPDATE:
            self.room, self.players = msg["room"], msg["players"]
            if self.screen_name in ("lobby", "login"):
                self.screen_name = "room"
        elif t == GAME_START:
            self.setup, self.state, self.my_dir = msg, None, "NONE"
            self.screen_name = "game"
        elif t == STATE:
            if self.state is None or msg["tick"] > self.state["tick"]:
                self.state = msg
        elif t == GAME_OVER:
            self.result = msg
            self.screen_name = "over"
        elif t == PLAYER_LEFT:
            self.notify(f"{msg['name']} left")

    # ------------------------------------------------------------ input

    def on_key(self, event):
        key = event.key
        if self.typing:
            if key == pygame.K_RETURN and self.text.strip():
                if self.typing == "name":
                    self.t.send(make_msg(LOGIN, name=self.text.strip()))
                else:
                    self.t.send(make_msg(CREATE_ROOM, room=self.text.strip()))
                    self.t.send(make_msg(JOIN_ROOM, room=self.text.strip()))
                    self.typing, self.text = None, ""
            elif key == pygame.K_ESCAPE and self.typing == "room":
                self.typing, self.text = None, ""
            elif key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.unicode.isprintable() and event.unicode and len(self.text) < NAME_MAX + 4:
                self.text += event.unicode
            return True

        if self.screen_name == "lobby":
            if key == pygame.K_ESCAPE:
                return False
            if key == pygame.K_UP:
                self.selected = max(0, self.selected - 1)
            elif key == pygame.K_DOWN:
                self.selected = max(0, min(len(self.rooms) - 1, self.selected + 1))
            elif key == pygame.K_RETURN and self.rooms:
                self.t.send(make_msg(JOIN_ROOM, room=self.rooms[self.selected]["room"]))
            elif key == pygame.K_c:
                self.typing, self.text = "room", ""
            elif key == pygame.K_l:
                self.t.send(make_msg(LIST_ROOMS))
        elif self.screen_name == "room":
            if key in (pygame.K_r, pygame.K_SPACE):
                ready = any(p["name"] == self.me and p["ready"] for p in self.players)
                self.t.send(make_msg(READY, ready=not ready))
            elif key == pygame.K_ESCAPE:
                self.leave_room()
        elif self.screen_name == "game":
            if key in KEYS:                    # always send: the same key must work again after a respawn
                self.my_dir = KEYS[key]
                self.t.send(make_msg(INPUT, dir=self.my_dir))
            elif key == pygame.K_ESCAPE:
                self.leave_room()
        elif self.screen_name == "over":
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                self.screen_name = "room"
            elif key == pygame.K_ESCAPE:
                self.leave_room()
        elif key == pygame.K_ESCAPE:                  # disconnected screen
            return False
        return True

    def leave_room(self):
        self.t.send(make_msg(LEAVE_ROOM))
        self.room, self.players = None, []
        self.screen_name = "lobby"

    # ------------------------------------------------------------ drawing

    def draw(self, screen, font, small):
        rtt = f"RTT {self.t.rtt_ms:.0f} ms" if self.t.rtt_ms is not None else ""
        lost, got = getattr(self.t, "states_lost", 0), getattr(self.t, "states_received", 0)
        if got:                                   # UDP only: STATE snapshots never received
            rtt += f"  lost {100 * lost / (lost + got):.0f} %"
        if not self.t.connected:
            screen.fill(render.BG)
            render.draw_lines(screen, font, ["Disconnected", self.t.close_reason or "", "", "Esc = quit"])
        elif self.screen_name == "game" and self.setup:
            render.draw_game(screen, font, self.setup, self.state, rtt)
        else:
            screen.fill(render.BG)
            render.draw_lines(screen, font, self.menu_lines())
        if rtt and self.screen_name != "game":
            screen.blit(small.render(rtt, True, render.DIM), (10, 10))
        if self.banner and time.monotonic() < self.banner_until:
            img = font.render(self.banner, True, (255, 120, 120))
            screen.blit(img, img.get_rect(midbottom=(screen.get_width() // 2, screen.get_height() - 10)))

    def menu_lines(self):
        cursor = "_" if (pygame.time.get_ticks() // 400) % 2 else " "
        if self.screen_name == "login":
            return ["MAZE ARENA", "", "Your name:", self.text + cursor, "", ("Enter = login", render.DIM)]
        if self.screen_name == "lobby":
            lines = [f"Lobby — {self.me}", ""]
            if self.typing == "room":
                return lines + ["New room name:", self.text + cursor, "", ("Enter = create, Esc = cancel", render.DIM)]
            if not self.rooms:
                lines.append(("no rooms yet", render.DIM))
            for i, r in enumerate(self.rooms):
                mark = ">" if i == self.selected else " "
                status = "playing" if r["in_game"] else f"{r['players']}/{r['max_players']}"
                lines.append(f"{mark} {r['room']}  ({status})")
            return lines + ["", ("Up/Down + Enter = join   C = create   L = refresh   Esc = quit", render.DIM)]
        if self.screen_name == "room":
            lines = [f"Room {self.room}", ""]
            for p in self.players:
                lines.append((f"{p['name']}  {'READY' if p['ready'] else '...'}",
                              (120, 255, 120) if p["ready"] else render.TEXT))
            return lines + ["", ("R = toggle ready (starts when all ready, 2+ players)   Esc = leave", render.DIM)]
        if self.screen_name == "over" and self.result:
            winner = self.result["winner"]
            lines = ["GAME OVER", f"Winner: {winner}" if winner else "Draw", ""]
            lines += [f"{i + 1}. {r['name']}  {r['score']}" for i, r in enumerate(self.result["ranking"])]
            return lines + ["", ("Enter = back to room   Esc = leave room", render.DIM)]
        return ["..."]


def main():
    parser = argparse.ArgumentParser(description="Maze Arena client")
    parser.add_argument("--proto", choices=["tcp", "udp"], default="tcp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--name", help="log in directly with this name")
    parser.add_argument("--room", help="create/join this room right after login")
    parser.add_argument("--drop", type=float, default=0.0, help="UDP only: drop this fraction of outgoing datagrams")
    args = parser.parse_args()

    try:
        transport = make_transport(args.proto, args.host, args.port, args.drop)
    except (OSError, ValueError) as exc:
        sys.exit(f"cannot connect to {args.host}:{args.port} ({args.proto}): {exc}")

    pygame.init()
    screen = pygame.display.set_mode(render.window_size(MAZE_MAP))
    pygame.display.set_caption(f"Maze Arena ({args.proto.upper()}) {args.name or ''}")
    font = pygame.font.SysFont(None, 30)
    small = pygame.font.SysFont(None, 22)
    clock = pygame.time.Clock()
    app = App(transport, args.name, args.room)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                running = app.on_key(event)
        transport.poll()                       # run on_message callbacks here
        app.draw(screen, font, small)
        pygame.display.flip()
        clock.tick(FPS)
    transport.close()
    pygame.quit()


if __name__ == "__main__":
    main()
