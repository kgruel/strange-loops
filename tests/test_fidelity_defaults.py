"""run_cli sets ambient IconSet from resolved context.

Palette is never auto-set — it's a deliberate aesthetic choice.
"""
from __future__ import annotations

from fidelis.fidelity import CliContext, Format, OutputMode, Zoom
from fidelis.fidelity import _setup_defaults
from fidelis.palette import current_palette, reset_palette, DEFAULT_PALETTE
from fidelis.icon_set import current_icons, reset_icons, ASCII_ICONS, IconSet


def test_plain_format_sets_ascii_icons():
    reset_palette()
    reset_icons()
    ctx = CliContext(
        zoom=Zoom.SUMMARY,
        mode=OutputMode.STATIC,
        format=Format.PLAIN,
        is_tty=False,
        width=80,
        height=24,
    )
    _setup_defaults(ctx)
    assert current_icons() is ASCII_ICONS
    # Palette is NOT auto-set — stays at default
    assert current_palette() is DEFAULT_PALETTE
    reset_palette()
    reset_icons()


def test_ansi_format_keeps_default_icons():
    reset_palette()
    reset_icons()
    ctx = CliContext(
        zoom=Zoom.SUMMARY,
        mode=OutputMode.STATIC,
        format=Format.ANSI,
        is_tty=True,
        width=80,
        height=24,
    )
    _setup_defaults(ctx)
    # Both stay at defaults
    assert current_palette() is DEFAULT_PALETTE
    assert current_icons().check == IconSet().check  # unicode default
    reset_palette()
    reset_icons()

