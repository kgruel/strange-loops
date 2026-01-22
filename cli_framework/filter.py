"""Base filter pattern and filter history management."""

from __future__ import annotations

from reaktiv import Signal


class FilterHistory:
    """Manages a deduped, bounded history of filter strings.

    Wraps a Signal[list[str]] so changes trigger reaktiv dependencies.
    """

    def __init__(self, max_size: int = 5):
        self._max_size = max_size
        self.entries: Signal[list[str]] = Signal([])

    def push(self, raw: str) -> None:
        """Add a filter string to history (deduped, most recent first)."""
        if not raw.strip():
            return
        self.entries.update(
            lambda h: ([raw] + [x for x in h if x != raw])[: self._max_size]
        )

    @property
    def latest(self) -> str | None:
        """Most recent filter string, or None."""
        entries = self.entries()
        return entries[0] if entries else None
