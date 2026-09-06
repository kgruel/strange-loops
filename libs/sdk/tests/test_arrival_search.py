"""Arrival SDK search uses only declared, exact-prefix FTS coverage."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from atoms import Fact as AtomFact
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import Head
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_store import ArrivalStore
from engine.residence import index_path_for
from lang import genesis_payload, parse_vertex_file

from sdk import search_facts, sync_search_index, sync_target
from sdk.errors import ArrivalRefusal


def _sign(_observer: str, commitment: str) -> str:
    return "test-signature:" + commitment


def _signed_fact_body(
    identifier: str,
    kind: str,
    ts: float,
    observer: str,
    origin: str,
    payload: str,
) -> dict:
    return body_of_fact_row(
        (
            identifier,
            kind,
            ts,
            observer,
            origin,
            payload,
            _sign(observer, fact_commitment_hash(kind, ts, observer, origin, payload)),
        )
    )


def _arrival_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ArrivalLog]:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    log = ArrivalLog.mint(
        tmp_path / "search.arrival",
        observer="kyle",
        signer=_sign,
        key=base64.b64encode(b"k" * 32).decode(),
        at=1.0,
    )
    vertex = tmp_path / "search.vertex"
    vertex.write_text(
        f'name "search"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        'loops { note { search "body" fold { items "collect" 20 } } }\n',
        encoding="utf-8",
    )
    store = ArrivalStore(
        path=index_path_for(log.path),
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=_sign,
    )
    try:
        store.absorb_genesis(
            genesis_payload(parse_vertex_file(vertex))["documents"],
            observer="kyle",
            fact_signer=_sign,
        )
        store.append(AtomFact.of("note", "kyle", body="alpha first"))
        store.append(AtomFact.of("note", "kyle", body="beta only"))
    finally:
        store.close()
    return vertex, log


def _append_and_project(vertex: Path, log: ArrivalLog, text: str) -> None:
    store = ArrivalStore(
        path=index_path_for(log.path),
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=_sign,
    )
    try:
        store.append(AtomFact.of("note", "kyle", body=text))
    finally:
        store.close()
    sync_target(vertex)


def _append_later_declaration(vertex: Path, log: ArrivalLog) -> None:
    documents = genesis_payload(parse_vertex_file(vertex))["documents"]
    note = next(document for document in documents if document["kind"] == "_decl.kind-defined")
    payload = dict(note["payload"])
    payload["order"] = 1
    edit = json.dumps(
        {
            "lineage": log.lineage(),
            "subject": "later",
            "change": "added",
            "payload": payload,
        }
    )
    log.append(
        "fact",
        _signed_fact_body(
            "later-declaration", "_decl.kind-defined", 9.0, "kyle", "test", edit
        ),
        observer="kyle",
        origin="test",
        at=9.0,
        signer=_sign,
    )


def test_arrival_search_requires_current_coverage_and_returns_basis_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _arrival_target(tmp_path, monkeypatch)
    with pytest.raises(ArrivalRefusal) as absent:
        search_facts(vertex, "alpha")
    assert absent.value.source_type == "SearchStale"

    indexed = sync_search_index(vertex)
    assert indexed.basis is not None
    assert indexed.target == indexed.basis.captured_head
    assert indexed.coverage_after is not None
    assert indexed.coverage_after["through"] == {
        "lineage": indexed.target.lineage,
        "ordinal": indexed.target.ordinal,
        "record_hash": indexed.target.record_hash,
    }
    json.dumps(indexed.as_dict(), allow_nan=False)

    result = search_facts(vertex, "alpha")
    assert result.read_path == "arrival"
    assert result.store is not None and result.store.backend == "file"
    assert result.basis is not None
    assert result.basis.captured_head == indexed.basis.captured_head
    # The explicit FTS DDL legitimately changes the query generation between
    # spec capture and the later read while preserving the same custody head.
    assert result.basis.view_generation != indexed.basis.view_generation
    assert result.total_matches == 1 and result.truncated is False
    assert [item.payload["body"] for item in result.matches] == ["alpha first"]
    assert result.ranking == "sqlite-fts5-bm25"
    assert result.ranking_through == result.basis.captured_head
    assert result.fields_hash == indexed.coverage_after["fields_hash"]
    json.dumps(result.as_dict(), allow_nan=False)

    _append_and_project(vertex, _log, "alpha stale")
    with pytest.raises(ArrivalRefusal) as stale:
        search_facts(vertex, "alpha")
    assert stale.value.source_type == "SearchStale"


def test_arrival_search_captured_snapshot_excludes_later_projected_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _arrival_target(tmp_path, monkeypatch)
    sync_search_index(vertex)
    original_open_snapshot = FileQuery.open_snapshot
    captured: list[Head] = []
    injected = False

    def append_before_snapshot(
        query: FileQuery,
        *,
        captured_head: Head,
        requirement,
        continuation=None,
    ):
        nonlocal injected
        if not injected:
            injected = True
            captured.append(captured_head)
            _append_and_project(vertex, log, "alpha later")
        return original_open_snapshot(
            query,
            captured_head=captured_head,
            requirement=requirement,
            continuation=continuation,
        )

    monkeypatch.setattr(FileQuery, "open_snapshot", append_before_snapshot)
    result = search_facts(vertex, "alpha")
    assert injected and captured == [result.basis.captured_head]
    assert [item.payload["body"] for item in result.matches] == ["alpha first"]
    assert FileLedger(log).head().ordinal > result.basis.captured_head.ordinal


def test_search_maintenance_keeps_first_declaration_capture_when_reopen_is_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _arrival_target(tmp_path, monkeypatch)
    initial = FileLedger(log).head()
    from engine import arrival_search as engine_search

    original_sync = engine_search.sync_search_index

    def advance_before_engine_reopen(registry, descriptor, spec, *, through=None):
        _append_later_declaration(vertex, log)
        sync_target(vertex)
        return original_sync(registry, descriptor, spec, through=through)

    monkeypatch.setattr(engine_search, "sync_search_index", advance_before_engine_reopen)
    result = sync_search_index(vertex)
    assert result.basis is not None and result.basis.captured_head == initial
    assert result.target == initial
    assert result.coordinator_captured_head is not None
    assert result.coordinator_captured_head.ordinal > initial.ordinal
    assert result.coverage_after is not None
    assert result.coverage_after["through"]["ordinal"] == initial.ordinal
