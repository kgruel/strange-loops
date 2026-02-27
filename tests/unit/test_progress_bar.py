"""Progress bar rendering with Palette and IconSet."""
from __future__ import annotations

from painted.cell import Style
from painted._components.progress import ProgressState, progress_bar
from painted.palette import (
    MONO_PALETTE,
    reset_palette,
    use_palette,
)
from painted.icon_set import (
    ASCII_ICONS,
    reset_icons,
    use_icons,
)


def test_progress_bar_default_no_args():
    """progress_bar with no palette/icons uses ambient defaults."""
    reset_palette()
    reset_icons()
    state = ProgressState(value=0.5)
    block = progress_bar(state, width=10)
    assert block.width == 10
    assert block.height == 1


def test_progress_bar_explicit_palette():
    state = ProgressState(value=0.5)
    block = progress_bar(state, width=10, palette=MONO_PALETTE)
    row = block.row(0)
    filled_cell = row[0]
    # MONO_PALETTE.accent is Style(bold=True) — fill should include bold
    # (merged with structural emphasis)
    assert filled_cell.style.bold is True


def test_progress_bar_explicit_icons():
    state = ProgressState(value=0.5)
    block = progress_bar(state, width=10, icons=ASCII_ICONS)
    row = block.row(0)
    assert row[0].char == "#"  # ASCII_ICONS.progress_fill
    assert row[-1].char == "-"  # ASCII_ICONS.progress_empty


def test_progress_bar_ambient_palette():
    """Ambient palette flows through without explicit kwarg."""
    reset_palette()
    use_palette(MONO_PALETTE)
    state = ProgressState(value=1.0)
    block = progress_bar(state, width=4)
    row = block.row(0)
    # All filled, should use MONO_PALETTE.accent
    assert row[0].style.bold is True
    reset_palette()


def test_progress_bar_style_overrides_palette():
    """Explicit filled_style takes precedence over palette."""
    custom = Style(fg="magenta")
    state = ProgressState(value=1.0)
    block = progress_bar(state, width=4, filled_style=custom)
    assert block.row(0)[0].style.fg == "magenta"

