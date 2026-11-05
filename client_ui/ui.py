"""pygame UI. Talks only to a transport exposing send(msg) and on_message(callback).

    python -m client_ui.ui --proto tcp --host 192.168.1.10 --port 5050 [--name alice] [--room arena]

Screens: login -> lobby -> room -> game -> over -> room ...
Everything works with the keyboard (keys shown on screen) and with the mouse (buttons, room rows).
client_ui/connect.py is the only place that picks a transport class;
everything here uses the Transport interface (send / on_message / poll).
"""

import argparse
import math
import sys
import time

import pygame

from client_ui import render, sfx
from client_ui.connect import make_transport
from client_ui.render import ACCENT, BAD, BG, BORDER, DIM, GOOD, PANEL, PANEL_HI, TEXT
from common.game import COLORS, MAX_PLAYERS, MAZE_MAP
from common.protocol import (
    CREATE_ROOM, GAME_OVER, GAME_START, INPUT, JOIN_ROOM, LEAVE_ROOM, LIST_ROOMS,
    LOGIN, LOGIN_FAIL, LOGIN_OK, NAME_MAX, PLAYER_LEFT, READY, ROOM_LIST,
    ROOM_UPDATE, STATE, make_msg,
)
from common.rooms import ROOM_NAME_MAX

FPS = 60
KEYS = {
    pygame.K_UP: "UP", pygame.K_w: "UP",
    pygame.K_DOWN: "DOWN", pygame.K_s: "DOWN",
    pygame.K_LEFT: "LEFT", pygame.K_a: "LEFT",
    pygame.K_RIGHT: "RIGHT", pygame.K_d: "RIGHT",
}
MEDALS = [(255, 205, 50), (200, 205, 220), (205, 127, 50)]


class _Silent:
    muted = True

    def play(self, _name):
        pass

    def toggle(self):
        return True


class App:
    def __init__(self, transport, name=None, room=None, proto="tcp", sounds=None, subtitle=""):
        self.t = transport
        self.t.on_message(self.on_message)
        self.proto = proto
        self.sfx = sounds or _Silent()
        self.subtitle = subtitle
        self.screen_name = "login"
        self.text = name or ""            # text being typed (name or room)
        self.typing = "name"
        self.me = None
        self.auto_room = room
        self.rooms = []
        self.selected = 0
        self.room = None
        self.players = []
        self.view = None                  # render.GameView of the current game
        self.result = None
        self.my_dir = "NONE"
        self.toasts = []                  # [text, color, until]
        self.buttons = []                 # [(rect, action)], rebuilt every frame
        self.quit_requested = False
        self.logging_in = bool(name)
        if name:
            self.t.send(make_msg(LOGIN, name=name))

    def notify(self, text, color=TEXT, seconds=3.0):
        self.toasts.append([text, color, time.monotonic() + seconds])
        self.toasts = self.toasts[-3:]

    # ------------------------------------------------------------ network

    def on_message(self, msg):
        t = msg["type"]
        if t == LOGIN_OK:
            self.me = msg["name"]
            self.logging_in = False
            self.screen_name, self.typing, self.text = "lobby", None, ""
            self.t.send(make_msg(LIST_ROOMS))
            if self.auto_room:
                self.t.send(make_msg(CREATE_ROOM, room=self.auto_room))   # fails if it exists: fine
                self.t.send(make_msg(JOIN_ROOM, room=self.auto_room))
        elif t == LOGIN_FAIL:
            self.logging_in = False
            self.notify(f"Login refused: {msg.get('reason')}", BAD)
            self.screen_name, self.typing = "login", "name"
        elif t == ROOM_LIST:
            self.rooms = msg.get("rooms", [])
            self.selected = min(self.selected, max(0, len(self.rooms) - 1))
            if msg.get("error") and not (self.auto_room and msg["error"] == "room already exists"):
                self.notify(msg["error"].capitalize(), BAD)
        elif t == ROOM_UPDATE:
            self.room, self.players = msg["room"], msg["players"]
            if self.screen_name in ("lobby", "login"):
                self.screen_name = "room"
        elif t == GAME_START:
            self.view = render.GameView(msg, self.me, 1 / msg.get("tick_rate", 10))
            self.result, self.my_dir = None, "NONE"
            self.screen_name = "game"
            self.sfx.play("start")
        elif t == STATE:
            if self.view and (self.view.state is None or msg["tick"] > self.view.state["tick"]):
                for kind, name, other in self.view.update(msg):
                    self._game_event(kind, name, other)
        elif t == GAME_OVER:
            self.result = msg
            self.screen_name = "over"
            self.sfx.play("over")
        elif t == PLAYER_LEFT:
            self.notify(f"{msg['name']} left the game", DIM)
            self.sfx.play("left")

    def _game_event(self, kind, name, other):
        """Cosmetic reactions to what the server's STATE shows."""
        if kind == "pellet" and name == self.me:
            self.sfx.play("pellet")
        elif kind == "power":
            self.sfx.play("power")
            self.notify("You are POWERED UP! Eat them!" if name == self.me else f"{name} is powered up! Run!",
                        ACCENT if name == self.me else render.player_rgb(self.view.setup, name))
        elif kind == "eaten":
            self.sfx.play("eaten")
            color = BAD if name == self.me else GOOD if other == self.me else TEXT
            victim = "you" if name == self.me else name
            if other:
                eater = "You" if other == self.me else other
                self.notify(f"{eater} ate {victim}!", color)
            else:
                self.notify("You got eaten!" if name == self.me else f"{name} got eaten!", color)

    # ------------------------------------------------------------ actions (keys and buttons)

    def submit_text(self):
        value = self.text.strip()
        if not value:
            return
        if self.typing == "name":
            self.logging_in = True
            self.t.send(make_msg(LOGIN, name=value))
        else:
            self.t.send(make_msg(CREATE_ROOM, room=value))
            self.t.send(make_msg(JOIN_ROOM, room=value))
            self.typing, self.text = None, ""

    def start_create(self):
        self.typing, self.text = "room", ""

    def cancel_create(self):
        self.typing, self.text = None, ""

    def join(self, room):
        self.t.send(make_msg(JOIN_ROOM, room=room))

    def refresh(self):
        self.t.send(make_msg(LIST_ROOMS))

    def toggle_ready(self):
        ready = any(p["name"] == self.me and p["ready"] for p in self.players)
        self.t.send(make_msg(READY, ready=not ready))

    def leave_room(self):
        self.t.send(make_msg(LEAVE_ROOM))
        self.room, self.players = None, []
        self.screen_name = "lobby"

    def back_to_room(self):
        self.screen_name = "room"

    def quit(self):
        self.quit_requested = True

    # ------------------------------------------------------------ input

    def on_click(self, pos):
        for rect, action in self.buttons:
            if rect.collidepoint(pos):
                self.sfx.play("click")
                action()
                return

    def on_key(self, event):
        """Returns False to quit."""
        key = event.key
        if self.typing:
            limit = NAME_MAX if self.typing == "name" else ROOM_NAME_MAX
            if key == pygame.K_RETURN:
                self.submit_text()
            elif key == pygame.K_ESCAPE:
                if self.typing == "room":
                    self.cancel_create()
                else:
                    return False
            elif key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.unicode and event.unicode.isprintable() and len(self.text) < limit:
                self.text += event.unicode
            return True

        if key == pygame.K_m:
            self.notify("Sound off" if self.sfx.toggle() else "Sound on", DIM, 1.5)
            return True
        if not self.t.connected:
            return key != pygame.K_ESCAPE
        if self.screen_name == "lobby":
            if key == pygame.K_ESCAPE:
                return False
            if key == pygame.K_UP:
                self.selected = max(0, self.selected - 1)
            elif key == pygame.K_DOWN:
                self.selected = max(0, min(len(self.rooms) - 1, self.selected + 1))
            elif key == pygame.K_RETURN and self.rooms:
                self.join(self.rooms[self.selected]["room"])
            elif key == pygame.K_c:
                self.start_create()
            elif key == pygame.K_l:
                self.refresh()
        elif self.screen_name == "room":
            if key in (pygame.K_r, pygame.K_SPACE):
                self.toggle_ready()
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
                self.back_to_room()
            elif key == pygame.K_ESCAPE:
                self.leave_room()
        return True

    # ------------------------------------------------------------ drawing

    def net_lines(self):
        lines = [f"{self.proto.upper()}   RTT {self.t.rtt_ms:.0f} ms" if self.t.rtt_ms is not None
                 else f"{self.proto.upper()}   RTT ..."]
        lost, got = getattr(self.t, "states_lost", 0), getattr(self.t, "states_received", 0)
        if got:                                   # UDP only: STATE snapshots never received
            lines.append(f"lost {100 * lost / (lost + got):.0f} % of updates")
        return lines

    def btn(self, screen, fonts, rect, label, action, color=ACCENT, enabled=True):
        rect = pygame.Rect(rect)
        hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())
        render.button(screen, fonts, rect, label, hovered, color, enabled)
        if enabled:
            self.buttons.append((rect, action))

    def draw(self, screen, fonts):
        self.buttons = []
        if not self.t.connected:
            self.draw_disconnected(screen, fonts)
        elif self.screen_name == "game" and self.view:
            self.view.draw(screen, fonts, {
                "room": self.room, "proto": self.proto, "net": self.net_lines(),
                "hints": [("Arrows/WASD", "move"), ("Esc", "leave game"),
                          ("M", "unmute" if self.sfx.muted else "mute")]})
        elif self.screen_name == "login":
            self.draw_login(screen, fonts)
        elif self.screen_name == "lobby":
            self.draw_lobby(screen, fonts)
        elif self.screen_name == "room":
            self.draw_room(screen, fonts)
        elif self.screen_name == "over" and self.result:
            self.draw_over(screen, fonts)
        self.draw_toasts(screen, fonts)

    def draw_toasts(self, screen, fonts):
        now = time.monotonic()
        self.toasts = [t for t in self.toasts if t[2] > now]
        y = render.TOP + 14 if self.screen_name == "game" else 168
        cx = (screen.get_width() - render.SIDE) // 2 if self.screen_name == "game" else screen.get_width() // 2
        for msg, color, until in self.toasts:
            img = fonts.body.render(msg, True, color)
            box = img.get_rect(midtop=(cx, y)).inflate(32, 16)
            surf = pygame.Surface(box.size, pygame.SRCALPHA)
            alpha = int(235 * min(1, (until - now) / 0.3))
            pygame.draw.rect(surf, (*BG, alpha), surf.get_rect(), border_radius=12)
            pygame.draw.rect(surf, (*color, alpha), surf.get_rect(), width=2, border_radius=12)
            img.set_alpha(alpha)
            surf.blit(img, img.get_rect(center=surf.get_rect().center))
            screen.blit(surf, box)
            y += box.height + 8

    def input_box(self, screen, fonts, rect, placeholder):
        rect = pygame.Rect(rect)
        render.panel(screen, rect, BG, ACCENT, 12)
        cursor = "|" if int(time.monotonic() * 2.5) % 2 else ""
        if self.text:
            render.text(screen, fonts.mid, self.text + cursor, TEXT, (rect.x + 18, rect.centery), "midleft", False)
        else:
            render.text(screen, fonts.mid, placeholder, DIM, (rect.x + 18, rect.centery), "midleft", False)

    def draw_login(self, screen, fonts):
        render.menu_background(screen, fonts, self.subtitle)
        w, h = screen.get_size()
        card = pygame.Rect(0, 0, 520, 290)
        card.center = (w // 2, h // 2 + 50)
        render.panel(screen, card)
        render.text(screen, fonts.mid, "What's your name?", TEXT, (card.centerx, card.y + 42), "center")
        render.text(screen, fonts.small, f"1 to {NAME_MAX} characters, it must be unique on the server",
                    DIM, (card.centerx, card.y + 74), "center", False)
        self.input_box(screen, fonts, (card.x + 50, card.y + 100, card.width - 100, 58), "e.g. alice")
        label = "LOGGING IN..." if self.logging_in else "PLAY"
        self.btn(screen, fonts, (card.centerx - 110, card.y + 190, 220, 56), label, self.submit_text,
                 enabled=bool(self.text.strip()) and not self.logging_in)
        render.key_hints(screen, fonts, [("Enter", "play"), ("Esc", "quit")], w // 2, h - 40)

    def draw_lobby(self, screen, fonts):
        render.menu_background(screen, fonts, self.subtitle)
        w, h = screen.get_size()
        render.text(screen, fonts.mid, f"Hi {self.me}! Pick a room or create one.", TEXT, (w // 2, 190), "center")
        box = pygame.Rect(w // 2 - 320, 222, 640, h - 222 - 140)
        render.panel(screen, box)
        mouse = pygame.mouse.get_pos()
        if not self.rooms:
            render.text(screen, fonts.body, "No rooms yet. Create the first one!", DIM, box.center, "center", False)
        for i, r in enumerate(self.rooms[: (box.height - 16) // 62]):
            row = pygame.Rect(box.x + 12, box.y + 12 + i * 62, box.width - 24, 54)
            full = r["players"] >= r["max_players"]
            joinable = not r["in_game"] and not full
            hovered = row.collidepoint(mouse)
            selected = i == self.selected
            render.panel(screen, row, PANEL_HI if (hovered or selected) else BG,
                         ACCENT if selected else BORDER, 10)
            render.draw_pac(screen, render.RGB[COLORS[i % len(COLORS)]], (row.x + 30, row.centery), 14, "RIGHT", 0.35)
            render.text(screen, fonts.mid, r["room"], TEXT, (row.x + 56, row.centery), "midleft")
            for k in range(r["max_players"]):
                pygame.draw.circle(screen, GOOD if k < r["players"] else BORDER,
                                   (row.right - 200 + k * 22, row.centery), 7)
            status, color = ("PLAYING", BAD) if r["in_game"] else ("FULL", BAD) if full else ("JOIN", GOOD)
            render.text(screen, fonts.body, status, color, (row.right - 20, row.centery), "midright")
            if joinable:
                self.buttons.append((row, lambda room=r["room"]: self.join(room)))
        y = h - 120
        self.btn(screen, fonts, (w // 2 - 300, y, 220, 54), "+ CREATE ROOM", self.start_create)
        self.btn(screen, fonts, (w // 2 - 60, y, 160, 54), "REFRESH", self.refresh, DIM)
        self.btn(screen, fonts, (w // 2 + 120, y, 180, 54), "QUIT", self.quit, BAD)
        render.key_hints(screen, fonts, [("C", "create"), ("Up/Down", "select"), ("Enter", "join"),
                                         ("L", "refresh"), ("M", "sound"), ("Esc", "quit")], w // 2, h - 40)
        if self.typing == "room":
            self.draw_create_dialog(screen, fonts)

    def draw_create_dialog(self, screen, fonts):
        w, h = screen.get_size()
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        screen.blit(shade, (0, 0))
        self.buttons = []                                  # modal: only the dialog is clickable
        card = pygame.Rect(0, 0, 520, 270)
        card.center = (w // 2, h // 2)
        render.panel(screen, card)
        render.text(screen, fonts.mid, "New room", TEXT, (card.centerx, card.y + 40), "center")
        self.input_box(screen, fonts, (card.x + 50, card.y + 76, card.width - 100, 58), "e.g. demo")
        self.btn(screen, fonts, (card.x + 60, card.y + 175, 190, 54), "CREATE", self.submit_text,
                 enabled=bool(self.text.strip()))
        self.btn(screen, fonts, (card.right - 250, card.y + 175, 190, 54), "CANCEL", self.cancel_create, DIM)

    def draw_room(self, screen, fonts):
        render.menu_background(screen, fonts, self.subtitle)
        w, h = screen.get_size()
        render.text(screen, fonts.big, f"Room {self.room}", TEXT, (w // 2, 196), "center")
        render.text(screen, fonts.small, "The game starts when everyone in the room is ready (2 or 3 players)",
                    DIM, (w // 2, 232), "center", False)
        t = time.monotonic()
        card_w, gap = 220, 24
        x0 = w // 2 - (MAX_PLAYERS * card_w + (MAX_PLAYERS - 1) * gap) // 2
        for i in range(MAX_PLAYERS):
            card = pygame.Rect(x0 + i * (card_w + gap), 260, card_w, 200)
            if i < len(self.players):
                p = self.players[i]
                mine = p["name"] == self.me
                render.panel(screen, card, PANEL_HI if mine else PANEL, (255, 255, 255) if mine else BORDER)
                color = render.RGB[COLORS[i % len(COLORS)]]
                render.draw_pac(screen, color, (card.centerx, card.y + 62), 34, "RIGHT", abs(math.sin(t * 5 + i)))
                render.text(screen, fonts.mid, p["name"], color, (card.centerx, card.y + 124), "center")
                if mine:
                    render.text(screen, fonts.small, "(you)", TEXT, (card.centerx, card.y + 148), "center", False)
                status, c = ("READY", GOOD) if p["ready"] else ("not ready", DIM)
                render.text(screen, fonts.body, status, c, (card.centerx, card.bottom - 22), "center")
            else:
                pygame.draw.rect(screen, BORDER, card, width=2, border_radius=14)
                dots = "." * (1 + int(t * 2) % 3)
                render.text(screen, fonts.body, f"waiting{dots}", DIM, card.center, "center", False)
        me_ready = any(p["name"] == self.me and p["ready"] for p in self.players)
        y = h - 120
        self.btn(screen, fonts, (w // 2 - 250, y, 280, 56), "NOT READY" if me_ready else "I'M READY!",
                 self.toggle_ready, DIM if me_ready else GOOD)
        self.btn(screen, fonts, (w // 2 + 50, y, 200, 56), "LEAVE ROOM", self.leave_room, BAD)
        render.key_hints(screen, fonts, [("R", "ready / not ready"), ("M", "sound"), ("Esc", "leave room")],
                         w // 2, h - 40)

    def draw_over(self, screen, fonts):
        render.menu_background(screen, fonts, self.subtitle)
        w, h = screen.get_size()
        winner = self.result["winner"]
        colors = self.view.setup["colors"] if self.view else {}
        if winner is None:
            title, color = "DRAW!", ACCENT
        elif winner == self.me:
            title, color = "YOU WIN!", ACCENT
        else:
            title, color = f"{winner} WINS!", render.RGB.get(colors.get(winner), TEXT)
        render.text(screen, fonts.title, title, color, (w // 2, 200), "center")
        for k, r in enumerate(self.result["ranking"][:3]):
            row = pygame.Rect(w // 2 - 260, 250 + k * 70, 520, 60)
            mine = r["name"] == self.me
            render.panel(screen, row, PANEL_HI if mine else PANEL, (255, 255, 255) if mine else BORDER, 12)
            pygame.draw.circle(screen, MEDALS[k], (row.x + 32, row.centery), 18)
            render.text(screen, fonts.body, str(k + 1), BG, (row.x + 32, row.centery), "center", False)
            pc = render.RGB.get(colors.get(r["name"]), TEXT)
            render.draw_pac(screen, pc, (row.x + 80, row.centery), 15, "RIGHT", 0.35)
            render.text(screen, fonts.mid, r["name"] + ("  (you)" if mine else ""), pc, (row.x + 108, row.centery), "midleft")
            render.text(screen, fonts.mid, r["score"], TEXT, (row.right - 22, row.centery), "midright")
        y = h - 120
        self.btn(screen, fonts, (w // 2 - 250, y, 260, 56), "PLAY AGAIN", self.back_to_room, GOOD)
        self.btn(screen, fonts, (w // 2 + 30, y, 220, 56), "LEAVE ROOM", self.leave_room, BAD)
        render.key_hints(screen, fonts, [("Enter", "back to the room"), ("Esc", "leave room")], w // 2, h - 40)

    def draw_disconnected(self, screen, fonts):
        render.menu_background(screen, fonts, self.subtitle)
        w, h = screen.get_size()
        card = pygame.Rect(0, 0, 620, 260)
        card.center = (w // 2, h // 2 + 40)
        render.panel(screen, card, PANEL, BAD)
        render.text(screen, fonts.big, "Disconnected", BAD, (card.centerx, card.y + 50), "center")
        render.text(screen, fonts.body, self.t.close_reason or "connection lost", TEXT,
                    (card.centerx, card.y + 100), "center", False)
        render.text(screen, fonts.small, "Is the server still running? Test the path with scripts/netcheck.py",
                    DIM, (card.centerx, card.y + 134), "center", False)
        self.btn(screen, fonts, (card.centerx - 100, card.bottom - 80, 200, 54), "QUIT", self.quit, BAD)
        render.key_hints(screen, fonts, [("Esc", "quit")], w // 2, h - 40)


def window_icon():
    icon = pygame.Surface((32, 32), pygame.SRCALPHA)
    render.draw_pac(icon, ACCENT, (16, 16), 14, "RIGHT", 0.6)
    return icon


def main():
    parser = argparse.ArgumentParser(description="Maze Arena client")
    parser.add_argument("--proto", choices=["tcp", "udp"], default="tcp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--name", help="log in directly with this name")
    parser.add_argument("--room", help="create/join this room right after login")
    parser.add_argument("--drop", type=float, default=0.0, help="UDP only: drop this fraction of outgoing datagrams")
    parser.add_argument("--mute", action="store_true", help="start with sound off (M toggles it)")
    args = parser.parse_args()

    try:
        transport = make_transport(args.proto, args.host, args.port, args.drop)
    except (OSError, ValueError) as exc:
        sys.exit(f"cannot connect to {args.host}:{args.port} ({args.proto}): {exc}")

    sfx.init()
    pygame.init()
    pygame.display.set_icon(window_icon())
    screen = pygame.display.set_mode(render.window_size(MAZE_MAP))
    pygame.display.set_caption(f"Maze Arena ({args.proto.upper()}) {args.name or ''}")
    fonts = render.Fonts()
    clock = pygame.time.Clock()
    sounds = sfx.Sfx()
    sounds.muted = args.mute
    subtitle = f"{args.proto.upper()} server {args.host}:{args.port}" + (f"   drop {args.drop:.0%}" if args.drop else "")
    app = App(transport, args.name, args.room, args.proto, sounds, subtitle)

    running = True
    while running and not app.quit_requested:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                running = app.on_key(event) and running
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                app.on_click(event.pos)
        transport.poll()                       # run on_message callbacks here
        app.draw(screen, fonts)
        pygame.display.flip()
        clock.tick(FPS)
    transport.close()
    pygame.quit()


if __name__ == "__main__":
    main()
