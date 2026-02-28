"""Palette: semantic Style roles for aesthetic personalization.

5 roles mapping to Style (not Color) — carries both color and modifier
fallbacks for monochrome output.

Usage:
    from painted.palette import current_palette, use_palette, MONO_PALETTE

    p = current_palette()
    fill_style = p.accent.merge(Style(bold=True))

    # Override ambient palette (setter)
    use_palette(MONO_PALETTE)

    # Scoped override (context manager)
    with use_palette(MONO_PALETTE):
        ...
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from contextlib import AbstractContextManager
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


class _PaletteOverride(AbstractContextManager[None]):
    def __init__(self, token: Token[Palette]) -> None:
        self._token = token
        self._active = True

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._active:
            _palette.reset(self._token)
            self._active = False
        return False


def current_palette() -> Palette:
    """Get the ambient palette."""

    return _palette.get()


def use_palette(palette: Palette) -> AbstractContextManager[None]:
    """Set the ambient palette for the current context.

    The palette is set immediately (setter semantics) and the return value can be
    used as a context manager for scoped overrides:

        use_palette(MONO_PALETTE)  # global / ambient until changed again

        with use_palette(MONO_PALETTE):
            ...  # restored on exit
    """

    token = _palette.set(palette)
    return _PaletteOverride(token)


def reset_palette() -> None:
    """Reset to the default palette."""

    _palette.set(DEFAULT_PALETTE)
