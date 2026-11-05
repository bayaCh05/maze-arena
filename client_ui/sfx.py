"""Tiny synthesized sound effects (no audio files, no numpy). Silent if there is no audio device.

Call init() BEFORE pygame.init(); then Sfx().play("pellet"). M in the UI toggles mute.
"""

import array
import math

import pygame

RATE = 22050


def init():
    """Ask pygame for a small, low-latency mixer; call before pygame.init()."""
    pygame.mixer.pre_init(RATE, -16, 1, 256)


def _tone(notes, volume=0.35, wave="square", rate=RATE):
    """notes = [(frequency Hz or 0 for silence, seconds)] -> 16-bit mono samples."""
    out = array.array("h")
    for freq, secs in notes:
        n = int(rate * secs)
        for i in range(n):
            env = min(1.0, i / 200, (n - i) / 400)              # tiny attack/release: no clicks
            if freq == 0:
                v = 0.0
            elif wave == "square":
                v = 1.0 if math.sin(2 * math.pi * freq * i / rate) >= 0 else -1.0
            else:
                v = math.sin(2 * math.pi * freq * i / rate)
            out.append(int(32767 * volume * env * v))
    return out.tobytes()


SOUNDS = {
    "pellet": ([(660, 0.04), (440, 0.04)], 0.12, "square"),
    "power": ([(392, 0.07), (523, 0.07), (659, 0.07), (784, 0.12)], 0.18, "square"),
    "eaten": ([(523, 0.08), (392, 0.08), (262, 0.08), (196, 0.18)], 0.2, "square"),
    "start": ([(523, 0.1), (0, 0.04), (523, 0.1), (0, 0.04), (784, 0.25)], 0.2, "square"),
    "over": ([(784, 0.12), (659, 0.12), (523, 0.12), (659, 0.12), (784, 0.35)], 0.2, "sine"),
    "click": ([(880, 0.03)], 0.15, "sine"),
    "left": ([(330, 0.1), (247, 0.18)], 0.18, "sine"),
}


class Sfx:
    """The game's sound effects, generated at startup; play() is silent without audio."""

    def __init__(self):
        self.muted = False
        self.sounds = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(RATE, -16, 1, 256)
            rate, _fmt, channels = pygame.mixer.get_init()        # the device may not give us RATE
            for name, (notes, vol, wave) in SOUNDS.items():
                data = _tone(notes, vol, wave, rate)
                if channels == 2:                                   # some devices force stereo
                    mono = array.array("h", data)
                    data = array.array("h", (s for s in mono for _ in (0, 1))).tobytes()
                self.sounds[name] = pygame.mixer.Sound(buffer=data)
        except (pygame.error, NotImplementedError, TypeError):
            self.sounds = {}                                        # no audio: play() is a no-op

    def play(self, name):
        """Play a named sound unless muted."""
        if not self.muted and name in self.sounds:
            self.sounds[name].play()

    def toggle(self):
        """Mute/unmute; returns the new muted state."""
        self.muted = not self.muted
        return self.muted
