"""JSONL-canonical store — the authority flip's write path.

The claim under test: the durable JSONL line is the store, sqlite is an
index derived from it. So the receipt must originate at the line (a crash
between line and index loses nothing and changes no id), the log must never
be left corrupt (torn line truncated), a lying offset must force a rebuild,
and signatures must ride the whole path verbatim — never re-signed.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact

from engine.jsonl_codec import deserialize_row
from engine.jsonl_store import JsonlCanonicalUnsupported, JsonlStore, log_path_for
from engine.sqlite_store import (
    SqliteStore,
    _fact_commitment_hash,
    tick_row_hash,
)
from engine.tick import Tick

# --- helpers ---------------------------------------------------------------


def open_store(tmp_path: Path, name: str = "s", **kw) -> JsonlStore:
    return JsonlStore(
        path=tmp_path / f"{name}.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        **kw,
    )


def fact(kind: str = "note", observer: str = "kyle", **payload) -> Fact:
    return Fact.of(kind, observer, **(payload or {"message": "hi"}))


def lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln]


def sqlite_facts(path: Path) -> list[tuple]:
    import sqlite3

    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(
            "SELECT id, kind, ts, observer, origin, payload, signature "
            "FROM facts ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()


def offset_of(store: JsonlStore) -> int:
    return store._read_offset()


# --- the basic contract ----------------------------------------------------


def test_append_writes_log_first_and_receipt_matches_sqlite(tmp_path):
    store = open_store(tmp_path)
    fid = store.append(fact())
    log = log_path_for(tmp_path / "s.db")

    assert log.exists()
    t, row = deserialize_row(lines(log)[0])
    assert t == "fact"
    assert row[0] == fid  # the receipt IS the id in the durable line
    assert [r[0] for r in sqlite_facts(store._path)] == [fid]
    assert offset_of(store) == log.stat().st_size
    store.close()


def test_log_path_defaults_beside_the_db(tmp_path):
    store = open_store(tmp_path, "project")
    assert store.log_path == tmp_path / "project.jsonl"
    store.close()


def test_tick_row_rides_the_log_and_rederives_its_hash(tmp_path):
    store = open_store(tmp_path)
    store.append(fact())
    store.append_tick(Tick(name="s", ts=datetime.now(UTC), payload={"n": 1}, origin="t"))
    store.close()

    kinds = [deserialize_row(ln) for ln in lines(tmp_path / "s.jsonl")]
    assert [t for t, _ in kinds] == ["fact", "tick"]
    tick_row = kinds[1][1]

    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    stored = conn.execute(
        "SELECT id, name, ts, since, origin, payload, prev_hash, window_start, "
        "fact_cursor, window_hash, signature FROM ticks"
    ).fetchone()
    conn.close()
    assert tick_row_hash(tick_row) == tick_row_hash(stored)


def test_reopen_is_synced_and_keeps_appending(tmp_path):
    store = open_store(tmp_path)
    first = store.append(fact())
    store.close()

    store = open_store(tmp_path)
    assert store.catch_up() == "synced"
    second = store.append(fact(message="two"))
    store.close()

    assert [r[0] for r in sqlite_facts(tmp_path / "s.db")] == [first, second]
    assert len(lines(tmp_path / "s.jsonl")) == 2


# --- crash window: log written, sqlite not ---------------------------------


def test_crash_window_reopen_tails_forward_with_stable_receipt(tmp_path):
    """The crash the flip exists to survive: the line is durable, the index
    never got it. Reopening must recover the row with its id unchanged."""
    store = open_store(tmp_path)
    kept = store.append(fact(message="indexed"))

    # Simulate: line flushed, process died before the sqlite transaction.
    lost_row = ("01LOSTFACT", "note", 2.0, "kyle", "", json.dumps({"m": "lost"}))
    from engine.jsonl_codec import serialize_fact_row

    with (tmp_path / "s.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(serialize_fact_row(lost_row) + "\n")
    store.close()

    store = open_store(tmp_path)
    assert store.catch_up() == "synced"  # the reopen already caught it up
    ids = [r[0] for r in sqlite_facts(tmp_path / "s.db")]
    assert ids == [kept, "01LOSTFACT"]
    assert offset_of(store) == (tmp_path / "s.jsonl").stat().st_size
    store.close()


def test_catch_up_preserves_a_foreign_signature_verbatim(tmp_path):
    """Indexing is not re-emitting: a signed line must land with its own
    signature, even though this store has no signer at all."""
    from engine.jsonl_codec import serialize_fact_row

    store = open_store(tmp_path)
    store.append(fact())
    store.close()

    row = ("01FOREIGN", "note", 3.0, "sol", "", json.dumps({"m": "signed"}),
           "sig-from-another-observer")
    with (tmp_path / "s.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(serialize_fact_row(row) + "\n")

    store = open_store(tmp_path)
    stored = [r for r in sqlite_facts(tmp_path / "s.db") if r[0] == "01FOREIGN"][0]
    assert stored == row
    store.close()


def test_signing_era_survives_the_new_path(tmp_path):
    """A signed fact appended through the JSONL path must verify: the
    commitment is over the payload TEXT the log carries."""
    signed: dict[str, str] = {}

    def fact_signer(observer: str, commitment: str) -> str | None:
        if observer != "kyle":
            return None
        signed[commitment] = f"sig::{commitment}"
        return signed[commitment]

    store = open_store(tmp_path, fact_signer=fact_signer)
    fid = store.append(fact())
    store.append(fact(observer="nokey"))
    store.close()

    rows = {r[0]: r for r in sqlite_facts(tmp_path / "s.db")}
    row = rows[fid]
    commitment = _fact_commitment_hash(row[1], row[2], row[3], row[4], row[5])
    assert row[6] == f"sig::{commitment}"          # signed under the stored text
    assert [r[6] for r in rows.values() if r[3] == "nokey"] == [None]

    # …and the line re-derives the same commitment, so verification survives.
    log_rows = [r for t, r in map(deserialize_row, lines(tmp_path / "s.jsonl"))]
    line = [r for r in log_rows if r[0] == fid][0]
    assert _fact_commitment_hash(line[1], line[2], line[3], line[4], line[5]) == commitment
    assert line[6] == row[6]


# --- torn line -------------------------------------------------------------


def test_torn_final_line_is_truncated_not_just_skipped(tmp_path):
    store = open_store(tmp_path)
    good = store.append(fact())
    store.close()
    log = tmp_path / "s.jsonl"
    intact = log.stat().st_size

    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"t":"fact","id":"01TORN","kind":"no')  # crash mid-write

    store = open_store(tmp_path)
    assert log.stat().st_size == intact          # truncated, not left as junk
    assert [r[0] for r in sqlite_facts(tmp_path / "s.db")] == [good]

    # And the next append lands as its own well-formed line.
    nxt = store.append(fact(message="after"))
    store.close()
    parsed = [deserialize_row(ln)[1][0] for ln in lines(log)]
    assert parsed == [good, nxt]


def test_torn_only_line_truncates_to_empty(tmp_path):
    log = tmp_path / "s.jsonl"
    log.write_text('{"t":"fact","id":"01TOR', encoding="utf-8")
    store = open_store(tmp_path)
    assert log.stat().st_size == 0
    fid = store.append(fact())
    store.close()
    assert [deserialize_row(ln)[1][0] for ln in lines(log)] == [fid]


# --- offset mismatch → rebuild ---------------------------------------------


def test_offset_beyond_log_size_forces_rebuild(tmp_path, caplog):
    store = open_store(tmp_path)
    a, b = store.append(fact()), store.append(fact(message="two"))
    store._conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('jsonl_offset', ?)",
        (str(10**9),),
    )
    store._conn.commit()
    store.close()

    with caplog.at_level("WARNING"):
        store = open_store(tmp_path)
    assert "rebuilding sqlite index" in caplog.text
    assert [r[0] for r in sqlite_facts(tmp_path / "s.db")] == [a, b]
    assert offset_of(store) == (tmp_path / "s.jsonl").stat().st_size
    store.close()


def test_content_mismatch_at_offset_forces_rebuild(tmp_path, caplog):
    """The cheap hash-match: the last consumed line must re-serialize from
    the row it names. A tampered index row is a mismatch."""
    store = open_store(tmp_path)
    store.append(fact())
    last = store.append(fact(message="two"))
    store._conn.execute(
        "UPDATE facts SET payload = ? WHERE id = ?",
        (json.dumps({"message": "tampered"}), last),
    )
    store._conn.commit()
    store.close()

    with caplog.at_level("WARNING"):
        store = open_store(tmp_path)
    assert "does not match the index" in caplog.text
    payloads = [json.loads(r[5])["message"] for r in sqlite_facts(tmp_path / "s.db")]
    assert payloads == ["hi", "two"]  # the log won, as canon
    store.close()


def test_offset_not_on_a_line_boundary_forces_rebuild(tmp_path, caplog):
    store = open_store(tmp_path)
    store.append(fact())
    store._conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('jsonl_offset', '3')"
    )
    store._conn.commit()
    store.close()

    with caplog.at_level("WARNING"):
        store = open_store(tmp_path)
    assert "rebuilding sqlite index" in caplog.text
    store.close()


def test_rebuild_preserves_own_lineage_identity(tmp_path):
    """A rebuild clears the derived tables only: ``own_lineage`` is identity,
    is not in the log, and cannot be re-derived from it."""
    store = open_store(tmp_path)
    store.append(fact())
    store._conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) "
        "VALUES ('own_lineage', 'LINEAGE-1')"
    )
    store._conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('jsonl_offset', '1')"
    )
    store._conn.commit()
    store.close()

    store = open_store(tmp_path)
    kept = store._conn.execute(
        "SELECT value FROM store_meta WHERE key = 'own_lineage'"
    ).fetchone()
    assert kept[0] == "LINEAGE-1"
    assert len(sqlite_facts(tmp_path / "s.db")) == 1
    store.close()


def test_missing_offset_marker_rebuilds_rather_than_double_indexing(tmp_path):
    """The post-export shape: a full log beside a full index, no consumption
    point recorded. Rebuild (not tail-from-0) is the honest answer."""
    plain = SqliteStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    a = plain.append(fact())
    b = plain.append(fact(message="two"))
    plain.close()

    # The S2 export shape, written here directly: engine may not import the
    # store lib (cross-lib DAG), so the fixture writes the log itself.
    from engine.jsonl_codec import serialize_fact_row

    (tmp_path / "s.jsonl").write_text(
        "".join(serialize_fact_row(r) + "\n" for r in sqlite_facts(tmp_path / "s.db")),
        encoding="utf-8",
    )

    store = open_store(tmp_path)
    assert [r[0] for r in sqlite_facts(tmp_path / "s.db")] == [a, b]
    assert offset_of(store) == (tmp_path / "s.jsonl").stat().st_size
    store.close()


def test_index_with_rows_but_no_log_refuses(tmp_path):
    plain = SqliteStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    plain.append(fact())
    plain.close()
    with pytest.raises(JsonlCanonicalUnsupported, match="export it first"):
        open_store(tmp_path)


# --- read surface + refusals ----------------------------------------------


def test_read_surface_is_untouched(tmp_path):
    store = open_store(tmp_path)
    store.append(fact(message="one"))
    store.append(fact(message="two"))
    assert store.total == 2
    assert [f.payload["message"] for f in store.since(0)] == ["one", "two"]
    assert [k for k, _ in store.since_raw(0)] == ["note", "note"]
    store.close()


@pytest.mark.parametrize("op", ["absorb_genesis", "absorb_edit", "reanchor"])
def test_history_mutating_ops_refuse_loudly(tmp_path, op):
    store = open_store(tmp_path)
    store.append(fact())
    with pytest.raises(JsonlCanonicalUnsupported, match="jsonl-canonical-store"):
        getattr(store, op)()
    store.close()


# --- review regressions (S3 round 1) --------------------------------------


def test_rejected_insert_never_orphans_a_line(tmp_path):
    """A duplicate id must fail BEFORE the line is durable.

    The INSERT is staged first precisely so a refused append cannot leave a
    line the index doesn't name — otherwise the next successful append would
    stamp the offset past the orphan and the index would stop being a
    function of the log, silently.
    """
    import sqlite3

    store = open_store(tmp_path)
    log = log_path_for(store._path)
    first = store.append(fact(message="one"))

    with pytest.raises(sqlite3.IntegrityError):
        store.append(fact(message="dup"), id_override=first)
    assert len(lines(log)) == 1  # no orphan line

    third = store.append(fact(message="three"))
    assert offset_of(store) == log.stat().st_size
    store.close()

    reopened = open_store(tmp_path)
    assert reopened.catch_up() == "synced"
    assert [r[0] for r in sqlite_facts(reopened._path)] == [first, third]
    reopened.close()


def test_duplicate_line_in_log_does_not_brick_reopen(tmp_path):
    """Even a hand-corrupted log must leave the store openable.

    The old failure mode: a rebuild raised from __init__ with DELETE FROM
    facts uncommitted on a leaked connection, so every later open failed
    with 'database is locked' — one bad open bricked the store forever.
    """
    import sqlite3

    store = open_store(tmp_path)
    log = log_path_for(store._path)
    store.append(fact(message="one"))
    store.close()

    with log.open("a", encoding="utf-8") as fh:  # duplicate the only line
        fh.write(lines(log)[0] + "\n")
    conn = sqlite3.connect(str(tmp_path / "s.db"))
    conn.execute("DELETE FROM store_meta WHERE key = 'jsonl_offset'")
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.IntegrityError):
        open_store(tmp_path)
    # the db is not locked: a second attempt fails the same way, not worse
    with pytest.raises(sqlite3.IntegrityError):
        open_store(tmp_path)


def test_integral_timestamps_stay_synced_across_opens(tmp_path):
    """sqlite REAL affinity must not read as corruption.

    An int ts in the line comes back as a float from sqlite; comparing
    re-serialized text made that look like divergence, so every open
    rebuilt the entire index and the WARNING became the steady state.
    """
    store = open_store(tmp_path)
    store.append(Fact.of("note", "kyle", ts=1700000000, message="int ts"))
    store.close()

    for _ in range(3):
        s = open_store(tmp_path)
        assert s.catch_up() == "synced"
        s.close()


def test_out_of_band_sqlite_rows_refuse_rather_than_vanish(tmp_path):
    """store.merge/receive INSERT straight into the db, bypassing the log.

    Accepting them as 'synced' meant the next rebuild deleted them with no
    error. Refusing is the only non-destructive answer — the rows survive.
    """
    import sqlite3

    store = open_store(tmp_path)
    store.append(fact(message="one"))
    store.close()

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    conn.execute(
        "INSERT OR IGNORE INTO facts (id, kind, ts, observer, origin, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("MERGED", "note", 1.0, "peer", "", "{}"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(JsonlCanonicalUnsupported, match="did not come through"):
        open_store(tmp_path)
    assert "MERGED" in [r[0] for r in sqlite_facts(tmp_path / "s.db")]


def test_long_line_still_gets_the_integrity_check(tmp_path):
    """The prefix check must not switch off as a function of payload size."""
    import sqlite3

    store = open_store(tmp_path)
    store.append(fact(message="x" * 70_000))
    store.close()

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    conn.execute("UPDATE facts SET observer = 'TAMPERED', payload = '{}'")
    conn.commit()
    conn.close()

    reopened = open_store(tmp_path)  # opening rebuilds: the tamper IS detected
    assert [r[3] for r in sqlite_facts(reopened._path)] == ["kyle"]
    assert reopened.catch_up() == "synced"
    reopened.close()


def test_two_open_handles_do_not_brick_the_store(tmp_path):
    """Regression: per-handle count caching bricked a consistent store.

    Two handles open at once (a daemon plus an ``sl emit``), one append
    through each. The log has both lines, sqlite has both rows, the offset
    equals the file size — fully consistent. A cached per-handle counter
    made the second committer stamp 1 against COUNT(*)=2, so the next open
    refused, naming out-of-band writers that never ran.
    """
    a = open_store(tmp_path)
    b = open_store(tmp_path)
    a.append(fact(message="from-a"))
    b.append(fact(message="from-b"))
    a.close()
    b.close()

    assert len(lines(log_path_for(tmp_path / "s.db"))) == 2
    assert len(sqlite_facts(tmp_path / "s.db")) == 2

    reopened = open_store(tmp_path)  # must not raise
    assert reopened.catch_up() == "synced"
    reopened.close()


def test_stale_handle_appending_after_another_wrote_stamps_the_truth(tmp_path):
    """Sequential variant: a long-lived handle must not stamp a stale count."""
    stale = open_store(tmp_path)  # opened when the store was empty
    other = open_store(tmp_path)
    for i in range(5):
        other.append(fact(message=f"m{i}"))
    other.close()

    stale.append(fact(message="late"))
    stale.close()

    assert len(sqlite_facts(tmp_path / "s.db")) == 6
    reopened = open_store(tmp_path)
    assert reopened.catch_up() == "synced"
    reopened.close()


def test_rebuild_drops_the_rowid_keyed_fts_index(tmp_path):
    """DELETE FROM facts resets rowids, so facts_fts/fts_state must go.

    Surviving FTS rows key on facts.rowid and would resolve stale text to
    freshly re-indexed facts, while fts_state.last_rowid would keep the
    incremental path from ever indexing them.
    """
    import sqlite3

    store = open_store(tmp_path)
    for i in range(3):
        store.append(fact(message=f"m{i}"))
    store.close()

    db = tmp_path / "s.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE VIRTUAL TABLE facts_fts USING fts5("
        "  text_content, fact_rowid UNINDEXED, kind UNINDEXED,"
        "  observer UNINDEXED);"
        "CREATE TABLE fts_state (key TEXT PRIMARY KEY, value TEXT);"
    )
    conn.execute(
        "INSERT INTO facts_fts(text_content, fact_rowid, kind, observer) "
        "VALUES ('m1', 2, 'note', 'kyle')"
    )
    conn.execute("INSERT INTO fts_state(key, value) VALUES ('last_rowid', '3')")
    conn.commit()
    conn.close()

    log = log_path_for(db)
    kept = lines(log)[0]
    log.write_text(kept + "\n", encoding="utf-8")  # shrink → forces a rebuild

    reopened = open_store(tmp_path)
    assert len(sqlite_facts(db)) == 1
    reopened.close()

    conn = sqlite3.connect(str(db))
    try:
        present = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
    finally:
        conn.close()
    assert "facts_fts" not in present
    assert "fts_state" not in present
