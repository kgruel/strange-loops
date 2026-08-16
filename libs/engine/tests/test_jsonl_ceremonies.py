"""Declaration ceremonies on JSONL-canonical stores (S1b).

The acceptance oracle of design:architecture/jsonl-declaration-ceremony-
encoding (ratified): genesis dissolves into ``_write``'s five-step shape (no
new grammar — one plain ``_decl.genesis`` fact line), a multi-row edit
ceremony lands as ONE ``"t":"batch"`` line (the log's atomicity unit), every
refusal class fires before any log byte, and recovery can never expose a
partial ceremony. Oracle #10 (reanchor stays refused) is pinned in
``test_jsonl_store.py::test_reanchor_still_refuses_loudly``; #9 (golden
fixtures) in ``test_jsonl_golden_fixtures.py``.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex
from lang.document import (
    DECL_GENESIS,
    diff_documents,
    documents_to_vertex,
    vertex_to_documents,
)

from engine.canonical_audit import audit_agreement, audit_deep
from engine.declaration import resolve_declaration_documents
from engine.jsonl_codec import deserialize_records, deserialize_row
from engine.jsonl_store import JsonlStore
from engine.residence import log_path_for
from engine.sqlite_store import (
    AmbiguousGenesis,
    GenesisExists,
    SqliteStore,
    StaleDeclarationHead,
    UnsignableEdit,
)

# --- helpers ---------------------------------------------------------------


def _signer(secret: str | None):
    def signer(observer: str, digest: str) -> str | None:
        if secret is None:
            return None
        return hashlib.sha256(f"{secret}:{observer}:{digest}".encode()).hexdigest()

    return signer


def open_store(tmp_path: Path, name: str = "s", **kw) -> JsonlStore:
    return JsonlStore(
        path=tmp_path / f"{name}.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        **kw,
    )


def lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln]


def sqlite_fact_ids(path: Path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY rowid")]
    finally:
        conn.close()


BASE = (
    'name "x"\nstore "./x.jsonl"\nloops {\n'
    '  a { fold { n "inc" } }\n  b { fold { n "inc" } }\n}\n'
)
EDIT_TWO = (
    'name "x"\nstore "./x.jsonl"\nloops {\n'
    '  a { fold { n "latest" } }\n  b { fold { n "latest" } }\n}\n'
)
EDIT_ONE = (
    'name "x"\nstore "./x.jsonl"\nloops {\n'
    '  a { fold { n "latest" } }\n  b { fold { n "inc" } }\n}\n'
)


def _genesis(store: JsonlStore) -> dict:
    docs = [d.as_json() for d in vertex_to_documents(parse_vertex(BASE))]
    return store.absorb_genesis(docs, observer="obs", fact_signer=_signer("k"))


def _changes(db: Path, target_text: str):
    head = resolve_declaration_documents(db)
    return diff_documents(head, vertex_to_documents(parse_vertex(target_text)))


# --- #1 genesis on a fresh JSONL-canonical store ---------------------------


def test_genesis_succeeds_and_log_carries_one_genesis_line(tmp_path):
    store = open_store(tmp_path)
    receipt = _genesis(store)
    log = log_path_for(store._path)

    assert receipt["signed"] is True
    assert receipt["chain_head"] is None and receipt["fact_cursor"] is None
    log_lines = lines(log)
    assert len(log_lines) == 1
    t, row = deserialize_row(log_lines[0])
    assert t == "fact"
    assert row[0] == receipt["lineage"]  # genesis row id IS the lineage id
    assert row[1] == DECL_GENESIS
    assert row[6] is not None  # signed
    assert store._meta_get("own_lineage") == receipt["lineage"]
    assert store._read_offset() == log.stat().st_size
    store.close()
    assert audit_deep(log).ok


def test_genesis_receipt_matches_sqlite_canonical_behavior(tmp_path):
    docs = [d.as_json() for d in vertex_to_documents(parse_vertex(BASE))]
    plain = SqliteStore(
        path=tmp_path / "p.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    sqlite_receipt = plain.absorb_genesis(docs, observer="obs", fact_signer=_signer("k"))
    plain.close()
    jsonl = open_store(tmp_path)
    jsonl_receipt = _genesis(jsonl)
    jsonl.close()
    # Same receipt surface; only the minted id differs.
    assert set(sqlite_receipt) == set(jsonl_receipt)
    for key in ("protocol", "documents", "chain_head", "fact_cursor", "observer", "signed"):
        assert sqlite_receipt[key] == jsonl_receipt[key]


# --- #2 second genesis refuses, log byte-identical -------------------------


def test_second_genesis_refuses_and_log_is_byte_identical(tmp_path):
    store = open_store(tmp_path)
    _genesis(store)
    log = log_path_for(store._path)
    before = log.read_bytes()
    with pytest.raises(GenesisExists):
        _genesis(store)
    assert log.read_bytes() == before
    store.close()


# --- #3 multi-change ceremony: one batch line, one ts, resolves ------------


def test_multi_change_ceremony_lands_as_one_batch_line_and_resolves(tmp_path):
    store = open_store(tmp_path)
    _genesis(store)
    db, log = store._path, log_path_for(store._path)

    changes = _changes(db, EDIT_TWO)
    assert len(changes) >= 2
    receipt = store.absorb_edit(changes, observer="obs", fact_signer=_signer("k"))
    assert receipt["defined"] + receipt["retired"] == len(changes)

    log_lines = lines(log)
    assert len(log_lines) == 2  # genesis line + ONE batch line
    records = deserialize_records(log_lines[-1])
    assert len(records) == len(changes)
    assert all(t == "fact" for t, _ in records)
    assert len({row[2] for _, row in records}) == 1  # one effective ts
    assert all(row[6] is not None for _, row in records)  # every row signed

    # Round-trip through declaration resolution: store ≡ parse(edited).
    target = parse_vertex(EDIT_TWO)
    head = resolve_declaration_documents(db)
    assert documents_to_vertex(head, path=target.path, store=target.store) == target
    assert store._read_offset() == log.stat().st_size
    store.close()
    assert audit_deep(log).ok


# --- #4 single-change ceremony is a plain fact line ------------------------


def test_single_change_ceremony_is_a_plain_fact_line(tmp_path):
    store = open_store(tmp_path)
    _genesis(store)
    db, log = store._path, log_path_for(store._path)

    changes = _changes(db, EDIT_ONE)
    assert len(changes) == 1
    store.absorb_edit(changes, observer="obs", fact_signer=_signer("k"))

    last = lines(log)[-1]
    t, row = deserialize_row(last)  # deserialize_row refuses batch lines
    assert t == "fact"
    assert row[1] == changes[0].kind
    store.close()
    assert audit_deep(log).ok


# --- #5 stale expected_head: log byte-identical, index lawfully converges --


def test_stale_head_refuses_with_log_byte_identical(tmp_path):
    store = open_store(tmp_path)
    _genesis(store)
    log = log_path_for(store._path)
    before = log.read_bytes()
    changes = _changes(store._path, EDIT_ONE)
    with pytest.raises(StaleDeclarationHead):
        store.absorb_edit(
            changes,
            observer="obs",
            fact_signer=_signer("k"),
            expected_head=(0, "01BOGUS"),
        )
    assert log.read_bytes() == before
    store.close()


def test_stale_head_allows_lawful_pre_cas_index_catch_up(tmp_path):
    """The nuance: the step-1 reconcile may catch the INDEX up to lines that
    were already durable before the call. That is convergence toward the
    unchanged log, not a ceremony artifact."""
    from engine.jsonl_codec import serialize_fact_row

    store = open_store(tmp_path)
    _genesis(store)
    log = log_path_for(store._path)
    changes = _changes(store._path, EDIT_ONE)

    # A durable line the index has not consumed (another process's write).
    orphan = ("01ORPHANROWDURABLEUNINDEXED", "note", 1721359999.0, "kyle", "", "{}")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(serialize_fact_row(orphan) + "\n")
    before = log.read_bytes()

    with pytest.raises(StaleDeclarationHead):
        store.absorb_edit(
            changes,
            observer="obs",
            fact_signer=_signer("k"),
            expected_head=(0, "01BOGUS"),
        )
    # LOG byte-identical; the index converged to a pure function of it.
    assert log.read_bytes() == before
    assert store._read_offset() == log.stat().st_size
    assert orphan[0] in sqlite_fact_ids(store._path)
    store.close()
    assert audit_agreement(log).ok


# --- #6 fault injection ----------------------------------------------------


def test_fault_before_append_leaves_log_untouched(tmp_path):
    """(a) A step-3 refusal (signer produces nothing) rolls back with no
    log byte written."""
    store = open_store(tmp_path)
    _genesis(store)
    log = log_path_for(store._path)
    before = log.read_bytes()
    changes = _changes(store._path, EDIT_TWO)
    with pytest.raises(UnsignableEdit):
        store.absorb_edit(changes, observer="obs", fact_signer=_signer(None))
    assert log.read_bytes() == before
    assert len(sqlite_fact_ids(store._path)) == 1  # genesis only
    store.close()
    assert audit_deep(log).ok


def test_fault_after_append_before_commit_tails_full_ceremony(tmp_path, monkeypatch):
    """(b) The line is durable, the index rolls back; the next open tails
    the WHOLE ceremony in — never a subset."""
    store = open_store(tmp_path)
    _genesis(store)
    log = log_path_for(store._path)
    changes = _changes(store._path, EDIT_TWO)

    real_stamp = JsonlStore._stamp

    def boom(self, *a, **kw):
        raise RuntimeError("crash between fsync and commit")

    monkeypatch.setattr(JsonlStore, "_stamp", boom)
    with pytest.raises(RuntimeError, match="between fsync and commit"):
        store.absorb_edit(changes, observer="obs", fact_signer=_signer("k"))
    monkeypatch.setattr(JsonlStore, "_stamp", real_stamp)

    # Durable batch line; index rolled back to genesis only.
    records = deserialize_records(lines(log)[-1])
    assert len(records) == len(changes)
    assert len(sqlite_fact_ids(store._path)) == 1
    store.close()

    reopened = open_store(tmp_path)
    ids = sqlite_fact_ids(reopened._path)
    assert set(row[0] for _, row in records) <= set(ids)  # all N, atomically
    assert reopened._read_offset() == log.stat().st_size
    reopened.close()
    assert audit_deep(log).ok


def test_fault_after_genesis_append_recovers_via_explicit_adoption(
    tmp_path, monkeypatch
):
    """(b), genesis flavor — DEVIATION FROM THE PROPOSAL'S RECOVERY MATRIX,
    pinned deliberately: the durable-but-unmarked genesis is NOT silently
    adopted on retry (the singleton heuristic was removed as a hijack vector,
    closing re-review #1 — see observation:implementation/
    s1b-genesis-selfheal-deviation). Retry surfaces AmbiguousGenesis; the
    honest recovery is the explicit adopt_lineage ceremony."""
    store = open_store(tmp_path)
    log = log_path_for(store._path)

    def boom(self, *a, **kw):
        raise RuntimeError("crash between fsync and commit")

    monkeypatch.setattr(JsonlStore, "_stamp", boom)
    with pytest.raises(RuntimeError):
        _genesis(store)
    monkeypatch.undo()

    t, row = deserialize_row(lines(log)[0])
    assert row[1] == DECL_GENESIS  # durable
    assert store._meta_get("own_lineage") is None  # marker never stamped
    store.close()

    reopened = open_store(tmp_path)  # tails the genesis row in
    assert sqlite_fact_ids(reopened._path) == [row[0]]
    with pytest.raises(AmbiguousGenesis):
        _genesis(reopened)
    adopted = reopened.adopt_lineage()
    assert adopted["lineage"] == row[0]
    with pytest.raises(GenesisExists):
        _genesis(reopened)  # the honest receipt, post-adoption
    reopened.close()
    assert audit_deep(log).ok


def test_torn_batch_line_truncates_and_no_ceremony_happened(tmp_path):
    """(c) A torn batch tail is truncated whole on the next open — the
    ceremony never happened, no subset survives."""
    from engine.jsonl_codec import serialize_batch

    store = open_store(tmp_path)
    _genesis(store)
    log = log_path_for(store._path)
    intact = log.read_bytes()
    store.close()

    rows = [
        ("01JTORNA", "_decl.kind-defined", 1721359123.5, "obs", "", "{}", "sig"),
        ("01JTORNB", "_decl.kind-retired", 1721359123.5, "obs", "", "{}", "sig"),
    ]
    torn = serialize_batch(rows)[:-7]  # mid-line crash, no newline
    with log.open("a", encoding="utf-8") as fh:
        fh.write(torn)

    reopened = open_store(tmp_path)
    assert log.read_bytes() == intact  # truncated back to the intact prefix
    ids = sqlite_fact_ids(reopened._path)
    assert "01JTORNA" not in ids and "01JTORNB" not in ids
    reopened.close()
    assert audit_deep(log).ok


# --- #7 rebuild from log reproduces ceremony rows --------------------------


def test_rebuild_from_log_reproduces_ceremony_rows_in_order(tmp_path):
    store = open_store(tmp_path)
    _genesis(store)
    store.append(Fact.of("note", "kyle", message="between"))
    store.absorb_edit(
        _changes(store._path, EDIT_TWO), observer="obs", fact_signer=_signer("k")
    )
    before_ids = sqlite_fact_ids(store._path)
    lineage = store._meta_get("own_lineage")
    db = store._path
    store.close()

    db.unlink()  # fresh clone: log tracked, index not
    rebuilt = open_store(tmp_path)
    assert sqlite_fact_ids(rebuilt._path) == before_ids  # same rows, same order
    # store_meta died with the db; identity re-derives via explicit adoption.
    assert rebuilt._meta_get("own_lineage") is None
    assert rebuilt.adopt_lineage()["lineage"] == lineage
    rebuilt.close()
    assert audit_deep(log_path_for(db)).ok


def test_rebuild_preserves_own_lineage_when_only_rows_cleared(tmp_path):
    """JsonlStore._rebuild clears facts/ticks only — the identity marker
    survives an in-place index rebuild."""
    store = open_store(tmp_path)
    receipt = _genesis(store)
    store._rebuild("test: forced")
    assert store._meta_get("own_lineage") == receipt["lineage"]
    assert sqlite_fact_ids(store._path) == [receipt["lineage"]]
    store.close()


# --- #8 last-line integrity over a trailing batch --------------------------


@pytest.mark.parametrize("victim", [0, 1])
def test_index_edit_to_any_row_of_a_trailing_batch_is_detected(tmp_path, victim):
    store = open_store(tmp_path)
    _genesis(store)
    store.absorb_edit(
        _changes(store._path, EDIT_TWO), observer="obs", fact_signer=_signer("k")
    )
    log = log_path_for(store._path)
    records = deserialize_records(lines(log)[-1])
    assert len(records) >= 2
    victim_id = records[victim][1][0]
    db = store._path
    store.close()

    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE facts SET payload = '{\"doctored\": true}' WHERE id = ?",
        (victim_id,),
    )
    conn.commit()
    conn.close()

    report = audit_agreement(log)
    assert not report.ok
    bad = {c.name for c in report.divergences}
    assert "last-line" in bad

    # The open path answers the same divergence with a rebuild from the log.
    reopened = open_store(tmp_path)
    assert audit_agreement(log).ok
    reopened.close()
