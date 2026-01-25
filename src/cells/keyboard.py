"""Terminal cbreak-mode keyboard input context manager."""

from __future__ import annotations

import os
import select
import sys
import termios
import tty

# Timeout (seconds) to wait for bytes following ESC
_ESC_TIMEOUT = 0.005

# CSI final byte → key name (no parameters)
_CSI_FINAL: dict[str, str] = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "H": "home",
    "F": "end",
    "Z": "shift_tab",
}

# CSI parameterized: (param, final) → key name
_CSI_PARAM: dict[tuple[str, str], str] = {
    ("2", "~"): "insert",
    ("3", "~"): "delete",
    ("5", "~"): "page_up",
    ("6", "~"): "page_down",
}

# SS3 (ESC O) sequences — alternate arrow/F-key encodings
_SS3: dict[str, str] = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "H": "home",
    "F": "end",
    "P": "f1",
    "Q": "f2",
    "R": "f3",
    "S": "f4",
}


class KeyboardInput:
    """Context manager that puts the terminal in cbreak mode for single-key reads.

    Usage:
        with KeyboardInput() as kb:
            key = kb.get_key()  # returns str | None (non-blocking)
    """

    def __init__(self):
        self._old_settings = None
        self._available = True
        self._fd: int = -1

    def __enter__(self):
        try:
            self._fd = sys.stdin.fileno()
            self._old_settings = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except (termios.error, OSError):
            self._available = False
        return self

    def __exit__(self, *args):
        if self._old_settings:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
            except (termios.error, OSError):
                pass

    def _read_byte(self, timeout: float = 0) -> bytes | None:
        """Read a single byte with optional timeout. Returns None if unavailable."""
        try:
            if select.select([self._fd], [], [], timeout)[0]:
                return os.read(self._fd, 1)
        except (OSError, ValueError):
            self._available = False
        return None

    def _read_escape_sequence(self) -> str:
        """After reading ESC, read and classify the full escape sequence.

        Handles CSI (ESC [), SS3 (ESC O), and bare ESC.
        Always drains the complete sequence to avoid leaving garbage in the buffer.
        """
        b = self._read_byte(_ESC_TIMEOUT)
        if b is None:
            return "escape"

        if b == b"[":
            return self._read_csi()

        if b == b"O":
            return self._read_ss3()

        # ESC followed by something else — treat as escape
        return "escape"

    def _read_csi(self) -> str:
        """Read a CSI sequence: parameter bytes, then final byte.

        CSI structure: ESC [ <params: 0x30-0x3F>* <intermediate: 0x20-0x2F>* <final: 0x40-0x7E>
        Drains all bytes through the final byte, returns named key or "escape".
        """
        params: list[bytes] = []
        while True:
            b = self._read_byte(_ESC_TIMEOUT)
            if b is None:
                return "escape"
            code = b[0]
            if 0x40 <= code <= 0x7E:
                # Final byte — sequence complete
                final = chr(code)
                param_str = b"".join(params).decode("ascii", errors="replace")
                if not param_str:
                    return _CSI_FINAL.get(final, "escape")
                # Strip modifier (e.g. "1;5" → param "1", ignore modifier)
                first_param = param_str.split(";")[0]
                return _CSI_PARAM.get((first_param, final), "escape")
            # Parameter or intermediate byte — accumulate
            params.append(b)

    def _read_ss3(self) -> str:
        """Read an SS3 sequence: ESC O <final byte>."""
        b = self._read_byte(_ESC_TIMEOUT)
        if b is None:
            return "escape"
        return _SS3.get(chr(b[0]), "escape")

    def get_key(self) -> str | None:
        """Non-blocking key read. Handles escape sequences atomically.

        Returns named keys ("up", "down", "left", "right", "home", "end",
        "escape", "backspace", "enter", "delete", "page_up", "page_down",
        "insert", "shift_tab", "f1"-"f4") or single character strings.
        Returns None if no key is available.
        """
        if not self._available:
            return None

        b = self._read_byte(0)
        if b is None:
            return None

        byte = b[0]

        if byte == 0x1B:
            return self._read_escape_sequence()
        if byte == 0x7F:
            return "backspace"
        if byte == 0x0D:
            return "enter"
        if byte == 0x09:
            return "tab"

        # Multi-byte UTF-8: determine expected length from leading byte
        if byte >= 0xF0:
            expected = 4
        elif byte >= 0xE0:
            expected = 3
        elif byte >= 0xC0:
            expected = 2
        else:
            return b.decode("utf-8", errors="replace")

        buf = bytearray(b)
        for _ in range(expected - 1):
            cont = self._read_byte(_ESC_TIMEOUT)
            if cont is None:
                break
            buf.extend(cont)
        return buf.decode("utf-8", errors="replace")
