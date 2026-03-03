"""Tests for the fidelity module: Zoom, OutputMode, Format, CliRunner."""

import argparse
import json
import sys

import pytest

from painted import Block, Style
from painted.fidelity import (
    CliContext,
    CliRunner,
    Format,
    HelpArg,
    HelpData,
    HelpFlag,
    HelpGroup,
    OutputMode,
    # New API
    Zoom,
    _build_help_data,
    _extract_add_args_flags,
    _help_args_to_flags,
    _render_help,
    add_cli_args,
    parse_format,
    parse_mode,
    parse_zoom,
    resolve_format,
    resolve_mode,
    run_cli,
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
        assert (
            resolve_mode(OutputMode.INTERACTIVE, is_tty=False, is_pipe=True)
            == OutputMode.INTERACTIVE
        )

    def test_auto_tty_gives_live(self):
        """AUTO resolves to LIVE for TTY (default)."""
        assert resolve_mode(OutputMode.AUTO, is_tty=True, is_pipe=False) == OutputMode.LIVE

    def test_auto_pipe_gives_static(self):
        """AUTO resolves to STATIC for pipe."""
        assert resolve_mode(OutputMode.AUTO, is_tty=False, is_pipe=True) == OutputMode.STATIC

    def test_auto_tty_with_default_mode_static(self):
        """AUTO on TTY respects default_mode override."""
        assert (
            resolve_mode(
                OutputMode.AUTO, is_tty=True, is_pipe=False, default_mode=OutputMode.STATIC
            )
            == OutputMode.STATIC
        )

    def test_auto_pipe_ignores_default_mode(self):
        """Pipe always gets STATIC regardless of default_mode."""
        assert (
            resolve_mode(OutputMode.AUTO, is_tty=False, is_pipe=True, default_mode=OutputMode.LIVE)
            == OutputMode.STATIC
        )


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

    def test_mode_args_filtered(self):
        """Passing modes={STATIC, LIVE} omits -i."""
        parser = argparse.ArgumentParser()
        add_cli_args(parser, modes={OutputMode.STATIC, OutputMode.LIVE})

        # --static and --live available
        args = parser.parse_args(["--static"])
        assert args.static is True

        args = parser.parse_args(["--live"])
        assert args.live is True

        # -i not recognized
        with pytest.raises(SystemExit):
            parser.parse_args(["-i"])

    def test_mode_args_static_only(self):
        """Mode group omitted entirely when only STATIC."""
        parser = argparse.ArgumentParser()
        add_cli_args(parser, modes={OutputMode.STATIC})

        # No mode flags at all
        with pytest.raises(SystemExit):
            parser.parse_args(["-i"])
        with pytest.raises(SystemExit):
            parser.parse_args(["--live"])
        with pytest.raises(SystemExit):
            parser.parse_args(["--static"])

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
        with pytest.raises(AttributeError):
            ctx.zoom = Zoom.FULL  # type: ignore


# =============================================================================
# CliRunner Tests
# =============================================================================


class TestCliRunner:
    """Tests for CliRunner class."""

    @staticmethod
    def _patch_print_block_to_current_stdout(monkeypatch):
        from painted import writer as writer_mod

        real_print_block = writer_mod.print_block

        def print_block(block, stream=None, *, use_ansi=None):
            return real_print_block(block, sys.stdout, use_ansi=use_ansi)

        monkeypatch.setattr(writer_mod, "print_block", print_block)

    def test_static_output(self, monkeypatch):
        """Static mode uses print_block and returns 0."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
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

        # AUTO resolves to STATIC when not a TTY
        result = run_cli(
            [],
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
            ["-v"],
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

    def test_fetch_failure_static_renders_error_and_returns_1(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)
        render_called = False

        def render(ctx: CliContext, data: str) -> Block:
            nonlocal render_called
            render_called = True
            return Block.text("unused", Style())

        def fetch() -> str:
            raise ValueError("nope")

        result = run_cli([], render=render, fetch=fetch)

        assert result == 1
        assert render_called is False
        captured = capsys.readouterr()
        assert "nope" in captured.out
        assert "Traceback" not in captured.out

    def test_fetch_failure_json_outputs_error_object_and_returns_1(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        def fetch() -> dict:
            raise RuntimeError("badness")

        result = run_cli(
            ["--json"],
            render=lambda ctx, data: Block.text("unused", Style()),
            fetch=fetch,
        )

        assert result == 1
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload == {"error": "badness"}

    def test_render_failure_static_renders_minimal_error_and_returns_2(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        def render(ctx: CliContext, data: str) -> Block:
            raise KeyError("kaboom")

        result = run_cli([], render=render, fetch=lambda: "ok")

        assert result == 2
        captured = capsys.readouterr()
        assert "KeyError" in captured.out
        assert "kaboom" in captured.out
        assert "Traceback" not in captured.out


# =============================================================================
# HelpArg and help augmentation tests
# =============================================================================


class TestHelpArg:
    """Tests for HelpArg dataclass."""

    def test_frozen(self):
        arg = HelpArg(name="--since", description="Time range")
        with pytest.raises(AttributeError):
            arg.name = "--other"  # type: ignore

    def test_defaults(self):
        arg = HelpArg(name="vertex")
        assert arg.description == ""
        assert arg.default is None
        assert arg.positional is False


class TestHelpArgsToFlags:
    """Tests for _help_args_to_flags conversion."""

    def test_positional_arg(self):
        flags = _help_args_to_flags([HelpArg("vertex", "Vertex name", positional=True)])
        assert len(flags) == 1
        assert flags[0].short is None
        assert flags[0].long == "vertex"
        assert flags[0].description == "Vertex name"

    def test_optional_arg(self):
        flags = _help_args_to_flags([HelpArg("--since", "Time range")])
        assert flags[0].long == "--since"
        assert flags[0].description == "Time range"

    def test_default_appended(self):
        flags = _help_args_to_flags([HelpArg("--since", "Time range", default="7d")])
        assert "(default: 7d)" in flags[0].description

    def test_default_only_no_description(self):
        flags = _help_args_to_flags([HelpArg("--since", default="7d")])
        assert flags[0].description == "(default: 7d)"


class TestExtractAddArgsFlags:
    """Tests for _extract_add_args_flags introspection."""

    def test_extracts_positional(self):
        def add_args(parser):
            parser.add_argument("name", help="The name")

        flags = _extract_add_args_flags(add_args)
        assert len(flags) == 1
        assert flags[0].long == "name"
        assert flags[0].description == "The name"

    def test_extracts_optional(self):
        def add_args(parser):
            parser.add_argument("-k", "--kind", help="Filter by kind")

        flags = _extract_add_args_flags(add_args)
        assert len(flags) == 1
        assert flags[0].short == "-k"
        assert flags[0].long == "--kind"
        assert flags[0].description == "Filter by kind"

    def test_skips_suppressed(self):
        def add_args(parser):
            parser.add_argument("--internal", help=argparse.SUPPRESS)
            parser.add_argument("--visible", help="Shown")

        flags = _extract_add_args_flags(add_args)
        assert len(flags) == 1
        assert flags[0].long == "--visible"


class TestBuildHelpDataAugmentation:
    """Tests for _build_help_data including command args."""

    def test_no_command_args_no_secondary(self):
        """Without help_args/add_args, all groups are non-secondary (backward compat)."""
        runner = CliRunner(
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: "ok",
            prog="test",
        )
        data = _build_help_data(runner)
        for group in data.groups:
            assert group.secondary is False

    def test_help_args_creates_command_group(self):
        """help_args appear as a primary group, rendering opts become secondary."""
        runner = CliRunner(
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: "ok",
            prog="test",
            help_args=[
                HelpArg("vertex", "Vertex name", positional=True),
                HelpArg("--since", "Time range", default="7d"),
            ],
        )
        data = _build_help_data(runner)

        # First group is command args (non-secondary, no name)
        assert data.groups[0].secondary is False
        assert data.groups[0].name == ""
        assert len(data.groups[0].flags) == 2
        assert data.groups[0].flags[0].long == "vertex"
        assert data.groups[0].flags[1].long == "--since"

        # Remaining groups are secondary
        for group in data.groups[1:]:
            assert group.secondary is True

    def test_add_args_creates_command_group(self):
        """add_args are introspected into a primary command group."""

        def add_args(parser):
            parser.add_argument("file", help="Input file")
            parser.add_argument("--format", help="Output format")

        runner = CliRunner(
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: "ok",
            prog="test",
            add_args=add_args,
        )
        data = _build_help_data(runner)

        # First group is command args
        assert data.groups[0].secondary is False
        assert data.groups[0].name == ""
        assert len(data.groups[0].flags) == 2

        # Remaining groups are secondary
        for group in data.groups[1:]:
            assert group.secondary is True


class TestRenderHelpAugmentation:
    """Tests for _render_help with primary/secondary hierarchy."""

    @staticmethod
    def _block_text(block: Block) -> str:
        """Extract all text from a block."""
        lines = []
        for y in range(block.height):
            lines.append("".join(cell.char for cell in block.row(y)).rstrip())
        return "\n".join(lines)

    def test_secondary_compact_at_minimal(self):
        """Secondary groups collapse to a compact dim line at MINIMAL zoom."""
        data = HelpData(
            prog="myapp",
            description="A test app",
            groups=(
                HelpGroup(name="", flags=(HelpFlag(None, "vertex", "Vertex name"),)),
                HelpGroup(
                    name="Zoom",
                    flags=(
                        HelpFlag("-q", "--quiet", "Minimal"),
                        HelpFlag("-v", "--verbose", "Verbose"),
                    ),
                    secondary=True,
                ),
                HelpGroup(
                    name="Help", flags=(HelpFlag("-h", "--help", "Show help"),), secondary=True
                ),
            ),
        )
        block = _render_help(data, Zoom.MINIMAL, 80, use_ansi=False)
        text = self._block_text(block)

        # Command arg should be present
        assert "vertex" in text

        # Secondary flags in compact line (no descriptions)
        assert "-q" in text
        assert "-h" in text

        # Secondary group headers should NOT appear at MINIMAL
        assert "Zoom" not in text

    def test_secondary_dim_at_summary(self):
        """Secondary groups render fully but dim at SUMMARY zoom."""
        data = HelpData(
            prog="myapp",
            description="A test app",
            groups=(
                HelpGroup(name="", flags=(HelpFlag(None, "vertex", "Vertex name"),)),
                HelpGroup(
                    name="Zoom",
                    flags=(HelpFlag("-q", "--quiet", "Minimal"),),
                    secondary=True,
                ),
            ),
        )
        block = _render_help(data, Zoom.SUMMARY, 80, use_ansi=False)
        text = self._block_text(block)

        # Command arg present
        assert "vertex" in text
        assert "Vertex name" in text

        # Secondary group expanded with header and descriptions
        assert "Zoom" in text
        assert "Minimal" in text

    def test_secondary_expanded_at_detailed(self):
        """Secondary groups expand fully at DETAILED zoom, with group headers."""
        data = HelpData(
            prog="myapp",
            description=None,
            groups=(
                HelpGroup(name="", flags=(HelpFlag(None, "vertex", "Vertex name"),)),
                HelpGroup(
                    name="Zoom",
                    hint="(what to show)",
                    flags=(HelpFlag("-q", "--quiet", "Minimal"),),
                    secondary=True,
                ),
            ),
        )
        block = _render_help(data, Zoom.DETAILED, 80, use_ansi=False)
        text = self._block_text(block)

        # Command arg present
        assert "vertex" in text

        # Secondary group header present at DETAILED
        assert "Zoom (what to show)" in text
        assert "Minimal" in text

    def test_no_secondary_renders_as_before(self):
        """Without secondary groups, rendering is unchanged."""
        data = HelpData(
            prog="deploy",
            description="Ship services",
            groups=(
                HelpGroup(
                    name="Zoom",
                    hint="(what to show)",
                    flags=(
                        HelpFlag("-q", "--quiet", "Minimal output"),
                        HelpFlag("-v", "--verbose", "Detailed (-v) or full (-vv)"),
                    ),
                ),
                HelpGroup(name="Help", flags=(HelpFlag("-h", "--help", "Show this help"),)),
            ),
        )
        block = _render_help(data, Zoom.SUMMARY, 80, use_ansi=False)
        text = self._block_text(block)

        # All groups rendered fully (not collapsed)
        assert "Zoom (what to show)" in text
        assert "-q, --quiet" in text
        assert "Help" in text
        assert "-h, --help" in text

        # No "details" hint (that's only for secondary compact)
        assert "--help -v for details" not in text


class TestRunCliHelp:
    """Integration tests for --help with command args."""

    @staticmethod
    def _patch_print_block_to_current_stdout(monkeypatch):
        from painted import writer as writer_mod

        real_print_block = writer_mod.print_block

        def print_block(block, stream=None, *, use_ansi=None):
            return real_print_block(block, sys.stdout, use_ansi=use_ansi)

        monkeypatch.setattr(writer_mod, "print_block", print_block)

    def test_help_with_help_args_shows_command_args(self, capsys, monkeypatch):
        """--help with help_args shows command args prominently."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        result = run_cli(
            ["--help"],
            render=lambda ctx, data: Block.text("unused", Style()),
            fetch=lambda: "ok",
            prog="myapp",
            description="My application",
            help_args=[
                HelpArg("vertex", "Vertex name", positional=True),
                HelpArg("--since", "Time range", default="7d"),
            ],
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "vertex" in captured.out
        assert "Vertex name" in captured.out
        assert "--since" in captured.out
        assert "(default: 7d)" in captured.out
        assert "myapp" in captured.out

    def test_help_with_add_args_shows_command_args(self, capsys, monkeypatch):
        """--help with add_args shows registered args."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        def add_args(parser):
            parser.add_argument("file", help="Input file")
            parser.add_argument("--format", help="Output format")

        result = run_cli(
            ["--help"],
            render=lambda ctx, data: Block.text("unused", Style()),
            fetch=lambda: "ok",
            prog="myapp",
            add_args=add_args,
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "file" in captured.out
        assert "Input file" in captured.out
        assert "--format" in captured.out

    def test_help_without_command_args_unchanged(self, capsys, monkeypatch):
        """--help without help_args/add_args shows rendering options as before."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        result = run_cli(
            ["--help"],
            render=lambda ctx, data: Block.text("unused", Style()),
            fetch=lambda: "ok",
            prog="myapp",
        )

        assert result == 0
        captured = capsys.readouterr()
        # Rendering groups shown with headers (not collapsed)
        assert "Zoom" in captured.out
        assert "-q, --quiet" in captured.out
