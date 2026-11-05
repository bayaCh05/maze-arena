"""common/protocol.py: encode/decode, TCP framing buffer, UDP transport fields, hostile input."""

import pytest

from common import protocol as p


def test_make_msg():
    assert p.make_msg(p.LOGIN, name="alice") == {"type": "LOGIN", "name": "alice"}
    with pytest.raises(p.ProtocolError):
        p.make_msg("HACK")


def test_encode_decode_roundtrip():
    msg = p.make_msg(p.STATE, tick=3, positions={"é": [1, 2]}, pellets=[], scores={})
    assert p.decode(p.encode(msg)) == msg


@pytest.mark.parametrize("data", [
    b"not json", b"[1,2]", b'{"name":"x"}', b'{"type":5}', b'{"type":"NOPE"}', b"\xff\xfe",
])
def test_decode_rejects_bad_input(data):
    with pytest.raises(p.ProtocolError):
        p.decode(data)


def test_valid_name():
    assert p.valid_name("alice")
    for bad in ["", " ", " bob", "x" * 13, None, 5, "a\nb", "a\x00", "tab\t", "zero\u200bwidth"]:
        assert not p.valid_name(bad)


# ---------------------------------------------------------------- TCP

def test_tcp_encoding_is_one_line():
    data = p.encode_tcp(p.make_msg(p.LOGIN, name="a\nb"))
    assert data.endswith(b"\n") and data.count(b"\n") == 1


def test_tcp_message_split_across_two_recvs():
    buf = p.TcpStreamBuffer()
    data = p.encode_tcp(p.make_msg(p.INPUT, dir="LEFT"))
    first, second = data[:7], data[7:]
    assert buf.feed(first) == []
    assert buf.pending() == 7
    assert buf.feed(second) == [{"type": "INPUT", "dir": "LEFT"}]
    assert buf.pending() == 0


def test_tcp_three_messages_in_one_recv():
    buf = p.TcpStreamBuffer()
    msgs = [p.make_msg(p.LOGIN, name="a"), p.make_msg(p.READY), p.make_msg(p.INPUT, dir="UP")]
    assert buf.feed(b"".join(p.encode_tcp(m) for m in msgs)) == msgs


def test_tcp_two_and_a_half_messages_then_rest():
    buf = p.TcpStreamBuffer()
    msgs = [p.make_msg(p.PING, t=1.5), p.make_msg(p.LIST_ROOMS), p.make_msg(p.LEAVE_ROOM)]
    stream = b"".join(p.encode_tcp(m) for m in msgs)
    cut = len(stream) - 5
    assert buf.feed(stream[:cut]) == msgs[:2]
    assert buf.feed(stream[cut:]) == msgs[2:]


def test_tcp_byte_by_byte_including_utf8():
    buf = p.TcpStreamBuffer()
    msg = p.make_msg(p.LOGIN, name="zoé")
    out = []
    for byte in p.encode_tcp(msg):
        out += buf.feed(bytes([byte]))
    assert out == [msg]


def test_tcp_bad_line_skipped_others_kept():
    buf = p.TcpStreamBuffer()
    out = buf.feed(b'garbage\n\n{"type":"READY"}\n')
    assert out == [{"type": "READY"}]
    assert buf.errors == 1


def test_tcp_buffer_overflow_raises():
    buf = p.TcpStreamBuffer(max_size=100)
    with pytest.raises(p.ProtocolError):
        buf.feed(b"x" * 101)


# ---------------------------------------------------------------- UDP

def test_udp_roundtrip_with_transport_fields():
    msg = p.make_msg(p.JOIN_ROOM, room="arena1")
    data = p.encode_udp(msg, seq=17, rel=True)
    decoded, meta = p.decode_udp(data)
    assert decoded == msg
    assert meta == p.UdpMeta(seq=17, ack=None, rel=True)


def test_udp_plain_message_has_no_transport_fields():
    data = p.encode_udp(p.make_msg(p.INPUT, dir="UP"))
    assert data == b'{"type":"INPUT","dir":"UP"}'
    assert p.decode_udp(data)[1] == p.UdpMeta(None, None, False)


def test_udp_ack():
    data = p.encode_udp(p.make_msg(p.ACK), seq=230, ack=17)
    msg, meta = p.decode_udp(data)
    assert msg == {"type": "ACK"} and meta.ack == 17 and meta.seq == 230


def test_udp_rejects_bad_seq():
    with pytest.raises(p.ProtocolError):
        p.decode_udp(b'{"type":"READY","seq":"7"}')


def test_udp_too_large():
    with pytest.raises(p.ProtocolError):
        p.encode_udp(p.make_msg(p.STATE, blob="x" * 70000))


def test_reliable_types_are_game_types():
    assert p.RELIABLE_TYPES <= p.GAME_TYPES
    assert p.STATE not in p.RELIABLE_TYPES and p.INPUT not in p.RELIABLE_TYPES


# ---------------------------------------------------------------- hostile input (robustness review)

@pytest.mark.parametrize("data", [
    b"[" * 100000,                        # RecursionError inside json
    b'{"type":"PING","t":NaN}',           # Python accepts NaN; we could not re-encode it
    b'{"type":"PING","t":Infinity}',
    b'{"type":"PING","t":-Infinity}',
])
def test_decode_rejects_hostile_json(data):
    with pytest.raises(p.ProtocolError):
        p.decode(data)


def test_tcp_buffer_survives_hostile_line():
    buf = p.TcpStreamBuffer()
    out = buf.feed(b"[" * 50000 + b'\n{"type":"READY"}\n')
    assert out == [{"type": "READY"}] and buf.errors == 1
