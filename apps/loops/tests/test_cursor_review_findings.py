"""Regression tests for the C1/C2 codex review's 3 HIGH findings.

1. Router mutual-exclusion bypass (read.py): --facts routing to stream
   used to run BEFORE the --at/--diff check, so `--facts --at X --as-of T`
   (or --since/--id) silently discarded --at/--diff and ran the event-time
   stream query instead of refusing.
2. Lens-fetch cursor mismatch (fold.py): a lens-declared fetch that doesn't
   accept at=/as_of= used to be called anyway (silently answering at head)
   while render_context still carried witness/as_of cursor metadata — a
   head answer mislabeled as historical.
3. --refs escaping the cursor (fetch.py): _walk_refs fetched every
   referenced entity at HEAD regardless of the primary fold's witness/as_of
   position, so a historical read's graph neighborhood silently leaked
   post-cursor facts.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from atoms import Fact

from engine.builder import fold_by, vertex
from engine.sqlite_store import SqliteStore, gen_id
from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import read as read_view

from .golden.helpers import block_to_text


def ctx(reporter: BufferReporter | None = None) -> Invocation:
    return Invocation(reporter=reporter or BufferReporter())


def _append(store, kind, ts, *, fid=None, observer="kyle", **payload) -> str:
    conn = sqlite3.connect(str(store))
    fid = fid or gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (fid, kind, ts, observer, "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()
    return fid


# ---------------------------------------------------------------------------
# Finding 1 — router silent-discard of --at/--diff on the facts route
# ---------------------------------------------------------------------------


class TestRouterNoLongerSilentlyDiscardsCursorFlags:
    def test_facts_at_as_of_refuses_instead_of_silent_stream(self):
        # Before the fix: known.facts and known.as_of routed to stream at
        # line 48, BEFORE the --at/--as-of exclusivity check ever ran — --at
        # vanished and the event-time stream query executed with rc=0.
        reporter = BufferReporter()
        rc = read_view.run(
            ["project", "--facts", "--at", "head", "--as-of", "30d"], ctx(reporter),
        )
        assert rc == 2
        err = reporter.err_text
        assert "--at" in err and "--diff" in err
        assert "fold route only" in err

    def test_facts_at_since_refuses_instead_of_silent_stream(self):
        reporter = BufferReporter()
        rc = read_view.run(
            ["project", "--facts", "--at", "head", "--since", "7d"], ctx(reporter),
        )
        assert rc == 2
        assert "fold route only" in reporter.err_text

    def test_facts_at_id_refuses_instead_of_silent_stream(self):
        reporter = BufferReporter()
        rc = read_view.run(
            ["project", "--facts", "--at", "head", "--id", "01ARZ3NDEKTSV4RRFFQ69G5FAV"],
            ctx(reporter),
        )
        assert rc == 2
        assert "fold route only" in reporter.err_text

    def test_facts_diff_since_refuses_instead_of_silent_stream(self):
        reporter = BufferReporter()
        rc = read_view.run(
            ["project", "--facts", "--diff", "head..head", "--since", "7d"],
            ctx(reporter),
        )
        assert rc == 2
        assert "fold route only" in reporter.err_text

    def test_ticks_at_still_refuses(self):
        # Guard: consolidating the check must not lose the pre-existing
        # --ticks refusal.
        reporter = BufferReporter()
        rc = read_view.run(["project", "--ticks", "--at", "head"], ctx(reporter))
        assert rc == 2
        assert "fold route only" in reporter.err_text

    def test_bare_facts_at_still_composes_on_fold_route(self):
        # Regression guard: --facts --at ADDRESS with NO since/as-of/id is a
        # legitimate fold-route composition (facts visibility layer over a
        # witnessed reconstruction) — must NOT be caught by the new check.
        from unittest import mock

        c = ctx()
        with mock.patch("loops.cli.views.fold.run", return_value=0) as m:
            rc = read_view.run(["project", "--facts", "--at", "head"], c)
        assert rc == 0
        argv = m.call_args[0][0]
        assert "--facts" in argv and "--at" in argv and "head" in argv


# ---------------------------------------------------------------------------
# Finding 2 — a lens fetch that can't honor the cursor must refuse, not
# silently answer at head under cursor metadata
# ---------------------------------------------------------------------------


@pytest.fixture
def cursor_vertex(tmp_path):
    v = vertex("cursor2").store("./c2.db").loop("decision", fold_by("topic"))
    vpath = tmp_path / "cursor2.vertex"
    v.write(vpath)
    store = tmp_path / "c2.db"
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict,
    ).close()
    return vpath, store


class TestLensFetchCursorMismatchRefuses:
    def test_builtin_composition_lens_refuses_at(self, cursor_vertex):
        # graph.fetch(vertex_path, kind=None, observer=None) declares neither
        # at= nor **kwargs — a real, shipped example of the gap (not a
        # synthetic fixture): --lens graph --at ... used to silently render
        # HEAD data under a "witness cursor" mode line.
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        reporter = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--lens", "graph", "--at", "head"], ctx(reporter),
        )
        assert rc == 2
        err = reporter.err_text
        assert "--at" in err
        assert "lens fetch" in err

    def test_builtin_composition_lens_refuses_as_of(self, cursor_vertex):
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        reporter = BufferReporter()
        rc = read_view.run(
            [str(vpath), "--lens", "confluence", "--as-of", "150"], ctx(reporter),
        )
        assert rc == 2
        assert "--as-of" in reporter.err_text

    def test_builtin_lens_without_cursor_flag_is_unaffected(self, cursor_vertex):
        # Regression guard: the SAME lens, with no cursor flag, must still
        # work exactly as before (head read, no refusal).
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        reporter = BufferReporter()
        rc = read_view.run([str(vpath), "--lens", "graph"], ctx(reporter))
        assert rc == 0
        assert reporter.blocks

    def test_default_fold_fetch_still_honors_at(self, cursor_vertex):
        # Regression guard: no --lens override (the built-in path) must
        # keep working — it always supports at=/as_of=.
        vpath, store = cursor_vertex
        _append(store, "decision", 100, topic="a", message="alpha")
        reporter = BufferReporter()
        rc = read_view.run([str(vpath), "--at", "head"], ctx(reporter))
        assert rc == 0
        assert "alpha" in block_to_text(reporter.blocks[0])


# ---------------------------------------------------------------------------
# Finding 3 — --refs walk must stay pinned to the primary fold's position
# ---------------------------------------------------------------------------


@pytest.fixture
def refs_vertex(tmp_path):
    v = (
        vertex("cursor3")
        .store("./c3.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
    )
    vpath = tmp_path / "cursor3.vertex"
    v.write(vpath)
    store = tmp_path / "c3.db"
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict,
    ).close()
    return vpath, store


class TestRefsWalkStaysAtTheCursor:
    def test_walked_entity_reflects_the_witness_position_not_head(self, refs_vertex):
        vpath, store = refs_vertex
        # A decision referencing thread t1, folded alongside t1's state.
        _append(
            store, "decision", 100, topic="design/a", message="alpha",
            ref="thread:t1",
        )
        _append(store, "thread", 100, name="t1", message="before-cursor")
        # Freeze a position that has seen exactly these two rows.
        reporter_before = BufferReporter()
        rc = read_view.run(
            [str(vpath), "decision/design/a", "--at", "seq:2", "--refs"],
            ctx(reporter_before),
        )
        assert rc == 0
        # A LATER fact updates t1 — arrives after the frozen position.
        _append(store, "thread", 200, name="t1", message="after-cursor")

        # Re-run at the SAME frozen position: the walked thread must still
        # show "before-cursor", never the post-position update.
        reporter = BufferReporter()
        rc = read_view.run(
            [str(vpath), "decision/design/a", "--at", "seq:2", "--refs"],
            ctx(reporter),
        )
        assert rc == 0
        text = block_to_text(reporter.blocks[0])
        assert "before-cursor" in text
        assert "after-cursor" not in text

    def test_head_walk_still_sees_the_latest_referenced_state(self, refs_vertex):
        # Regression guard: an UNCURSORED --refs walk must still be head-
        # scoped exactly as before the fix.
        vpath, store = refs_vertex
        _append(
            store, "decision", 100, topic="design/a", message="alpha",
            ref="thread:t1",
        )
        _append(store, "thread", 100, name="t1", message="before-cursor")
        _append(store, "thread", 200, name="t1", message="after-cursor")

        reporter = BufferReporter()
        rc = read_view.run(
            [str(vpath), "decision/design/a", "--refs"], ctx(reporter),
        )
        assert rc == 0
        text = block_to_text(reporter.blocks[0])
        assert "after-cursor" in text
