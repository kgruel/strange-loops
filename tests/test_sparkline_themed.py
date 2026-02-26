"""Sparkline rendering with Palette and IconSet."""
from __future__ import annotations

from painted.cell import Style
from painted._components.sparkline import sparkline, sparkline_with_range
from painted.palette import MONO_PALETTE, reset_palette, use_palette
from painted.icon_set import ASCII_ICONS, reset_icons, use_icons


def test_sparkline_default():
    reset_palette()
    reset_icons()
    block = sparkline([1, 2, 3], width=3)
    assert block.width == 3
    assert block.height == 1


def test_sparkline_explicit_palette():
    block = sparkline([1, 2, 3], width=3, palette=MONO_PALETTE)
    # MONO_PALETTE.muted is Style(dim=True) — default sparkline style
    assert block.row(0)[0].style.dim is True
    assert block.row(0)[0].style.fg is None


def test_sparkline_explicit_icons():
    block = sparkline([0, 50, 100], width=3, icons=ASCII_ICONS)
    row = block.row(0)
    # ASCII sparkline chars: ("_", ".", "-", "~", "^", "*", "#", "@")
    # All chars should be from ASCII set
    for cell in row:
        assert ord(cell.char) < 128


def test_sparkline_ambient_icons():
    reset_icons()
    use_icons(ASCII_ICONS)
    block = sparkline([0, 50, 100], width=3)
    row = block.row(0)
    for cell in row:
        assert ord(cell.char) < 128
    reset_icons()


def test_sparkline_with_range_palette():
    block = sparkline_with_range(
        [10, 50, 90],
        width=3,
        min_val=0,
        max_val=100,
        palette=MONO_PALETTE,
    )
    assert block.row(0)[0].style.dim is True


def test_sparkline_style_overrides_palette():
    custom = Style(fg="magenta")
    block = sparkline([1, 2, 3], width=3, style=custom, palette=MONO_PALETTE)
    assert block.row(0)[0].style.fg == "magenta"

