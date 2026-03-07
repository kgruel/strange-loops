"""Extended tests for painted.fidelity: CliRunner error paths, format/mode edge cases."""

from __future__ import annotations

import json
import sys

import pytest

from painted import Block, Style
from painted.fidelity import (
    CliContext,
    CliRunner,
    OutputMode,
    Zoom,
    resolve_mode,
    run_cli,
)


# =============================================================================
# resolve_mode edge cases
# =============================================================================


class TestResolveModeEdgeCases:
    def test_auto_neither_tty_nor_pipe(self):
        # Both False => falls through to final STATIC return.
        assert resolve_mode(OutputMode.AUTO, is_tty=False, is_pipe=False) == OutputMode.STATIC


# =============================================================================
# CliRunner._exception_message
# =============================================================================


class TestExceptionMessage:
    def test_normal_message(self):
        assert CliRunner._exception_message(ValueError("boom")) == "boom"

    def test_empty_message_falls_back_to_class_name(self):
        assert CliRunner._exception_message(RuntimeError("")) == "RuntimeError"

    def test_whitespace_only_message(self):
        assert CliRunner._exception_message(TypeError("   ")) == "TypeError"


# =============================================================================
# CliRunner mode inference (fetch_stream / handlers)
# =============================================================================


class TestCliRunnerModeInference:
    @staticmethod
    def _patch_print_block_to_current_stdout(monkeypatch):
        from painted import writer as writer_mod

        real_print_block = writer_mod.print_block

        def print_block(block, stream=None, *, use_ansi=None):
            return real_print_block(block, sys.stdout, use_ansi=use_ansi)

        monkeypatch.setattr(writer_mod, "print_block", print_block)

    def test_fetch_stream_enables_live_mode(self, monkeypatch):
        """When fetch_stream is provided, LIVE mode is available."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        async def fake_stream():
            yield "data"

        runner = CliRunner(
            render=lambda ctx, data: Block.text(str(data), Style()),
            fetch=lambda: "data",
            fetch_stream=fake_stream,
        )

        # parse_args should not error with --live
        import argparse

        parser = argparse.ArgumentParser()
        from painted.fidelity import add_cli_args

        modes = {OutputMode.STATIC, OutputMode.LIVE}
        add_cli_args(parser, modes=modes)
        parsed = parser.parse_args(["--live"])
        assert parsed.live is True

    def test_handler_returns_none_becomes_zero(self, monkeypatch):
        """Custom handler returning None is treated as exit code 0."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        def handler(ctx: CliContext) -> None:
            return None  # type: ignore[return-value]

        result = run_cli(
            ["-i"],
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: "ok",
            handlers={OutputMode.INTERACTIVE: handler},
        )
        assert result == 0

    def test_json_format_implies_static(self, capsys, monkeypatch):
        """--json with AUTO mode resolves to STATIC."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        received_ctx = None

        def render(ctx: CliContext, data: str) -> Block:
            nonlocal received_ctx
            received_ctx = ctx
            return Block.text(data, Style())

        result = run_cli(
            ["--json"],
            render=render,
            fetch=lambda: {"val": 1},
        )
        assert result == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == {"val": 1}

    def test_plain_format_implies_static(self, capsys, monkeypatch):
        """--plain with AUTO mode resolves to STATIC."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        result = run_cli(
            ["--plain"],
            render=lambda ctx, data: Block.text("hello", Style()),
            fetch=lambda: "ok",
        )
        assert result == 0

    def test_quiet_implies_static(self, monkeypatch):
        """Zoom.MINIMAL (-q) with AUTO mode resolves to STATIC."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        result = run_cli(
            ["-q"],
            render=lambda ctx, data: Block.text("minimal", Style()),
            fetch=lambda: "ok",
        )
        assert result == 0


# =============================================================================
# CliRunner JSON path edge cases
# =============================================================================


class TestCliRunnerJsonPath:
    def test_json_non_dataclass_state(self, capsys, monkeypatch):
        """JSON mode handles non-dataclass state (dict, list, etc.)."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        result = run_cli(
            ["--json"],
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: [1, 2, 3],
        )
        assert result == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out) == [1, 2, 3]

    def test_json_fetch_error(self, capsys, monkeypatch):
        """JSON mode fetch error produces error JSON."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        result = run_cli(
            ["--json"],
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: (_ for _ in ()).throw(IOError("disk full")),
        )
        assert result == 1
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"error": "disk full"}


# =============================================================================
# CliRunner error block rendering
# =============================================================================


class TestCliRunnerErrorBlocks:
    def test_fetch_error_block_uses_palette(self):
        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.STATIC,
            use_ansi=True,
            is_tty=True,
            width=80,
            height=24,
        )
        block = CliRunner._fetch_error_block(ctx, ValueError("bad input"))
        text = "".join(cell.char for cell in block.row(0))
        assert "bad input" in text

    def test_render_error_block_includes_type(self):
        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.STATIC,
            use_ansi=True,
            is_tty=True,
            width=80,
            height=24,
        )
        block = CliRunner._render_error_block(ctx, KeyError("missing"))
        text = "".join(cell.char for cell in block.row(0))
        assert "KeyError" in text

    def test_render_error_block_empty_message(self):
        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.STATIC,
            use_ansi=True,
            is_tty=True,
            width=80,
            height=24,
        )
        block = CliRunner._render_error_block(ctx, RuntimeError(""))
        text = "".join(cell.char for cell in block.row(0))
        assert "RuntimeError" in text

    def test_fetch_error_block_narrow_width(self):
        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.STATIC,
            use_ansi=True,
            is_tty=True,
            width=0,
            height=24,
        )
        block = CliRunner._fetch_error_block(ctx, ValueError("x"))
        assert block.width >= 1


# =============================================================================
# CliRunner._run_live without fetch_stream
# =============================================================================


class TestCliRunnerLiveFallback:
    @staticmethod
    def _patch_print_block_to_current_stdout(monkeypatch):
        from painted import writer as writer_mod

        real_print_block = writer_mod.print_block

        def print_block(block, stream=None, *, use_ansi=None):
            return real_print_block(block, sys.stdout, use_ansi=use_ansi)

        monkeypatch.setattr(writer_mod, "print_block", print_block)

    def test_live_without_stream_renders_static(self, capsys, monkeypatch):
        """LIVE mode without fetch_stream falls back to fetch-and-render."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.LIVE,
            use_ansi=True,
            is_tty=False,
            width=80,
            height=24,
        )
        runner = CliRunner(
            render=lambda ctx, data: Block.text("live-ok", Style()),
            fetch=lambda: "ok",
        )
        result = runner._dispatch(ctx)
        assert result == 0
        captured = capsys.readouterr()
        assert "live-ok" in captured.out

    def test_live_fetch_error(self, capsys, monkeypatch):
        """LIVE mode fetch error returns 1."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.LIVE,
            use_ansi=True,
            is_tty=False,
            width=80,
            height=24,
        )
        runner = CliRunner(
            render=lambda ctx, data: Block.text("x", Style()),
            fetch=lambda: (_ for _ in ()).throw(IOError("fail")),
        )
        result = runner._dispatch(ctx)
        assert result == 1

    def test_live_render_error(self, capsys, monkeypatch):
        """LIVE mode render error returns 2."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.LIVE,
            use_ansi=True,
            is_tty=False,
            width=80,
            height=24,
        )

        def bad_render(ctx, data):
            raise ValueError("render broke")

        runner = CliRunner(
            render=bad_render,
            fetch=lambda: "ok",
        )
        result = runner._dispatch(ctx)
        assert result == 2

    def test_interactive_without_handler_falls_to_live(self, capsys, monkeypatch):
        """INTERACTIVE mode without custom handler falls through to _run_live."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        self._patch_print_block_to_current_stdout(monkeypatch)

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.INTERACTIVE,
            use_ansi=True,
            is_tty=False,
            width=80,
            height=24,
        )
        runner = CliRunner(
            render=lambda ctx, data: Block.text("interactive-fallback", Style()),
            fetch=lambda: "ok",
        )
        result = runner._dispatch(ctx)
        assert result == 0
        captured = capsys.readouterr()
        assert "interactive-fallback" in captured.out


# =============================================================================
# CliRunner._run_live with fetch_stream
# =============================================================================


class TestCliRunnerLiveStreaming:
    def test_live_with_stream_renders_each_state_and_finalizes(self, monkeypatch):
        renderers: list[object] = []

        class StubRenderer:
            def __init__(self, *args, **kwargs):
                self.blocks: list[Block] = []
                self.finalized = False
                renderers.append(self)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def render(self, block: Block) -> None:
                self.blocks.append(block)

            def finalize(self) -> None:
                self.finalized = True

        import painted.inplace as inplace_mod

        monkeypatch.setattr(inplace_mod, "InPlaceRenderer", StubRenderer)

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.LIVE,
            use_ansi=False,
            is_tty=False,
            width=40,
            height=5,
        )

        async def fake_stream():
            yield "a"
            yield "b"

        runner = CliRunner(
            render=lambda ctx, data: Block.text(str(data), Style()),
            fetch=lambda: "unused",
            fetch_stream=fake_stream,
        )

        result = runner._dispatch(ctx)
        assert result == 0
        assert len(renderers) == 1
        renderer: StubRenderer = renderers[0]  # type: ignore[assignment]
        assert [row[0].char for row in (renderer.blocks[0].row(0), renderer.blocks[1].row(0))] == [
            "a",
            "b",
        ]
        assert renderer.finalized is True

    def test_live_stream_render_error_returns_2(self, monkeypatch):
        renderers: list[object] = []

        class StubRenderer:
            def __init__(self, *args, **kwargs):
                self.blocks: list[Block] = []
                self.finalized = False
                renderers.append(self)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def render(self, block: Block) -> None:
                self.blocks.append(block)

            def finalize(self) -> None:
                self.finalized = True

        import painted.inplace as inplace_mod

        monkeypatch.setattr(inplace_mod, "InPlaceRenderer", StubRenderer)

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.LIVE,
            use_ansi=False,
            is_tty=False,
            width=40,
            height=5,
        )

        async def fake_stream():
            yield "ok"
            yield "boom"

        def maybe_bad_render(ctx, data):
            if data == "boom":
                raise ValueError("render broke")
            return Block.text(str(data), Style())

        runner = CliRunner(
            render=maybe_bad_render,
            fetch=lambda: "unused",
            fetch_stream=fake_stream,
        )

        result = runner._dispatch(ctx)
        assert result == 2
        assert len(renderers) == 1
        renderer: StubRenderer = renderers[0]  # type: ignore[assignment]
        assert renderer.finalized is True
        # Last rendered block should be an error block.
        assert "ValueError" in "".join(c.char for c in renderer.blocks[-1].row(0))

    def test_live_stream_fetch_error_returns_1(self, monkeypatch):
        renderers: list[object] = []

        class StubRenderer:
            def __init__(self, *args, **kwargs):
                self.blocks: list[Block] = []
                self.finalized = False
                renderers.append(self)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def render(self, block: Block) -> None:
                self.blocks.append(block)

            def finalize(self) -> None:
                self.finalized = True

        import painted.inplace as inplace_mod

        monkeypatch.setattr(inplace_mod, "InPlaceRenderer", StubRenderer)

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.LIVE,
            use_ansi=False,
            is_tty=False,
            width=40,
            height=5,
        )

        async def bad_stream():
            yield "ok"
            raise RuntimeError("fetch broke")

        runner = CliRunner(
            render=lambda ctx, data: Block.text(str(data), Style()),
            fetch=lambda: "unused",
            fetch_stream=bad_stream,
        )

        result = runner._dispatch(ctx)
        assert result == 1
        assert len(renderers) == 1
        renderer: StubRenderer = renderers[0]  # type: ignore[assignment]
        assert renderer.finalized is True
        assert "fetch broke" in "".join(c.char for c in renderer.blocks[-1].row(0))
