"""Does the audit see a poisoned index?

The claim under test (design/store/verify-canonical-agreement): a store whose
derived sqlite index disagrees with its canonical log must NOT verify. Every
test here injects one specific disagreement and asserts the audit names it —
and that the audit is a pure reader, leaving both artifacts exactly as it
found them (a repair would destroy the evidence it exists to inspect).
"""

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from atoms import Fact

from engine.canonical_audit import audit_agreement, audit_deep
from engine.jsonl_codec import serialize_fact_row
from engine.jsonl_store import JsonlStore
from engine.tick import Tick


def open_store(tmp_path: Path, name: str = "s") -> JsonlStore:
    return JsonlStore(
        path=tmp_path / f"{name}.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )


def seeded(tmp_path: Path) -> tuple[Path, Path]:
    """A small clean JSONL-canonical store: facts, a seal, more facts, a seal."""
    store = open_store(tmp_path)
    store.append(Fact.of("note", "kyle", message="one"))
    store.append(Fact.of("note", "kyle", message="two"))
    store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1},
                           origin="t"))
    store.append(Fact.of("note", "kyle", message="three"))
    store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={"n": 2},
                           origin="t"))
    store.close()
    return tmp_path / "s.jsonl", tmp_path / "s.db"


def failed(report) -> set[str]:
    return {c.name for c in report.divergences}


def artifacts(log: Path, db: Path) -> tuple[bytes, bytes]:
    return log.read_bytes(), db.read_bytes()


# --- clean stores -----------------------------------------------------------


def test_a_clean_store_agrees_at_both_depths(tmp_path):
    log, db = seeded(tmp_path)
    assert audit_agreement(log).ok
    deep = audit_deep(log)
    assert deep.ok, deep.summary()
    assert deep.deep
    assert {c.name for c in deep.checks} >= {"offset", "counts", "last-line",
                                             "content", "chain"}


def test_the_audit_never_touches_either_artifact(tmp_path):
    """Pure reader: no catch-up, no truncation, no marker write."""
    log, db = seeded(tmp_path)
    before = artifacts(log, db)
    audit_agreement(log)
    audit_deep(log)
    assert artifacts(log, db) == before


def test_an_empty_store_agrees(tmp_path):
    store = open_store(tmp_path)
    store.close()
    log = tmp_path / "s.jsonl"
    log.touch()
    assert audit_agreement(log).ok
    assert audit_deep(log).ok


# --- L1 divergences ---------------------------------------------------------


def test_out_of_band_insert_fails_count_parity(tmp_path):
    """The lie the index-only walk missed: a row the log never carried."""
    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
        "VALUES ('01FORGED', 'note', ?, 'mallory', '', ?)",
        (time.time(), json.dumps({"message": "forged"})),
    )
    conn.commit()
    conn.close()

    report = audit_agreement(log)
    assert not report.ok
    assert "counts" in failed(report)
    assert "out of band" in report.summary()


def test_log_ahead_of_the_index_fails_offset_parity(tmp_path):
    """A durable, unindexed line — the post-fsync crash window.

    The audit must see it as a disagreement rather than silently catching the
    index up: that is the difference between verification and repair.
    """
    log, _db = seeded(tmp_path)
    orphan = ("01UNINDEXED", "note", time.time(), "sol", "",
              json.dumps({"m": "durable"}))
    with log.open("a", encoding="utf-8") as fh:
        fh.write(serialize_fact_row(orphan) + "\n")

    report = audit_agreement(log)
    assert not report.ok
    assert failed(report) >= {"offset"}
    assert "unindexed" in report.summary()


def test_an_edited_last_row_fails_the_last_line_check(tmp_path):
    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    last = conn.execute("SELECT id FROM ticks ORDER BY rowid DESC").fetchone()[0]
    conn.execute("UPDATE ticks SET name = 'renamed' WHERE id = ?", (last,))
    conn.commit()
    conn.close()

    report = audit_agreement(log)
    assert not report.ok
    assert "last-line" in failed(report)


def test_a_missing_index_is_named_not_materialized(tmp_path):
    log, db = seeded(tmp_path)
    db.unlink()
    report = audit_agreement(log)
    assert not report.ok
    assert "index" in failed(report)
    assert "materialize" in report.summary()


def test_a_truncated_log_is_named_as_such(tmp_path):
    log, _db = seeded(tmp_path)
    raw = log.read_bytes()
    log.write_bytes(raw[: raw.rindex(b"\n", 0, len(raw) - 1) + 1])
    report = audit_agreement(log)
    assert not report.ok
    assert "offset" in failed(report)
    assert "truncated or replaced" in report.summary()


# --- --deep -----------------------------------------------------------------


def test_interior_index_edit_is_invisible_to_l1_and_named_by_deep(tmp_path):
    """The check that needs the whole log: a row neither last nor counted.

    L1 is O(1) by construction, so an interior edit passes it — stated, not
    implied. ``--deep`` streams the log and names the line.
    """
    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    first = conn.execute("SELECT id FROM facts ORDER BY rowid").fetchone()[0]
    conn.execute(
        "UPDATE facts SET payload = ? WHERE id = ?",
        (json.dumps({"message": "TAMPERED"}), first),
    )
    conn.commit()
    conn.close()

    assert audit_agreement(log).ok  # L1's honest blind spot
    deep = audit_deep(log)
    assert not deep.ok
    assert "content" in failed(deep)
    assert first in deep.summary()
    assert "log line 1" in deep.summary()


def test_deep_re_derives_the_chain_from_canonical_content(tmp_path):
    """A window whose facts were altered in the LOG breaks the re-derivation.

    The index still verifies against itself; the chain does not verify against
    the log. That is the check an index-only walk cannot make.
    """
    log, db = seeded(tmp_path)
    raw = log.read_text(encoding="utf-8").split("\n")
    obj = json.loads(raw[0])
    obj["payload"] = json.dumps({"message": "REWRITTEN"})
    raw[0] = json.dumps(obj, separators=(",", ":"))
    log.write_text("\n".join(raw), encoding="utf-8")

    deep = audit_deep(log)
    assert not deep.ok
    # The line no longer matches its index row either — both are true, and the
    # content check is the earlier, more specific report.
    assert "content" in failed(deep)


def test_deep_names_a_chain_break_when_index_and_log_agree(tmp_path):
    """Coordinated edit of BOTH artifacts: content agrees, the chain does not."""
    log, db = seeded(tmp_path)
    lines = log.read_text(encoding="utf-8").rstrip("\n").split("\n")
    obj = json.loads(lines[0])
    poisoned = json.dumps({"message": "COORDINATED"})
    obj["payload"] = poisoned
    lines[0] = json.dumps(obj, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE facts SET payload = ? WHERE id = ?", (poisoned, obj["id"]))
    conn.commit()
    conn.close()

    deep = audit_deep(log)
    assert not deep.ok
    assert "chain" in failed(deep)
    assert "window_hash mismatch" in deep.summary()


def test_deep_names_index_rows_the_log_never_carried(tmp_path):
    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
        "VALUES ('01APPENDED', 'note', ?, 'mallory', '', ?)",
        (time.time(), json.dumps({"message": "forged"})),
    )
    conn.commit()
    conn.close()

    deep = audit_deep(log)
    assert not deep.ok
    assert "content" in failed(deep)
    assert "never carried" in deep.summary()


def test_an_incomplete_tail_is_not_judged_as_content(tmp_path):
    """A torn final line was never indexed — offset says so; deep does not
    invent a content divergence out of it (truncating it is a writer's job)."""
    log, _db = seeded(tmp_path)
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"t":"fact","id":"01TOR')

    report = audit_agreement(log)
    assert "offset" in failed(report)
    deep = audit_deep(log)
    assert "content" not in failed(deep)


# --- lag is not tampering ---------------------------------------------------
#
# The writer fsyncs the log BEFORE committing the index rows and markers, so a
# crash in that window (and a torn append) leaves a truthful index that is
# merely BEHIND. The audit must report that once, as lag, and must not also
# accuse the index of an out-of-band edit for bytes it never claimed to have
# consumed.


def test_the_crash_window_reports_lag_once_and_never_as_an_index_edit(tmp_path):
    log, _db = seeded(tmp_path)
    orphan = ("01UNINDEXED", "note", time.time(), "sol", "",
              json.dumps({"m": "durable"}))
    with log.open("a", encoding="utf-8") as fh:
        fh.write(serialize_fact_row(orphan) + "\n")

    report = audit_agreement(log)
    assert failed(report) == {"offset"}
    assert "out of band" not in report.summary()
    assert report.lag_only
    last = next(c for c in report.checks if c.name == "last-line")
    assert last.ok and "last consumed" in last.detail


def test_a_torn_tail_does_not_read_as_an_unreadable_final_line(tmp_path):
    log, _db = seeded(tmp_path)
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"t":"fact","id":"01TOR')

    report = audit_agreement(log)
    assert failed(report) == {"offset"}
    assert report.lag_only
    assert "incomplete or unreadable" not in report.summary()


def test_deep_calls_an_unindexed_line_lag_not_tampering(tmp_path):
    log, _db = seeded(tmp_path)
    orphan = ("01UNINDEXED", "note", time.time(), "sol", "",
              json.dumps({"m": "durable"}))
    with log.open("a", encoding="utf-8") as fh:
        fh.write(serialize_fact_row(orphan) + "\n")

    deep = audit_deep(log)
    assert not deep.ok
    assert deep.lag_only
    assert failed(deep) >= {"offset", "content"}


def test_a_real_index_edit_is_still_tampering_not_lag(tmp_path):
    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    last = conn.execute("SELECT id FROM ticks ORDER BY rowid DESC").fetchone()[0]
    conn.execute("UPDATE ticks SET name = 'renamed' WHERE id = ?", (last,))
    conn.commit()
    conn.close()

    report = audit_agreement(log)
    assert "last-line" in failed(report)
    assert not report.lag_only
    assert "edited out of band" in report.summary()


def test_an_out_of_band_insert_is_never_lag(tmp_path):
    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, payload) "
        "VALUES ('01GHOST', 'note', ?, 'sol', '{}')", (time.time(),)
    )
    conn.commit()
    conn.close()

    report = audit_agreement(log)
    assert not report.lag_only


# --- lag is corroborated against the log, never taken from the marker -------
#
# The offset marker lives inside the sqlite file this audit exists to judge.
# If it alone decided `lag`, rewinding one integer would downgrade a tampered
# index to "not tampering" — an affirmative innocence claim, attacker-written.
# So lag holds only when the log suffix past the offset is really unindexed.


def _rewind_offset(db: Path, to: int) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE store_meta SET value = ? WHERE key = 'jsonl_offset'", (str(to),)
    )
    conn.commit()
    conn.close()


def _line_ends(log: Path) -> list[int]:
    ends, pos = [], 0
    for raw in log.read_bytes().splitlines(keepends=True):
        pos += len(raw)
        ends.append(pos)
    return ends


def test_a_rewound_offset_over_indexed_rows_is_never_lag(tmp_path):
    """Finding 1's repro: edit an interior row, rewind the marker below it."""
    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    fid = conn.execute("SELECT id FROM facts ORDER BY rowid").fetchall()[1][0]
    conn.execute("UPDATE facts SET payload = '{\"m\": \"forged\"}' WHERE id = ?",
                 (fid,))
    conn.commit()
    conn.close()
    _rewind_offset(db, _line_ends(log)[0])

    report = audit_agreement(log)
    assert not report.ok
    assert not report.lag_only, report.summary()
    assert "marker was moved" in report.summary()


def test_deep_never_stamps_lag_on_a_line_behind_a_rewound_offset(tmp_path):
    log, db = seeded(tmp_path)
    _rewind_offset(db, _line_ends(log)[0])
    deep = audit_deep(log)
    assert not deep.lag_only
    assert not any(c.lag for c in deep.checks), deep.as_dict()


def test_a_pure_marker_rewind_with_no_tamper_is_still_not_the_crash_shape(tmp_path):
    log, db = seeded(tmp_path)
    _rewind_offset(db, _line_ends(log)[0])
    report = audit_agreement(log)
    assert "offset" in failed(report)
    assert not report.lag_only


def test_honest_lag_still_reads_as_lag_after_the_corroboration(tmp_path):
    """The case 49a1cd0 got right must not regress."""
    log, _db = seeded(tmp_path)
    orphan = ("01STILLLAG", "note", time.time(), "sol", "",
              json.dumps({"m": "durable"}))
    with log.open("a", encoding="utf-8") as fh:
        fh.write(serialize_fact_row(orphan) + "\n")
    assert audit_agreement(log).lag_only


def test_a_rewound_offset_heals_through_a_read_verb_instead_of_crashing(tmp_path):
    """Finding 2's repro: the advertised remedy must not raise IntegrityError."""
    from engine.jsonl_store import ensure_index

    log, db = seeded(tmp_path)
    conn = sqlite3.connect(str(db))
    fid = conn.execute("SELECT id FROM facts ORDER BY rowid").fetchall()[1][0]
    conn.execute("UPDATE facts SET payload = '{\"m\": \"forged\"}' WHERE id = ?",
                 (fid,))
    conn.commit()
    conn.close()
    _rewind_offset(db, _line_ends(log)[0])

    ensure_index(log)  # was: sqlite3.IntegrityError: UNIQUE constraint failed
    healed = audit_agreement(log)
    assert healed.ok, healed.summary()
    assert audit_deep(log).ok
