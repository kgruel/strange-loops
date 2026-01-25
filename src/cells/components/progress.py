"""Progress bar component: horizontal fill indicator."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..cell import Style, Cell
from ..block import Block


@dataclass(frozen=True)
class ProgressState:
    """Immutable progress state tracking a 0.0-1.0 value."""

    value: float = 0.0

    def set(self, value: float) -> ProgressState:
        """Set progress value, clamped to 0.0-1.0."""
        return replace(self, value=max(0.0, min(1.0, value)))


def progress_bar(
    state: ProgressState,
    width: int,
    *,
    filled_style: Style = Style(fg="green"),
    empty_style: Style = Style(dim=True),
    filled_char: str = "█",
    empty_char: str = "░",
) -> Block:
    """Render a horizontal progress bar."""
    filled_count = round(state.value * width)
    empty_count = width - filled_count

    cells = (
        [Cell(filled_char, filled_style)] * filled_count
        + [Cell(empty_char, empty_style)] * empty_count
    )
    return Block([cells], width)
