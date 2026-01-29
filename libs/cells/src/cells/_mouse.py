"""Mouse input types and SGR protocol parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class MouseButton(Enum):
    """Mouse button identifiers."""

    LEFT = 0
    MIDDLE = 1
    RIGHT = 2
    NONE = 3  # Motion without button (or release in legacy mode)
    SCROLL_UP = 64
    SCROLL_DOWN = 65
    SCROLL_LEFT = 66
    SCROLL_RIGHT = 67


class MouseAction(Enum):
    """Type of mouse event."""

    PRESS = auto()
    RELEASE = auto()
    MOVE = auto()
    SCROLL = auto()


@dataclass(frozen=True, slots=True)
class MouseEvent:
    """A mouse event with position, button, and modifiers.

    Coordinates are 0-indexed (terminal reports 1-indexed, we convert).
    """

    action: MouseAction
    button: MouseButton
    x: int
    y: int
    shift: bool = False
    meta: bool = False
    ctrl: bool = False

    @property
    def is_scroll(self) -> bool:
        """True if this is a scroll wheel event."""
        return self.action == MouseAction.SCROLL

    @property
    def is_click(self) -> bool:
        """True if this is a button press (not scroll/move/release)."""
        return self.action == MouseAction.PRESS and self.button in (
            MouseButton.LEFT,
            MouseButton.MIDDLE,
            MouseButton.RIGHT,
        )

    @property
    def scroll_delta(self) -> int:
        """Return scroll direction: -1 for up, +1 for down, 0 for non-scroll."""
        if self.button == MouseButton.SCROLL_UP:
            return -1
        if self.button == MouseButton.SCROLL_DOWN:
            return 1
        return 0

    def translate(self, dx: int, dy: int) -> MouseEvent:
        """Return event with translated coordinates (for local coordinate systems)."""
        return MouseEvent(
            action=self.action,
            button=self.button,
            x=self.x - dx,
            y=self.y - dy,
            shift=self.shift,
            meta=self.meta,
            ctrl=self.ctrl,
        )


def parse_sgr_mouse(params: str, final: str) -> MouseEvent | None:
    """Parse SGR mouse sequence parameters.

    SGR format: CSI < Cb ; Cx ; Cy M (press) or CSI < Cb ; Cx ; Cy m (release)

    Args:
        params: The parameter string after '<' (e.g., "0;10;5")
        final: The final byte ('M' for press, 'm' for release)

    Returns:
        MouseEvent or None if malformed.
    """
    parts = params.split(";")
    if len(parts) != 3:
        return None

    try:
        cb = int(parts[0])
        cx = int(parts[1]) - 1  # Convert to 0-indexed
        cy = int(parts[2]) - 1
    except ValueError:
        return None

    # Clamp negative coordinates (shouldn't happen, but defensive)
    cx = max(0, cx)
    cy = max(0, cy)

    # Decode modifiers from bits 2-4
    shift = bool(cb & 4)
    meta = bool(cb & 8)
    ctrl = bool(cb & 16)

    # Bit 5 indicates motion event
    motion = bool(cb & 32)

    # Bits 6-7 indicate scroll wheel (64 = up, 65 = down, etc.)
    high_bits = cb & 192

    # Low bits indicate button (0=left, 1=middle, 2=right, 3=release/none)
    button_bits = cb & 3

    if high_bits >= 64:
        # Scroll wheel event
        scroll_button = high_bits + button_bits
        if scroll_button == 64:
            button = MouseButton.SCROLL_UP
        elif scroll_button == 65:
            button = MouseButton.SCROLL_DOWN
        elif scroll_button == 66:
            button = MouseButton.SCROLL_LEFT
        elif scroll_button == 67:
            button = MouseButton.SCROLL_RIGHT
        else:
            return None  # Unknown scroll value
        action = MouseAction.SCROLL
    elif motion:
        # Motion event (drag or hover)
        if button_bits == 3:
            button = MouseButton.NONE
        else:
            button = MouseButton(button_bits)
        action = MouseAction.MOVE
    else:
        # Regular button press/release
        if button_bits == 3:
            button = MouseButton.NONE
        else:
            button = MouseButton(button_bits)
        action = MouseAction.RELEASE if final == "m" else MouseAction.PRESS

    return MouseEvent(
        action=action,
        button=button,
        x=cx,
        y=cy,
        shift=shift,
        meta=meta,
        ctrl=ctrl,
    )
