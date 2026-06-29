"""Tests for cli.views.fold._resolve_mode — output-mode resolution.

Guards friction:live-mode-hangs-silently-on-pipe: --live must downgrade to
static on a non-tty (the alt-screen + infinite stream would otherwise hang
with zero output on a pipe).
"""

from __future__ import annotations

from types import SimpleNamespace

from loops.cli.views.fold import _resolve_mode


def args(*, live=False, interactive=False):
    return SimpleNamespace(live=live, interactive=interactive)


class TestResolveMode:
    def test_default_is_static(self):
        assert _resolve_mode(args(), None, is_tty=True) == "static"
        assert _resolve_mode(args(), None, is_tty=False) == "static"

    def test_live_on_tty_is_live(self):
        assert _resolve_mode(args(live=True), None, is_tty=True) == "live"

    def test_live_on_non_tty_downgrades_to_static(self):
        # The fix: no alt-screen / infinite stream on a pipe.
        assert _resolve_mode(args(live=True), None, is_tty=False) == "static"

    def test_interactive_only_for_autoresearch_lens(self):
        a = args(interactive=True)
        assert _resolve_mode(a, "autoresearch", is_tty=True) == "interactive"
        assert _resolve_mode(a, "fold", is_tty=True) == "static"

    def test_live_wins_over_interactive_on_tty(self):
        a = args(live=True, interactive=True)
        assert _resolve_mode(a, "autoresearch", is_tty=True) == "live"
