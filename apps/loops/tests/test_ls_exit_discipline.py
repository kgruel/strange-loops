"""S2 exit-discipline family — ls error paths exit nonzero with stderr.

Pins the three cli-honesty-wave S2 frictions:

- friction:ls-vertex-not-found-exits-zero — unknown vertex: nonzero exit,
  error on STDERR, did-you-mean parity with read's kind treatment.
- friction:ls-kind-flag-no-validation — ``ls <v> --kind bogus`` runs the
  SAME validator as read (``_validate_kind_or_exit``: exit 2, stderr,
  did-you-mean) instead of rendering a plausible 0-entries section.
- friction:reindex-hint-omits-vertex-target — the FTS staleness hint names
  the vertex (``sl store reindex <vertex>``), not the bare refusing form.

And the flip side: valid invocations still exit 0.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from engine.builder import fold_by, vertex
from loops.commands.ls import _run_kind_stat, _run_ls
from loops.main import cmd_emit


@pytest.fixture
def proj(loops_home, monkeypatch, tmp_path) -> Path:
    """A store-backed vertex named 'project' with a few decision facts.

    cwd is pinned to an empty dir so vertex enumeration (did-you-mean
    candidates) sees only the isolated LOOPS_HOME, never the repo's own
    local vertices.
    """
    monkeypatch.chdir(tmp_path)
    vdir = loops_home / "project"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "project.vertex"
    (
        vertex("project")
        .store("./data/project.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
        .write(vpath)
    )

    def emit(kind, **payload):
        parts = [f"{k}={v}" for k, v in payload.items()]
        ns = argparse.Namespace(
            vertex=None, kind=kind, parts=parts, observer="", dry_run=False
        )
        assert cmd_emit(ns, vertex_path=vpath) == 0

    emit("decision", topic="design/a", message="one")
    emit("decision", topic="arch/b", message="two")
    return vpath


# ---------------------------------------------------------------------------
# (a) unknown vertex — nonzero, stderr, did-you-mean
# ---------------------------------------------------------------------------


class TestUnknownVertex:
    def test_listing_exits_nonzero_with_stderr_suggestion(self, proj, capsys):
        code = _run_ls(["projcet"])
        captured = capsys.readouterr()
        assert code == 1  # read's unresolvable-vertex exit code
        assert captured.out == ""
        assert "vertex not found: projcet" in captured.err
        assert "Did you mean: project?" in captured.err
        assert "Known vertices:" in captured.err

    def test_kind_descent_on_unknown_vertex_exits_nonzero(self, proj, capsys):
        code = _run_kind_stat("projcet", "decision", [])
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "vertex not found: projcet" in captured.err
        assert "Did you mean: project?" in captured.err


# ---------------------------------------------------------------------------
# (b) --kind bogus — read's validator, verbatim
# ---------------------------------------------------------------------------


class TestBogusKind:
    def test_descent_bogus_kind_matches_reads_error(self, proj, capsys):
        with pytest.raises(SystemExit) as exc:
            _run_kind_stat("project", "decsion", [])
        captured = capsys.readouterr()
        assert exc.value.code == 2  # read's _validate_kind_or_exit code
        assert captured.out == ""
        assert "does not declare kind 'decsion'" in captured.err
        assert "Did you mean: decision?" in captured.err
        assert "Declared kinds:" in captured.err

    def test_composed_kind_narrow_validates_too(self, proj, capsys):
        # --kind bogus --observer: bypasses the descent path, still validated.
        with pytest.raises(SystemExit) as exc:
            _run_ls(["project", "--kind", "decsion", "--observer"])
        assert exc.value.code == 2
        assert "does not declare kind 'decsion'" in capsys.readouterr().err

    def test_declared_but_empty_kind_still_renders(self, proj, capsys):
        # thread is declared with zero facts — that's a valid 0-entries view,
        # not a typo (same stance as read's validator).
        code = _run_kind_stat("project", "thread", ["--plain"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""


# ---------------------------------------------------------------------------
# valid invocations — still exit 0
# ---------------------------------------------------------------------------


class TestValidInvocationsExitZero:
    def test_vertex_listing(self, proj, capsys):
        code = _run_ls(["project", "--plain"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert "project" in captured.out

    def test_kind_descent(self, proj, capsys):
        code = _run_kind_stat("project", "decision", ["--plain"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert "decision" in captured.out


# ---------------------------------------------------------------------------
# (c) staleness hint names the vertex
# ---------------------------------------------------------------------------


class TestReindexHintNamesVertex:
    def _stale_surface(self):
        from loops.surface import Surface, Window

        return Surface(
            rows=(),
            vertex="project",
            window=Window(query="auth", stale=("decision",)),
        )

    def test_hint_renders_reindex_with_vertex_name(self):
        from painted import Zoom

        from loops.lenses.fold import fold_view

        from .helpers import block_text

        text = block_text(fold_view(self._stale_surface(), Zoom.SUMMARY, None))
        assert "`sl store reindex project`" in text
        assert "index stale" in text
