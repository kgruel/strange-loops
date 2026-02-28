"""IconSet: glyph vocabulary with ContextVar delivery."""

from __future__ import annotations

import pytest

from painted.icon_set import (
    ASCII_ICONS,
    IconSet,
    current_icons,
    reset_icons,
    use_icons,
)


def test_icon_set_is_frozen():
    icons = IconSet()
    with pytest.raises(AttributeError):
        icons.check = "X"  # type: ignore[misc]


def test_default_icon_set_uses_unicode():
    icons = IconSet()
    assert icons.check == "✓"
    assert icons.cross == "✗"
    assert "█" in icons.progress_fill


def test_ascii_icons_are_ascii_safe():
    for field_name in (
        "check",
        "cross",
        "progress_fill",
        "progress_empty",
        "tree_branch",
        "tree_last",
        "tree_indent",
    ):
        val = getattr(ASCII_ICONS, field_name)
        assert all(ord(c) < 128 for c in val), f"ASCII_ICONS.{field_name} has non-ASCII"


def test_sparkline_chars_length():
    """Sparkline needs 8 levels for proper resolution."""
    icons = IconSet()
    assert len(icons.sparkline) == 8
    assert len(ASCII_ICONS.sparkline) == 8


def test_context_var_default():
    reset_icons()
    default = current_icons()
    assert default.check == "✓"


def test_use_icons_sets_context():
    reset_icons()
    use_icons(ASCII_ICONS)
    assert current_icons() is ASCII_ICONS
    reset_icons()


def test_use_icons_context_manager_restores_previous():
    reset_icons()
    use_icons(ASCII_ICONS)

    with use_icons(IconSet()):
        assert current_icons().check == "✓"

    assert current_icons() is ASCII_ICONS
    reset_icons()


def test_reset_icons_restores_default():
    use_icons(ASCII_ICONS)
    reset_icons()
    assert current_icons().check == "✓"
