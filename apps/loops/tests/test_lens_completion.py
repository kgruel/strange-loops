"""Tests for lens enumeration + the ``--lens`` completer (shell completion T3 S1).

Two surfaces:

- ``lens_resolver.enumerate_lenses`` — the enumeration side of resolution:
  built-in + custom tiers, resolver precedence, missing dirs, inspection-only.
- ``cli.completers.complete_lens`` — the domain completer hung on ``--lens``:
  described candidates, vertex scoping, empty-on-error, and the render-free
  import guarantee (asserted in a clean subprocess via ``sys.modules``).
"""

import subprocess
import sys
from pathlib import Path

import pytest

from loops.lens_resolver import LensInfo, enumerate_lenses


# A minimal lens module: a public ``*_view`` function + a module docstring.
def _write_lens(directory: Path, name: str, docstring: str = "A test lens.") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.py").write_text(
        f'"""{docstring}"""\n\n'
        "def fold_view(data, zoom, width):\n"
        "    return None\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Isolate the cwd and user-global lens tiers to empty tmp dirs.

    Enumeration scans ``<cwd>/lenses`` and ``~/.config/loops/lenses``; without
    isolation a developer's real custom lenses would leak into assertions.
    """
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return tmp_path


class TestEnumerateBuiltins:
    def test_flagship_lenses_present_with_descriptions(self, isolated):
        by_name = {info.name: info for info in enumerate_lenses()}
        for name in ("confluence", "graph", "horizon", "fold"):
            assert name in by_name, f"{name} missing from enumeration"
            assert by_name[name].tier == "builtin"
            assert by_name[name].description, f"{name} has no description"

    def test_private_and_dunder_modules_skipped(self, isolated):
        names = {info.name for info in enumerate_lenses()}
        # _helpers.py / _grammar.py / __init__.py are not --lens names.
        assert not any(n.startswith("_") for n in names)


class TestEnumerateCustomTiers:
    def test_vertex_local_lens_enumerated(self, isolated, tmp_path):
        vertex_dir = tmp_path / "vx"
        _write_lens(vertex_dir / "lenses", "mylens", "My vertex-local lens.")
        by_name = {info.name: info for info in enumerate_lenses(vertex_dir=vertex_dir)}
        assert "mylens" in by_name
        assert by_name["mylens"].tier == "vertex"
        assert by_name["mylens"].description == "My vertex-local lens."

    def test_cwd_and_user_tiers(self, isolated, monkeypatch):
        # isolated points cwd/home at empty dirs; drop a lens into each.
        _write_lens(Path.cwd() / "lenses", "cwdlens", "cwd lens.")
        _write_lens(Path.home() / ".config" / "loops" / "lenses", "userlens", "user lens.")
        by_name = {info.name: info for info in enumerate_lenses()}
        assert by_name["cwdlens"].tier == "cwd"
        assert by_name["userlens"].tier == "user"

    def test_precedence_custom_shadows_builtin(self, isolated, tmp_path):
        # A vertex-local lens named "graph" masks the built-in graph, exactly
        # as resolve_lens would resolve it (custom tiers win).
        vertex_dir = tmp_path / "vx"
        _write_lens(vertex_dir / "lenses", "graph", "Shadowing graph.")
        graphs = [i for i in enumerate_lenses(vertex_dir=vertex_dir) if i.name == "graph"]
        assert len(graphs) == 1
        assert graphs[0].tier == "vertex"
        assert graphs[0].description == "Shadowing graph."


class TestEnumerateResilience:
    def test_missing_vertex_dir_no_crash(self, isolated, tmp_path):
        # Nonexistent vertex dir → still returns built-ins, no exception.
        infos = enumerate_lenses(vertex_dir=tmp_path / "does-not-exist")
        assert any(i.name == "confluence" for i in infos)

    def test_non_lens_file_skipped(self, isolated):
        # A .py with no public *_view function is not a lens.
        (Path.cwd() / "lenses").mkdir()
        (Path.cwd() / "lenses" / "helper.py").write_text(
            '"""Not a lens."""\n\ndef helper():\n    return 1\n', encoding="utf-8"
        )
        assert not any(i.name == "helper" for i in enumerate_lenses())

    def test_syntax_broken_file_skipped(self, isolated):
        (Path.cwd() / "lenses").mkdir()
        (Path.cwd() / "lenses" / "broken.py").write_text(
            "def fold_view(  <<< not python", encoding="utf-8"
        )
        # Inspection-only: a broken file is skipped, never raised.
        assert not any(i.name == "broken" for i in enumerate_lenses())

    def test_description_falls_back_to_view_docstring(self, isolated):
        (Path.cwd() / "lenses").mkdir()
        (Path.cwd() / "lenses" / "nodoc.py").write_text(
            "def fold_view(data, zoom, width):\n"
            '    """View-level description."""\n'
            "    return None\n",
            encoding="utf-8",
        )
        info = next(i for i in enumerate_lenses() if i.name == "nodoc")
        assert info.description == "View-level description."

    def test_long_description_truncated(self, isolated):
        _write_lens(Path.cwd() / "lenses", "verbose", "x" * 200)
        info = next(i for i in enumerate_lenses() if i.name == "verbose")
        assert len(info.description) <= 72
        assert info.description.endswith("…")


# ---------------------------------------------------------------------------
# The completer
# ---------------------------------------------------------------------------


def _ctx(tokens=None, prefix=""):
    from painted.cli import CompletionContext
    from painted.cli.types import ArgsView

    return CompletionContext(args=ArgsView({"tokens": tokens or []}), prefix=prefix)


class TestCompleteLens:
    def test_returns_described_candidates(self, isolated):
        from painted.cli import Candidate

        from loops.cli.completers import complete_lens

        cands = complete_lens(_ctx())
        assert all(isinstance(c, Candidate) for c in cands)
        by_value = {c.value: c for c in cands}
        assert "confluence" in by_value
        assert by_value["confluence"].description  # non-empty description

    def test_empty_on_error(self, isolated, monkeypatch):
        from loops.cli import completers

        def boom(*a, **k):
            raise RuntimeError("enumeration failed")

        monkeypatch.setattr("loops.lens_resolver.enumerate_lenses", boom)
        # TAB must never traceback — a broken enumeration degrades to [].
        assert completers.complete_lens(_ctx()) == []

    def test_vertex_scoping_offers_vertex_local_lens(self, isolated, monkeypatch, tmp_path):
        # A vertex named on the line scopes in that vertex's lenses/ dir.
        vertex_dir = tmp_path / "vx"
        _write_lens(vertex_dir / "lenses", "vxonly", "Vertex-only lens.")
        vertex_file = vertex_dir / "vx.vertex"
        vertex_file.parent.mkdir(parents=True, exist_ok=True)
        vertex_file.write_text("vertex\n", encoding="utf-8")

        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex_file if name == "vx" else None,
        )
        from loops.cli.completers import complete_lens

        # Without the vertex token, vxonly is not in scope.
        assert not any(c.value == "vxonly" for c in complete_lens(_ctx()))
        # With it on the line, it is offered.
        values = {c.value for c in complete_lens(_ctx(tokens=["vx"]))}
        assert "vxonly" in values

    def test_scoping_ignores_predicates_and_flags(self, isolated, monkeypatch):
        # Only barewords name a vertex — field=value predicates and flags skip.
        seen = []

        def record(name):
            seen.append(name)
            return None

        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch", record
        )
        from loops.cli.completers import complete_lens

        complete_lens(_ctx(tokens=["kind=decision", "--foo", "project"]))
        assert seen == ["project"]  # the predicate and flag were skipped


class TestRenderFreeImport:
    def test_completers_import_pulls_no_renderer_or_lens_body(self):
        """Importing cli.completers loads neither the renderer nor a lens body.

        The no-renderer-on-TAB guarantee: asserted in a *clean* subprocess so a
        renderer already imported by an earlier test can't mask a regression.
        Painted's render-free foundation (core.zoom/fidelity/errors) is allowed;
        the renderer proper (core.block/core.doc) and any loops.lenses.* body
        are not.
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


def test_lensinfo_is_frozen():
    info = LensInfo("x", "desc", "builtin")
    with pytest.raises(Exception):
        info.name = "y"  # frozen dataclass
