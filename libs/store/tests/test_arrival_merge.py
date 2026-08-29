"""Merging into an arrival-canonical store — cut B §Q4.

The arrival log is the store, so a merge APPENDS INTO IT and then re-derives
the projections. Nothing in this path ever INSERTs into the index — which is
the premise gate item 1 rests on, and the reason
``test_rederivation_reproduces_every_rowid`` gains its merged-store case
here rather than at B3.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from engine.arrival import ArrivalLog
from engine.arrival_projection import (
    audit_derived_log,
    derived_log_path_for,
    rederive_projections,
)
from engine.arrival_store import ARRIVAL_ORDINAL_KEY, ArrivalCanonicalUnsupported
from store.merge import merge_store
from store.receive import receive_store
from tests.conftest import STUB_KEY, stub_sign

_TS = 1700000000.0


def _fact_body(ident, message, *, ts=_TS, observer="kyle", signature=None):
    body = {
        "id": ident,
        "kind": "note",
        "ts": ts,
        "observer": observer,
        "origin": "",
        "payload": json.dumps({"message": message}),
    }
    if signature is not None:
        body["signature"] = signature
    return body


def _tick_body(ident, name="check", *, ts=_TS, chained=False):
    body = {
        "id": ident,
        "name": name,
        "ts": ts,
        "since": None,
        "origin": "v",
        "payload": json.dumps({"n": 1}),
        "prev_hash": None,
        "window_start": None,
        "fact_cursor": None,
        "window_hash": None,
    }
    if chained:
        body.update(
            prev_hash="a" * 64,
            window_start="01WINDOWSTART00000000000000",
            fact_cursor="01FACTCURSOR000000000000000",
            window_hash="b" * 64,
            signature="sig:tick",
        )
    return body


def arrival_store(tmp_path, name, facts=(), ticks=(), observer="kyle"):
    """An arrival-canonical store: a minted log plus its built index.

    ``observer`` is the log's GENESIS observer — its custodian — which is
    what every tick record it mints names. Parameterized so a test can give
    two logs different custodians and tell whose label a merged record
    carries.
    """
    log = ArrivalLog.mint(
        tmp_path / f"{name}.arrival", observer=observer, signer=stub_sign, key=STUB_KEY
    )
    for body in facts:
        log.append("fact", body, observer=body["observer"], at=body["ts"])
    for body in ticks:
        # A tick's envelope names this log's CUSTODIAN (its genesis
        # observer), never the tick's name — ruling 2 of
        # decision:design/arrival-wire-v1-seam-triage. The fixture mints
        # what the live write path would mint, so a merge reading it back
        # is reading real records.
        log.append("tick", body, observer=log.genesis()["observer"], at=body["ts"])
    from engine.arrival_store import ensure_arrival_index

    ensure_arrival_index(log.path)
    return log, tmp_path / f"{name}.db"


def sqlite_source(tmp_path, name, facts=()):
    """A plain sqlite store — the transport shape ``slice_store`` emits."""
    from engine.sqlite_store import SqliteStore

    path = tmp_path / f"{name}.db"
    store: SqliteStore = SqliteStore(
        path=path, serialize=lambda d: d, deserialize=lambda d: d
    )
    conn = store._conn
    for idx, body in enumerate(facts):
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                body["id"], body["kind"], body["ts"], body["observer"],
                body["origin"], body["payload"], body.get("signature"),
                idx + 1, 0,
            ),
        )
    conn.commit()
    store.close()
    return path


def ids(db, table="facts"):
    conn = sqlite3.connect(str(db))
    try:
        return [r[0] for r in conn.execute(f"SELECT id FROM {table} ORDER BY rowid")]
    finally:
        conn.close()


def records(log_path):
    return list(ArrivalLog(log_path).walk())


def meta(db, key):
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


# --- the arrival arm ---------------------------------------------------------


def test_merge_appends_into_arrival_in_source_ordinal_order(tmp_path):
    """NON-NEGOTIABLE: an arrival source replays in ORDINAL order. Merging
    is replaying the source's arrival into the target's; no event-time field
    is an ordering input anywhere in this path."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    source_log, source_db = arrival_store(
        tmp_path,
        "s",
        facts=[
            # Deliberately DESCENDING event time: if any (ts, id) sort were
            # in this path, the replay order would come out reversed.
            _fact_body("01S0", "s0", ts=_TS + 30),
            _fact_body("01S1", "s1", ts=_TS + 20),
            _fact_body("01S2", "s2", ts=_TS + 10),
        ],
    )

    result = merge_store(target_db, source_db)

    assert result.facts_added == 3 and result.facts_skipped == 0
    appended = [r for r in records(tmp_path / "t.arrival") if r["k"] == "fact"]
    assert [r["body"]["id"] for r in appended] == ["01T0", "01S0", "01S1", "01S2"]
    assert ids(target_db) == ["01T0", "01S0", "01S1", "01S2"]
    assert source_log.size() == (tmp_path / "s.arrival").stat().st_size


def test_merge_never_writes_the_index_directly(tmp_path):
    """The premise gate item 1 rests on: the index carries rows from no
    source but the log. After a merge, every index row is accounted for by
    a log record."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(
        tmp_path, "s", facts=[_fact_body("01S0", "s0")], ticks=[_tick_body("01K0")]
    )

    merge_store(target_db, source_db)

    from engine.arrival_projection import rows_of_record

    accounted = [
        row[0]
        for record in records(tmp_path / "t.arrival")
        for _t, row in rows_of_record(record)
    ]
    assert sorted(ids(target_db) + ids(target_db, "ticks")) == sorted(accounted)
    # And the resume mark accounts for the whole log.
    assert int(meta(target_db, ARRIVAL_ORDINAL_KEY)) == records(
        tmp_path / "t.arrival"
    )[-1]["ord"]


def test_a_row_the_target_already_holds_appends_nothing(tmp_path):
    """NON-NEGOTIABLE: the arrival log must never carry one row id twice."""
    shared = _fact_body("01SHARED", "shared")
    _, target_db = arrival_store(tmp_path, "t", facts=[shared])
    _, source_db = arrival_store(
        tmp_path, "s", facts=[shared, _fact_body("01NEW", "new")]
    )

    result = merge_store(target_db, source_db)

    assert result.facts_added == 1 and result.facts_skipped == 1
    assert ids(target_db) == ["01SHARED", "01NEW"]
    body_ids = [r["body"]["id"] for r in records(tmp_path / "t.arrival") if r["k"] == "fact"]
    assert body_ids == ["01SHARED", "01NEW"]
    assert len(body_ids) == len(set(body_ids))


def test_a_re_run_merge_is_a_no_op(tmp_path):
    """Recovery from an interrupted merge is "re-run it" — dedup is what
    makes that idempotent."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])

    first = merge_store(target_db, source_db)
    before = (tmp_path / "t.arrival").read_bytes()
    second = merge_store(target_db, source_db)

    assert first.facts_added == 1
    assert second.facts_added == 0 and second.facts_skipped == 1
    assert (tmp_path / "t.arrival").read_bytes() == before


def test_a_fact_body_rides_verbatim_with_its_own_signature(tmp_path):
    """NON-NEGOTIABLE: the fact signature is a per-observer authorship claim
    over content only. Carried verbatim, never re-signed."""
    authored = _fact_body("01AUTH", "authored", observer="alice", signature="sig:alice")
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(tmp_path, "s", facts=[authored])

    merge_store(target_db, source_db)

    record = next(
        r
        for r in records(tmp_path / "t.arrival")
        if r["k"] == "fact" and r["body"]["id"] == "01AUTH"
    )
    assert record["body"] == authored
    # The record describes the AUTHORED row, not the operator who admitted it.
    assert record["observer"] == "alice"
    conn = sqlite3.connect(str(target_db))
    try:
        assert conn.execute(
            "SELECT observer, signature FROM facts WHERE id = '01AUTH'"
        ).fetchone() == ("alice", "sig:alice")
    finally:
        conn.close()


def test_merged_tick_carries_no_foreign_chain(tmp_path):
    """NON-NEGOTIABLE: chain columns and the tick signature are store-local
    receipt custody. Carrying them verbatim would put ticks in the target
    whose links reference the SOURCE's chain, and keeping the signature while
    nulling the chain would be a verification lie — the signature covers the
    chain fields."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(
        tmp_path, "s", ticks=[_tick_body("01CHAINED", chained=True)]
    )

    merge_store(target_db, source_db)

    record = next(r for r in records(tmp_path / "t.arrival") if r["k"] == "tick")
    body = record["body"]
    for field in ("prev_hash", "window_start", "fact_cursor", "window_hash"):
        assert body[field] is None, field
    assert "signature" not in body  # absent, not null — the codec's rule

    conn = sqlite3.connect(str(target_db))
    try:
        assert conn.execute(
            "SELECT prev_hash, window_start, fact_cursor, window_hash, signature "
            "FROM ticks WHERE id = '01CHAINED'"
        ).fetchone() == (None, None, None, None, None)
    finally:
        conn.close()

    # And the target's own chain verification passes over the merged store.
    from engine.jsonl_store import open_canonical_store

    store = open_canonical_store(
        tmp_path / "t.arrival", serialize=lambda d: d, deserialize=lambda d: d
    )
    try:
        assert store.verify_chain()["ok"]
    finally:
        store.close()


def test_a_merged_tick_names_the_TARGETS_custodian(tmp_path):
    """Ruling 2 of decision:design/arrival-wire-v1-seam-triage, at the
    SECOND mint site.

    ``engine.admission._draft_for`` encodes tick records independently of the
    live write path, so the respell has to land in both places or merge
    keeps committing the retired convention. Nothing pinned this before —
    which is precisely how a one-site fix would have gone green and wrong.

    The label names the log the record is being MINTED INTO, so a merged
    tick carries the TARGET's custodian, not the source's: the target's
    fold engine is not what produced the source's tick, but the target's
    log is where this record is arriving, and the envelope describes the
    record. Three-way distinct fixture (target custodian, source custodian,
    tick name) so the assertion cannot pass by coincidence.
    """
    _, target_db = arrival_store(tmp_path, "t", observer="target-custodian")
    _, source_db = arrival_store(
        tmp_path,
        "s",
        observer="source-custodian",
        ticks=[_tick_body("01K0", name="pulse")],
    )

    merge_store(target_db, source_db)

    merged = [r for r in records(tmp_path / "t.arrival") if r["k"] == "tick"]
    assert len(merged) == 1
    assert merged[0]["observer"] == "target-custodian"
    assert merged[0]["observer"] != "source-custodian"
    assert merged[0]["observer"] != merged[0]["body"]["name"] == "pulse"
    # And the body no longer echoes the record class.
    assert "t" not in merged[0]["body"]


def test_a_merged_record_carries_no_record_level_signature(tmp_path):
    """NON-NEGOTIABLE: merge_store takes no signer and never will. No store
    signs for an observer whose key it does not hold, and the grammar makes
    record signatures optional above ordinal 0."""
    import inspect

    assert "signer" not in inspect.signature(merge_store).parameters

    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])

    merge_store(target_db, source_db)

    merged = records(tmp_path / "t.arrival")[-1]
    assert "sig" not in merged
    # The authorship claim that survives is the fact row's own, in the body.
    assert merged["body"]["id"] == "01S0"


def test_an_atomic_ceremony_stays_one_record_across_a_merge(tmp_path):
    from engine.arrival_body import body_of_batch

    rows = [
        ("01CER0", "_decl.defined", _TS, "kyle", "", json.dumps({"subject": "a"}), None),
        ("01CER1", "_decl.retired", _TS, "kyle", "", json.dumps({"subject": "b"}), None),
    ]
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    source_log, source_db = arrival_store(tmp_path, "s")
    source_log.append("batch", body_of_batch(rows), observer="kyle")
    from engine.arrival_store import ensure_arrival_index

    ensure_arrival_index(source_log.path)

    result = merge_store(target_db, source_db)

    assert result.facts_added == 2
    batches = [r for r in records(tmp_path / "t.arrival") if r["k"] == "batch"]
    assert len(batches) == 1
    assert [row["id"] for row in batches[0]["body"]["rows"]] == ["01CER0", "01CER1"]


def test_a_partly_deduped_ceremony_appends_its_remainder(tmp_path):
    """Design-silent case, decided here: when some of a ceremony's rows are
    already in the target, the remainder is appended — as a batch when two
    or more survive, as a plain fact when one does (a one-row batch is a
    second spelling the codec refuses), and not at all when none do."""
    from engine.arrival_body import body_of_batch

    rows = [
        ("01CER0", "note", _TS, "kyle", "", json.dumps({"n": 0}), None),
        ("01CER1", "note", _TS, "kyle", "", json.dumps({"n": 1}), None),
    ]
    already = dict(_fact_body("01CER0", "x", ts=_TS))
    already["payload"] = json.dumps({"n": 0})  # the SAME body the source carries
    _, target_db = arrival_store(tmp_path, "t", facts=[already])
    # The target already holds 01CER0 with an IDENTICAL body, so it dedups;
    # a divergent body would refuse instead (TestDivergenceRefusal).
    source_log, source_db = arrival_store(tmp_path, "s")
    source_log.append("batch", body_of_batch(rows), observer="kyle")
    from engine.arrival_store import ensure_arrival_index

    ensure_arrival_index(source_log.path)

    result = merge_store(target_db, source_db)

    assert result.facts_added == 1 and result.facts_skipped == 1
    tail = records(tmp_path / "t.arrival")[-1]
    assert tail["k"] == "fact"  # one survivor: a plain fact line, not a batch
    assert tail["body"]["id"] == "01CER1"


def test_dry_run_appends_nothing_and_reports_the_counts(tmp_path):
    """The log never rewrites, so a rollback is neither available nor needed
    — cleaner than the savepoint the sqlite arm needs."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(
        tmp_path, "s", facts=[_fact_body("01T0", "t0"), _fact_body("01S0", "s0")]
    )
    before = (tmp_path / "t.arrival").read_bytes()

    result = merge_store(target_db, source_db, dry_run=True)

    assert result.facts_added == 1 and result.facts_skipped == 1
    assert (tmp_path / "t.arrival").read_bytes() == before
    assert ids(target_db) == ["01T0"]


def test_the_derived_log_is_regenerated_after_a_merge(tmp_path):
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])

    merge_store(target_db, source_db)

    assert derived_log_path_for(tmp_path / "t.arrival").exists()
    assert audit_derived_log(tmp_path / "t.arrival").ok


def test_a_sqlite_source_replays_facts_then_ticks_in_rowid_order(tmp_path):
    """The transport case. Deterministic, and deliberately not routed
    through any event-time sort."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    source = sqlite_source(
        tmp_path,
        "slice",
        facts=[
            _fact_body("01B", "b", ts=_TS + 30),
            _fact_body("01A", "a", ts=_TS + 10),
            _fact_body("01C", "c", ts=_TS + 20),
        ],
    )

    merge_store(target_db, source)

    # rowid order, which is insertion order — NOT (ts, id), which would give
    # 01A, 01C, 01B.
    assert ids(target_db) == ["01T0", "01B", "01A", "01C"]


def test_a_fresh_clone_with_no_index_yet_is_a_merge_target(tmp_path):
    """Design-silent case, decided here: the target ``.db`` is absent but
    the ``.arrival`` beside it is not. The STORE exists — only its
    projection is missing, and an open builds an absent projection."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])
    target_db.unlink()
    for sidecar in ("t.db-wal", "t.db-shm"):
        (tmp_path / sidecar).unlink(missing_ok=True)

    result = merge_store(target_db, source_db)

    assert result.facts_added == 1
    assert ids(target_db) == ["01T0", "01S0"]


def test_a_genuinely_missing_target_still_raises(tmp_path):
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])
    with pytest.raises(FileNotFoundError, match="Target store not found"):
        merge_store(tmp_path / "nowhere.db", source_db)


def test_an_unminted_arrival_log_is_not_a_merge_target(tmp_path):
    (tmp_path / "t.arrival").write_bytes(b"")
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])
    with pytest.raises(FileNotFoundError, match="no arrival genesis"):
        merge_store(tmp_path / "t.db", source_db)


def test_a_target_that_cannot_account_for_its_log_refuses(tmp_path):
    """Merging into an index that does not account for its log would dedup
    against a lie, so catch-up's refusal is the merge's refusal."""
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    conn = sqlite3.connect(str(target_db))
    try:
        conn.execute("DELETE FROM store_meta WHERE key = ?", (ARRIVAL_ORDINAL_KEY,))
        conn.commit()
    finally:
        conn.close()
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])

    with pytest.raises(ArrivalCanonicalUnsupported):
        merge_store(target_db, source_db)


# --- the ordering claim ------------------------------------------------------


def test_merge_ordering_claim_is_the_target_ordinal(tmp_path):
    """Replaces the discarded direction test. ``merge(A,B)`` and
    ``merge(B,A)`` each replay in THEIR OWN arrival-ordinal order; content
    is equal, sequences are not, and the assertion is against the ordinal —
    never against rowids as a doctrine."""
    a_facts = [_fact_body("01A0", "a0"), _fact_body("01A1", "a1")]
    b_facts = [_fact_body("01B0", "b0"), _fact_body("01B1", "b1")]

    _, a_db = arrival_store(tmp_path, "a", facts=a_facts)
    _, b_db = arrival_store(tmp_path, "b", facts=b_facts)
    _, a2_db = arrival_store(tmp_path, "a2", facts=a_facts)
    _, b2_db = arrival_store(tmp_path, "b2", facts=b_facts)

    merge_store(a_db, b_db)    # A <- B
    merge_store(b2_db, a2_db)  # B <- A

    def by_ordinal(log_name):
        return [
            r["body"]["id"]
            for r in sorted(records(tmp_path / log_name), key=lambda r: r["ord"])
            if r["k"] == "fact"
        ]

    ab, ba = by_ordinal("a.arrival"), by_ordinal("b2.arrival")
    assert ab == ["01A0", "01A1", "01B0", "01B1"]
    assert ba == ["01B0", "01B1", "01A0", "01A1"]
    # Different custody events, and the ordinal says so. Content is equal.
    assert ab != ba and sorted(ab) == sorted(ba)


def test_merge_direction_is_deterministic_for_an_arrival_target(tmp_path):
    """The arrival twin of the sqlite test that survives cut B."""
    orders = []
    for trial in range(3):
        _, a_db = arrival_store(
            tmp_path, f"a{trial}", facts=[_fact_body("01A0", "a0")]
        )
        _, b_db = arrival_store(
            tmp_path,
            f"b{trial}",
            facts=[_fact_body("01B0", "b0"), _fact_body("01B1", "b1")],
        )
        merge_store(a_db, b_db)
        orders.append(
            [r["body"]["id"] for r in records(tmp_path / f"a{trial}.arrival")
             if r["k"] == "fact"]
        )
    assert orders[0] == orders[1] == orders[2]


# --- the jsonl refusal -------------------------------------------------------


def test_merge_into_jsonl_canonical_refuses(tmp_path):
    """The one behaviour change to a legacy mode, and it is the same verdict
    delivered earlier: today a merge here succeeds and then bricks the store
    at its NEXT open."""
    from engine.jsonl_store import JsonlCanonicalUnsupported, JsonlStore

    legacy = tmp_path / "legacy.jsonl"
    store: JsonlStore = JsonlStore(
        path=tmp_path / "legacy.db",
        log_path=legacy,
        serialize=lambda d: d,
        deserialize=lambda d: d,
    )
    store.close()
    legacy.touch()
    _, source_db = arrival_store(tmp_path, "s", facts=[_fact_body("01S0", "s0")])

    with pytest.raises(JsonlCanonicalUnsupported, match="migrate it to an arrival log"):
        merge_store(tmp_path / "legacy.db", source_db)


# --- receive -----------------------------------------------------------------


def test_receive_refuses_to_copy_over_a_live_arrival_logs_index(tmp_path):
    """NON-NEGOTIABLE. The index is absent, not the store — and a projection
    is built from its log, never copied from a stranger."""
    ArrivalLog.mint(
        tmp_path / "t.arrival", observer="kyle", signer=stub_sign, key=STUB_KEY
    )
    source = sqlite_source(tmp_path, "incoming", facts=[_fact_body("01S0", "s0")])

    with pytest.raises(ArrivalCanonicalUnsupported, match="second custody holder"):
        receive_store(tmp_path / "t.db", source)

    assert not (tmp_path / "t.db").exists()


def test_receive_into_a_plain_location_still_creates_a_sqlite_store(tmp_path):
    source = sqlite_source(tmp_path, "incoming", facts=[_fact_body("01S0", "s0")])
    result = receive_store(tmp_path / "fresh.db", source)
    assert result.status == "created" and result.facts == 1


def test_receive_into_an_arrival_target_inherits_the_merge_dispatch(tmp_path):
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    source = sqlite_source(tmp_path, "incoming", facts=[_fact_body("01S0", "s0")])

    result = receive_store(target_db, source)

    assert result.status == "merged" and result.facts == 1
    assert [r["body"]["id"] for r in records(tmp_path / "t.arrival") if r["k"] == "fact"] == [
        "01T0",
        "01S0",
    ]


# --- gate item 1, extended over a merged store -------------------------------


def test_rederivation_reproduces_every_rowid_over_a_merged_store(tmp_path):
    """The B3 ratchet, extended to the case its premise 3 forbade until now.

    Before this seam the index carried rows that never came through the log,
    so a re-derivation would have renumbered every row after the first
    merged one. THIS SEAM is what establishes the premise, and this is the
    assertion that says so."""
    _, target_db = arrival_store(
        tmp_path, "t", facts=[_fact_body("01T0", "t0"), _fact_body("01T1", "t1")]
    )
    _, source_db = arrival_store(
        tmp_path,
        "s",
        facts=[_fact_body("01S0", "s0"), _fact_body("01S1", "s1")],
        ticks=[_tick_body("01K0", chained=True)],
    )

    merge_store(target_db, source_db)

    def snapshot():
        conn = sqlite3.connect(str(target_db))
        try:
            return (
                conn.execute(
                    "SELECT rowid, id, kind, ts, observer, origin, payload, "
                    "signature FROM facts ORDER BY rowid"
                ).fetchall(),
                conn.execute(
                    "SELECT rowid, id, name, ts, since, origin, payload, "
                    "prev_hash, window_start, fact_cursor, window_hash, "
                    "signature FROM ticks ORDER BY rowid"
                ).fetchall(),
            )
        finally:
            conn.close()

    before = snapshot()
    assert len(before[0]) == 4 and len(before[1]) == 1

    rederive_projections(tmp_path / "t.arrival")

    assert snapshot() == before
    assert [r[0] for r in snapshot()[0]] == [1, 2, 3, 4]


# --- concurrent merges -------------------------------------------------------


# Three mergers over a 60-record source: enough of an append phase that the
# compare-and-swap window is genuinely contended rather than theoretical.
_MERGERS = 3

_MERGE_WORKER = """
    import sys
    import time
    from pathlib import Path
    from store.merge import merge_store

    target, source, gate = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    print("ready", flush=True)
    # Both processes spin on the same gate file so the race is real rather
    # than serialized by process start-up cost.
    while not gate.exists():
        time.sleep(0.005)
    merge_store(target, source)
    """


def test_concurrent_merges_never_double_append(tmp_path):
    """Two REAL processes, the same source, one target: the log carries each
    id exactly once.

    One lock acquisition alone does not buy this — a second process that
    deduped against the pre-merge snapshot appends the moment the lock is
    released. The compare-and-swap pin is what refuses that append, and the
    retry loop is what makes the loser converge instead of failing.
    """
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(
        tmp_path,
        "s",
        facts=[_fact_body(f"01S{n:03d}", f"s{n}") for n in range(60)],
    )

    script = tmp_path / "merge_worker.py"
    script.write_text(textwrap.dedent(_MERGE_WORKER))
    gate = tmp_path / "go"

    workers = [
        subprocess.Popen(
            [sys.executable, str(script), str(target_db), str(source_db), str(gate)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(_MERGERS)
    ]
    for worker in workers:
        assert worker.stdout is not None
        assert worker.stdout.readline().strip() == "ready"
    gate.touch()

    for n, worker in enumerate(workers):
        out, err = worker.communicate(timeout=300)
        assert worker.returncode == 0, f"merger {n} failed:\n{out}\n{err}"

    body_ids = [
        r["body"]["id"] for r in records(tmp_path / "t.arrival") if r["k"] == "fact"
    ]
    assert len(body_ids) == len(set(body_ids)), (
        f"the log carries a row id twice: {body_ids}"
    )
    assert sorted(body_ids) == sorted(["01T0", *(f"01S{n:03d}" for n in range(60))])

    # The index agrees, and the whole log is accounted for.
    from engine.jsonl_store import open_canonical_store

    open_canonical_store(
        tmp_path / "t.arrival", serialize=lambda d: d, deserialize=lambda d: d
    ).close()
    assert sorted(ids(target_db)) == sorted(body_ids)
    assert int(meta(target_db, ARRIVAL_ORDINAL_KEY)) == records(
        tmp_path / "t.arrival"
    )[-1]["ord"]


def test_an_interrupted_merge_leaves_a_re_runnable_store(tmp_path):
    """One trailing fsync means a crash loses an un-fsynced suffix or leaves
    one torn tail line. Truncation happens only under the append lock, so the
    re-run must have something to append — which is the realistic shape: the
    crash lost a suffix, and re-running is what lands it.
    """
    _, target_db = arrival_store(tmp_path, "t", facts=[_fact_body("01T0", "t0")])
    _, source_db = arrival_store(
        tmp_path,
        "s",
        facts=[
            _fact_body("01S0", "s0"),
            _fact_body("01S1", "s1"),
            _fact_body("01S2", "s2"),
        ],
    )
    # A merge that landed only part of the source, then crashed mid-record.
    partial_source = arrival_store(
        tmp_path, "part", facts=[_fact_body("01S0", "s0"), _fact_body("01S1", "s1")]
    )[1]
    merge_store(target_db, partial_source)
    log_path = tmp_path / "t.arrival"
    log_path.write_bytes(log_path.read_bytes() + b'{"partial":')

    result = merge_store(target_db, source_db)

    # Dedup made the re-run idempotent over what already landed.
    assert result.facts_added == 1 and result.facts_skipped == 2
    # The torn tail was removed under the append lock, not skipped.
    assert log_path.read_bytes().endswith(b"\n")
    assert b'{"partial":' not in log_path.read_bytes()
    assert sorted(ids(target_db)) == ["01S0", "01S1", "01S2", "01T0"]


class TestDivergenceRefusal:
    """Same id, different content REFUSES (CX-BR-01, whole-branch r1).

    The admission table (decision:design/arrival-substrate-laws) rejects an
    id collision over different bytes; Kyle's r1 ruling applies it to this
    merge arm, superseding the target-wins vector. Comparison is strict —
    signature included, so an era-mixed carry of the same fact (signed vs
    pre-signature-era NULL) also refuses; deliberate, because a merge cannot
    tell that apart from a stripped signature.
    """

    def test_divergent_payload_refuses_and_appends_nothing(self, tmp_path):
        from store.merge import MergeDivergence

        _, target_db = arrival_store(
            tmp_path, "t", facts=[_fact_body("01DIV", "target-body")]
        )
        _, source_db = arrival_store(
            tmp_path, "s",
            facts=[_fact_body("01FRESH", "fresh"), _fact_body("01DIV", "source-body")],
        )
        before = list(records(tmp_path / "t.arrival"))

        with pytest.raises(MergeDivergence, match="01DIV.*diverging: payload"):
            merge_store(target_db, source_db)

        # Nothing appended — the fresh row that preceded the divergence
        # included: refusal happens before any append.
        assert list(records(tmp_path / "t.arrival")) == before

    def test_divergent_signature_refuses_naming_the_field(self, tmp_path):
        from store.merge import MergeDivergence

        _, target_db = arrival_store(
            tmp_path, "t", facts=[_fact_body("01SIG", "same", signature="sig:a")]
        )
        _, source_db = arrival_store(
            tmp_path, "s", facts=[_fact_body("01SIG", "same")]  # era-mixed: NULL
        )
        with pytest.raises(MergeDivergence, match="diverging: signature"):
            merge_store(target_db, source_db)

    def test_identical_body_still_dedups(self, tmp_path):
        _, target_db = arrival_store(
            tmp_path, "t", facts=[_fact_body("01SAME", "same")]
        )
        _, source_db = arrival_store(
            tmp_path, "s", facts=[_fact_body("01SAME", "same")]
        )
        result = merge_store(target_db, source_db)
        assert result.facts_added == 0 and result.facts_skipped == 1

    def test_tick_chain_columns_never_ground_a_divergence(self, tmp_path):
        """A target-native chained tick vs the same tick carried chainless:
        chain columns (and the tick signature that covers them) are
        store-local custody the merge strips, so this is a dedup, not a
        divergence."""
        _, target_db = arrival_store(
            tmp_path, "t", ticks=[_tick_body("01TCK", chained=True)]
        )
        _, source_db = arrival_store(
            tmp_path, "s", ticks=[_tick_body("01TCK", chained=False)]
        )
        result = merge_store(target_db, source_db)
        assert result.ticks_added == 0 and result.ticks_skipped == 1

    def test_dry_run_also_refuses(self, tmp_path):
        from store.merge import MergeDivergence

        _, target_db = arrival_store(
            tmp_path, "t", facts=[_fact_body("01DIV", "target-body")]
        )
        _, source_db = arrival_store(
            tmp_path, "s", facts=[_fact_body("01DIV", "source-body")]
        )
        with pytest.raises(MergeDivergence):
            merge_store(target_db, source_db, dry_run=True)
