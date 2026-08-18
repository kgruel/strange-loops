"""arrival_projection — re-derivation as an explicit verb.

Cut B (decision:design/arrival-sliceB-projections §Q1/§Q5): the sqlite index
is a projection of the arrival log, rebuildable at will, and rebuilding it is
an operator's verb rather than an open-time side effect. This suite covers
the index half — the states catch-up refuses and this verb resolves, the
``own_lineage`` restore that dissolves the restamp requirement, and the one
refusal re-derivation itself makes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from atoms import Fact
from lang import parse_vertex
from lang.document import DECL_GENESIS, vertex_to_documents

from engine.arrival import ArrivalLog, GenesisRefused
from engine.arrival_projection import Rederivation, rederive_projections
from engine.arrival_store import (
    ARRIVAL_LINEAGE_KEY,
    ARRIVAL_OFFSET_KEY,
    ARRIVAL_ORDINAL_KEY,
    ArrivalCanonicalUnsupported,
    ArrivalStore,
)
from engine.tick import Tick
from tests.conftest import ARRIVAL_VERTEX_SRC as BASE


def mint(tmp_path, keys, signer, name: str = "s") -> ArrivalLog:
    return ArrivalLog.mint(
        tmp_path / f"{name}.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
    )


def open_store(tmp_path, name: str = "s", **kw) -> ArrivalStore:
    return ArrivalStore(
        path=tmp_path / f"{name}.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        **kw,
    )


def fact(kind: str = "note", observer: str = "kyle", **payload) -> Fact:
    return Fact.of(kind, observer, **(payload or {"message": "hi"}))


def _docs():
    return [d.as_json() for d in vertex_to_documents(parse_vertex(BASE))]


def meta(db, key):
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT value FROM store_meta WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def rows(db, table="facts"):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(f"SELECT rowid, id FROM {table} ORDER BY rowid").fetchall()
    finally:
        conn.close()


def build(tmp_path, keys, signer, *, absorb=True, ticks=True):
    """A store built THROUGH the arrival write path — facts, a tick, and
    optionally the declaration ceremony. Returns (log, db)."""
    log = mint(tmp_path, keys, signer)
    store = open_store(tmp_path, fact_signer=signer)
    try:
        store.append(fact(message="one"))
        if absorb:
            store.absorb_genesis(_docs(), observer="kyle", fact_signer=signer)
        store.append(fact(message="two"))
        if ticks:
            store.append_tick(
                Tick(name="check", ts=datetime.now(UTC), payload={"n": 1}, origin="t")
            )
        store.append(fact(message="three"))
    finally:
        store.close()
    return log, tmp_path / "s.db"


# --- the verb itself ---------------------------------------------------------


def test_rederivation_reproduces_the_index_it_discarded(tmp_path, keys, signer):
    log, db = build(tmp_path, keys, signer)
    before_facts, before_ticks = rows(db), rows(db, "ticks")
    before_mark = tuple(
        meta(db, k) for k in (ARRIVAL_LINEAGE_KEY, ARRIVAL_OFFSET_KEY, ARRIVAL_ORDINAL_KEY)
    )

    result = rederive_projections(log.path)

    assert isinstance(result, Rederivation)
    assert result.lineage == log.lineage()
    assert result.projections == ("index",)
    assert result.facts == len(before_facts)
    assert result.ticks == len(before_ticks)
    assert rows(db) == before_facts
    assert rows(db, "ticks") == before_ticks
    assert (
        tuple(meta(db, k) for k in (ARRIVAL_LINEAGE_KEY, ARRIVAL_OFFSET_KEY, ARRIVAL_ORDINAL_KEY))
        == before_mark
    )


def test_rederivation_never_constructs_the_store_it_repairs(tmp_path, keys, signer):
    """NON-NEGOTIABLE: the module that repairs never constructs the store
    that refuses — a method would be unreachable on exactly these stores."""
    assert not hasattr(ArrivalStore, "rederive")
    assert not hasattr(ArrivalStore, "rederive_projections")

    log, db = build(tmp_path, keys, signer)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("DELETE FROM store_meta WHERE key = ?", (ARRIVAL_ORDINAL_KEY,))
        conn.commit()
    finally:
        conn.close()
    # The store cannot even be opened in this state...
    with pytest.raises(ArrivalCanonicalUnsupported):
        open_store(tmp_path)
    # ...and the verb resolves it anyway.
    rederive_projections(log.path)
    store = open_store(tmp_path)
    store.close()


def test_the_derived_log_is_not_materialized_unless_asked(tmp_path, keys, signer):
    log, _ = build(tmp_path, keys, signer)
    rederive_projections(log.path)
    assert not (tmp_path / "s.jsonl").exists()


def test_a_path_that_is_not_an_arrival_log_refuses(tmp_path):
    (tmp_path / "s.arrival").write_text("not a record\n")
    with pytest.raises(GenesisRefused):
        rederive_projections(tmp_path / "s.arrival")


def test_an_absent_index_is_built_rather_than_refused(tmp_path, keys, signer):
    """Building an ABSENT projection destroys nothing, so it is not gated."""
    log, db = build(tmp_path, keys, signer)
    before = rows(db)
    db.unlink()
    for sidecar in (tmp_path / "s.db-wal", tmp_path / "s.db-shm"):
        sidecar.unlink(missing_ok=True)

    result = rederive_projections(log.path)

    assert result.facts == len(before)
    assert rows(db) == before


# --- the three catch-up refusals --------------------------------------------


def test_rows_without_a_mark_are_resolved_by_the_verb(tmp_path, keys, signer):
    log, db = build(tmp_path, keys, signer)
    before = rows(db)
    conn = sqlite3.connect(str(db))
    try:
        for key in (ARRIVAL_LINEAGE_KEY, ARRIVAL_OFFSET_KEY, ARRIVAL_ORDINAL_KEY):
            conn.execute("DELETE FROM store_meta WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ArrivalCanonicalUnsupported, match="rederive_projections"):
        open_store(tmp_path)

    rederive_projections(log.path)
    assert rows(db) == before
    open_store(tmp_path).close()


def test_a_mark_the_log_rejects_is_resolved_by_the_verb(tmp_path, keys, signer):
    log, db = build(tmp_path, keys, signer)
    before = rows(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE store_meta SET value = '999999' WHERE key = ?",
            (ARRIVAL_OFFSET_KEY,),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ArrivalCanonicalUnsupported, match="rederive_projections"):
        open_store(tmp_path)

    rederive_projections(log.path)
    assert rows(db) == before
    open_store(tmp_path).close()


def test_an_index_without_its_log_stays_a_dead_end(tmp_path, keys, signer):
    """NON-NEGOTIABLE: no verb is offered here. Re-derivation cannot
    manufacture a log, and naming it would name an operation that destroys
    the only surviving artifact."""
    log, _ = build(tmp_path, keys, signer)
    log.path.unlink()

    with pytest.raises(ArrivalCanonicalUnsupported) as exc:
        open_store(tmp_path)
    assert "rederive_projections" not in str(exc.value)
    assert "cannot manufacture a log" in str(exc.value)


# --- what a re-derivation clears, and what it keeps --------------------------


def test_the_fts_projection_is_dropped_not_left_resolving_stale_text(tmp_path, keys, signer):
    """DELETE FROM facts resets sqlite's rowid counter, so a surviving FTS
    index would resolve stale text to new facts — the same reason the legacy
    rebuild drops it. Search reports `missing`, the honest state."""
    log, db = build(tmp_path, keys, signer)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE facts_fts (fact_rowid INTEGER, text TEXT)")
        conn.execute("CREATE TABLE fts_state (last_rowid INTEGER)")
        conn.execute("INSERT INTO fts_state VALUES (99)")
        conn.commit()
    finally:
        conn.close()

    rederive_projections(log.path)

    conn = sqlite3.connect(str(db))
    try:
        present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "facts_fts" not in present and "fts_state" not in present


def test_store_meta_rows_that_are_not_projections_survive(tmp_path, keys, signer):
    log, db = build(tmp_path, keys, signer)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("INSERT OR REPLACE INTO store_meta (key, value) VALUES ('keepme', 'yes')")
        conn.commit()
    finally:
        conn.close()

    rederive_projections(log.path)

    assert meta(db, "keepme") == "yes"


# --- own_lineage: the restamp verb that dissolved ----------------------------


def test_the_ceremony_crash_window_recovers_on_the_next_open(tmp_path, keys, signer):
    """The whole restamp requirement is ONE projection row. A crash between
    the log's fsync and the ceremony's COMMIT rolls back the _decl.genesis
    INSERT, the marker and the mark together; catch-up tails the record
    forward and the row recovers itself, so the marker is the only residue —
    and catch-up restores it because absent→present destroys nothing."""
    log, db = build(tmp_path, keys, signer)
    assert meta(db, "own_lineage") == log.lineage()

    # Reproduce the post-crash residue exactly: the row is present (it came
    # back through the log), the marker is not.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("DELETE FROM store_meta WHERE key = 'own_lineage'")
        conn.commit()
    finally:
        conn.close()
    assert meta(db, "own_lineage") is None

    open_store(tmp_path).close()

    assert meta(db, "own_lineage") == log.lineage()


def test_re_derivation_restores_the_marker_too(tmp_path, keys, signer):
    log, db = build(tmp_path, keys, signer)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("DELETE FROM store_meta WHERE key = 'own_lineage'")
        conn.commit()
    finally:
        conn.close()

    rederive_projections(log.path)

    assert meta(db, "own_lineage") == log.lineage()


def test_a_minted_but_unabsorbed_store_is_not_flipped_to_adopted(tmp_path, keys, signer):
    """NON-NEGOTIABLE: the stamp is licensed by a consumed _decl.genesis ROW
    (movement 2), never by the arrival genesis at ordinal 0 (movement 1).
    Stamping on movement 1 would start emitting portable witness handles for
    stores that never opened a declaration lineage."""
    log, db = build(tmp_path, keys, signer, absorb=False)
    assert meta(db, "own_lineage") is None

    rederive_projections(log.path)
    assert meta(db, "own_lineage") is None

    open_store(tmp_path).close()
    assert meta(db, "own_lineage") is None


def test_a_foreign_genesis_row_does_not_license_the_stamp(tmp_path, keys, signer):
    """A merged store's log can carry a FOREIGN _decl.genesis verbatim. Only
    the row whose id IS this log's lineage licenses the marker; anything
    else would mint the 'marker without its genesis' corruption."""
    log, db = build(tmp_path, keys, signer, absorb=False)
    log.append(
        "fact",
        {
            "t": "fact",
            "id": "01FOREIGNGENESIS0000000000",
            "kind": DECL_GENESIS,
            "ts": 5.0,
            "observer": "someone-else",
            "origin": "",
            "payload": json.dumps({"protocol": 1, "documents": []}),
        },
        observer="someone-else",
    )

    rederive_projections(log.path)
    assert meta(db, "own_lineage") is None

    conn = sqlite3.connect(str(db))
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM facts WHERE kind = ?", (DECL_GENESIS,)).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_a_present_marker_that_disagrees_with_the_log_refuses(tmp_path, keys, signer):
    """NON-NEGOTIABLE: overwriting a present, disagreeing marker means this
    index is some other log's projection, and repointing it silently would
    be the strongest lie available in this design. The refusal runs BEFORE
    anything is cleared."""
    log, db = build(tmp_path, keys, signer)
    before = rows(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) "
            "VALUES ('own_lineage', '01SOMEOTHERLINEAGE00000000')"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ArrivalCanonicalUnsupported, match="some other log"):
        rederive_projections(log.path)

    # Nothing was cleared: the refusal is before the destructive step.
    assert rows(db) == before
    assert meta(db, "own_lineage") == "01SOMEOTHERLINEAGE00000000"


def test_catch_up_never_overwrites_a_present_marker(tmp_path, keys, signer):
    """Catch-up stamps only when the marker is ABSENT, so it can never
    repoint an identity claim — which is why it needs no refusal of its own."""
    log, db = build(tmp_path, keys, signer)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) "
            "VALUES ('own_lineage', '01SOMEOTHERLINEAGE00000000')"
        )
        conn.commit()
    finally:
        conn.close()

    open_store(tmp_path).close()

    assert meta(db, "own_lineage") == "01SOMEOTHERLINEAGE00000000"
    assert meta(db, "own_lineage") != log.lineage()


# --- adopt stays refused, with a repointed message ---------------------------


def test_adopt_still_refuses_and_now_names_where_repair_lives(tmp_path, keys, signer):
    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        with pytest.raises(ArrivalCanonicalUnsupported) as exc:
            store.adopt_lineage()
    finally:
        store.close()
    assert "ordinal 0" in str(exc.value)
    assert "rederive_projections" in str(exc.value)
