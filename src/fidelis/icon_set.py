"""IconSet: glyph vocabulary for view rendering.

Replaces ComponentTheme.Icons. Style fields removed (those move to Palette).

Usage:
    from fidelis.icon_set import current_icons, use_icons, ASCII_ICONS

    icons = current_icons()
    fill = icons.progress_fill
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class IconSet:
    """Named glyph slots for view rendering.

    Covers both capability adaptation (ASCII fallback) and user preference
    (DOTS vs BRAILLE spinner frames).
    """

    # Spinner frames
    spinner: Sequence[str] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    # Progress bar
    progress_fill: str = "█"
    progress_empty: str = "░"

    # Tree branches
    tree_branch: str = "├─ "
    tree_last: str = "└─ "
    tree_indent: str = "│  "
    tree_space: str = "   "

    # Status indicators
    check: str = "✓"
    cross: str = "✗"

    # Sparkline (8 levels, low to high)
    sparkline: tuple[str, ...] = ("▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")

    # Bar chart
    bar_fill: str = "█"
    bar_empty: str = "░"


ASCII_ICONS = IconSet(
    spinner=("-", "\\", "|", "/"),
    progress_fill="#",
    progress_empty="-",
    tree_branch="+-- ",
    tree_last="`-- ",
    tree_indent="|   ",
    tree_space="    ",
    check="[x]",
    cross="[!]",
    sparkline=("_", ".", "-", "~", "^", "*", "#", "@"),
    bar_fill="#",
    bar_empty="-",
)


# --- ContextVar delivery ---

_DEFAULT_ICONS = IconSet()

_icons: ContextVar[IconSet] = ContextVar("icons", default=_DEFAULT_ICONS)


def current_icons() -> IconSet:
    """Get the ambient icon set."""

    return _icons.get()


def use_icons(icons: IconSet) -> None:
    """Set the ambient icon set for the current context."""

    _icons.set(icons)


def reset_icons() -> None:
    """Reset to the default icon set."""

    _icons.set(_DEFAULT_ICONS)

