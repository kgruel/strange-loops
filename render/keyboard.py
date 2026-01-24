"""Terminal cbreak-mode keyboard input context manager."""

from __future__ import annotations

import os
import select
import sys
import termios
import tty

# Escape sequence mapping: suffix after ESC [ -> key name
_CSI_SEQUENCES: dict[str, str] = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "H": "home",
    "F": "end",
}

# Timeout (seconds) to wait for bytes following ESC
_ESC_TIMEOUT = 0.005


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
        """After reading ESC, try to read a CSI escape sequence.

        Returns a named key (e.g. "up") or "escape" if no sequence follows.
        """
        b = self._read_byte(_ESC_TIMEOUT)
        if b is None:
            return "escape"

        if b == b"[":
            # CSI sequence — read the final byte
            final = self._read_byte(_ESC_TIMEOUT)
            if final is not None:
                ch = final.decode("utf-8", errors="replace")
                if ch in _CSI_SEQUENCES:
                    return _CSI_SEQUENCES[ch]
            # Unknown CSI sequence — drop it
            return "escape"

        # ESC followed by something other than '[' — treat as escape
        return "escape"

    def get_key(self) -> str | None:
        """Non-blocking key read. Handles escape sequences atomically.

        Returns named keys ("up", "down", "left", "right", "home", "end",
        "escape", "backspace", "enter") or single character strings.
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

        return b.decode("utf-8", errors="replace")
