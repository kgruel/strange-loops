"""Focus management — primitives and navigation patterns."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Focus:
    """Immutable focus state primitive.

    Tracks what's focused and whether the focused component has captured
    keyboard input (two-tier focus: navigation vs widget interaction).
    """

    id: str
    captured: bool = False

    def focus(self, id: str) -> Focus:
        """Return new Focus on the given id, releasing capture."""
        return Focus(id=id, captured=False)

    def capture(self) -> Focus:
        """Return new Focus with keyboard captured by current component."""
        return replace(self, captured=True)

    def release(self) -> Focus:
        """Return new Focus with keyboard released to navigation."""
        return replace(self, captured=False)

    def toggle_capture(self) -> Focus:
        """Return new Focus with capture toggled."""
        return replace(self, captured=not self.captured)


# Navigation patterns — pure functions operating on sequences


def ring_next(items: Sequence[str], current: str) -> str:
    """Move to next item in ring, wrapping at end."""
    if not items:
        return current
    try:
        idx = list(items).index(current)
        return items[(idx + 1) % len(items)]
    except ValueError:
        return items[0] if items else current


def ring_prev(items: Sequence[str], current: str) -> str:
    """Move to previous item in ring, wrapping at start."""
    if not items:
        return current
    try:
        idx = list(items).index(current)
        return items[(idx - 1) % len(items)]
    except ValueError:
        return items[0] if items else current


def linear_next(items: Sequence[str], current: str) -> str:
    """Move to next item, stopping at end."""
    if not items:
        return current
    try:
        idx = list(items).index(current)
        if idx < len(items) - 1:
            return items[idx + 1]
        return current
    except ValueError:
        return items[0] if items else current


def linear_prev(items: Sequence[str], current: str) -> str:
    """Move to previous item, stopping at start."""
    if not items:
        return current
    try:
        idx = list(items).index(current)
        if idx > 0:
            return items[idx - 1]
        return current
    except ValueError:
        return items[0] if items else current


# Legacy FocusRing for backwards compatibility


@dataclass
class FocusRing:
    """Tracks which component is focused in a linear sequence.

    Note: Consider using Focus + navigation functions for new code.
    FocusRing is mutable; Focus is immutable.
    """

    items: list[str]
    current: int = 0

    def __init__(self, items: list[str] | None = None, current: int = 0):
        self.items = items if items is not None else []
        self.current = current

    def next(self) -> None:
        """Move focus to the next item, wrapping around."""
        if self.items:
            self.current = (self.current + 1) % len(self.items)

    def prev(self) -> None:
        """Move focus to the previous item, wrapping around."""
        if self.items:
            self.current = (self.current - 1) % len(self.items)

    def focus(self, id: str) -> None:
        """Focus a specific item by ID. No-op if not found."""
        try:
            self.current = self.items.index(id)
        except ValueError:
            pass

    @property
    def focused(self) -> str:
        """Return the currently focused item ID."""
        if not self.items:
            return ""
        return self.items[self.current]
