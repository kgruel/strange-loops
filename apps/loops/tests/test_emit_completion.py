"""Tests for emit's completion wiring (shell completion T3 S4).

Two surfaces:

- ``cli.completers.complete_emit_tokens`` — the domain completer hung on
  emit's single ``tokens`` bucket: vertex candidates for the leading (empty)
  slot, kind candidates once exactly one token is on the line, ``[]`` beyond
  that (payload ``field=value`` completion is out of scope for this slice).
- the ``add_args`` seam itself (``cli.app._add_args_for("emit")`` →
  ``cli.emit_args.add_emit_args``) — exercised end to end via painted's
  ``complete_app`` producer, the same path a shell TAB actually drives.
"""

import subprocess
import sys
from pathlib import Path

import pytest


def _write_instance(directory: Path, name: str, *, kinds: tuple[str, ...] = ("thing",)) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    blocks = "".join(f'  {k} {{ fold {{ count "inc" }} }}\n' for k in kinds)
    (directory / f"{name}.vertex").write_text(
        f'name "{name}"\n'
        f'store "./data/{name}.db"\n\n'
        "loops {\n"
        f"{blocks}"
        "}\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Isolate cwd and LOOPS_HOME — same shape as ``test_vertex_completion.py``."""
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd))
    monkeypatch.setenv("LOOPS_HOME", str(home))
    return tmp_path


def _ctx(tokens=None, prefix=""):
    from painted.cli import CompletionContext
    from painted.cli.types import ArgsView

    return CompletionContext(args=ArgsView({"tokens": tokens or []}), prefix=prefix)


# ---------------------------------------------------------------------------
# complete_emit_tokens
# ---------------------------------------------------------------------------


class TestCompleteEmitTokens:
    def test_empty_bucket_offers_vertex_candidates(self, isolated):
        from painted.cli import Candidate
        from loops.cli.completers import complete_emit_tokens

        _write_instance(Path.cwd() / ".loops", "project")
        cands = complete_emit_tokens(_ctx())
        assert all(isinstance(c, Candidate) for c in cands)
        assert "project" in {c.value for c in cands}

    def test_one_token_offers_kind_candidates(self, isolated, monkeypatch):
        from loops.cli.completers import complete_emit_tokens

        vertex = Path.cwd() / "vx.vertex"
        _write_instance(Path.cwd(), "vx", kinds=("decision", "thread"))
        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex if name == "vx" else None,
        )
        cands = complete_emit_tokens(_ctx(tokens=["vx"]))
        assert {c.value for c in cands} == {"decision", "thread"}

    def test_two_or_more_tokens_defers(self, isolated, monkeypatch):
        from loops.cli.completers import complete_emit_tokens

        vertex = Path.cwd() / "vx.vertex"
        _write_instance(Path.cwd(), "vx")
        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex if name == "vx" else None,
        )
        assert complete_emit_tokens(_ctx(tokens=["vx", "thing"])) == []

    def test_empty_on_error(self, monkeypatch):
        from loops.cli import completers

        def boom(*a, **k):
            raise RuntimeError("enumeration failed")

        # Break the underlying enumeration the delegated completer
        # (complete_vertex) uses — the composed completer inherits its
        # guard, so this still degrades to [] rather than a traceback.
        monkeypatch.setattr("loops.commands.resolve.enumerate_vertices", boom)
        assert completers.complete_emit_tokens(_ctx()) == []


class TestRenderFreeImport:
    def test_emit_args_import_pulls_no_renderer_or_lens_body(self):
        """Importing cli.emit_args loads neither the renderer nor a lens body.

        Same render-free guarantee the S1/S2/S3 test files assert.
        """
        script = (
            "import sys\n"
            "import loops.cli.emit_args\n"
            "renderer = [m for m in sys.modules "
            "if 'painted.core.block' in m or 'painted.core.doc' in m]\n"
            "lenses = [m for m in sys.modules if m.startswith('loops.lenses')]\n"
            "assert not renderer, f'renderer imported: {renderer}'\n"
            "assert not lenses, f'lens body imported: {lenses}'\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"render-free import violated:\nstdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
        assert result.stdout.strip() == "ok"


# ---------------------------------------------------------------------------
# End to end: the add_args seam via painted's complete_app producer
# ---------------------------------------------------------------------------


class TestEmitAddArgsSeam:
    def test_wired_into_add_args_for(self):
        from loops.cli.app import _add_args_for
        from loops.cli.emit_args import add_emit_args

        assert _add_args_for("emit") is add_emit_args

    def test_loops_emit_offers_vertex_names(self, isolated):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project")
        cmds = _build_commands()
        cands = complete_app(cmds, ["emit"], "", prog="loops")
        assert "project" in {c.value for c in cands}

    def test_loops_emit_vertex_offers_kind_names(self, isolated):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project", kinds=("decision", "thread"))
        cmds = _build_commands()
        cands = complete_app(cmds, ["emit", "project"], "", prog="loops")
        values = {c.value for c in cands}
        assert "decision" in values
        assert "thread" in values
