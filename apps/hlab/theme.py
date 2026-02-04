"""Theme — centralized styling for hlab CLI display.

Zoom adds detail to the same view structure. Higher zoom = more
information visible, not a different presentation mode.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Icons:
    """Status and structure icons."""

    healthy: str = "+"
    unhealthy: str = "x"
    branch: str = "├─"
    branch_last: str = "└─"
    continuation: str = "│  "
    continuation_last: str = "   "
    selected: str = "▸"
    spinner: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


@dataclass(frozen=True)
class Colors:
    """Color scheme for status display."""

    success: str = "green"
    error: str = "red"
    accent: str = "cyan"
    muted: str = "dim"
    selected_fg: str = "black"
    selected_bg: str = "cyan"


@dataclass(frozen=True)
class Theme:
    """Combined theme with icons and colors."""

    icons: Icons = None  # type: ignore[assignment]
    colors: Colors = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Use object.__setattr__ because frozen=True
        if self.icons is None:
            object.__setattr__(self, "icons", Icons())
        if self.colors is None:
            object.__setattr__(self, "colors", Colors())


DEFAULT_THEME = Theme()
