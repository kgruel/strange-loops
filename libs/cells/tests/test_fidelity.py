"""Tests for the fidelity module: Zoom, OutputMode, Format, CliRunner."""

import argparse

import pytest

from cells import Block, Style
from cells.fidelity import (
    # New API
    Zoom,
    OutputMode,
    Format,
    CliContext,
    CliRunner,
    add_cli_args,
    parse_zoom,
    parse_mode,
    parse_format,
    resolve_mode,
    resolve_format,
    detect_context,
    run_cli,
    # Deprecated API
    Fidelity,
    fidelity_to_zoom,
)


# =============================================================================
# Zoom Tests
# =============================================================================


class TestZoom:
    """Tests for Zoom enum."""

    def test_ordering(self):
        """Zoom levels are ordered MINIMAL < SUMMARY < DETAILED < FULL."""
        assert Zoom.MINIMAL < Zoom.SUMMARY < Zoom.DETAILED < Zoom.FULL

    def test_values(self):
        """Zoom levels have correct integer values."""
        assert Zoom.MINIMAL == 0
        assert Zoom.SUMMARY == 1
        assert Zoom.DETAILED == 2
        assert Zoom.FULL == 3


class TestParseZoom:
    """Tests for parse_zoom function."""

    def test_quiet_flag(self):
        """--quiet/-q gives MINIMAL."""
        args = argparse.Namespace(quiet=True, verbose=0)
        assert parse_zoom(args) == Zoom.MINIMAL

    def test_default(self):
        """No flags gives SUMMARY (default)."""
        args = argparse.Namespace(quiet=False, verbose=0)
        assert parse_zoom(args) == Zoom.SUMMARY

    def test_single_verbose(self):
        """-v gives DETAILED."""
        args = argparse.Namespace(quiet=False, verbose=1)
        assert parse_zoom(args) == Zoom.DETAILED

    def test_double_verbose(self):
        """-vv gives FULL."""
        args = argparse.Namespace(quiet=False, verbose=2)
        assert parse_zoom(args) == Zoom.FULL

    def test_triple_verbose_caps_at_full(self):
        """-vvv still gives FULL (capped)."""
        args = argparse.Namespace(quiet=False, verbose=3)
        assert parse_zoom(args) == Zoom.FULL

    def test_custom_default(self):
        """Custom default zoom is respected."""
        args = argparse.Namespace(quiet=False, verbose=0)
        assert parse_zoom(args, default=Zoom.DETAILED) == Zoom.DETAILED


# =============================================================================
# OutputMode Tests
# =============================================================================


class TestParseMode:
    """Tests for parse_mode function."""

    def test_interactive_flag(self):
        """-i/--interactive gives INTERACTIVE."""
        args = argparse.Namespace(interactive=True, static=False, live=False)
        assert parse_mode(args) == OutputMode.INTERACTIVE

    def test_static_flag(self):
        """--static gives STATIC."""
        args = argparse.Namespace(interactive=False, static=True, live=False)
        assert parse_mode(args) == OutputMode.STATIC

    def test_live_flag(self):
        """--live gives LIVE."""
        args = argparse.Namespace(interactive=False, static=False, live=True)
        assert parse_mode(args) == OutputMode.LIVE

    def test_no_flag_gives_auto(self):
        """No flags gives AUTO."""
        args = argparse.Namespace(interactive=False, static=False, live=False)
        assert parse_mode(args) == OutputMode.AUTO


class TestResolveMode:
    """Tests for resolve_mode function."""

    def test_explicit_mode_preserved(self):
        """Non-AUTO modes are returned unchanged."""
        assert resolve_mode(OutputMode.STATIC, is_tty=True, is_pipe=False) == OutputMode.STATIC
        assert resolve_mode(OutputMode.LIVE, is_tty=False, is_pipe=True) == OutputMode.LIVE
        assert resolve_mode(OutputMode.INTERACTIVE, is_tty=False, is_pipe=True) == OutputMode.INTERACTIVE

    def test_auto_tty_gives_live(self):
        """AUTO resolves to LIVE for TTY."""
        assert resolve_mode(OutputMode.AUTO, is_tty=True, is_pipe=False) == OutputMode.LIVE

    def test_auto_pipe_gives_static(self):
        """AUTO resolves to STATIC for pipe."""
        assert resolve_mode(OutputMode.AUTO, is_tty=False, is_pipe=True) == OutputMode.STATIC


# =============================================================================
# Format Tests
# =============================================================================


class TestParseFormat:
    """Tests for parse_format function."""

    def test_json_flag(self):
        """--json gives JSON."""
        args = argparse.Namespace(json=True, plain=False)
        assert parse_format(args) == Format.JSON

    def test_plain_flag(self):
        """--plain gives PLAIN."""
        args = argparse.Namespace(json=False, plain=True)
        assert parse_format(args) == Format.PLAIN

    def test_no_flag_gives_auto(self):
        """No flags gives AUTO."""
        args = argparse.Namespace(json=False, plain=False)
        assert parse_format(args) == Format.AUTO


class TestResolveFormat:
    """Tests for resolve_format function."""

    def test_explicit_format_preserved(self):
        """Non-AUTO formats are returned unchanged."""
        assert resolve_format(Format.JSON, is_tty=True, mode=OutputMode.LIVE) == Format.JSON
        assert resolve_format(Format.PLAIN, is_tty=True, mode=OutputMode.LIVE) == Format.PLAIN
        assert resolve_format(Format.ANSI, is_tty=False, mode=OutputMode.STATIC) == Format.ANSI

    def test_auto_interactive_gives_ansi(self):
        """AUTO with INTERACTIVE mode gives ANSI."""
        assert resolve_format(Format.AUTO, is_tty=False, mode=OutputMode.INTERACTIVE) == Format.ANSI

    def test_auto_tty_gives_ansi(self):
        """AUTO with TTY gives ANSI."""
        assert resolve_format(Format.AUTO, is_tty=True, mode=OutputMode.STATIC) == Format.ANSI

    def test_auto_pipe_gives_plain(self):
        """AUTO with pipe gives PLAIN."""
        assert resolve_format(Format.AUTO, is_tty=False, mode=OutputMode.STATIC) == Format.PLAIN


# =============================================================================
# Argument Parsing Integration
# =============================================================================


class TestAddCliArgs:
    """Tests for add_cli_args function."""

    def test_zoom_args(self):
        """Zoom arguments are added correctly."""
        parser = argparse.ArgumentParser()
        add_cli_args(parser)

        # -q
        args = parser.parse_args(["-q"])
        assert args.quiet is True
        assert args.verbose == 0

        # -v
        args = parser.parse_args(["-v"])
        assert args.quiet is False
        assert args.verbose == 1

        # -vv
        args = parser.parse_args(["-v", "-v"])
        assert args.verbose == 2

    def test_mode_args(self):
        """Mode arguments are added correctly."""
        parser = argparse.ArgumentParser()
        add_cli_args(parser)

        args = parser.parse_args(["-i"])
        assert args.interactive is True

        args = parser.parse_args(["--static"])
        assert args.static is True

        args = parser.parse_args(["--live"])
        assert args.live is True

    def test_format_args(self):
        """Format arguments are added correctly."""
        parser = argparse.ArgumentParser()
        add_cli_args(parser)

        args = parser.parse_args(["--json"])
        assert args.json is True

        args = parser.parse_args(["--plain"])
        assert args.plain is True

    def test_zoom_mutual_exclusion(self):
        """Cannot combine -q and -v."""
        parser = argparse.ArgumentParser()
        add_cli_args(parser)

        with pytest.raises(SystemExit):
            parser.parse_args(["-q", "-v"])

    def test_mode_mutual_exclusion(self):
        """Cannot combine -i, --static, --live."""
        parser = argparse.ArgumentParser()
        add_cli_args(parser)

        with pytest.raises(SystemExit):
            parser.parse_args(["-i", "--static"])


# =============================================================================
# CliContext Tests
# =============================================================================


class TestCliContext:
    """Tests for CliContext dataclass."""

    def test_frozen(self):
        """CliContext is immutable."""
        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.STATIC,
            format=Format.ANSI,
            is_tty=True,
            width=80,
            height=24,
        )
        with pytest.raises(Exception):
            ctx.zoom = Zoom.FULL  # type: ignore


# =============================================================================
# CliRunner Tests
# =============================================================================


class TestCliRunner:
    """Tests for CliRunner class."""

    def test_static_output(self):
        """Static mode uses print_block and returns 0."""
        render_called = False
        fetch_called = False
        received_ctx = None

        def render(ctx: CliContext, data: str) -> Block:
            nonlocal render_called, received_ctx
            render_called = True
            received_ctx = ctx
            return Block.text(f"zoom={ctx.zoom.value}: {data}", Style())

        def fetch() -> str:
            nonlocal fetch_called
            fetch_called = True
            return "test data"

        # Use --static to force static mode regardless of TTY
        result = run_cli(
            ["--static"],
            render=render,
            fetch=fetch,
        )

        assert result == 0
        assert render_called, "render should be called"
        assert fetch_called, "fetch should be called"
        assert received_ctx.mode == OutputMode.STATIC

    def test_json_output(self, capsys, monkeypatch):
        """JSON mode outputs JSON."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        def render(ctx: CliContext, data: dict) -> Block:
            return Block.text("unused", Style())

        def fetch() -> dict:
            return {"status": "ok", "count": 42}

        result = run_cli(
            ["--json"],
            render=render,
            fetch=fetch,
        )

        assert result == 0
        captured = capsys.readouterr()
        assert '"status": "ok"' in captured.out
        assert '"count": 42' in captured.out

    def test_zoom_passed_to_render(self, monkeypatch):
        """Zoom level is passed to render function."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        received_zoom = None

        def render(ctx: CliContext, data: str) -> Block:
            nonlocal received_zoom
            received_zoom = ctx.zoom
            return Block.text(data, Style())

        run_cli(
            ["-v", "--static"],
            render=render,
            fetch=lambda: "data",
        )

        assert received_zoom == Zoom.DETAILED

    def test_custom_handler(self, monkeypatch):
        """Custom handler is called for matching mode."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        handler_called = False
        received_ctx = None

        def custom_interactive(ctx: CliContext) -> int:
            nonlocal handler_called, received_ctx
            handler_called = True
            received_ctx = ctx
            return 42

        result = run_cli(
            ["-i"],
            render=lambda ctx, data: Block.text("unused", Style()),
            fetch=lambda: "data",
            handlers={OutputMode.INTERACTIVE: custom_interactive},
        )

        assert handler_called
        assert received_ctx.mode == OutputMode.INTERACTIVE
        assert result == 42


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestFidelityCompat:
    """Tests for deprecated Fidelity API."""

    def test_fidelity_values(self):
        """Fidelity enum still works."""
        assert Fidelity.QUIET == 0
        assert Fidelity.NORMAL == 1
        assert Fidelity.VERBOSE == 2
        assert Fidelity.FULL == 3

    def test_fidelity_to_zoom(self):
        """fidelity_to_zoom converts correctly."""
        assert fidelity_to_zoom(Fidelity.QUIET) == Zoom.MINIMAL
        assert fidelity_to_zoom(Fidelity.NORMAL) == Zoom.SUMMARY
        assert fidelity_to_zoom(Fidelity.VERBOSE) == Zoom.DETAILED
        assert fidelity_to_zoom(Fidelity.FULL) == Zoom.FULL
