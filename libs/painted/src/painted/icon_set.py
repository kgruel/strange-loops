"""IconSet: glyph vocabulary for view rendering.

Replaces ComponentTheme.Icons. Style fields removed (those move to Palette).

Usage:
    from painted.icon_set import current_icons, use_icons, ASCII_ICONS

    icons = current_icons()
    fill = icons.progress_fill

    # Scoped override (context manager)
    with use_icons(ASCII_ICONS):
        ...
"""

from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar, Token
from contextlib import AbstractContextManager
from dataclasses import dataclass


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


class _IconsOverride(AbstractContextManager[None]):
    def __init__(self, token: Token[IconSet]) -> None:
        self._token = token
        self._active = True

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._active:
            _icons.reset(self._token)
            self._active = False
        return False


def current_icons() -> IconSet:
    """Get the ambient icon set."""

    return _icons.get()


def use_icons(icons: IconSet) -> AbstractContextManager[None]:
    """Set the ambient icon set for the current context.

    The icon set is set immediately (setter semantics) and the return value can be
    used as a context manager for scoped overrides:

        use_icons(ASCII_ICONS)  # global / ambient until changed again

        with use_icons(ASCII_ICONS):
            ...  # restored on exit
    """

    token = _icons.set(icons)
    return _IconsOverride(token)


def reset_icons() -> None:
    """Reset to the default icon set."""

    _icons.set(_DEFAULT_ICONS)
