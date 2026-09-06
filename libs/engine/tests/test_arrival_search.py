"""Exact-prefix File FTS maintenance and bounded snapshot search."""

from __future__ import annotations

from pathlib import Path

import pytest
from atoms import Fact as AtomFact

from engine.arrival import ArrivalLog
from engine.arrival_contract import (
    Continuation,
    FactRequest,
    InvalidContinuation,
    Profile,
    ProjectionRequirement,
    SearchFieldSpec,
    SearchRequest,
    SearchStale,
    StoreDescriptor,
)
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_registry import BackendRegistry
from engine.arrival_search import SearchIndexSyncError, sync_search_index
from engine.arrival_store import ArrivalStore
from engine.residence import index_path_for
from engine.search_fields import EXTRACTION_VERSION
from engine.vertex_reader import _extract_field


def _target(tmp_path: Path, keys, signer) -> tuple[ArrivalLog, Path, StoreDescriptor]:
    log = ArrivalLog.mint(
        tmp_path / "search.arrival", observer="kyle", signer=signer, key=keys.public
    )
    database = index_path_for(log.path)
    store = ArrivalStore(
        path=database,
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    try:
        store.append(AtomFact.of("note", "kyle", body="alpha alpha"))
        store.append(AtomFact.of("note", "kyle", body="beta"))
        store.append(AtomFact.of("note", "kyle", body="alpha distant"))
    finally:
        store.close()
    return log, database, StoreDescriptor(
        backend="file", location=str(log.path), lineage=log.lineage(), role=Profile.AUTHORITY
    )


def _spec() -> SearchFieldSpec:
    return SearchFieldSpec.from_fields(
        {"note": ("body",)}, normalization_version=EXTRACTION_VERSION
    )


def _append_and_project(log: ArrivalLog, database: Path, signer, text: str) -> None:
    store = ArrivalStore(
        path=database,
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    try:
        store.append(AtomFact.of("note", "kyle", body=text))
    finally:
        store.close()


def test_file_search_builds_exact_head_corpus_and_refuses_newer_head(tmp_path, keys, signer):
    log, database, descriptor = _target(tmp_path, keys, signer)
    registry = BackendRegistry.with_builtin_backends()
    spec = _spec()
    built = sync_search_index(registry, descriptor, spec)
    assert built.target == built.coverage_after.through
    assert built.coverage_after.fields_hash == spec.fields_hash

    captured = FileLedger(log).head()
    query = FileQuery(database)
    snapshot = query.open_snapshot(
        captured_head=captured, requirement=ProjectionRequirement.CURRENT
    )
    try:
        page = snapshot.search(SearchRequest("alpha", spec.fields_hash, limit=1))
        assert len(page.matches) == 1
        assert page.total_matches == 2 and page.truncated is True
        assert isinstance(page.matches[0].rank, float)
        assert page.ranking_through == captured
        full = snapshot.search(SearchRequest("alpha", spec.fields_hash, limit=50))
        assert len(full.matches) == 2 and full.truncated is False
    finally:
        snapshot.close()

    _append_and_project(log, database, signer, "alpha future alpha")
    newer = FileLedger(log).head()
    old = query.open_snapshot(captured_head=captured, requirement=ProjectionRequirement.CURRENT)
    try:
        assert old.search(SearchRequest("alpha", spec.fields_hash)).ranking_through == captured
    finally:
        old.close()
    latest = query.open_snapshot(captured_head=newer, requirement=ProjectionRequirement.CURRENT)
    try:
        with pytest.raises(SearchStale, match="exactly match"):
            latest.search(SearchRequest("alpha", spec.fields_hash))
    finally:
        latest.close()
    refreshed = sync_search_index(registry, descriptor, spec)
    assert refreshed.coverage_after.through == newer
    latest = query.open_snapshot(captured_head=newer, requirement=ProjectionRequirement.CURRENT)
    try:
        refreshed_page = latest.search(SearchRequest("alpha", spec.fields_hash))
        assert refreshed_page.total_matches == 3
        assert refreshed_page.ranking_through == newer
    finally:
        latest.close()
        query.close()


def test_search_fields_hash_and_failed_build_retain_explicit_coverage(
    tmp_path, keys, signer, monkeypatch
):
    log, database, descriptor = _target(tmp_path, keys, signer)
    registry = BackendRegistry.with_builtin_backends()
    spec = _spec()
    first = sync_search_index(registry, descriptor, spec)
    wrong = SearchFieldSpec.from_fields(
        {"note": ("other",)}, normalization_version=EXTRACTION_VERSION
    )
    snapshot = FileQuery(database).open_snapshot(
        captured_head=first.target,
        requirement=ProjectionRequirement.CURRENT,
    )
    try:
        with pytest.raises(SearchStale, match="different declared fields"):
            snapshot.search(SearchRequest("alpha", wrong.fields_hash))
    finally:
        snapshot.close()

    def fail_extract(_payload, _field):
        raise RuntimeError("injected extraction failure")

    monkeypatch.setattr("engine.search_fields.extract_field_text", fail_extract)
    with pytest.raises(SearchIndexSyncError) as raised:
        sync_search_index(registry, descriptor, spec)
    assert raised.value.coverage_before is not None
    assert raised.value.observed_after == raised.value.coverage_before

    snapshot = FileQuery(database).open_snapshot(
        captured_head=first.target,
        requirement=ProjectionRequirement.CURRENT,
    )
    try:
        assert snapshot.search(SearchRequest("alpha", spec.fields_hash)).total_matches == 2
    finally:
        snapshot.close()


def test_search_rebuild_invalidates_fact_continuations_by_schema_generation(
    tmp_path, keys, signer
):
    log, database, descriptor = _target(tmp_path, keys, signer)
    head = FileLedger(log).head()
    query = FileQuery(database)
    request = FactRequest(limit=1, order="oldest")
    snapshot = query.open_snapshot(
        captured_head=head, requirement=ProjectionRequirement.CURRENT
    )
    try:
        page = snapshot.facts(request)
        assert page.cursor is not None
        token = Continuation(
            head, head, request, page.cursor, snapshot.view_generation
        )
    finally:
        snapshot.close()

    sync_search_index(BackendRegistry.with_builtin_backends(), descriptor, _spec())
    try:
        with pytest.raises(InvalidContinuation, match="view changed"):
            query.open_snapshot(
                captured_head=head,
                requirement=ProjectionRequirement.CURRENT,
                continuation=token,
            )
    finally:
        query.close()


def test_search_field_text_preserves_legacy_dot_path_list_and_mapping_semantics():
    payload = {
        "nested": {"title": "needle"},
        "items": ["first", {"text": "second"}, 3, {"other": "ignored"}],
        "object": {"answer": 42},
        "number": 3,
        "null": None,
    }
    expected = {
        "nested.title": "needle",
        "items": "first second",
        "object": '{"answer": 42}',
        "number": "3",
        "null": "",
        "missing.path": "",
    }
    from engine.search_fields import extract_field_text

    for field, text in expected.items():
        assert extract_field_text(payload, field) == text
        assert _extract_field(payload, field) == text
