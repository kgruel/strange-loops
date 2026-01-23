"""Terminal cbreak-mode keyboard input context manager."""

from __future__ import annotations

import os
import select
import sys
import termios
import tty


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

    def get_key(self) -> str | None:
        """Non-blocking single byte read. Returns None if no key available."""
        if not self._available:
            return None
        try:
            if select.select([self._fd], [], [], 0)[0]:
                b = os.read(self._fd, 1)
                return b.decode("utf-8", errors="replace") if b else None
        except (OSError, ValueError):
            self._available = False
        return None
