"""Re-derivation reproduces every rowid — gate item 1 of cut B.

decision:design/arrival-sliceB-projections §Q7. Outstanding witness positions
and seals survive a re-derivation, and this suite is why that is a property
rather than a hope. It is a CONSEQUENCE of four premises, so it is ratcheted,
not asserted:

1. Re-derivation always replays from ordinal 0 — never a partial rebuild.
2. The arrival ordinal is dense and gapless, verified at every walk.
3. **The index carries rows from no other source.** Before cut B this was
   FALSE: merge/receive INSERTed straight into ``facts``. The merge rewrite
   at seam B6 is what establishes it — which is why the merged-store case is
   added there and not here, and why this suite is deliberately
   merge-free.
4. Rows are never deleted and rowids are dense by construction.

``facts`` has no ``AUTOINCREMENT``, so ``DELETE FROM facts`` resets sqlite's
rowid counter and a replay from empty hands out ``1, 2, 3, …`` in insert
order — reproducing the original assignment exactly.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from atoms import Fact
from lang import parse_vertex
from lang.document import (
    DECL_KIND_DEFINED,
    DECL_KIND_RETIRED,
    Change,
    vertex_to_documents,
)

from engine.arrival import ArrivalLog
from engine.arrival_projection import rederive_projections
from engine.arrival_store import ArrivalStore
from engine.tick import Tick
from engine.witness import (
    durable_handle,
    receipt_group_span,
    resolve_witness_position,
)

# Two loops, so an edit ceremony can carry TWO change rows and land as one
# multi-row batch record — the receipt group whose contiguity must survive.
SRC = (
    'name "x"\nstore "./s.arrival"\nloops {\n'
    '  a { fold { n "inc" } }\n'
    '  b { fold { n "inc" } }\n}\n'
)


def _tick_signer(digest: str) -> str:
    return hashlib.sha256(digest.encode()).hexdigest()


def build_through_the_write_path(tmp_path, keys, signer):
    """A store with facts, chained ticks and a declaration ceremony — every
    row of it authored through the arrival write path, no merge involved."""
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=signer, key=keys.public
    )
    store: ArrivalStore = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
        tick_signer=_tick_signer,
    )
    try:
        store.append(Fact.of("note", "kyle", message="one"))
        store.append(Fact.of("note", "kyle", message="two"))
        ast = parse_vertex(SRC)
        store.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(ast)],
            observer="kyle",
            fact_signer=signer,
        )
        store.append_tick(
            Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1}, origin="t")
        )
        store.append(Fact.of("note", "kyle", message="three"))
        # A two-row edit ceremony: ONE batch record, one receipt group.
        store.absorb_edit(
            [
                Change(
                    kind=DECL_KIND_DEFINED,
                    subject="a",
                    payload={"order": 0},
                    annotation="modified",
                ),
                Change(
                    kind=DECL_KIND_RETIRED,
                    subject="b",
                    payload=None,
                    annotation="removed",
                ),
            ],
            observer="kyle",
            fact_signer=signer,
        )
        store.append(Fact.of("note", "kyle", message="four"))
        store.append_tick(
            Tick(name="seal", ts=datetime.now(UTC), payload={"n": 2}, origin="t")
        )
        store.append(Fact.of("note", "kyle", message="five"))
    finally:
        store.close()
    return log, tmp_path / "s.db"


def snapshot(db):
    conn = sqlite3.connect(str(db))
    try:
        return {
            "facts": conn.execute(
                "SELECT rowid, id, kind, ts, observer, origin, payload, signature "
                "FROM facts ORDER BY rowid"
            ).fetchall(),
            "ticks": conn.execute(
                "SELECT rowid, id, name, ts, since, origin, payload, prev_hash, "
                "window_start, fact_cursor, window_hash, signature "
                "FROM ticks ORDER BY rowid"
            ).fetchall(),
        }
    finally:
        conn.close()


def fact_ids(db):
    conn = sqlite3.connect(str(db))
    try:
        return [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY rowid")]
    finally:
        conn.close()


def positions(db):
    """Every resolvable witness position in the store, by fact id.

    ``group_boundary="allow"`` because this is a rowid-identity probe over
    every row, not a fold cut — the mid-ceremony rows are exactly the ones
    whose rowid identity matters most here.
    """
    out = {}
    for fid in fact_ids(db):
        pos = resolve_witness_position(db, fid, group_boundary="allow")
        out[fid] = (pos.ordinal, pos.seq, pos.lineage, pos.unadopted, durable_handle(pos))
    return out


def test_rederivation_reproduces_every_rowid(tmp_path, keys, signer):
    """The gate assertion: every ``(rowid, id)`` pair, in both tables, and
    every resolved witness position, is IDENTICAL across a re-derivation."""
    log, db = build_through_the_write_path(tmp_path, keys, signer)
    before = snapshot(db)
    before_positions = positions(db)
    assert len(before["facts"]) >= 8 and len(before["ticks"]) == 2

    result = rederive_projections(log.path)

    after = snapshot(db)
    assert after["facts"] == before["facts"]
    assert after["ticks"] == before["ticks"]
    assert positions(db) == before_positions
    assert result.facts == len(before["facts"])
    assert result.ticks == len(before["ticks"])
    # Not vacuous: rowids are dense from 1, so a renumbering would show.
    assert [r[0] for r in after["facts"]] == list(
        range(1, len(after["facts"]) + 1)
    )


def test_a_durable_handle_survives_because_it_never_named_a_rowid(
    tmp_path, keys, signer
):
    """The guarantee is doubled. ``durable_handle`` is
    ``fact:<lineage>/<id>`` and resolution is a primary-key lookup on
    ``facts.id``, so order preservation alone would suffice; identity of
    rowids is what we actually get."""
    log, db = build_through_the_write_path(tmp_path, keys, signer)
    handles = {h for h in (v[4] for v in positions(db).values()) if h}
    assert handles and all("/" in h for h in handles)

    rederive_projections(log.path)

    assert {h for h in (v[4] for v in positions(db).values()) if h} == handles


def test_rederivation_preserves_receipt_group_contiguity(tmp_path, keys, signer):
    """A ceremony's rows ride as ONE batch record and expand in array order,
    so the contiguity heuristic sees the same runs."""
    log, db = build_through_the_write_path(tmp_path, keys, signer)

    def spans():
        conn = sqlite3.connect(str(db))
        try:
            top = conn.execute("SELECT MAX(arrival_ordinal) FROM facts").fetchone()[0]
            return [receipt_group_span(conn, r) for r in range(1, top + 1)]
        finally:
            conn.close()

    before = spans()
    # Not vacuous: the two-row edit ceremony IS a group, so some probe lands
    # strictly inside it.
    assert any(s is not None for s in before)

    rederive_projections(log.path)

    assert spans() == before


def test_verify_chain_passes_after_rederivation(tmp_path, keys, signer):
    """Seals survive: window membership is a rowid range whose INPUTS are
    fact row hashes over content. Identical rowids means identical
    membership means identical window hash, and the chain columns ride
    verbatim in the record bodies."""
    log, db = build_through_the_write_path(tmp_path, keys, signer)

    def report():
        store: ArrivalStore = ArrivalStore(
            path=db,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        try:
            return store.verify_chain(include_ticks=True)
        finally:
            store.close()

    before = report()
    assert before["ok"] and before["chained"] == 2 and before["covered_facts"] > 0

    rederive_projections(log.path)

    after = report()
    assert after["ok"], after["breaks"]
    assert after["covered_facts"] == before["covered_facts"]
    assert after["tick_detail"] == before["tick_detail"]


def test_a_partial_rebuild_is_not_reachable_through_this_verb(
    tmp_path, keys, signer
):
    """NON-NEGOTIABLE premise 1: re-derivation always replays from ordinal
    0. There is no parameter that would start it anywhere else — a partial
    rebuild would renumber every row after the resume point, which is
    exactly what the rowid property cannot survive."""
    import inspect

    params = inspect.signature(rederive_projections).parameters
    assert set(params) == {"canonical", "derived_log"}

    log, db = build_through_the_write_path(tmp_path, keys, signer)
    result = rederive_projections(log.path)
    # Every record in the log was consumed, genesis included.
    assert result.records == len(list(ArrivalLog(log.path).walk()))
