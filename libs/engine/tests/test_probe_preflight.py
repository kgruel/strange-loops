"""probe_target + read_preflight — the S7 matrix oracle.

Two claims under test:

1. For every target class (vertex file, jsonl-canonical log, derived index
   sibling, sqlite-canonical store, missing path, stale index, out-of-band
   tampered store) :func:`engine.probe.probe_target` returns the documented
   :class:`~engine.probe.TargetInfo` — AND provably mutated nothing (the
   target directory is byte-hashed, every file's contents, before/after).

2. :func:`engine.preflight.read_preflight` keeps its three modes typed and
   separate: audit-only reports damage without repairing, audit-then-open
   refuses on damage, recover-then-open repairs — and only it.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact

from engine.jsonl_store import JsonlStore
from engine.preflight import (
    PREFLIGHT_STATUSES,
    PreflightMode,
    read_preflight,
)
from engine.probe import TargetInfo, probe_target
from engine.tick import Tick

# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


_WAL_SIDE_FILES = (".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm")


def dir_hash(root: Path) -> dict[str, str]:
    """Every file under ``root`` → sha256 of its CONTENTS (not mtimes).

    Sqlite's WAL side files are excluded from the equality claim: ANY
    read-only connection to a WAL-mode database (mode=ro URI included) may
    create ``-wal``/``-shm`` scaffolding — that is sqlite's shared-memory
    protocol, not a store mutation, and it happens on ``sl read`` too. The
    oracle is therefore: every artifact byte-identical, and no NEW files
    beyond that scaffolding (asserted in ``probed_unchanged``).
    """
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.endswith(_WAL_SIDE_FILES)
    }


def new_files_ok(root: Path, before: set[str]) -> bool:
    """No new files beyond sqlite WAL scaffolding."""
    now = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    return all(n.endswith(_WAL_SIDE_FILES) for n in now - before)


def seeded_jsonl(tmp_path: Path, name: str = "s") -> tuple[Path, Path]:
    """A clean JSONL-canonical store: facts, a seal, more facts, a seal."""
    store: JsonlStore = JsonlStore(
        path=tmp_path / f"{name}.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    store.append(Fact.of("note", "kyle", message="one"))
    store.append(Fact.of("note", "kyle", message="two"))
    store.append_tick(
        Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1}, origin="t")
    )
    store.append(Fact.of("note", "kyle", message="three"))
    store.close()
    return tmp_path / f"{name}.jsonl", tmp_path / f"{name}.db"


def seeded_sqlite(tmp_path: Path, name: str = "solo") -> Path:
    """A sqlite-canonical store (no sibling log)."""
    from engine.sqlite_store import SqliteStore

    store: SqliteStore = SqliteStore(
        path=tmp_path / f"{name}.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    store.append(Fact.of("note", "kyle", message="solo"))
    store.close()
    return tmp_path / f"{name}.db"


_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  note {{ fold {{ count "inc" }} }}
}}
'''

_BARE_KDL = 'name "bare"\nloops { note { fold { count "inc" } } }\n'


def probed_unchanged(root: Path, target: Path) -> TargetInfo:
    """Probe, asserting the directory's bytes did not change."""
    names = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    before = dir_hash(root)
    info = probe_target(target)
    assert dir_hash(root) == before, "probe mutated the target directory"
    assert new_files_ok(root, names), "probe created non-scaffolding files"
    return info


# ---------------------------------------------------------------------------
# probe_target — the target-class matrix
# ---------------------------------------------------------------------------


def test_probe_vertex_with_jsonl_store(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=log))
    info = probed_unchanged(tmp_path, vpath)
    assert info.target_type == "vertex"
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path == log
    assert info.index_path == db
    assert info.exists is True
    assert info.index_current is True
    assert info.declaration_status in (
        "store", "file-pre-genesis", "unhistorized", "aggregate-head",
    )


def test_probe_vertex_missing_and_storeless(tmp_path):
    missing = probed_unchanged(tmp_path, tmp_path / "nope.vertex")
    assert missing.target_type == "vertex"
    assert missing.exists is False
    assert missing.canonical_path is None
    assert missing.declaration_status is None

    storeless = tmp_path / "bare.vertex"
    storeless.write_text(_BARE_KDL)
    info = probed_unchanged(tmp_path, storeless)
    assert info.target_type == "vertex"
    assert info.canonical_mode is None
    assert info.canonical_path is None
    assert "no store" in info.reason


def test_probe_unparseable_vertex_reports_instead_of_raising(tmp_path):
    bad = tmp_path / "bad.vertex"
    bad.write_text("this is { not } kdl \x00")
    info = probed_unchanged(tmp_path, bad)
    assert info.target_type == "vertex"
    assert info.declaration_status is None
    assert "does not resolve" in info.reason


def test_probe_jsonl_canonical_log(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    info = probed_unchanged(tmp_path, log)
    assert info.target_type == "jsonl_log"
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path == log
    assert info.index_path == db
    assert info.exists is True
    assert info.index_current is True
    assert info.writable is True


def test_probe_derived_index_sibling_is_not_a_write_target(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    info = probed_unchanged(tmp_path, db)
    assert info.target_type == "derived_index"
    assert info.canonical_mode == "jsonl"
    assert info.canonical_path == log, "canonical must be the LOG, not the db"
    assert info.index_path == db
    assert info.writable is False
    assert "out-of-band" in info.reason


def test_probe_sqlite_canonical_store(tmp_path):
    db = seeded_sqlite(tmp_path)
    info = probed_unchanged(tmp_path, db)
    assert info.target_type == "sqlite_store"
    assert info.canonical_mode == "sqlite"
    assert info.canonical_path == db
    assert info.index_path == db
    assert info.index_current is None, "currency does not apply: the db IS the store"
    assert info.writable is True


def test_probe_missing_paths_classify_by_suffix(tmp_path):
    log = probed_unchanged(tmp_path, tmp_path / "ghost.jsonl")
    assert (log.target_type, log.exists, log.index_current) == (
        "jsonl_log", False, None,
    )
    db = probed_unchanged(tmp_path, tmp_path / "ghost.db")
    assert (db.target_type, db.exists) == ("sqlite_store", False)
    other = probed_unchanged(tmp_path, tmp_path / "ghost.txt")
    assert (other.target_type, other.canonical_path, other.writable) == (
        "unknown", None, False,
    )


def test_probe_stale_index_reports_not_current_without_repairing(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    # Make the index stale the honest way: append to the log out-of-band
    # (a durable line the index never consumed — the crash-window shape).
    with log.open("a") as fh:
        fh.write("\n")  # a blank line changes size; offset parity breaks
    info = probed_unchanged(tmp_path, log)
    assert info.target_type == "jsonl_log"
    assert info.index_current is False
    # And a MISSING index is "not current", not "current" and not None.
    db.unlink()
    info2 = probed_unchanged(tmp_path, log)
    assert info2.index_current is False
    # The probe did not materialize it.
    assert not db.exists()


def test_probe_tampered_store_makes_no_verdict_and_mutates_nothing(tmp_path):
    """Out-of-band sqlite insert: probe reports LOCATION state only.

    Offset parity is untouched by a row insert, so index_current stays True
    — that is the documented scope (a currency claim, not integrity). The
    verdict lives in preflight/audit, tested below on the same shape.
    """
    log, db = seeded_jsonl(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO facts (id, ts, kind, observer, payload)"
        " VALUES ('oob', 1.0, 'note', 'mallory', '{}')"
    )
    conn.commit()
    conn.close()
    info = probed_unchanged(tmp_path, log)
    assert info.target_type == "jsonl_log"
    assert info.index_current is True  # scope: offset parity only
    assert "verified" not in info.reason


def test_probe_content_corroboration_notes_suffix_lies(tmp_path):
    fake_log = tmp_path / "fake.jsonl"
    fake_log.write_text("not a codec row\n")
    assert "does not decode" in probed_unchanged(tmp_path, fake_log).reason
    fake_db = tmp_path / "solo.db"  # no sibling log → sqlite_store
    fake_db.write_bytes(b"definitely not sqlite")
    assert "not a sqlite database" in probed_unchanged(tmp_path, fake_db).reason


def test_probe_content_corroboration_accepts_batch_first_line(tmp_path):
    """S1b seam pin: a log whose first complete line is a ceremony batch is a
    valid loops log — the corroboration note must stay silent (S7 re-gate
    finding 1b: deserialize_row refuses batch lines; probe must decode via
    deserialize_records)."""
    from engine.jsonl_codec import serialize_batch

    rows = [
        ("b1", "_decl.kind-defined", 9.0, "kyle", "", "{}", None),
        ("b2", "_decl.kind-retired", 9.0, "kyle", "", "{}", None),
    ]
    log = tmp_path / "ceremony.jsonl"
    log.write_text(serialize_batch(rows) + "\n")
    info = probed_unchanged(tmp_path, log)
    assert info.target_type == "jsonl_log"
    assert "does not decode" not in info.reason


def test_probe_never_creates_sqlite_siblings_for_missing_targets(tmp_path):
    """The bare-connect trap: probing missing paths must create nothing."""
    for name in ("a.jsonl", "b.db", "c.sqlite", "d.vertex", "e.whatever"):
        probe_target(tmp_path / name)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# read_preflight — three modes, kept apart
# ---------------------------------------------------------------------------


def damage_out_of_band(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO facts (id, ts, kind, observer, payload)"
        " VALUES ('oob', 1.0, 'note', 'mallory', '{}')"
    )
    conn.commit()
    conn.close()


def test_audit_only_on_a_clean_store(tmp_path):
    log, _ = seeded_jsonl(tmp_path)
    r = read_preflight(log, PreflightMode.AUDIT_ONLY)
    assert (r.status, r.agreed, r.opened, r.recovered) == ("ok", True, False, False)
    assert r.store is None
    assert r.report is not None and r.report.ok


def test_audit_only_on_damage_returns_typed_damage_without_repairing(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    damage_out_of_band(db)
    before = dir_hash(tmp_path)
    r = read_preflight(log, PreflightMode.AUDIT_ONLY)
    assert dir_hash(tmp_path) == before, "audit-only mutated the store"
    assert r.status == "diverged"
    assert r.agreed is False and r.opened is False and r.recovered is False
    assert r.store is None
    assert "counts" in {c.name for c in r.report.divergences}
    assert r.status in PREFLIGHT_STATUSES


def test_audit_then_open_refuses_on_damage(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    damage_out_of_band(db)
    before = dir_hash(tmp_path)
    r = read_preflight(log, PreflightMode.AUDIT_THEN_OPEN)
    assert dir_hash(tmp_path) == before, "a refusal must not repair"
    assert (r.status, r.opened, r.recovered, r.store) == (
        "refused", False, False, None,
    )
    assert "recover-then-open" in r.reason


def test_audit_then_open_opens_a_clean_store(tmp_path):
    log, _ = seeded_jsonl(tmp_path)
    r = read_preflight(log, PreflightMode.AUDIT_THEN_OPEN)
    assert (r.status, r.agreed, r.opened) == ("ok", True, True)
    assert isinstance(r.store, JsonlStore)
    r.store.close()


def test_audit_then_open_refuses_a_fresh_clone_by_contract(tmp_path):
    """Missing derived index: materializing is repair, so this mode refuses."""
    log, db = seeded_jsonl(tmp_path)
    db.unlink()
    r = read_preflight(log, PreflightMode.AUDIT_THEN_OPEN)
    assert (r.status, r.opened) == ("refused", False)
    assert not db.exists(), "the refusal materialized the index"


def test_recover_then_open_repairs_a_stale_index_and_reports_both_sides(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    db.unlink()  # fresh-clone shape: log without index
    r = read_preflight(log, PreflightMode.RECOVER_THEN_OPEN)
    assert (r.status, r.opened, r.recovered) == ("recovered", True, True)
    assert r.report is not None and not r.report.ok  # pre-repair evidence kept
    assert r.post_report is not None and r.post_report.ok
    assert isinstance(r.store, JsonlStore)
    r.store.close()
    assert db.exists()


def test_recover_then_open_still_refuses_out_of_band_rows(tmp_path):
    """Unrecoverable damage: the log cannot account for injected rows."""
    log, db = seeded_jsonl(tmp_path)
    damage_out_of_band(db)
    r = read_preflight(log, PreflightMode.RECOVER_THEN_OPEN)
    assert (r.status, r.opened, r.recovered, r.store) == (
        "refused", False, False, None,
    )
    assert r.report is not None and not r.report.ok


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(b"this is not json at all\n", id="corrupt-suffix"),
        pytest.param(b'\xff\xfe not utf-8 \x80\n', id="invalid-utf8"),
        pytest.param(b'{"t":"unknown"}\n', id="unknown-discriminator"),
    ],
)
def test_recover_then_open_types_canonical_corruption_as_unreadable(
    tmp_path, suffix
):
    """SOL-R1-03: corruption recovery cannot fix must come back as a typed
    ``unreadable`` PreflightResult with the pre-recovery audit attached —
    never a raw JsonlCodecError/UnicodeDecodeError escaping the mode.

    The corrupt suffix is newline-terminated on purpose: a torn tail
    (no trailing newline) is legitimately repaired by open-time recovery,
    which is not the behavior under test.
    """
    log, _db = seeded_jsonl(tmp_path)
    with log.open("ab") as fh:
        fh.write(suffix)
    r = read_preflight(log, PreflightMode.RECOVER_THEN_OPEN)
    assert r.status == "unreadable"
    assert (r.opened, r.recovered, r.store, r.post_report) == (
        False, False, None, None,
    )
    assert r.report is not None  # pre-recovery evidence kept


def test_recover_then_open_on_a_clean_store_reports_no_recovery(tmp_path):
    log, _ = seeded_jsonl(tmp_path)
    r = read_preflight(log, PreflightMode.RECOVER_THEN_OPEN)
    assert (r.status, r.recovered, r.opened) == ("ok", False, True)
    r.store.close()


def test_recover_then_open_never_invents_a_log(tmp_path):
    r = read_preflight(tmp_path / "ghost.jsonl", PreflightMode.RECOVER_THEN_OPEN)
    assert (r.status, r.opened) == ("unreadable", False)
    assert list(tmp_path.iterdir()) == []


def test_sqlite_canonical_agreement_is_vacuous(tmp_path):
    db = seeded_sqlite(tmp_path)
    audit = read_preflight(db, PreflightMode.AUDIT_ONLY)
    assert (audit.status, audit.agreed, audit.report, audit.opened) == (
        "ok", True, None, False,
    )
    assert "vacuous" in audit.reason
    opened = read_preflight(db, PreflightMode.AUDIT_THEN_OPEN)
    assert opened.opened is True and opened.recovered is False
    opened.store.close()


def test_preflight_composes_with_probe_and_reroutes_a_derived_index(tmp_path):
    log, db = seeded_jsonl(tmp_path)
    # A TargetInfo flows straight in.
    via_info = read_preflight(probe_target(log), PreflightMode.AUDIT_ONLY)
    assert via_info.canonical_path == log
    # A derived-index path is re-routed to the canonical log.
    via_db = read_preflight(db, PreflightMode.AUDIT_ONLY)
    assert via_db.canonical_path == log
    # A storeless target is a typed error, not a silent guess.
    bare = tmp_path / "bare.vertex"
    bare.write_text(_BARE_KDL)
    with pytest.raises(ValueError, match="no canonical_path"):
        read_preflight(probe_target(bare), PreflightMode.AUDIT_ONLY)


def test_index_behind_maps_to_its_own_status(tmp_path):
    """A durable-but-unindexed suffix is 'index-behind', not 'diverged'."""
    log, db = seeded_jsonl(tmp_path)
    with log.open("a") as fh:
        # A torn tail: durable bytes the index never consumed — the
        # interrupted-append shape, beyond the consumed prefix by construction.
        fh.write("{torn")
    r = read_preflight(log, PreflightMode.AUDIT_ONLY)
    assert r.status == "index-behind"
    assert r.report.index_behind


def test_preflight_never_creates_a_missing_sqlite_store(tmp_path):
    """A read preflight of a missing sqlite-canonical db creates nothing.

    SqliteStore.__init__ creates a missing file, so an unconditional open
    would turn preflight into store creation — in every mode.
    """
    ghost = tmp_path / "ghost.db"
    for mode in PreflightMode:
        r = read_preflight(ghost, mode)
        assert (r.status, r.opened, r.recovered, r.store) == (
            "unreadable", False, False, None,
        )
        assert "never creates" in r.reason
    assert list(tmp_path.iterdir()) == []
