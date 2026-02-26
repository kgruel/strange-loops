"""Progress bar component: horizontal fill indicator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..cell import Style, Cell
from ..block import Block

if TYPE_CHECKING:
    from ..icon_set import IconSet
    from ..palette import Palette


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
    filled_style: Style | None = None,
    empty_style: Style | None = None,
    filled_char: str | None = None,
    empty_char: str | None = None,
    palette: "Palette | None" = None,
    icons: "IconSet | None" = None,
) -> Block:
    """Render a horizontal progress bar.

    Args:
        state: Current progress state (0.0-1.0).
        width: Width in characters.
        filled_style: Style for filled portion. Defaults to palette.accent + bold.
        empty_style: Style for empty portion. Defaults to palette.muted.
        filled_char: Character for filled portion. Defaults to icons.progress_fill.
        empty_char: Character for empty portion. Defaults to icons.progress_empty.
        palette: Optional Palette override (uses ambient if None).
        icons: Optional IconSet override (uses ambient if None).

    Returns:
        Block with rendered progress bar.
    """
    from ..icon_set import current_icons
    from ..palette import current_palette

    p = palette or current_palette()
    ic = icons or current_icons()

    filled_char = filled_char or ic.progress_fill
    empty_char = empty_char or ic.progress_empty
    filled_style = filled_style or p.accent.merge(Style(bold=True))
    empty_style = empty_style or p.muted

    filled_count = round(state.value * width)
    empty_count = width - filled_count

    cells = (
        [Cell(filled_char, filled_style)] * filled_count
        + [Cell(empty_char, empty_style)] * empty_count
    )
    return Block([cells], width)
