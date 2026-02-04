"""Progress bar component: horizontal fill indicator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..cell import Style, Cell
from ..block import Block

if TYPE_CHECKING:
    from ..component_theme import ComponentTheme


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
    theme: "ComponentTheme | None" = None,
) -> Block:
    """Render a horizontal progress bar.

    Args:
        state: Current progress state (0.0-1.0).
        width: Width in characters.
        filled_style: Style for filled portion. Defaults to theme.accent or green.
        empty_style: Style for empty portion. Defaults to theme.muted or dim.
        filled_char: Character for filled portion. Defaults to theme icon or "█".
        empty_char: Character for empty portion. Defaults to theme icon or "░".
        theme: Optional ComponentTheme for icons and styles.

    Returns:
        Block with rendered progress bar.
    """
    # Resolve characters from theme or defaults
    if theme is not None:
        filled_char = filled_char or theme.icons.progress_filled
        empty_char = empty_char or theme.icons.progress_empty
        filled_style = filled_style or theme.accent
        empty_style = empty_style or theme.muted
    else:
        filled_char = filled_char or "█"
        empty_char = empty_char or "░"
        filled_style = filled_style or Style(fg="green")
        empty_style = empty_style or Style(dim=True)

    filled_count = round(state.value * width)
    empty_count = width - filled_count

    cells = (
        [Cell(filled_char, filled_style)] * filled_count
        + [Cell(empty_char, empty_style)] * empty_count
    )
    return Block([cells], width)
