"""Tests for vertex enumeration + the leading-token completer (shell completion T3 S2).

Two surfaces, mirroring ``test_lens_completion.py``'s shape:

- ``commands.resolve.enumerate_vertices`` — the enumeration side: local tier
  (``.loops/*.vertex``, ``cwd/*.vertex``), config tier
  (``LOOPS_HOME/**/<name>.vertex``, incl. slashed names), instance/aggregation
  description, resilience.
- ``cli.completers.complete_vertex`` — the domain completer hung on the
  read verb's ``tokens`` positional: candidates only for the leading slot,
  empty-on-error, render-free import.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from loops.commands.resolve import VertexInfo, enumerate_vertices


def _write_instance(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.vertex").write_text(
        f'name "{name}"\n'
        f'store "./data/{name}.db"\n\n'
        "loops {\n"
        '  thing { fold { count "inc" } }\n'
        "}\n",
        encoding="utf-8",
    )


def _write_aggregation(directory: Path, name: str, *, children: tuple[str, ...] = ()) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    combine = "".join(f'  vertex "{c}"\n' for c in children) or '  vertex "nonexistent"\n'
    (directory / f"{name}.vertex").write_text(
        f'name "{name}"\n\n'
        "combine {\n"
        f"{combine}"
        "}\n\n"
        "loops {\n"
        '  thing { fold { count "inc" } }\n'
        "}\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Isolate cwd and LOOPS_HOME to empty tmp dirs — the same isolation
    shape as ``test_lens_completion.py``'s fixture, scoped to vertex tiers
    (``.loops/`` / cwd / ``LOOPS_HOME``) instead of lens dirs."""
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd))
    monkeypatch.setenv("LOOPS_HOME", str(home))
    return tmp_path


class TestEnumerateLocalTier:
    def test_loops_dir_instance(self, isolated, tmp_path):
        _write_instance(Path.cwd() / ".loops", "project")
        by_name = {v.name: v for v in enumerate_vertices()}
        assert "project" in by_name
        assert by_name["project"].tier == "local"
        assert by_name["project"].description == "instance"

    def test_cwd_fallback_instance(self, isolated):
        _write_instance(Path.cwd(), "legacy")
        by_name = {v.name: v for v in enumerate_vertices()}
        assert by_name["legacy"].tier == "local"

    def test_loops_dir_shadows_cwd(self, isolated):
        # Same name in both tiers — .loops/ wins (first spelling, local-first).
        _write_instance(Path.cwd() / ".loops", "dup")
        _write_instance(Path.cwd(), "dup")
        matches = [v for v in enumerate_vertices() if v.name == "dup"]
        assert len(matches) == 1

    def test_bare_dotvertex_not_a_candidate(self, isolated):
        # .loops/.vertex is the unnamed workspace-root convention — nothing
        # to type for it, so it must not surface as a completion candidate.
        loops_dir = Path.cwd() / ".loops"
        loops_dir.mkdir()
        (loops_dir / ".vertex").write_text('name "root"\nstore "./x.db"\n', encoding="utf-8")
        assert enumerate_vertices() == []


class TestEnumerateConfigTier:
    def test_top_level_instance(self, isolated, tmp_path):
        home = tmp_path / "home"
        _write_instance(home / "project", "project")
        by_name = {v.name: v for v in enumerate_vertices()}
        assert by_name["project"].tier == "config"
        assert by_name["project"].description == "instance"

    def test_aggregation_description(self, isolated, tmp_path):
        home = tmp_path / "home"
        _write_aggregation(home / "meta", "meta")
        by_name = {v.name: v for v in enumerate_vertices()}
        assert by_name["meta"].description == "aggregation"

    def test_slashed_name(self, isolated, tmp_path):
        # LOOPS_HOME/comms/discord/discord.vertex -> name "comms/discord",
        # mirroring resolve_vertex's home/name/name.vertex convention.
        home = tmp_path / "home"
        _write_instance(home / "comms" / "discord", "discord")
        by_name = {v.name: v for v in enumerate_vertices()}
        assert "comms/discord" in by_name

    def test_non_matching_stem_skipped(self, isolated, tmp_path):
        # A .vertex file whose stem doesn't match its parent dir isn't a
        # named vertex by this convention (e.g. a stray backup file).
        home = tmp_path / "home"
        d = home / "project"
        d.mkdir(parents=True)
        (d / "project.vertex.bak.vertex").write_text('name "x"\n', encoding="utf-8")
        assert enumerate_vertices() == []

    def test_local_shadows_config(self, isolated, tmp_path):
        home = tmp_path / "home"
        _write_instance(home / "project", "project")
        _write_instance(Path.cwd() / ".loops", "project")
        matches = [v for v in enumerate_vertices() if v.name == "project"]
        assert len(matches) == 1
        assert matches[0].tier == "local"


class TestEnumerateResilience:
    def test_missing_home_no_crash(self, isolated, monkeypatch, tmp_path):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "does-not-exist"))
        assert enumerate_vertices() == []

    def test_broken_vertex_file_still_enumerated_undescribed(self, isolated, tmp_path):
        home = tmp_path / "home"
        d = home / "broken"
        d.mkdir(parents=True)
        (d / "broken.vertex").write_text("not < valid kdl {{{", encoding="utf-8")
        by_name = {v.name: v for v in enumerate_vertices()}
        assert "broken" in by_name
        assert by_name["broken"].description == ""

    def test_empty_everywhere(self, isolated):
        assert enumerate_vertices() == []


# ---------------------------------------------------------------------------
# The completer
# ---------------------------------------------------------------------------


def _ctx(tokens=None, prefix=""):
    from painted.cli import CompletionContext
    from painted.cli.types import ArgsView

    return CompletionContext(args=ArgsView({"tokens": tokens or []}), prefix=prefix)


class TestCompleteVertex:
    def test_returns_described_candidates_for_leading_slot(self, isolated):
        from painted.cli import Candidate

        from loops.cli.completers import complete_vertex

        _write_instance(Path.cwd() / ".loops", "project")
        cands = complete_vertex(_ctx())
        assert all(isinstance(c, Candidate) for c in cands)
        by_value = {c.value: c for c in cands}
        assert "project" in by_value
        assert by_value["project"].description == "instance"

    def test_defers_once_a_token_is_already_present(self, isolated):
        from loops.cli.completers import complete_vertex

        _write_instance(Path.cwd() / ".loops", "project")
        # A vertex name is already on the line — this slice doesn't offer
        # kind/key candidates, so the completer defers with [].
        assert complete_vertex(_ctx(tokens=["project"])) == []

    def test_empty_on_error(self, isolated, monkeypatch):
        from loops.cli import completers

        def boom(*a, **k):
            raise RuntimeError("enumeration failed")

        monkeypatch.setattr("loops.commands.resolve.enumerate_vertices", boom)
        # TAB must never traceback — a broken enumeration degrades to [].
        assert completers.complete_vertex(_ctx()) == []

    def test_empty_when_nothing_resolvable(self, isolated):
        from loops.cli.completers import complete_vertex

        assert complete_vertex(_ctx()) == []


class TestRenderFreeImport:
    def test_completers_import_pulls_no_renderer_or_lens_body(self):
        """Importing cli.completers loads neither the renderer nor a lens body.

        Same render-free guarantee ``test_lens_completion.py`` asserts —
        checked again here because ``complete_vertex`` is a new import path
        into ``commands.resolve``, which must stay off the renderer.
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


def test_vertexinfo_is_frozen():
    info = VertexInfo("x", "desc", "local")
    with pytest.raises(Exception):
        info.name = "y"  # frozen dataclass
