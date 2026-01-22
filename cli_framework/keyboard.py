"""Terminal cbreak-mode keyboard input context manager."""

from __future__ import annotations

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

    def __enter__(self):
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, OSError):
            self._available = False
        return self

    def __exit__(self, *args):
        if self._old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            except (termios.error, OSError):
                pass

    def get_key(self) -> str | None:
        """Non-blocking single character read. Returns None if no key available."""
        if not self._available:
            return None
        import select
        try:
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
        except (OSError, ValueError):
            self._available = False
        return None
