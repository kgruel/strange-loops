"""Tests for surface.py — the typed projection between fetch and render.

Load-bearing guards:
  * salience/inbound PARITY against the lens helpers (non-circular lift guard)
  * complete-key granularity on a MIXED surface (the RESHAPE proof)
  * painted-free AST guard (the leaf invariant S2 depends on)
  * collect-fold order preservation (the S2 empty-diff prerequisite)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from atoms import FoldItem, FoldSection, FoldState, WalkedItem

import loops.surface as surface_mod
from loops.surface import (
    budget,
    count,
    filter,
    project,
    search,
    select,
    to_dict,
    whole,
)

# The salience helpers now live in surface.py (lifted from lenses/fold.py and
# the lens copies DELETED in S2). The cross-module byte-faithfulness of the lift
# was proven at S1 (AST-segment diff vs the lens originals, in git history); the
# HAND-COMPUTED assertions below (inbound==2, salience==3, …) remain the genuine
# independent oracle — they don't depend on either helper being "right".
from loops.surface import (
    _compute_inbound_refs,
    _inbound_count,
)


# ---------------------------------------------------------------------------
# Fixtures — FoldStates built directly for precise control of refs/n/fold_type
# ---------------------------------------------------------------------------


def _decision(topic, *, n=1, refs=(), ts=100.0, observer="me", id=None):
    return FoldItem(
        payload={"topic": topic, "message": f"body of {topic}"},
        ts=ts, observer=observer, id=id, n=n, refs=tuple(refs),
    )


def _byfold_state(*items, vertex="t", kind="decision", key_field="topic"):
    return FoldState(
        sections=(
            FoldSection(
                kind=kind, items=tuple(items), fold_type="by",
                key_field=key_field, preview_fields=("message",),
            ),
        ),
        vertex=vertex,
    )


# ---------------------------------------------------------------------------
# AST guard — painted-free leaf
# ---------------------------------------------------------------------------


def test_surface_is_painted_free():
    """surface.py must import nothing from painted or loops.lenses — it is the
    leaf the lens depends on, not the reverse."""
    src = Path(str(surface_mod.__file__)).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert not n.name.startswith("painted"), f"painted import: {n.name}"
                assert not n.name.startswith("loops.lenses"), f"lens import: {n.name}"
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("painted"), f"painted from-import: {mod}"
            assert not mod.startswith("loops.lenses"), f"lens from-import: {mod}"


# ---------------------------------------------------------------------------
# Parity — the non-circular byte-for-byte lift guard
# ---------------------------------------------------------------------------


def test_project_materializes_salience_parity():
    """Every Row.salience/inbound equals recomputing on the same FoldState.

    Exercises all three matching forms against ``cache``: a canonical
    ``decision:cache`` colon ref AND a legacy ``decision/cache`` slash ref
    both land on ``Address(decision, cache)`` (kind-exact), and a bare
    separator-less ``cache`` ref lands on ``Address('', cache)`` (the bare
    fallback). Non-circular: project() and _inbound_count are compared, and
    the explicit counts pin the exact-match contract.
    """
    state = _byfold_state(
        _decision("cache", n=2, refs=()),
        _decision("auth", n=1, refs=("decision:cache", "decision/cache")),
        _decision("db", n=3, refs=("cache",)),
    )
    inbound = _compute_inbound_refs(state)
    surface = project(state)

    by_topic = {r.key: r for r in surface.rows}
    for section in state.sections:
        kf = section.key_field
        for item in section.items:
            topic = item.payload["topic"]
            row = by_topic[topic]
            assert row.inbound == _inbound_count(item, section.kind, kf, inbound), topic
            assert row.salience == item.n + _inbound_count(
                item, section.kind, kf, inbound
            ), topic

    # cache: colon + legacy-slash both count kind-exact (2) + one bare ref (1)
    # → inbound 3; plus n=2 → salience 5. auth/db reference out, not in.
    assert by_topic["cache"].inbound == 3
    assert by_topic["cache"].salience == 5
    assert by_topic["auth"].inbound == 0
    assert by_topic["db"].inbound == 0


# ---------------------------------------------------------------------------
# Granularity — complete-key address, the RESHAPE proof
# ---------------------------------------------------------------------------


def test_mixed_surface_complete_key_granularity():
    """A complete-key query makes the exact-match row 'whole' and its prefix
    siblings 'headline' — window.granularity summarizes to 'mixed'."""
    state = _byfold_state(
        _decision("design/foo"),
        _decision("design/foobar"),
    )
    surface = project(state, queried_key="design/foo")

    by_topic = {r.key: r for r in surface.rows}
    assert by_topic["design/foo"].granularity == "whole"
    assert by_topic["design/foobar"].granularity == "headline"
    assert surface.window.granularity == "mixed"


def test_complete_key_granularity_is_case_insensitive():
    state = _byfold_state(_decision("Design/Foo"))
    surface = project(state, queried_key="design/foo")
    assert surface.rows[0].granularity == "whole"


def test_adding_sibling_does_not_flip_existing_granularity():
    """The decisive property: a 2nd fact under the same prefix never changes an
    existing complete-key read's granularity (cardinality could not guarantee
    this; complete-key address does)."""
    one = project(_byfold_state(_decision("design/foo")), queried_key="design/foo")
    two = project(
        _byfold_state(_decision("design/foo"), _decision("design/foobar")),
        queried_key="design/foo",
    )
    foo_one = {r.key: r for r in one.rows}["design/foo"]
    foo_two = {r.key: r for r in two.rows}["design/foo"]
    assert foo_one.granularity == foo_two.granularity == "whole"


def test_full_forces_whole():
    state = _byfold_state(_decision("design/foo"), _decision("design/bar"))
    surface = project(state, full=True)
    assert all(r.granularity == "whole" for r in surface.rows)
    assert surface.window.granularity == "whole"


def test_prefix_query_yields_no_whole_rows():
    """A bare-prefix query (design/) is NOT a complete-key address — no row is
    whole. This guards the exact-vs-prefix distinction the rule exists for; a
    future == → startswith regression would flip these rows to whole."""
    state = _byfold_state(_decision("design/foo"), _decision("design/bar"))
    surface = project(state, queried_key="design/")
    assert all(r.granularity == "headline" for r in surface.rows)
    assert surface.window.granularity == "headline"


def test_collect_row_never_whole_via_key_branch():
    """A keyless (collect) row can only go whole via --full, never via a key
    query — the key branch is guarded on key_field + key not None."""
    state = FoldState(
        sections=(
            FoldSection(kind="log",
                        items=(FoldItem(payload={"message": "m"}, ts=1.0, id="x"),),
                        fold_type="collect", key_field=None),
        ),
        vertex="t",
    )
    surface = project(state, queried_key="m")
    assert surface.rows[0].granularity == "headline"


# ---------------------------------------------------------------------------
# Ordering — declaration order, salience-desc by-folds, collect preservation
# ---------------------------------------------------------------------------


def test_declaration_order_and_entity_axis():
    state = FoldState(
        sections=(
            FoldSection(kind="decision", items=(_decision("d1"),),
                        fold_type="by", key_field="topic"),
            FoldSection(kind="thread",
                        items=(FoldItem(payload={"name": "t1"}, ts=1.0),),
                        fold_type="by", key_field="name"),
        ),
        vertex="t",
    )
    surface = project(state)
    kinds = [r.kind for r in surface.rows]
    assert kinds == ["decision", "thread"]
    assert all(r.axis == "entity" for r in surface.rows)


def test_project_preserves_fold_order_for_byfold():
    """project() yields FAITHFUL fold order (no salience pre-sort) — the lens
    derives the namespace-group tiebreak and --refs edge order from fold order,
    so pre-sorting here would make the S2 render diverge byte-for-byte. Ranking
    is a transform (budget(limit)), not the base order."""
    state = _byfold_state(
        _decision("low", n=1),
        _decision("high", n=9),
        _decision("mid", n=4),
    )
    surface = project(state)
    assert [r.key for r in surface.rows] == ["low", "high", "mid"]  # fold order, not salience


def test_budget_limit_is_the_ranking_path():
    """Salience-desc ordering is produced by budget(limit), not project()."""
    state = _byfold_state(_decision("low", n=1), _decision("high", n=9), _decision("mid", n=4))
    ranked = budget(project(state), limit=3)
    assert [r.key for r in ranked.rows] == ["high", "mid", "low"]


def test_collect_section_preserves_fold_order():
    """COLLECT folds keep fold order (the lens does NOT re-sort them) — project()
    must NOT salience-sort them, or S2's empty-diff render flips."""
    state = FoldState(
        sections=(
            FoldSection(
                kind="log",
                items=(
                    FoldItem(payload={"message": "first"}, ts=1.0, id="a"),
                    FoldItem(payload={"message": "second"}, ts=2.0, id="b"),
                    FoldItem(payload={"message": "third"}, ts=3.0, id="c"),
                ),
                fold_type="collect", key_field=None,
            ),
        ),
        vertex="t",
    )
    surface = project(state)
    assert [r.payload["message"] for r in surface.rows] == ["first", "second", "third"]


def test_falsy_fold_key_is_treated_as_keyless():
    """A falsy fold value (int 0, False, "") is no-key — byte-matching the lens's
    old _item_full_key/_inbound_count truthiness gate. Row.key is None so the
    address falls back to kind/<id> and the edge/facts lookups (keyed by
    address-when-key-not-None) correctly skip it, as the old lens did."""
    state = FoldState(
        sections=(
            FoldSection(
                kind="thread", fold_type="by", key_field="name",
                items=(
                    FoldItem(payload={"name": 0, "status": "zero"}, ts=1.0, id="Z1"),
                ),
            ),
        ),
        vertex="t",
    )
    row = project(state).rows[0]
    assert row.key is None
    assert row.address == "thread/Z1"  # not "thread/0"


def test_collect_row_address_uses_id():
    state = FoldState(
        sections=(
            FoldSection(kind="log",
                        items=(FoldItem(payload={"message": "m"}, ts=1.0, id="01ABC"),),
                        fold_type="collect", key_field=None),
        ),
        vertex="t",
    )
    row = project(state).rows[0]
    assert row.key is None
    assert row.address == "log/01ABC"


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


def test_predicate_eq_and_comma_or():
    state = FoldState(
        sections=(
            FoldSection(
                kind="thread",
                items=(
                    FoldItem(payload={"name": "a", "status": "open"}, ts=1.0),
                    FoldItem(payload={"name": "b", "status": "proposed"}, ts=2.0),
                    FoldItem(payload={"name": "c", "status": "resolved"}, ts=3.0),
                ),
                fold_type="by", key_field="name",
            ),
        ),
        vertex="t",
    )
    surface = project(state)

    eq = filter(surface, where={"status": ("open",)})
    assert {r.key for r in eq.rows} == {"a"}

    comma_or = filter(surface, where={"status": ("open", "proposed")})
    assert {r.key for r in comma_or.rows} == {"a", "b"}
    assert comma_or.window.shown == 2


def test_predicate_and_across_fields_and_missing_field():
    state = FoldState(
        sections=(
            FoldSection(
                kind="thread",
                items=(
                    FoldItem(payload={"name": "a", "status": "open", "owner": "me"}, ts=1.0),
                    FoldItem(payload={"name": "b", "status": "open", "owner": "you"}, ts=2.0),
                ),
                fold_type="by", key_field="name",
            ),
        ),
        vertex="t",
    )
    surface = project(state)
    # AND across two fields: status=open AND owner=me → only a
    both = filter(surface, where={"status": ("open",), "owner": ("me",)})
    assert {r.key for r in both.rows} == {"a"}
    # missing field → no match (neither row has 'priority')
    none = filter(surface, where={"priority": ("high",)})
    assert none.rows == ()


def test_filter_by_kind_key_observer():
    state = FoldState(
        sections=(
            FoldSection(kind="decision",
                        items=(_decision("design/x", observer="me"),
                               _decision("ops/y", observer="you")),
                        fold_type="by", key_field="topic"),
        ),
        vertex="t",
    )
    surface = project(state)
    assert {r.key for r in filter(surface, key="design/").rows} == {"design/x"}
    assert {r.key for r in filter(surface, observer="you").rows} == {"ops/y"}
    assert {r.key for r in filter(surface, kind="decision").rows} == {"design/x", "ops/y"}


def test_select_narrows_payload():
    surface = project(_byfold_state(_decision("design/foo")))
    narrowed = select(surface, ("topic",))
    assert narrowed.rows[0].payload == {"topic": "design/foo"}
    assert narrowed.window.fields == ("topic",)


def test_budget_limit_takes_salience_head():
    state = _byfold_state(
        _decision("low", n=1), _decision("high", n=9), _decision("mid", n=5),
    )
    surface = project(state)
    b = budget(surface, limit=2)
    assert [r.key for r in b.rows] == ["high", "mid"]
    assert b.window.limited_by == "limit"
    assert b.window.shown == 2


def test_budget_last_takes_newest_by_ts():
    state = _byfold_state(
        _decision("old", ts=1.0), _decision("new", ts=3.0), _decision("mid", ts=2.0),
    )
    surface = project(state)
    b = budget(surface, last=2)
    assert [r.key for r in b.rows] == ["new", "mid"]
    assert b.window.limited_by == "last"


def test_count_total_and_by_kind():
    state = FoldState(
        sections=(
            FoldSection(kind="decision", items=(_decision("a"), _decision("b")),
                        fold_type="by", key_field="topic"),
            FoldSection(kind="thread",
                        items=(FoldItem(payload={"name": "t"}, ts=1.0),),
                        fold_type="by", key_field="name"),
        ),
        vertex="t",
    )
    surface = project(state)

    total = count(surface)
    assert total.rows[0].payload == {"count": 3}

    by_kind = count(surface, by="kind")
    counts = {r.payload["kind"]: r.payload["count"] for r in by_kind.rows}
    assert counts == {"decision": 2, "thread": 1}


def test_count_by_payload_field_falls_through_to_payload():
    """by=<payload field> (not a Row attr) groups by the payload value —
    _row_group prefers a Row attribute, else the payload."""
    state = FoldState(
        sections=(
            FoldSection(
                kind="thread",
                items=(
                    FoldItem(payload={"name": "a", "status": "open"}, ts=1.0),
                    FoldItem(payload={"name": "b", "status": "open"}, ts=2.0),
                    FoldItem(payload={"name": "c", "status": "resolved"}, ts=3.0),
                ),
                fold_type="by", key_field="name",
            ),
        ),
        vertex="t",
    )
    by_status = count(project(state), by="status")
    counts = {r.payload["status"]: r.payload["count"] for r in by_status.rows}
    assert counts == {"open": 2, "resolved": 1}
    # count-desc ordering: open (2) before resolved (1)
    assert [r.payload["status"] for r in by_status.rows] == ["open", "resolved"]


def test_budget_salience_window_keeps_high_and_falls_back():
    state = _byfold_state(
        _decision("a", n=1),  # salience 1
        _decision("b", n=3),  # salience 3
        _decision("c", n=1),  # salience 1
    )
    surface = project(state)
    windowed = budget(surface, salience_window=True)
    assert {r.key for r in windowed.rows} == {"b"}  # only salience>1 survives
    assert windowed.window.limited_by == "salience"

    # fallback: when ALL rows are salience<=1, keep the top-1 (never empty)
    flat = project(_byfold_state(_decision("x", n=1), _decision("y", n=1)))
    fb = budget(flat, salience_window=True)
    assert len(fb.rows) == 1


def test_whole_forces_granularity():
    surface = project(_byfold_state(_decision("design/foo"), _decision("design/bar")))
    forced = whole(surface)
    assert all(r.granularity == "whole" for r in forced.rows)

    one = whole(surface, address="decision/design/foo")
    by_addr = {r.address: r for r in one.rows}
    assert by_addr["decision/design/foo"].granularity == "whole"
    assert by_addr["decision/design/bar"].granularity == "headline"


def test_search_produces_event_rows():
    state = _byfold_state(
        _decision("design/foo"),   # body: "body of design/foo"
        _decision("ops/bar"),      # body: "body of ops/bar"
    )
    surface = project(state)
    found = search(surface, "design/foo")
    assert len(found.rows) == 1
    assert found.rows[0].axis == "event"
    assert found.window.query == "design/foo"


def test_search_orders_ts_desc():
    state = _byfold_state(
        _decision("design/a", ts=1.0),
        _decision("design/b", ts=3.0),
        _decision("design/c", ts=2.0),
    )
    surface = project(state)
    # all share the substring "body of design" via the message body
    found = search(surface, "body of design")
    assert [r.key for r in found.rows] == ["design/b", "design/c", "design/a"]


# --- S5: FTS5 + substring fallback + coverage signal -----------------------


def _search_vertex(tmp_path, *, reindex: bool = True):
    """A two-kind vertex: ``decision`` FTS-indexed (search=), ``thread`` NOT.

    Returns (vpath) after seeding one searchable fact in each kind. Calls
    ``engine.vertex_reindex`` by default (S2: reads never build the index —
    a caller that wants FTS-fresh results must reindex explicitly, same as
    ``sl store reindex`` would). Pass ``reindex=False`` to get a vertex whose
    index was NEVER built, for tests exercising the staleness/missing-index
    fallback path itself.
    """
    import argparse

    from engine.builder import fold_by, vertex
    from loops.main import cmd_emit

    v = (
        vertex("srch")
        .store("./srch.db")
        .loop("decision", fold_by("topic"), search=["topic", "message"])
        .loop("thread", fold_by("name"))
    )
    vpath = tmp_path / "srch.vertex"
    v.write(vpath)

    def emit(kind, **payload):
        parts = [f"{k}={val}" for k, val in payload.items()]
        cmd_emit(
            argparse.Namespace(vertex=None, kind=kind, parts=parts, observer="", dry_run=False),
            vertex_path=vpath,
        )

    emit("decision", topic="design/auth", message="choose JWT over sessions")
    emit("thread", name="auth-arc", message="revisit JWT rotation later")

    if reindex:
        from engine import vertex_reindex

        vertex_reindex(vpath)

    return vpath


def test_search_coverage_signal_lists_unindexed_kinds():
    # Pure (vertex_path=None) → every present kind is treated as un-indexed and
    # surfaced in the coverage signal; the substring path still runs.
    state = _byfold_state(_decision("design/auth"))
    surface = project(state)
    found = search(surface, "auth", vertex_path=None)
    assert found.window.query == "auth"
    assert found.window.unindexed == ("decision",)
    assert all(r.axis == "event" for r in found.rows)


def test_search_fts_finds_bodies_in_indexed_kind(tmp_path):
    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path)
    state = fetch_fold(vpath)
    found = search(project(state), "JWT", vertex_path=vpath)
    # FTS finds the decision body (indexed). thread is un-indexed → flagged.
    kinds = {r.kind for r in found.rows}
    assert "decision" in kinds
    assert "thread" in found.window.unindexed
    assert found.window.query == "JWT"
    # Proves this genuinely went through FTS, not a silent substring
    # degradation: search()'s substring branch is `kind not in fts_kinds`,
    # so a hit for a kind that's neither unindexed NOR stale can only have
    # come from the FTS branch — the fixture reindexed, so the index is
    # fresh for `decision`.
    assert found.window.stale == ()


def test_search_never_reindexed_falls_back_with_disclosure(tmp_path):
    """A search-declared kind whose index was NEVER built (no `sl store
    reindex` ever ran) still finds matches — via the substring fallback, not
    a crash and not a silently-empty result — with the gap named as
    ``stale`` (distinct from ``unindexed``, which is a declaration-time
    fact: this kind DOES declare search, the index just isn't there yet)."""
    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path, reindex=False)
    state = fetch_fold(vpath)
    found = search(project(state), "JWT", vertex_path=vpath)
    kinds = {r.kind for r in found.rows}
    assert "decision" in kinds
    assert "decision" in found.window.stale
    assert "decision" not in found.window.unindexed


def test_search_stale_after_edit_falls_back_with_disclosure(tmp_path):
    """S2 phantom-symmetry re-derivation (design:fts-confirm-symmetry-is-
    phantom): a fact emitted AFTER the last reindex is STILL found by the
    very next ``--match`` — that property survives read-purity — but now via
    the substring fallback rather than FTS auto-catch-up, with the gap named
    honestly in ``Window.stale`` instead of silently riding on a read that
    mutates the store."""
    import argparse

    from loops.commands.fetch import fetch_fold
    from loops.main import cmd_emit

    vpath = _search_vertex(tmp_path)  # reindexed once by the fixture

    # Emit a NEW decision fact with no reindex afterward — the index is now
    # behind head for `decision`.
    cmd_emit(
        argparse.Namespace(
            vertex=None, kind="decision",
            parts=["topic=design/late", "message=unreindexed uniquephrase"],
            observer="", dry_run=False,
        ),
        vertex_path=vpath,
    )

    state = fetch_fold(vpath)
    found = search(project(state), "uniquephrase", vertex_path=vpath)
    kinds = {r.kind for r in found.rows}
    assert "decision" in kinds  # found — not silently missing
    assert "decision" in found.window.stale  # and the gap is disclosed


def test_search_substring_fallback_for_undeclared_kind(tmp_path):
    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path)
    state = fetch_fold(vpath)
    # "rotation" lives only in the thread (un-indexed) — found via substring,
    # not FTS (vertex_search can't see un-indexed kinds).
    found = search(project(state), "rotation", vertex_path=vpath)
    assert any(r.kind == "thread" for r in found.rows)
    assert "thread" in found.window.unindexed


def test_search_fts_respects_kind_scoped_surface(tmp_path):
    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path)
    # Both decision (indexed) and thread mention "JWT". A surface already scoped
    # to decision (the --kind fetch narrowing) must NOT leak thread FTS hits.
    decision_only = fetch_fold(vpath, kind="decision")
    found = search(project(decision_only), "JWT", vertex_path=vpath)
    assert {r.kind for r in found.rows} == {"decision"}
    # thread was filtered out at fetch → not present → not in the coverage gap.
    assert "thread" not in found.window.unindexed


def test_search_fts_truncation_disclosed_in_window(tmp_path):
    """S2 arbitration F2 (friction:fts-match-limit-100-silent-cap): when the
    FTS query hits its result limit, ``Window.truncated`` names the gap
    instead of silently capping with no signal. The default limit itself is
    unchanged (still exactly 100 results surfaced) — disclosure only."""
    import json
    import sqlite3

    from engine import vertex_reindex
    from engine.builder import fold_by, vertex
    from loops.commands.fetch import fetch_fold

    v = (
        vertex("trunc")
        .store("./trunc.db")
        .loop("decision", fold_by("topic"), search=["topic", "message"])
    )
    vpath = tmp_path / "trunc.vertex"
    v.write(vpath)

    db_path = tmp_path / "trunc.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS facts ("
        "    id TEXT NOT NULL PRIMARY KEY,"
        "    kind TEXT NOT NULL,"
        "    ts REAL NOT NULL,"
        "    observer TEXT NOT NULL,"
        "    origin TEXT NOT NULL DEFAULT '',"
        "    payload TEXT NOT NULL"
        ");"
    )
    for i in range(101):  # one past the default limit
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"TRUNC{i:04d}", "decision", float(i), "test", "",
                json.dumps({"topic": f"topic-{i}", "message": "truncatetoken"}),
            ),
        )
    conn.commit()
    conn.close()

    vertex_reindex(vpath)
    state = fetch_fold(vpath)
    found = search(project(state), "truncatetoken", vertex_path=vpath)
    assert found.window.truncated is True
    assert len([r for r in found.rows if r.kind == "decision"]) == 100


def test_search_no_truncation_when_under_limit(tmp_path):
    # Sanity converse: a result set under the limit is never flagged truncated.
    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path)
    state = fetch_fold(vpath)
    found = search(project(state), "JWT", vertex_path=vpath)
    assert found.window.truncated is False


def test_search_stale_kind_crowd_does_not_bury_fresh_kind_match(tmp_path):
    """S2 sol P2 regression: a STALE indexed kind with more matching facts
    than the FTS limit must not silently push a FRESH kind's genuine match
    out of the result set. Before the fix, surface.search() queried
    vertex_search across every indexed kind (no SQL-level kind restriction)
    and filtered to fts_kinds AFTER the LIMIT already applied — so a stale
    kind's crowd of matches could consume the whole limit window before the
    caller ever got to discard them, silently dropping the fresh kind's
    result. Post-fix, kinds=fts_kinds restricts the SQL query BEFORE the
    limit, so the crowd kind (excluded from fts_kinds because it's stale)
    can never compete for the fresh kind's limit window at all."""
    import json
    import sqlite3

    from engine import vertex_reindex
    from engine.builder import fold_by, vertex
    from loops.commands.fetch import fetch_fold

    v = (
        vertex("crowd")
        .store("./crowd.db")
        .loop("crowd_kind", fold_by("topic"), search=["topic", "message"])
        .loop("target_kind", fold_by("topic"), search=["topic", "message"])
    )
    vpath = tmp_path / "crowd.vertex"
    v.write(vpath)

    db_path = tmp_path / "crowd.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS facts ("
        "    id TEXT NOT NULL PRIMARY KEY,"
        "    kind TEXT NOT NULL,"
        "    ts REAL NOT NULL,"
        "    observer TEXT NOT NULL,"
        "    origin TEXT NOT NULL DEFAULT '',"
        "    payload TEXT NOT NULL"
        ");"
    )
    # crowd_kind: 105 matching facts, all NEWER than target_kind's one match —
    # in an unrestricted newest-first query these would fill the whole
    # limit window before target_kind is ever reached.
    for i in range(105):
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"CROWD{i:04d}", "crowd_kind", 5000.0 + i, "test", "",
                json.dumps({"topic": f"crowd-{i}", "message": "needle"}),
            ),
        )
    # target_kind: one older matching fact.
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "TARGET0001", "target_kind", 1.0, "test", "",
            json.dumps({"topic": "target", "message": "needle"}),
        ),
    )
    conn.commit()
    conn.close()

    # Reindex once — both kinds are fresh.
    vertex_reindex(vpath)

    # Make crowd_kind STALE by writing one more fact under it, no reindex.
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "CROWDSTALE", "crowd_kind", 6000.0, "test", "",
            json.dumps({"topic": "crowd-stale", "message": "irrelevant"}),
        ),
    )
    conn.commit()
    conn.close()

    state = fetch_fold(vpath)
    found = search(project(state), "needle", vertex_path=vpath)

    kinds_found = {r.kind for r in found.rows}
    assert "target_kind" in kinds_found  # the fresh kind's match survives
    assert "crowd_kind" in kinds_found  # the stale kind still found via substring
    assert "crowd_kind" in found.window.stale
    assert "target_kind" not in found.window.stale
    # Only target_kind ever reaches the FTS branch (1 match, well under the
    # limit) — truncated must be False, not a false positive from the
    # crowd kind's now-excluded matches.
    assert found.window.truncated is False


def test_search_coverage_probe_failure_fails_closed(tmp_path, monkeypatch):
    """Capstone sol P2: if vertex_search_coverage RAISES (corrupt fts_state,
    unreadable db, ...), search() must fail CLOSED — treat every indexed
    kind as untrustworthy, not silently promote them all to trustworthy.

    A real root cause that breaks the coverage probe (corrupt db, I/O
    error) breaks ``vertex_search`` the SAME way — both are mocked to raise
    here, reproducing the exact silent-empty failure sol described: before
    the fix, a probe exception left `stale_kinds` empty (the `coverage is
    None` branch was a no-op), so EVERY indexed kind stayed "trustworthy";
    the FTS branch then swallowed the SAME underlying failure into
    `facts = []` via its own defensive except, and the substring fallback
    skipped these kinds too (wrongly counted as fts_kinds) — a silent,
    fully-empty result with NO disclosure at all.
    """
    import sqlite3

    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path)  # reindexed by the fixture

    def _boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated: disk I/O error")

    # search() does `from engine import vertex_search_coverage` / `vertex_search`
    # INSIDE the function body (a fresh lookup on every call) — patch the
    # attributes on the `engine` module itself so those lookups resolve to
    # the failing stand-ins.
    import engine

    monkeypatch.setattr(engine, "vertex_search_coverage", _boom)
    monkeypatch.setattr(engine, "vertex_search", _boom)

    state = fetch_fold(vpath)
    found = search(project(state), "JWT", vertex_path=vpath)

    # Not silently empty: the fact is still found, via the substring
    # fallback the fail-closed path routes it through — and vertex_search
    # (also mocked to raise) is never even reached, because fail-closed
    # means fts_kinds is empty and the FTS branch's guard short-circuits.
    kinds_found = {r.kind for r in found.rows}
    assert "decision" in kinds_found
    # And the gap is disclosed, not hidden — a probe failure is treated
    # exactly like "everything indexed is stale".
    assert "decision" in found.window.stale


def test_search_generation_skew_fails_closed(tmp_path, monkeypatch):
    """sol P2-a: the index is rebuilt under a NEW declaration between the
    coverage probe and the query. The certification no longer describes what
    would be read, so the FTS branch must drop out and the substring path must
    cover those kinds — with the gap DISCLOSED, not swallowed into an empty
    result (the certify-then-query race, same fail-closed posture as a probe
    failure above).
    """
    import engine
    from engine import FtsGenerationChanged
    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path)  # reindexed by the fixture

    def _skewed(*_args, **_kwargs):
        raise FtsGenerationChanged("simulated: reindexed under a new declaration")

    monkeypatch.setattr(engine, "vertex_search", _skewed)

    state = fetch_fold(vpath)
    found = search(project(state), "JWT", vertex_path=vpath)

    # Still found — via the substring fallback the skew reroutes it through.
    assert "decision" in {r.kind for r in found.rows}
    # And named as untrustworthy rather than silently reported as fresh.
    assert "decision" in found.window.stale


def test_search_passes_the_certified_generation(tmp_path, monkeypatch):
    """The query is issued UNDER the generation coverage certified — the
    binding is a real argument, not a comment."""
    import engine
    from loops.commands.fetch import fetch_fold

    vpath = _search_vertex(tmp_path)
    certified = engine.vertex_search_coverage(vpath).generation
    assert certified is not None

    seen = {}
    real = engine.vertex_search

    def _spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "vertex_search", _spy)

    state = fetch_fold(vpath)
    search(project(state), "JWT", vertex_path=vpath)
    assert seen.get("require_generation") == certified


# ---------------------------------------------------------------------------
# Encoders + source_facts carry
# ---------------------------------------------------------------------------


def test_to_dict_is_json_safe():
    state = _byfold_state(
        _decision("design/a", n=2, refs=("decision/design/b",)),
        _decision("design/b"),
    )
    surface = project(state)
    d = to_dict(surface)
    # round-trips through json with no custom encoder
    encoded = json.dumps(d)
    again = json.loads(encoded)
    assert again["vertex"] == "t"
    assert {r["key"] for r in again["rows"]} == {"design/a", "design/b"}
    row_a = next(r for r in again["rows"] if r["key"] == "design/a")
    assert row_a["salience"] == 2  # n=2, no inbound
    assert row_a["refs"] == ["decision/design/b"]
    assert "window" in again and "schema" in again
    # level discriminator (§7A) — folded entity rows are level "key".
    assert {r["level"] for r in again["rows"]} == {"key"}


def test_source_facts_carried_onto_surface():
    state = FoldState(
        sections=(
            FoldSection(kind="decision", items=(_decision("design/a", n=2),),
                        fold_type="by", key_field="topic"),
        ),
        vertex="t",
        source_facts={"decision/design/a": [{"topic": "design/a", "message": "v1"}]},
    )
    surface = project(state)
    assert surface.source_facts == {
        "decision/design/a": [{"topic": "design/a", "message": "v1"}]
    }


def test_to_dict_includes_source_facts():
    """to_dict carries source_facts so --facts --json honors the SAME content
    the text encoder renders (the S2 invariant; the old raw dump included it)."""
    state = FoldState(
        sections=(
            FoldSection(kind="decision", items=(_decision("design/a", n=2),),
                        fold_type="by", key_field="topic"),
        ),
        vertex="t",
        source_facts={"decision/design/a": [
            {"topic": "design/a", "message": "v1", "_ts": 1.0},
            {"topic": "design/a", "message": "v2", "_ts": 2.0},
        ]},
    )
    d = to_dict(project(state))
    encoded = json.loads(json.dumps(d))  # round-trips
    assert encoded["source_facts"]["decision/design/a"][0]["message"] == "v1"
    assert len(encoded["source_facts"]["decision/design/a"]) == 2


def test_schema_carries_render_hints():
    state = _byfold_state(_decision("design/a"))
    surface = project(state)
    kv = surface.schema["decision"]
    assert kv.key_field == "topic"
    assert kv.fold_type == "by"
    assert kv.preview_fields == ("message",)


def test_row_carries_key_field_primary_and_walked():
    """Row.key_field carries the fold-key FIELD name — needed by _render_walked
    and as a label hint when a walked row's kind has no schema entry under a
    --kind filter."""
    walked = WalkedItem(
        item=FoldItem(payload={"name": "t1", "status": "open"}, ts=2.0, id="w1"),
        section_kind="thread", key_field="name",
        via_anchor="decision/design/a", depth=1,
    )
    state = FoldState(
        sections=(
            FoldSection(kind="decision",
                        items=(_decision("design/a", refs=("thread:t1",)),),
                        fold_type="by", key_field="topic"),
        ),
        vertex="t",
        walked=(walked,),
    )
    surface = project(state)
    by_kind = {r.kind: r for r in surface.rows}
    assert by_kind["decision"].key_field == "topic"
    # the walked thread row carries its OWN key_field even though no thread
    # section (hence no schema['thread']) exists in this --kind-style state
    assert "thread" not in surface.schema
    assert by_kind["thread"].key_field == "name"
    assert by_kind["thread"].depth == 1
    assert by_kind["thread"].via_anchor == "decision/design/a"


def test_inbound_edges_materialized_in_fold_order():
    """inbound_edges is materialized on the Surface (target -> [source...]) so
    --refs reads it rather than rebuilding from reordered rows. The source list
    follows fold order — and only primaries (not walked) contribute."""
    state = _byfold_state(
        _decision("design/a", refs=("decision/design/c",)),
        _decision("design/b", refs=("decision/design/c",)),
        _decision("design/c"),
    )
    surface = project(state)
    # design/c is referenced by a then b — sources in FOLD order, each tagged
    # with its edge predicate ("ref" for the grandfathered union edge).
    assert surface.inbound_edges["decision/design/c"] == [
        ("decision/design/a", "ref"), ("decision/design/b", "ref"),
    ]


def test_dataclasses_are_frozen():
    surface = project(_byfold_state(_decision("design/a")))
    row = surface.rows[0]
    for obj in (row, surface, surface.window, surface.schema["decision"]):
        import dataclasses
        assert dataclasses.is_dataclass(obj)
    # frozen → mutation raises
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.salience = 99  # type: ignore


class TestTierAssignment:
    """Rail tiers — quantile buckets over the projected population
    (decision:design/salience-tier-scope-vertex, default dial 5a=A)."""

    def test_flat_population_is_all_mid(self):
        from loops.surface import _tier_thresholds

        assert _tier_thresholds([3, 3, 3]) is None
        assert _tier_thresholds([]) is None
        assert _tier_thresholds([7]) is None

    def test_quantile_buckets(self):
        from loops.surface import _tier_for, _tier_thresholds

        # 10 keys, salience 1..10: q90=9, q50=6 (nearest-rank on 0..9)
        th = _tier_thresholds(list(range(1, 11)))
        tiers = [_tier_for(s, th) for s in range(1, 11)]
        assert tiers.count("high") == 2  # 9, 10
        assert "mid" in tiers and "tail" in tiers
        assert tiers[0] == "tail"
        assert tiers[-1] == "high"

    def test_two_value_split(self):
        from loops.surface import _tier_for, _tier_thresholds

        th = _tier_thresholds([5, 1])
        assert _tier_for(5, th) == "high"
        assert _tier_for(1, th) != "high"

    def test_project_materializes_tiers(self, monkeypatch=None):
        # Reuse whatever fixture style the module uses lightly: build via
        # project() on a minimal FoldState through the public path.
        from atoms import FoldItem, FoldSection, FoldState

        from loops.surface import project

        items = tuple(
            FoldItem(payload={"topic": f"t{i}", "message": "m"}, ts=None,
                     observer="o", id=None, n=i)
            for i in (1, 1, 1, 1, 1, 1, 1, 1, 2, 9)
        )
        state = FoldState(
            vertex="v",
            sections=(FoldSection(kind="decision", items=items,
                                  fold_type="by", key_field="topic"),),
        )
        surface = project(state)
        tiers = {r.key: r.tier for r in surface.rows}
        assert tiers["t9"] == "high"
        assert set(tiers.values()) <= {"high", "mid", "tail"}

    def test_tier_map_and_max(self):
        """tier_map projects (kind,key)→tier from entity rows; tier_max is the
        container propagation (high > mid > tail > untiered)."""
        from atoms import FoldItem, FoldSection, FoldState

        from loops.surface import project, tier_map, tier_max

        items = tuple(
            FoldItem(payload={"topic": f"t{i}", "message": "m"}, ts=None,
                     observer="o", id=None, n=n)
            for i, n in enumerate([1, 1, 1, 2, 9])
        )
        state = FoldState(
            vertex="v",
            sections=(FoldSection(kind="decision", items=items,
                                  fold_type="by", key_field="topic"),),
        )
        tmap = tier_map(project(state))
        assert tmap[("decision", "t4")] == "high"  # n=9
        # MAX propagation + untiered handling
        assert tier_max(["tail", "high", "mid"]) == "high"
        assert tier_max(["tail", "mid"]) == "mid"
        assert tier_max(["", ""]) == ""
        assert tier_max([]) == ""

    def test_transforms_preserve_tier(self):
        from atoms import FoldItem, FoldSection, FoldState

        from loops.surface import filter as sfilter
        from loops.surface import project

        items = tuple(
            FoldItem(payload={"topic": f"t{i}", "message": "m"}, ts=None,
                     observer="o", id=None, n=n)
            for i, n in enumerate([1, 1, 1, 2, 9])
        )
        state = FoldState(
            vertex="v",
            sections=(FoldSection(kind="decision", items=items,
                                  fold_type="by", key_field="topic"),),
        )
        surface = project(state)
        before = {r.key: r.tier for r in surface.rows}
        narrowed = sfilter(surface, key="t")
        after = {r.key: r.tier for r in narrowed.rows}
        for k, t in after.items():
            assert t == before[k]
