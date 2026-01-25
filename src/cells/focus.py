"""Focus management — tracks which component receives key events."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FocusRing:
    """Tracks which component is focused in a linear sequence."""

    items: list[str] = field(default_factory=list)
    current: int = 0

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
