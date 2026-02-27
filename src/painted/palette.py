"""Palette: semantic Style roles for aesthetic personalization.

5 roles mapping to Style (not Color) — carries both color and modifier
fallbacks for monochrome output.

Usage:
    from painted.palette import current_palette, use_palette, MONO_PALETTE

    p = current_palette()
    fill_style = p.accent.merge(Style(bold=True))

    # Override ambient palette
    use_palette(MONO_PALETTE)
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from .cell import Style


@dataclass(frozen=True)
class Palette:
    """Semantic style roles for aesthetic personalization.

    Each role is a Style (not a Color) so that monochrome palettes can
    use modifiers (bold, reverse, dim) for differentiation.
    """

    success: Style = field(default_factory=lambda: Style(fg="green"))
    warning: Style = field(default_factory=lambda: Style(fg="yellow"))
    error: Style = field(default_factory=lambda: Style(fg="red"))
    accent: Style = field(default_factory=lambda: Style(fg="cyan"))
    muted: Style = field(default_factory=lambda: Style(dim=True))


# --- Presets ---

DEFAULT_PALETTE = Palette()

NORD_PALETTE = Palette(
    success=Style(fg=108),
    warning=Style(fg=179),
    error=Style(fg=174),
    accent=Style(fg=110),
    muted=Style(fg=60),
)

MONO_PALETTE = Palette(
    success=Style(bold=True),
    warning=Style(underline=True),
    error=Style(bold=True, reverse=True),
    accent=Style(bold=True),
    muted=Style(dim=True),
)

# --- ContextVar delivery ---

_palette: ContextVar[Palette] = ContextVar("palette", default=DEFAULT_PALETTE)


def current_palette() -> Palette:
    """Get the ambient palette."""

    return _palette.get()


def use_palette(palette: Palette) -> None:
    """Set the ambient palette for the current context."""

    _palette.set(palette)


def reset_palette() -> None:
    """Reset to the default palette."""

    _palette.set(DEFAULT_PALETTE)
