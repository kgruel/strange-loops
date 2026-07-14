"""Tests for --kind completion (shell completion T3 S3, kind half).

Two surfaces, mirroring ``test_vertex_completion.py``'s shape:

- ``commands.resolve._declared_kind_names`` — the enumeration side: a plain
  KDL parse of the vertex's own ``loops {}`` block, no store open, internal
  ``_decl.*`` kinds excluded.
- ``cli.completers.complete_kind`` — the domain completer hung on
  ``--kind``: candidates only when a vertex resolves on the line, empty-on-
  error, render-free import.
"""

import subprocess
import sys
from pathlib import Path

from loops.commands.resolve import _declared_kind_names


def _write_vertex(path: Path, *, loops: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'name "test"\n'
        'store "./data/test.db"\n\n'
        "loops {\n"
        f"{loops}"
        "}\n",
        encoding="utf-8",
    )


class TestDeclaredKindNames:
    def test_returns_sorted_declared_kinds(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        _write_vertex(
            vertex,
            loops=(
                '  thread { fold { items "by" "name" } }\n'
                '  decision { fold { items "by" "topic" } }\n'
            ),
        )
        assert _declared_kind_names(vertex) == ["decision", "thread"]

    def test_excludes_internal_decl_kinds(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        _write_vertex(
            vertex,
            loops=(
                '  decision { fold { items "by" "topic" } }\n'
                '  "_decl.kind-defined" { fold { count "inc" } }\n'
            ),
        )
        assert _declared_kind_names(vertex) == ["decision"]

    def test_empty_on_missing_file(self, tmp_path):
        assert _declared_kind_names(tmp_path / "nope.vertex") == []

    def test_empty_on_broken_syntax(self, tmp_path):
        vertex = tmp_path / "broken.vertex"
        vertex.write_text("not < valid kdl {{{", encoding="utf-8")
        assert _declared_kind_names(vertex) == []

    def test_empty_when_no_loops_block(self, tmp_path):
        vertex = tmp_path / "bare.vertex"
        vertex.write_text('name "bare"\n', encoding="utf-8")
        assert _declared_kind_names(vertex) == []


# ---------------------------------------------------------------------------
# The completer
# ---------------------------------------------------------------------------


def _ctx(tokens=None, prefix=""):
    from painted.cli import CompletionContext
    from painted.cli.types import ArgsView

    return CompletionContext(args=ArgsView({"tokens": tokens or []}), prefix=prefix)


class TestCompleteKind:
    def test_returns_declared_kinds_when_vertex_resolves(self, tmp_path, monkeypatch):
        vertex = tmp_path / "vx.vertex"
        _write_vertex(vertex, loops='  decision { fold { items "by" "topic" } }\n')

        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex if name == "vx" else None,
        )
        from painted.cli import Candidate
        from loops.cli.completers import complete_kind

        cands = complete_kind(_ctx(tokens=["vx"]))
        assert all(isinstance(c, Candidate) for c in cands)
        assert [c.value for c in cands] == ["decision"]

    def test_empty_when_no_vertex_on_line(self):
        from loops.cli.completers import complete_kind

        assert complete_kind(_ctx()) == []

    def test_empty_when_resolution_fails(self, monkeypatch):
        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: None,
        )
        from loops.cli.completers import complete_kind

        assert complete_kind(_ctx(tokens=["nope"])) == []

    def test_empty_on_error(self, monkeypatch):
        from loops.cli import completers

        def boom(*a, **k):
            raise RuntimeError("enumeration failed")

        monkeypatch.setattr("loops.cli.completers._vertex_path_on_line", boom)
        # TAB must never traceback — a broken lookup degrades to [].
        assert completers.complete_kind(_ctx()) == []

    def test_scoping_ignores_predicates_and_flags(self, monkeypatch):
        seen = []

        def record(name):
            seen.append(name)
            return None

        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch", record
        )
        from loops.cli.completers import complete_kind

        complete_kind(_ctx(tokens=["kind=decision", "--foo", "project"]))
        assert seen == ["project"]


class TestRenderFreeImport:
    def test_completers_import_pulls_no_renderer_or_lens_body(self):
        """Importing cli.completers loads neither the renderer nor a lens body.

        Same render-free guarantee the S1/S2 test files assert — checked
        again here because ``complete_kind`` is a new import path.
        """
        script = (
            "import sys\n"
            "import loops.cli.completers\n"
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
