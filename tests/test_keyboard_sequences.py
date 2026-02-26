"""Tests for VT-style escape sequences and UTF-8 assembly."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from painted.tui import KeyboardInput


def _bytes_stream(data: bytes) -> list[bytes]:
    return [bytes([b]) for b in data]


def _get_input_from_stream(stream: list[bytes | None]):
    kb = KeyboardInput()
    kb._available = True

    it = iter(stream)

    def _read_byte(_timeout: float = 0):
        try:
            return next(it)
        except StopIteration:
            return None

    with patch.object(kb, "_read_byte", side_effect=_read_byte):
        return kb.get_input()


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        (b"\x1b[A", "up"),
        (b"\x1b[B", "down"),
        (b"\x1b[C", "right"),
        (b"\x1b[D", "left"),
        (b"\x1b[H", "home"),
        (b"\x1b[F", "end"),
        (b"\x1b[Z", "shift_tab"),
    ],
)
def test_csi_final_mappings(seq: bytes, expected: str):
    assert _get_input_from_stream(_bytes_stream(seq)) == expected


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        (b"\x1bOA", "up"),
        (b"\x1bOB", "down"),
        (b"\x1bOC", "right"),
        (b"\x1bOD", "left"),
        (b"\x1bOH", "home"),
        (b"\x1bOF", "end"),
        (b"\x1bOP", "f1"),
        (b"\x1bOQ", "f2"),
        (b"\x1bOR", "f3"),
        (b"\x1bOS", "f4"),
    ],
)
def test_ss3_mappings(seq: bytes, expected: str):
    assert _get_input_from_stream(_bytes_stream(seq)) == expected


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        (b"\x1b[2~", "insert"),
        (b"\x1b[3~", "delete"),
        (b"\x1b[5~", "page_up"),
        (b"\x1b[6~", "page_down"),
        (b"\x1b[3;5~", "delete"),  # strip modifier
    ],
)
def test_csi_parameterized_mappings(seq: bytes, expected: str):
    assert _get_input_from_stream(_bytes_stream(seq)) == expected


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        (b"\x1b[1;5A", "up"),
        (b"\x1b[1;2B", "down"),
        (b"\x1b[1;3C", "right"),
        (b"\x1b[1;4D", "left"),
        (b"\x1b[1;5H", "home"),
        (b"\x1b[1;5F", "end"),
    ],
)
def test_csi_modifier_variants_return_base_key(seq: bytes, expected: str):
    assert _get_input_from_stream(_bytes_stream(seq)) == expected


def test_bare_escape_timeout_returns_escape():
    assert _get_input_from_stream([b"\x1b", None]) == "escape"


@pytest.mark.parametrize(
    ("text",),
    [
        ("é",),
        ("€",),
        ("😀",),
    ],
)
def test_utf8_multibyte_assembly(text: str):
    data = text.encode("utf-8")
    assert _get_input_from_stream(_bytes_stream(data)) == text


def test_utf8_incomplete_sequence_degrades_gracefully():
    # 0xC3 expects one continuation byte; omit it.
    assert _get_input_from_stream([b"\xC3", None]) == "�"


@pytest.mark.parametrize(
    "stream",
    [
        [b"\x1b", b"[", None],
        [b"\x1b", b"[", b"2", None],
        [b"\x1b", b"[", b"<", None],
    ],
)
def test_incomplete_escape_sequences_return_escape(stream: list[bytes | None]):
    assert _get_input_from_stream(stream) == "escape"


def test_unknown_csi_final_returns_escape():
    assert _get_input_from_stream(_bytes_stream(b"\x1b[X")) == "escape"


# --- Alt key handling ---


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        (b"\x1ba", "alt_a"),
        (b"\x1bA", "alt_A"),
        (b"\x1b1", "alt_1"),
        (b"\x1b ", "alt_ "),
        (b"\x1b~", "alt_~"),
    ],
)
def test_alt_key_combinations(seq: bytes, expected: str):
    assert _get_input_from_stream(_bytes_stream(seq)) == expected


def test_esc_bracket_still_routes_to_csi():
    """ESC + '[' must route to CSI, not alt_[."""
    assert _get_input_from_stream(_bytes_stream(b"\x1b[A")) == "up"


def test_esc_o_still_routes_to_ss3():
    """ESC + 'O' must route to SS3, not alt_O."""
    assert _get_input_from_stream(_bytes_stream(b"\x1bOP")) == "f1"


def test_esc_followed_by_control_byte_returns_escape():
    """ESC + non-printable (e.g. 0x01) returns plain escape."""
    assert _get_input_from_stream([b"\x1b", b"\x01"]) == "escape"


# --- UTF-8 continuation timeout ---


def test_utf8_continuation_uses_generous_timeout():
    """Continuation bytes should be read with _UTF8_CONT_TIMEOUT, not _ESC_TIMEOUT."""
    from painted.keyboard import _UTF8_CONT_TIMEOUT

    kb = KeyboardInput()
    kb._available = True

    timeouts: list[float] = []
    # é = 0xC3 0xA9 (2-byte UTF-8)
    stream = iter([b"\xC3", b"\xA9"])

    original_read_byte = kb._read_byte

    def _tracking_read_byte(timeout: float = 0):
        timeouts.append(timeout)
        try:
            return next(stream)
        except StopIteration:
            return None

    with patch.object(kb, "_read_byte", side_effect=_tracking_read_byte):
        result = kb.get_input()

    assert result == "é"
    # First call is non-blocking (timeout=0), second is the continuation read
    assert len(timeouts) == 2
    assert timeouts[0] == 0  # initial read
    assert timeouts[1] == _UTF8_CONT_TIMEOUT  # continuation read
