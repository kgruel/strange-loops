"""Runtime theme switching for fidelis.

Usage:
    from fidelis.themes import current_theme, use_theme, list_themes

    # Get current theme's styles
    style = current_theme().header_connected

    # Switch theme at runtime
    use_theme("dracula")

    # List available themes
    names = list_themes()
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from ..cell import Style, Color


@dataclass(frozen=True)
class Theme:
    """Immutable collection of semantic color tokens.

    A theme defines a palette of colors and derives semantic styles from them.
    All fields are immutable; to "modify" a theme, create a new one.

    Palette colors (Color = str | int | None):
        - primary: Main brand/accent color
        - secondary: Supporting accent
        - accent: Highlight, call-to-action
        - success: Positive state (connected, ok)
        - warning: Caution state
        - error: Negative state (failed, error)
        - muted: De-emphasized, dim content
        - text: Default text color
        - text_dim: Secondary text

    Background tones (int for 256-color compatibility):
        - bg_base: Primary background
        - bg_subtle: Slightly elevated (headers, footers)
        - bg_emphasis: Selected/highlighted rows
    """

    name: str

    # Palette
    primary: Color
    secondary: Color
    accent: Color
    success: Color
    warning: Color
    error: Color
    muted: Color
    text: Color
    text_dim: Color

    # Background tones (256-color ints for TUI compatibility)
    bg_base: int
    bg_subtle: int
    bg_emphasis: int

    # -- Derived styles (computed from palette) --

    # Header
    @property
    def header_base(self) -> Style:
        return Style(bg=self.bg_subtle)

    @property
    def header_bold(self) -> Style:
        return Style(bold=True)

    @property
    def header_dim(self) -> Style:
        return Style(dim=True)

    @property
    def header_connected(self) -> Style:
        return Style(fg=self.success)

    @property
    def header_error(self) -> Style:
        return Style(fg=self.error)

    @property
    def header_spinner(self) -> Style:
        return Style(fg=self.warning)

    @property
    def header_level_filter(self) -> Style:
        return Style(fg=self.accent)

    # Footer
    @property
    def footer_key(self) -> Style:
        return Style(bold=True, dim=True)

    @property
    def footer_dim(self) -> Style:
        return Style(dim=True)

    @property
    def footer_active_filter(self) -> Style:
        return Style(fg=self.accent, dim=True)

    # Filter input
    @property
    def filter_prompt(self) -> Style:
        return Style(fg=self.accent, bold=True)

    @property
    def filter_cursor(self) -> Style:
        return Style(reverse=True)

    # Selection & main area
    @property
    def selection_cursor(self) -> Style:
        return Style(fg=self.accent, bold=True)

    @property
    def selection_highlight(self) -> Style:
        return Style(bg=self.bg_emphasis)

    @property
    def source_dim(self) -> Style:
        return Style(dim=True)

    @property
    def debug_overlay(self) -> Style:
        return Style(fg=self.text, bg=self.bg_base)

    # Log levels
    def level_style(self, level: Optional[str]) -> Style:
        """Get style for a log level."""
        if level == "error":
            return Style(fg=self.error, bold=True)
        elif level == "warn":
            return Style(fg=self.warning)
        elif level == "info":
            return Style()
        elif level == "debug":
            return Style(dim=True)
        elif level == "trace":
            return Style(dim=True)
        else:
            return Style()

    @property
    def level_styles(self) -> dict[Optional[str], Style]:
        """Dict of level -> Style for backward compat."""
        return {
            "error": self.level_style("error"),
            "warn": self.level_style("warn"),
            "info": self.level_style("info"),
            "debug": self.level_style("debug"),
            "trace": self.level_style("trace"),
            None: self.level_style(None),
        }


# -- Built-in themes --

DEFAULT_THEME = Theme(
    name="default",
    primary="cyan",
    secondary="blue",
    accent="cyan",
    success="green",
    warning="yellow",
    error="red",
    muted="white",
    text="white",
    text_dim="white",
    bg_base=235,
    bg_subtle=236,
    bg_emphasis=237,
)

LIGHT_THEME = Theme(
    name="light",
    primary=25,   # Darker blue for better contrast on white
    secondary=30,  # Teal
    accent=25,    # Match primary
    success=28,   # Darker green for contrast
    warning=166,  # Darker orange for contrast
    error=124,    # Darker red for contrast
    muted=244,    # Medium gray (readable on white)
    text=235,     # Dark gray (good contrast)
    text_dim=244,
    bg_base=231,  # Pure white (#ffffff)
    bg_subtle=255, # Light gray
    bg_emphasis=254, # Slightly darker for selections
)

SOLARIZED_THEME = Theme(
    name="solarized",
    primary=37,   # Cyan
    secondary=33, # Blue
    accent=37,
    success=64,   # Green
    warning=136,  # Yellow
    error=160,    # Red
    muted=246,    # Base0
    text=254,     # Base2
    text_dim=246,
    bg_base=234,  # Base03
    bg_subtle=235,
    bg_emphasis=236,
)

DRACULA_THEME = Theme(
    name="dracula",
    primary=141,  # Purple
    secondary=212, # Pink
    accent=141,
    success=84,   # Green
    warning=228,  # Yellow
    error=210,    # Red/Orange
    muted=61,     # Comment gray
    text=253,     # Foreground
    text_dim=61,
    bg_base=235,  # Background
    bg_subtle=236,
    bg_emphasis=237,
)

NORD_THEME = Theme(
    name="nord",
    primary=110,  # Frost blue
    secondary=109,
    accent=110,
    success=108,  # Aurora green
    warning=179,  # Aurora yellow
    error=174,    # Aurora red
    muted=60,     # Polar night
    text=253,     # Snow storm
    text_dim=60,
    bg_base=236,  # Polar night
    bg_subtle=237,
    bg_emphasis=238,
)

CATPPUCCIN_THEME = Theme(
    name="catppuccin",
    primary=183,  # Mauve
    secondary=218, # Pink
    accent=183,
    success=120,  # Green
    warning=222,  # Yellow
    error=210,    # Red
    muted=243,    # Overlay
    text=255,     # Text
    text_dim=243,
    bg_base=235,  # Base
    bg_subtle=236,
    bg_emphasis=237,
)


# -- Theme registry --

_THEMES: dict[str, Theme] = {
    "default": DEFAULT_THEME,
    "light": LIGHT_THEME,
    "solarized": SOLARIZED_THEME,
    "dracula": DRACULA_THEME,
    "nord": NORD_THEME,
    "catppuccin": CATPPUCCIN_THEME,
}

_current_theme: ContextVar[Theme] = ContextVar("current_theme", default=DEFAULT_THEME)


def register_theme(theme: Theme) -> None:
    """Register a custom theme."""
    _THEMES[theme.name] = theme


def get_theme(name: str) -> Theme:
    """Get a theme by name. Raises KeyError if not found."""
    return _THEMES[name]


def list_themes() -> list[str]:
    """List all registered theme names."""
    return list(_THEMES.keys())


def current_theme() -> Theme:
    """Get the current theme."""
    return _current_theme.get()


def use_theme(name: str) -> None:
    """Switch to a named theme. Raises KeyError if not found."""
    _current_theme.set(_THEMES[name])


def set_theme(theme: Theme) -> None:
    """Set a theme instance directly (for custom themes)."""
    _current_theme.set(theme)


__all__ = [
    "Theme",
    "DEFAULT_THEME",
    "LIGHT_THEME",
    "SOLARIZED_THEME",
    "DRACULA_THEME",
    "NORD_THEME",
    "CATPPUCCIN_THEME",
    "register_theme",
    "get_theme",
    "list_themes",
    "current_theme",
    "use_theme",
    "set_theme",
]
