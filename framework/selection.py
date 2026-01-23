"""SelectionTracker — reactive selection state for list-based UIs.

A leaf primitive that owns an index Signal and provides movement/clamping logic.
Designed to pair with event_table()'s selected_idx parameter.

Usage:
    from framework import SelectionTracker

    sel = SelectionTracker()

    # In a key handler:
    sel.move(+1, len(items))   # move down
    sel.move(-1, len(items))   # move up

    # In render:
    table, scroll = event_table(rows, columns, max_rows, selected_idx=sel.value)

    # After list changes (e.g., filter update):
    sel.clamp(len(items))      # keep in bounds
    # or
    sel.reset()                # clear selection entirely
"""

from __future__ import annotations

from reaktiv import Signal


class SelectionTracker:
    """Signal-based selection state for use with event_table()."""

    def __init__(self) -> None:
        self.index: Signal[int | None] = Signal(None)

    def move(self, delta: int, list_len: int) -> None:
        """Move selection by delta, clamping to [0, list_len-1].

        If the list is empty, does nothing.
        If current selection is None, initializes to first (delta > 0) or last (delta < 0) item.
        """
        if list_len <= 0:
            return
        current = self.index()
        if current is None:
            new_idx = 0 if delta > 0 else list_len - 1
        else:
            new_idx = max(0, min(list_len - 1, current + delta))
        self.index.set(new_idx)

    def reset(self) -> None:
        """Reset selection to None."""
        self.index.set(None)

    def clamp(self, list_len: int) -> None:
        """Clamp current index to valid range, or reset if list is empty."""
        current = self.index()
        if current is None:
            return
        if list_len <= 0:
            self.index.set(None)
        elif current >= list_len:
            self.index.set(list_len - 1)

    @property
    def value(self) -> int | None:
        """Current selected index (reads the signal, triggering reactivity)."""
        return self.index()
