"""ComponentTheme: icons and styles for render components.

Provides theming for components like spinners, progress bars, tree lenses.
Separate from the app-level Theme (semantic colors for TUI chrome).

Usage:
    from fidelis.component_theme import ComponentTheme, Icons, component_theme

    # Use default theme
    theme = component_theme()
    print(theme.icons.check)  # ✓

    # Custom ASCII-only theme
    ascii_icons = Icons(
        spinner=("-", "\\\\", "|", "/"),
        check="[x]",
        cross="[!]",
    )
    ascii_theme = ComponentTheme(icons=ascii_icons)
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Sequence

from .cell import Style


@dataclass(frozen=True)
class Icons:
    """Icon sets for components."""

    # Spinner frames (tuple for immutability)
    spinner: Sequence[str] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    # Progress bar
    progress_filled: str = "█"
    progress_empty: str = "░"
    progress_partial: Sequence[str] = ("▏", "▎", "▍", "▌", "▋", "▊", "▉")

    # Tree branches
    tree_branch: str = "├─ "
    tree_last: str = "└─ "
    tree_pipe: str = "│  "
    tree_space: str = "   "

    # Status indicators
    check: str = "✓"
    cross: str = "✗"
    dot: str = "●"
    empty_dot: str = "○"
    arrow: str = "→"

    # Sparkline (8 levels, low to high)
    sparkline: str = "▁▂▃▄▅▆▇█"

    # Bar chart
    bar_filled: str = "█"
    bar_empty: str = "░"


# ASCII-compatible icon set
ASCII_ICONS = Icons(
    spinner=("-", "\\", "|", "/"),
    progress_filled="#",
    progress_empty="-",
    progress_partial=(".", ":", "|"),
    tree_branch="+-- ",
    tree_last="`-- ",
    tree_pipe="|   ",
    tree_space="    ",
    check="[x]",
    cross="[!]",
    dot="*",
    empty_dot="o",
    arrow="->",
    sparkline="_.-~^*#@",
    bar_filled="#",
    bar_empty="-",
)


@dataclass(frozen=True)
class ComponentTheme:
    """Theme for component rendering.

    Combines icons with semantic styles for consistent appearance.
    """

    icons: Icons = field(default_factory=Icons)

    # Semantic styles for components
    success: Style = field(default_factory=lambda: Style(fg="green"))
    warning: Style = field(default_factory=lambda: Style(fg="yellow"))
    error: Style = field(default_factory=lambda: Style(fg="red"))
    muted: Style = field(default_factory=lambda: Style(dim=True))
    accent: Style = field(default_factory=lambda: Style(fg="cyan"))
    bold: Style = field(default_factory=lambda: Style(bold=True))


# Default theme instance
DEFAULT_COMPONENT_THEME = ComponentTheme()

# ASCII theme for limited terminals
ASCII_COMPONENT_THEME = ComponentTheme(
    icons=ASCII_ICONS,
    # No color, just bold for emphasis
    success=Style(bold=True),
    warning=Style(bold=True),
    error=Style(bold=True),
    muted=Style(),
    accent=Style(bold=True),
    bold=Style(bold=True),
)

# Context variable for implicit theming
_component_theme: ContextVar[ComponentTheme] = ContextVar(
    "component_theme",
    default=DEFAULT_COMPONENT_THEME,
)


def component_theme() -> ComponentTheme:
    """Get current component theme."""
    return _component_theme.get()


def use_component_theme(theme: ComponentTheme) -> None:
    """Set component theme for current context."""
    _component_theme.set(theme)


def reset_component_theme() -> None:
    """Reset to default component theme."""
    _component_theme.set(DEFAULT_COMPONENT_THEME)
