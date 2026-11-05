"""Message types, constructors, encoding and framing helpers. No sockets here.

Contract: .claude/skills/protocol-contract/SKILL.md (change both together).
"""

import json
from collections import namedtuple

# Login
LOGIN = "LOGIN"
LOGIN_OK = "LOGIN_OK"
LOGIN_FAIL = "LOGIN_FAIL"
# Lobby
LIST_ROOMS = "LIST_ROOMS"
CREATE_ROOM = "CREATE_ROOM"
ROOM_LIST = "ROOM_LIST"
JOIN_ROOM = "JOIN_ROOM"
LEAVE_ROOM = "LEAVE_ROOM"
READY = "READY"
ROOM_UPDATE = "ROOM_UPDATE"
# Game
GAME_START = "GAME_START"
INPUT = "INPUT"
STATE = "STATE"
GAME_OVER = "GAME_OVER"
# Liveness
PING = "PING"
PONG = "PONG"
HEARTBEAT = "HEARTBEAT"
PLAYER_LEFT = "PLAYER_LEFT"
# UDP transport only (never reaches the game layer)
ACK = "ACK"

GAME_TYPES = frozenset({
    LOGIN, LOGIN_OK, LOGIN_FAIL,
    LIST_ROOMS, CREATE_ROOM, ROOM_LIST, JOIN_ROOM, LEAVE_ROOM, READY, ROOM_UPDATE,
    GAME_START, INPUT, STATE, GAME_OVER,
    PING, PONG, HEARTBEAT, PLAYER_LEFT,
})
ALL_TYPES = GAME_TYPES | {ACK}

# UDP: messages sent with rel=True (acked + retransmitted).
RELIABLE_TYPES = frozenset({
    LOGIN, LOGIN_OK, LOGIN_FAIL,
    LIST_ROOMS, CREATE_ROOM, ROOM_LIST, JOIN_ROOM, LEAVE_ROOM, READY, ROOM_UPDATE,
    GAME_START, GAME_OVER, PLAYER_LEFT,
})

DIRECTIONS = ("UP", "DOWN", "LEFT", "RIGHT", "NONE")
NAME_MAX = 12

PING_INTERVAL = 1.0           # seconds between client PINGs (also act as heartbeats)
HEARTBEAT_TIMEOUT = 5.0       # seconds of silence before a peer is considered gone

TCP_MAX_BUFFER = 64 * 1024     # bytes without a newline before we give up on a client
UDP_MAX_DATAGRAM = 65507       # hard limit of a UDP payload over IPv4
UDP_SAFE_SIZE = 1400           # stay under this to avoid IP fragmentation

TRANSPORT_FIELDS = ("seq", "ack", "rel")


class ProtocolError(Exception):
    """Malformed or unknown message. Callers drop the message, never crash."""


def make_msg(msg_type, **fields):
    if msg_type not in ALL_TYPES:
        raise ProtocolError(f"unknown message type: {msg_type!r}")
    msg = {"type": msg_type}
    msg.update(fields)
    return msg


def valid_name(name):
    return (isinstance(name, str) and 1 <= len(name.strip()) <= NAME_MAX
            and name == name.strip() and name.isprintable())


def encode(msg):
    return json.dumps(msg, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def decode(data):
    try:
        # parse_constant: Python's json accepts NaN/Infinity, which we could not re-encode.
        msg = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except RecursionError:
        raise ProtocolError("JSON nested too deeply") from None
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(f"bad JSON: {exc}") from None
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise ProtocolError("message must be an object with a string 'type'")
    if msg["type"] not in ALL_TYPES:
        raise ProtocolError(f"unknown message type: {msg['type']!r}")
    return msg


# ---------------------------------------------------------------- TCP

def encode_tcp(msg):
    """One message = one line of compact JSON."""
    return encode(msg) + b"\n"


class TcpStreamBuffer:
    """Turns a TCP byte stream into whole messages.

    One recv() may hold half a message or several; feed() keeps the
    unfinished tail for the next call. Bad lines are skipped and counted.
    """

    def __init__(self, max_size=TCP_MAX_BUFFER):
        self.max_size = max_size
        self._buf = b""
        self.errors = 0

    def feed(self, data):
        self._buf += data
        messages = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                messages.append(decode(line))
            except ProtocolError:
                self.errors += 1
        if len(self._buf) > self.max_size:
            raise ProtocolError("line too long without newline")
        return messages

    def pending(self):
        """Bytes of an unfinished message waiting for more data."""
        return len(self._buf)


# ---------------------------------------------------------------- UDP

UdpMeta = namedtuple("UdpMeta", "seq ack rel")


def encode_udp(msg, seq=None, ack=None, rel=False):
    """One message = one datagram, with optional transport fields."""
    out = {k: v for k, v in msg.items() if k not in TRANSPORT_FIELDS}
    if seq is not None:
        out["seq"] = seq
    if ack is not None:
        out["ack"] = ack
    if rel:
        out["rel"] = True
    data = encode(out)
    if len(data) > UDP_MAX_DATAGRAM:
        raise ProtocolError(f"datagram too large: {len(data)} bytes")
    return data


def decode_udp(data):
    """Return (msg without transport fields, UdpMeta)."""
    msg = decode(data)
    seq, ack = msg.pop("seq", None), msg.pop("ack", None)
    rel = msg.pop("rel", False) is True
    for value in (seq, ack):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise ProtocolError("seq/ack must be integers")
    return msg, UdpMeta(seq, ack, rel)
