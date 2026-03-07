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
    Zoom,
    _build_help_data,
    _extract_add_args_flags,
    help_args_to_flags,
    render_help,
    add_cli_args,
    parse_format,
    parse_mode,
    parse_zoom,
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


class TestUseAnsiResolution:
    """Tests for use_ansi resolution via detect_context.

    Format dissolved: resolve_format removed, use_ansi derived from
    force_plain + TTY detection + mode in detect_context.
    """

    def test_force_plain_gives_no_ansi(self, monkeypatch):
        """force_plain=True always produces use_ansi=False."""
        from painted.fidelity import detect_context

        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        ctx = detect_context(Zoom.SUMMARY, OutputMode.STATIC, force_plain=True)
        assert ctx.use_ansi is False

    def test_tty_gives_ansi(self, monkeypatch):
        """TTY without force_plain produces use_ansi=True."""
        from painted.fidelity import detect_context

        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        ctx = detect_context(Zoom.SUMMARY, OutputMode.STATIC)
        assert ctx.use_ansi is True

    def test_pipe_gives_no_ansi(self, monkeypatch):
        """Pipe without force_plain produces use_ansi=False."""
        from painted.fidelity import detect_context

        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        ctx = detect_context(Zoom.SUMMARY, OutputMode.STATIC)
        assert ctx.use_ansi is False

    def test_interactive_always_ansi(self, monkeypatch):
        """INTERACTIVE mode forces use_ansi=True even on pipe."""
        from painted.fidelity import detect_context

        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        ctx = detect_context(Zoom.SUMMARY, OutputMode.INTERACTIVE)
        assert ctx.use_ansi is True


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
            use_ansi=True,
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
    """Tests for help_args_to_flags conversion."""

    def test_positional_arg(self):
        flags = help_args_to_flags([HelpArg("vertex", "Vertex name", positional=True)])
        assert len(flags) == 1
        assert flags[0].short is None
        assert flags[0].long == "vertex"
        assert flags[0].description == "Vertex name"

    def test_optional_arg(self):
        flags = help_args_to_flags([HelpArg("--since", "Time range")])
        assert flags[0].long == "--since"
        assert flags[0].description == "Time range"

    def test_default_appended(self):
        flags = help_args_to_flags([HelpArg("--since", "Time range", default="7d")])
        assert "(default: 7d)" in flags[0].description

    def test_default_only_no_description(self):
        flags = help_args_to_flags([HelpArg("--since", default="7d")])
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

    def test_no_command_args_min_zoom_minimal(self):
        """Without help_args/add_args, all groups have min_zoom=MINIMAL."""
        runner = CliRunner(
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: "ok",
            prog="test",
        )
        data = _build_help_data(runner)
        for group in data.groups:
            assert group.min_zoom == Zoom.MINIMAL

    def test_help_args_creates_command_group(self):
        """help_args appear as min_zoom=MINIMAL group, framework groups get SUMMARY."""
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

        # First group is command args (min_zoom=MINIMAL, no name)
        assert data.groups[0].min_zoom == Zoom.MINIMAL
        assert data.groups[0].name == ""
        assert len(data.groups[0].flags) == 2
        assert data.groups[0].flags[0].long == "vertex"
        assert data.groups[0].flags[1].long == "--since"

        # Framework groups have min_zoom=SUMMARY
        for group in data.groups[1:]:
            assert group.min_zoom == Zoom.SUMMARY

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

        # First group is command args (min_zoom=MINIMAL)
        assert data.groups[0].min_zoom == Zoom.MINIMAL
        assert data.groups[0].name == ""
        assert len(data.groups[0].flags) == 2

        # Framework groups have min_zoom=SUMMARY
        for group in data.groups[1:]:
            assert group.min_zoom == Zoom.SUMMARY


class TestRenderHelpAugmentation:
    """Tests for render_help with effective zoom (min_zoom) rendering."""

    @staticmethod
    def _block_text(block: Block) -> str:
        """Extract all text from a block."""
        lines = []
        for y in range(block.height):
            lines.append("".join(cell.char for cell in block.row(y)).rstrip())
        return "\n".join(lines)

    def test_compact_at_min_zoom(self):
        """Groups at eff_zoom=0 render as compact dim line (flag names only)."""
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
                    min_zoom=Zoom.SUMMARY,
                ),
                HelpGroup(
                    name="Help",
                    flags=(HelpFlag("-h", "--help", "Show help"),),
                    min_zoom=Zoom.SUMMARY,
                ),
            ),
        )
        block = render_help(data, Zoom.SUMMARY, 80, use_ansi=False)
        text = self._block_text(block)

        # Command arg should be expanded (eff=1)
        assert "vertex" in text
        assert "Vertex name" in text

        # Framework flags in compact line (eff=0, no descriptions)
        assert "-q" in text
        assert "-h" in text

        # Group headers should NOT appear at compact
        lines = text.split("\n")
        header_lines = [l for l in lines if l.strip().startswith("Zoom")]
        assert not header_lines

    def test_expanded_above_min_zoom(self):
        """Groups at eff_zoom=1 render expanded with header and descriptions."""
        data = HelpData(
            prog="myapp",
            description="A test app",
            groups=(
                HelpGroup(name="", flags=(HelpFlag(None, "vertex", "Vertex name"),)),
                HelpGroup(
                    name="Zoom",
                    flags=(HelpFlag("-q", "--quiet", "Minimal"),),
                    min_zoom=Zoom.SUMMARY,
                ),
            ),
        )
        block = render_help(data, Zoom.DETAILED, 80, use_ansi=False)
        text = self._block_text(block)

        # Command arg expanded (eff=2)
        assert "vertex" in text
        assert "Vertex name" in text

        # Framework group expanded with header (eff=1)
        assert "Zoom" in text
        assert "Minimal" in text

    def test_detail_at_eff_zoom_two(self):
        """Group and flag detail shown when eff_zoom >= 2."""
        data = HelpData(
            prog="myapp",
            description=None,
            groups=(
                HelpGroup(name="", flags=(HelpFlag(None, "vertex", "Vertex name"),)),
                HelpGroup(
                    name="Zoom",
                    hint="(what to show)",
                    detail="Controls detail level.",
                    flags=(HelpFlag("-q", "--quiet", "Minimal", detail="Implies --static."),),
                    min_zoom=Zoom.SUMMARY,
                ),
            ),
        )
        block = render_help(data, Zoom.FULL, 80, use_ansi=False)
        text = self._block_text(block)

        # Framework group at eff=2: header + detail + flag detail
        assert "Zoom (what to show)" in text
        assert "Controls detail level." in text
        assert "Implies --static." in text

    def test_all_minimal_renders_uniformly(self):
        """All groups at min_zoom=MINIMAL render expanded at SUMMARY."""
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
        block = render_help(data, Zoom.SUMMARY, 80, use_ansi=False)
        text = self._block_text(block)

        # All groups rendered expanded (eff=1)
        assert "Zoom (what to show)" in text
        assert "-q, --quiet" in text
        assert "Help" in text
        assert "-h, --help" in text

    def test_primary_compact_at_minimal(self):
        """Primary groups (min_zoom=MINIMAL) render compact at MINIMAL."""
        data = HelpData(
            prog="myapp",
            description="A test app",
            groups=(
                HelpGroup(
                    name="Zoom",
                    flags=(
                        HelpFlag("-q", "--quiet", "Minimal"),
                        HelpFlag("-v", "--verbose", "Verbose"),
                    ),
                ),
            ),
        )
        block = render_help(data, Zoom.MINIMAL, 80, use_ansi=False)
        text = self._block_text(block)

        # At MINIMAL (eff=0), compact: flag names present, no descriptions
        assert "-q" in text
        assert "-v" in text
        # Group header should NOT appear in compact
        lines = text.split("\n")
        header_lines = [l for l in lines if l.strip().startswith("Zoom")]
        assert not header_lines

    def test_hidden_below_min_zoom(self):
        """Groups are hidden when zoom < min_zoom."""
        data = HelpData(
            prog="myapp",
            description=None,
            groups=(
                HelpGroup(name="", flags=(HelpFlag(None, "vertex", "Vertex name"),)),
                HelpGroup(
                    name="Zoom",
                    flags=(HelpFlag("-q", "--quiet", "Minimal"),),
                    min_zoom=Zoom.SUMMARY,
                ),
            ),
        )
        block = render_help(data, Zoom.MINIMAL, 80, use_ansi=False)
        text = self._block_text(block)

        # Command arg visible (eff=0, compact)
        assert "vertex" in text

        # Framework group hidden (eff=-1)
        assert "Zoom" not in text
        assert "-q" not in text


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
