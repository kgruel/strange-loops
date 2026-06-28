"""Tests for cli.output — Reporter Protocol and implementations."""
from __future__ import annotations

import sys

from loops.cli.output import BufferReporter, PaintedReporter, Reporter


class TestBufferReporter:
    def test_default_width(self):
        r = BufferReporter()
        assert r.width == 80

    def test_custom_width(self):
        r = BufferReporter(width=120)
        assert r.width == 120

    def test_none_width(self):
        # None width matches painted's "piped" semantics.
        r = BufferReporter(width=None)
        assert r.width is None

    def test_err_captures(self):
        r = BufferReporter()
        r.err("oops")
        r.err("again")
        assert r.err_lines == ["oops", "again"]
        assert r.out_lines == []
        assert r.shown == []
        assert r.blocks == []

    def test_msg_captures(self):
        r = BufferReporter()
        r.msg("hello")
        assert r.out_lines == ["hello"]

    def test_show_captures(self):
        r = BufferReporter()
        r.show("receipt")
        r.show({"id": 42})
        assert r.shown == ["receipt", {"id": 42}]

    def test_print_block_captures(self):
        from painted import Block, Style

        r = BufferReporter()
        b1 = Block.text("hi", Style())
        b2 = Block.text("bye", Style())
        r.print_block(b1)
        r.print_block(b2)
        assert r.blocks == [b1, b2]

    def test_text_helpers_join_with_newlines(self):
        r = BufferReporter()
        r.err("line1")
        r.err("line2")
        assert r.err_text == "line1\nline2"
        r.msg("a")
        r.msg("b")
        assert r.out_text == "a\nb"

    def test_text_helpers_empty(self):
        r = BufferReporter()
        assert r.err_text == ""
        assert r.out_text == ""

    def test_implements_protocol(self):
        # Structural typing — BufferReporter should satisfy Reporter Protocol.
        r: Reporter = BufferReporter()
        r.err("x")
        r.msg("y")
        r.show("z")


class TestPaintedReporter:
    def test_width_when_piped(self, monkeypatch):
        # Force non-TTY → width should be None.
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        r = PaintedReporter()
        assert r.width is None

    def test_implements_protocol(self):
        r: Reporter = PaintedReporter()
        # Just confirms the methods exist and are callable — we don't
        # spy on stdout here.
        assert callable(r.err)
        assert callable(r.msg)
        assert callable(r.show)
        assert callable(r.print_block)

    # --- use_ansi derivation (S3: the plain-default inversion) -----------
    # Each test constructs a FRESH reporter and clears NO_COLOR/FORCE_COLOR so
    # the host env can't bleed into the assertion.

    @staticmethod
    def _clear_color_env(monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)

    def test_use_ansi_off_when_piped(self, monkeypatch):
        """The inversion: piped (non-TTY) stdout → no ANSI by default."""
        self._clear_color_env(monkeypatch)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert PaintedReporter().use_ansi is False

    def test_use_ansi_on_when_tty(self, monkeypatch):
        self._clear_color_env(monkeypatch)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert PaintedReporter().use_ansi is True

    def test_no_color_forces_off_even_on_tty(self, monkeypatch):
        self._clear_color_env(monkeypatch)
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert PaintedReporter().use_ansi is False

    def test_no_color_empty_value_still_forces_off(self, monkeypatch):
        """no-color.org: NO_COLOR present (any value, even empty) → off."""
        self._clear_color_env(monkeypatch)
        monkeypatch.setenv("NO_COLOR", "")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert PaintedReporter().use_ansi is False

    def test_force_color_forces_on_even_when_piped(self, monkeypatch):
        self._clear_color_env(monkeypatch)
        monkeypatch.setenv("FORCE_COLOR", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert PaintedReporter().use_ansi is True

    def test_no_color_wins_over_force_color(self, monkeypatch):
        self._clear_color_env(monkeypatch)
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("FORCE_COLOR", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert PaintedReporter().use_ansi is False

    def test_explicit_use_ansi_overrides_derivation(self, monkeypatch):
        """An explicit bool (the --plain force-off, or a forced-on) wins over
        the env+TTY derivation."""
        self._clear_color_env(monkeypatch)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert PaintedReporter(use_ansi=False).use_ansi is False
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert PaintedReporter(use_ansi=True).use_ansi is True


class TestModuleConvenience:
    def test_default_reporter_is_singleton(self):
        from loops.cli import output

        # Clear any cached default to make the test deterministic.
        output._default_reporter = None  # noqa: SLF001
        a = output.default_reporter()
        b = output.default_reporter()
        assert a is b

    def test_err_routes_through_default(self, capsys):
        # err() uses the default PaintedReporter, which writes to stderr.
        # Reset the cached singleton so we exercise the lazy construction.
        from loops.cli import output

        output._default_reporter = None  # noqa: SLF001
        output.err("error-message")
        captured = capsys.readouterr()
        assert "error-message" in captured.err
