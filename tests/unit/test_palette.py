"""Palette: semantic Style roles with ContextVar delivery."""

from __future__ import annotations

import pytest

from painted.cell import Style
from painted.palette import (
    DEFAULT_PALETTE,
    MONO_PALETTE,
    Palette,
    current_palette,
    reset_palette,
    use_palette,
)


def test_palette_is_frozen():
    p = Palette()
    with pytest.raises(AttributeError):
        p.accent = Style()  # type: ignore[misc]


def test_default_palette_roles_are_styles():
    p = DEFAULT_PALETTE
    for role in ("success", "warning", "error", "accent", "muted"):
        assert isinstance(getattr(p, role), Style)


def test_mono_palette_has_no_colors():
    """MONO_PALETTE uses modifiers only — no fg/bg."""
    p = MONO_PALETTE
    for role in ("success", "warning", "error", "accent", "muted"):
        s = getattr(p, role)
        assert s.fg is None, f"MONO_PALETTE.{role} should not set fg"
        assert s.bg is None, f"MONO_PALETTE.{role} should not set bg"


def test_mono_palette_roles_differ():
    """Each MONO_PALETTE role must be visually distinguishable."""
    p = MONO_PALETTE
    styles = {getattr(p, r) for r in ("success", "warning", "error", "accent", "muted")}
    # At least 4 distinct styles (muted=dim may overlap if another uses dim alone)
    assert len(styles) >= 4


def test_context_var_default():
    reset_palette()
    assert current_palette() is DEFAULT_PALETTE


def test_use_palette_sets_context():
    reset_palette()
    use_palette(MONO_PALETTE)
    assert current_palette() is MONO_PALETTE
    reset_palette()


def test_reset_palette_restores_default():
    use_palette(MONO_PALETTE)
    reset_palette()
    assert current_palette() is DEFAULT_PALETTE


def test_palette_compose_with_merge():
    """Views compose palette roles with structural emphasis via Style.merge."""
    p = DEFAULT_PALETTE
    composed = p.accent.merge(Style(bold=True))
    assert composed.fg == p.accent.fg
    assert composed.bold is True
