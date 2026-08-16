"""VertexHandle S2 — fold-in-place (checkpoint-suffix) equivalence and telemetry.

Under receipt-order replay, fold order IS append order, so the facts after a
held handle's cursor are a *suffix* that can be folded onto the checkpoint the
handle already holds. This module pins the two things that makes true:

- **Equivalence**: the incrementally-advanced snapshot equals the cold
  ``vertex_fold(at=)`` full reconstruction at EVERY position, for random append
  sequences including backdated timestamps and mixed kinds. ``vertex_fold`` is
  the unmodified oracle; this path must never disagree with it.
- **Honest telemetry**: ``replay_mode`` reports what actually happened —
  ``"full"`` for a cold/forced/epoch-turning refresh (and for the one seeding
  refresh that builds the checkpoint), ``"checkpoint-suffix"`` for a genuine
  fold-in-place, ``"tick-only"`` when no facts moved.

Plus: ``_diff_folds`` must produce identical ``ChangeBatch.rows`` for the same
append whichever path computed the fold — the change feed is not allowed to
depend on how the state was reached.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.handle import open_vertex
from engine.sqlite_store import gen_id
from engine.vertex_reader import vertex_fold

_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
  thread {{ fold {{ items "by" "name" }} }}
  system {{ fold {{ items "collect" 50 }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''

_KEY_FIELD = {"decision": "topic", "thread": "name", "system": "note"}


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "store.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, kind TEXT, ts REAL,"
        " observer TEXT, origin TEXT, payload TEXT, signature TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ticks (id TEXT PRIMARY KEY, name TEXT, ts REAL,"
        " payload TEXT)"
    )
    conn.commit()
    conn.close()
    return vpath, store


def _append(store: Path, kind: str, ts: float, **payload) -> str:
    fid = gen_id()
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id,kind,ts,observer,origin,payload,signature)"
        " VALUES (?,?,?,?,?,?,NULL)",
        (fid, kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()
    return fid


def _items(fold) -> dict[str, list]:
    return {s.kind: [i.payload for i in s.items] for s in fold.sections}


def _cold(vpath: Path, position) -> dict[str, list]:
    """The oracle: an unmodified full reconstruction at this exact position."""
    return _items(vertex_fold(vpath, at=position).fold)


# ---------------------------------------------------------------------------
# 1. Equivalence with the cold oracle, at every position
# ---------------------------------------------------------------------------


_appends = st.lists(
    st.tuples(
        st.sampled_from(["decision", "thread", "system"]),
        # deliberately unsorted timestamps: a backdated arrival must land LAST
        # in the fold (receipt order), which is exactly what makes the suffix
        # fold legal — and what would break under a (ts, id) replay.
        st.floats(min_value=1.0, max_value=500.0, allow_nan=False),
        st.sampled_from(["a", "b", "c"]),
        st.integers(min_value=0, max_value=9),
    ),
    min_size=1,
    max_size=25,
)


@settings(max_examples=200, deadline=None)
@given(appends=_appends)
def test_incremental_fold_equals_cold_fold_at_every_position(tmp_path_factory, appends):
    tmp_path = tmp_path_factory.mktemp("inc")
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as h:
        for kind, ts, key, val in appends:
            _append(store, kind, ts, **{_KEY_FIELD[kind]: key, "value": val})
            batch = h.refresh()
            assert batch is not None
            assert _items(h.snapshot.fold) == _cold(vpath, h.snapshot.position)


@settings(max_examples=40, deadline=None)
@given(appends=_appends, batch_at=st.integers(min_value=1, max_value=5))
def test_multi_fact_batches_fold_in_place_correctly(tmp_path_factory, appends, batch_at):
    """The suffix is often more than one fact — a refresh that catches up on
    several appends at once must fold them in receipt order, not one arbitrary
    one of them."""
    tmp_path = tmp_path_factory.mktemp("incb")
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as h:
        pending = 0
        for kind, ts, key, val in appends:
            _append(store, kind, ts, **{_KEY_FIELD[kind]: key, "value": val})
            pending += 1
            if pending >= batch_at:
                pending = 0
                assert h.refresh() is not None
                assert _items(h.snapshot.fold) == _cold(vpath, h.snapshot.position)
        if pending:
            assert h.refresh() is not None
            assert _items(h.snapshot.fold) == _cold(vpath, h.snapshot.position)


def test_backdated_append_still_wins_the_upsert_incrementally(tmp_path):
    """The concrete case the property covers in the abstract: a fact with an
    OLDER ts appended later folds last, on the incremental path too."""
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as h:
        _append(store, "decision", 300.0, topic="a", position="late")
        h.refresh()
        _append(store, "decision", 100.0, topic="a", position="early")
        batch = h.refresh()
        assert batch.replay_mode == "checkpoint-suffix"
        items = _items(h.snapshot.fold)["decision"]
        assert items[0]["position"] == "early"
        assert _items(h.snapshot.fold) == _cold(vpath, h.snapshot.position)


# ---------------------------------------------------------------------------
# 2. replay_mode telemetry
# ---------------------------------------------------------------------------


def test_warm_refresh_reports_checkpoint_suffix_after_seeding(tmp_path):
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as h:
        _append(store, "decision", 100.0, topic="a")
        # the seeding refresh really does replay all of history — it says so
        assert h.refresh().replay_mode == "full"
        for i in range(5):
            _append(store, "decision", 100.0 + i, topic=f"k{i}")
            assert h.refresh().replay_mode == "checkpoint-suffix"


def test_force_reports_full_and_drops_the_checkpoint(tmp_path):
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as h:
        _append(store, "decision", 100.0, topic="a")
        h.refresh()
        _append(store, "decision", 101.0, topic="b")
        assert h.refresh().replay_mode == "checkpoint-suffix"
        assert h.refresh(force=True).replay_mode == "full"
        # the forced reconstruction dropped the checkpoint, so the next refresh
        # reseeds (full) before fold-in-place resumes
        _append(store, "decision", 102.0, topic="c")
        assert h.refresh().replay_mode == "full"
        _append(store, "decision", 103.0, topic="d")
        assert h.refresh().replay_mode == "checkpoint-suffix"
        assert _items(h.snapshot.fold) == _cold(vpath, h.snapshot.position)


def test_control_fact_forces_full_never_folds_across_an_epoch(tmp_path):
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as h:
        _append(store, "decision", 100.0, topic="a")
        h.refresh()
        _append(store, "decision", 101.0, topic="b")
        assert h.refresh().replay_mode == "checkpoint-suffix"
        # a `_decl.*` control in the batch is an epoch turn: full, and the
        # ontology-changed flag is raised
        _append(store, "_decl.note", 102.0, text="ontology moved")
        batch = h.refresh()
        assert batch.replay_mode == "full"
        assert batch.ontology_changed is True
        assert _items(h.snapshot.fold) == _cold(vpath, h.snapshot.position)


def test_tick_only_refresh_is_unchanged(tmp_path):
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as h:
        _append(store, "decision", 100.0, topic="a")
        h.refresh()
        conn = sqlite3.connect(str(store))
        conn.execute(
            "INSERT INTO ticks (id,name,ts,payload) VALUES (?,?,?,?)",
            (gen_id(), "t1", 200.0, json.dumps({})),
        )
        conn.commit()
        conn.close()
        assert h.refresh().replay_mode == "tick-only"


# ---------------------------------------------------------------------------
# 3. The change feed does not depend on which path computed the fold
# ---------------------------------------------------------------------------


def test_diff_folds_rows_identical_on_both_paths(tmp_path):
    """Two handles over the same store see the same append; one is forced onto
    the full path, the other folds in place. Their ChangeBatch.rows must match
    exactly — same typed row changes, same order."""
    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as warm, open_vertex(vpath) as full:
        # bring both to the same checkpoint, and seed only the warm one
        for i in range(3):
            _append(store, "decision", 100.0 + i, topic=f"k{i}", value=i)
        warm.refresh()  # seeding refresh (full)
        full.refresh()
        _append(store, "decision", 200.0, topic="k1", value=99)  # update
        _append(store, "thread", 50.0, name="n1", state="open")  # add, backdated
        w = warm.refresh()
        f = full.refresh(force=True)
        assert w.replay_mode == "checkpoint-suffix"
        assert f.replay_mode == "full"
        assert w.rows == f.rows
        assert _items(warm.snapshot.fold) == _items(full.snapshot.fold)
