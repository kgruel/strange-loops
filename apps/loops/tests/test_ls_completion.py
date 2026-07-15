"""Tests for top-level ``ls`` completion — feature/completion-store-ls.

Mirrors ``test_emit_completion.py``'s shape. Two completers:

- ``cli.completers.complete_ls_vertex`` — vertex-name candidates on ``ls``'s
  single ``vertex`` positional, deferring once it's filled (same rule
  ``complete_vertex`` follows for read/emit's ``tokens`` bucket, scoped to
  the ``vertex`` dest instead).
- ``cli.completers.complete_ls_kind`` — declared-kind candidates on
  ``--kind``, resolved through ls's OWN target/qualifier split
  (``vertex/qualifier`` — ``commands/ls.py:fetch_declarations``), not read's
  entity-address classifier.

Plus the ``add_args`` seam end to end via painted's ``complete_app``.
"""

from __future__ import annotations

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


def _ctx(vertex=None, prefix="", **flags):
    from painted.cli import CompletionContext
    from painted.cli.types import ArgsView

    return CompletionContext(args=ArgsView({"vertex": vertex, **flags}), prefix=prefix)


# ---------------------------------------------------------------------------
# complete_ls_vertex
# ---------------------------------------------------------------------------


class TestCompleteLsVertex:
    def test_offers_vertex_candidates_when_slot_empty(self, isolated):
        from painted.cli import Candidate
        from loops.cli.completers import complete_ls_vertex

        _write_instance(Path.cwd() / ".loops", "project")
        cands = complete_ls_vertex(_ctx())
        assert all(isinstance(c, Candidate) for c in cands)
        assert "project" in {c.value for c in cands}

    def test_defers_once_vertex_is_filled(self, isolated):
        from loops.cli.completers import complete_ls_vertex

        _write_instance(Path.cwd() / ".loops", "project")
        assert complete_ls_vertex(_ctx(vertex="project")) == []

    def test_empty_on_error(self, isolated, monkeypatch):
        from loops.cli import completers

        def boom(*a, **k):
            raise RuntimeError("enumeration failed")

        monkeypatch.setattr("loops.commands.resolve.enumerate_vertices", boom)
        assert completers.complete_ls_vertex(_ctx()) == []


# ---------------------------------------------------------------------------
# complete_ls_kind
# ---------------------------------------------------------------------------


class TestCompleteLsKind:
    def test_returns_declared_kinds_for_bare_vertex(self, isolated, monkeypatch):
        from loops.cli.completers import complete_ls_kind

        vertex = Path.cwd() / "vx.vertex"
        _write_instance(Path.cwd(), "vx", kinds=("decision", "thread"))
        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex if name == "vx" else None,
        )
        cands = complete_ls_kind(_ctx(vertex="vx"))
        assert {c.value for c in cands} == {"decision", "thread"}

    def test_qualified_target_resolves_the_vertex_before_the_slash(
        self, isolated, monkeypatch
    ):
        """``ls reading/feeds --kind`` must scope to 'reading', not treat the
        slashed bareword as a read-style entity address into the local
        vertex — the bug a naive reuse of read's classifier would produce."""
        from loops.cli.completers import complete_ls_kind

        vertex = Path.cwd() / "reading.vertex"
        _write_instance(Path.cwd(), "reading", kinds=("row",))
        local = Path.cwd() / "local.vertex"
        _write_instance(Path.cwd(), "local", kinds=("nope",))

        def resolve(name):
            return {"reading": vertex, "local": local}.get(name)

        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch", resolve
        )
        cands = complete_ls_kind(_ctx(vertex="reading/feeds"))
        assert {c.value for c in cands} == {"row"}

    def test_empty_when_no_vertex_on_line(self, isolated):
        from loops.cli.completers import complete_ls_kind

        assert complete_ls_kind(_ctx()) == []

    def test_empty_on_error(self, monkeypatch):
        from loops.cli import completers

        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr("loops.cli.completers._ls_vertex_path_on_line", boom)
        assert completers.complete_ls_kind(_ctx(vertex="x")) == []


class TestRenderFreeImport:
    def test_ls_args_import_pulls_no_renderer_or_lens_body(self):
        script = (
            "import sys\n"
            "import loops.cli.ls_args\n"
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


class TestLsAddArgsSeam:
    def test_wired_into_add_args_for(self):
        from loops.cli.app import _add_args_for
        from loops.cli.ls_args import add_ls_args

        assert _add_args_for("ls") is add_ls_args

    def test_loops_ls_offers_vertex_names(self, isolated):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project")
        cmds = _build_commands()
        cands = complete_app(cmds, ["ls"], "", prog="loops")
        assert "project" in {c.value for c in cands}

    def test_loops_ls_vertex_kind_offers_kind_names(self, isolated, monkeypatch):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        vertex = Path.cwd() / "project.vertex"
        _write_instance(Path.cwd(), "project", kinds=("decision", "thread"))
        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex if name == "project" else None,
        )
        cmds = _build_commands()
        cands = complete_app(cmds, ["ls", "project", "--kind"], "", prog="loops")
        values = {c.value for c in cands}
        assert "decision" in values
        assert "thread" in values

    def test_second_word_does_not_reoffer_vertex_names(self, isolated):
        """Once the vertex slot is filled, TAB on the next word must not
        keep re-listing vertex names (painted has one positional here; the
        completer's own defer-when-filled guard is what prevents this)."""
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project")
        _write_instance(Path.cwd() / ".loops", "other")
        cmds = _build_commands()
        cands = complete_app(cmds, ["ls", "project"], "", prog="loops")
        values = {c.value for c in cands}
        assert "other" not in values
        assert "--kind" in values
