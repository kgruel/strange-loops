"""Complete fact history is one descriptor-first Arrival snapshot."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_batch, body_of_fact_row
from engine.arrival_contract import (
    DeclarationAnchor,
    Fact,
    FactCursor,
    FactPage,
    Head,
    NotSupported,
    ProjectionAbsent,
    ProjectionBehind,
    ReadBasis,
)
from engine.arrival_file_backend import (
    FileLedger,
    FileProjectionMaintenance,
    FileQuery,
    file_projection_path,
)
from engine.arrival_registry import BackendRegistry
from lang import genesis_payload, parse_vertex_file

from sdk import init_vertex, sync_target
from sdk.history import FactHistoryResult, read_all_facts
from sdk.types import SdkValueError, TargetUnsupported


@pytest.fixture(autouse=True)
def _isolated_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "XDG_STATE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "LOOPS_HOME",
    ):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))


@pytest.fixture
def arrival_vertex(tmp_path: Path) -> Path:
    vertex = tmp_path / "history.vertex"
    vertex.write_text(
        'name "history"\n'
        'store "opaque://tenant//original" backend="opaque" '
        'lineage="physical" role="replica"\n'
        'loops { note { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    return vertex


class _Snapshot:
    def __init__(
        self,
        vertex: Path,
        facts: tuple[Fact, ...],
        *,
        lineage: str = "physical",
        declaration_payload: dict[str, Any] | None = None,
        genesis_ordinal: int = 1,
    ) -> None:
        self.requests: list[Any] = []
        self._facts = facts
        self._genesis = Fact(
            id=lineage,
            kind="_decl.genesis",
            ts=1.0,
            observer="system",
            origin="fixture",
            payload=declaration_payload or genesis_payload(parse_vertex_file(vertex)),
            arrival_ordinal=genesis_ordinal,
            arrival_seq=0,
        )

    @property
    def declaration_anchor(self) -> DeclarationAnchor:
        return DeclarationAnchor(own_lineage=self._genesis.id, genesis=self._genesis)

    def facts(self, request: Any) -> FactPage:
        self.requests.append(request)
        if request.kind == "_decl":
            return FactPage((self._genesis,), None, False, request.order)
        selected = tuple(
            fact
            for fact in self._facts
            if (
                request.kind is None
                or fact.kind == request.kind
                or fact.kind.startswith(request.kind + ".")
            )
            and (request.observer is None or fact.observer == request.observer)
            and (request.include_internal or not fact.kind.startswith("_decl."))
        )
        if request.order == "newest":
            selected = tuple(reversed(selected))
        return FactPage(selected, None, False, request.order)


@dataclass
class _Opened:
    snapshot: _Snapshot
    basis: ReadBasis
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def _fact(identifier: str, ordinal: int, *, kind: str = "note", observer: str = "alice") -> Fact:
    return Fact(
        id=identifier,
        kind=kind,
        ts=float(ordinal),
        observer=observer,
        origin="fixture",
        payload={"id": identifier, "ordinal": ordinal},
        arrival_ordinal=ordinal,
        arrival_seq=0,
    )


def _current_open(vertex: Path, facts: tuple[Fact, ...]) -> _Opened:
    return _Opened(
        _Snapshot(vertex, facts),
        ReadBasis(
            lineage="physical",
            captured_head=Head("physical", 100, "captured"),
            projected_through=Head("physical", 100, "captured"),
            view_generation="fixture",
        ),
    )


def test_history_serialization_detaches_nested_payloads() -> None:
    result = FactHistoryResult(
        items=({"id": "one", "payload": {"nested": [{"value": "original"}]}},),
        item_count=1,
    )
    serialized = result.as_dict()
    serialized["items"][0]["payload"]["nested"][0]["value"] = "serialized-change"
    assert result.items[0]["payload"]["nested"] == [{"value": "original"}]

    result.items[0]["payload"]["nested"].append({"value": "retained-change"})
    assert serialized["items"][0]["payload"]["nested"] == [{"value": "serialized-change"}]
    assert json.loads(json.dumps(serialized, allow_nan=False)) == serialized


def test_history_is_unbounded_materialization_with_stable_body_and_basis(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # More than the normal page default, including rows that could have been
    # expanded from one packed Arrival record (same ordinal, distinct seq).
    facts = tuple(
        Fact(
            id=f"fact-{index}",
            kind="note",
            ts=float(index),
            observer="alice",
            origin="fixture",
            payload={"body": index},
            arrival_ordinal=2 if index < 3 else index,
            arrival_seq=index if index < 3 else 0,
        )
        for index in range(60)
    )
    opened = _current_open(arrival_vertex, facts)
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: opened)

    oldest = read_all_facts(arrival_vertex, order="oldest", registry=object())  # type: ignore[arg-type]
    assert oldest.basis == opened.basis
    assert oldest.item_count == 60 and oldest.complete is True
    assert [item["id"] for item in oldest.items] == [fact.id for fact in facts]
    assert oldest.items[1]["payload"] == {"body": 1}
    assert oldest.as_dict()["basis"]["captured_head"]["record_hash"] == "captured"
    user_requests = [
        request for request in opened.snapshot.requests if request.kind != "_decl"
    ]
    assert len(user_requests) == 1 and user_requests[0].limit is None

    newest_opened = _current_open(arrival_vertex, facts)
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read", lambda *_a, **_kw: newest_opened
    )
    newest = read_all_facts(arrival_vertex, order="newest", registry=object())  # type: ignore[arg-type]
    assert [item["id"] for item in newest.items] == [fact.id for fact in reversed(facts)]


def test_history_real_file_adapter_materializes_packed_and_separate_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex = tmp_path / "real.vertex"
    initialized = init_vertex(vertex, store_type="arrival", observer="kyle")
    log = ArrivalLog(vertex.parent / str(initialized.store_path))
    packed = [
        (f"packed-{index}", "note", float(index), "kyle", "fixture", json.dumps({"n": index}))
        for index in range(55)
    ]
    log.append("batch", body_of_batch(packed), observer="kyle", origin="fixture", at=55.0)
    log.append(
        "fact",
        body_of_fact_row(
            ("separate", "note", 99.0, "kyle", "fixture", json.dumps({"n": 99}), None)
        ),
        observer="kyle",
        origin="fixture",
        at=99.0,
    )
    sync_target(vertex)

    oldest = read_all_facts(vertex, order="oldest")
    newest = read_all_facts(vertex, order="newest")
    expected = [*(f"packed-{index}" for index in range(55)), "separate"]
    assert [item["id"] for item in oldest.items] == expected
    assert [item["id"] for item in newest.items] == list(reversed(expected))
    assert oldest.basis is not None
    assert oldest.basis.projected_through == oldest.basis.captured_head
    assert oldest.items[12]["payload"] == {"n": 12}
    assert oldest.item_count == 56 and oldest.complete


def test_history_filters_internal_visibility_and_empty_selection(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = (
        _fact("one", 2),
        _fact("two", 3, kind="note.child", observer="bob"),
        _fact("internal", 4, kind="_decl.review"),
    )
    opened = _current_open(arrival_vertex, facts)
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: opened)

    selected = read_all_facts(
        arrival_vertex, kind="note", observer="bob", order="oldest", registry=object()  # type: ignore[arg-type]
    )
    assert [item["id"] for item in selected.items] == ["two"]

    internal_opened = _current_open(arrival_vertex, facts)
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read", lambda *_a, **_kw: internal_opened
    )
    internal = read_all_facts(arrival_vertex, include_internal=True, registry=object())  # type: ignore[arg-type]
    assert {item["id"] for item in internal.items} == {"one", "two", "internal"}

    empty_opened = _current_open(arrival_vertex, facts)
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: empty_opened)
    empty = read_all_facts(arrival_vertex, kind="absent", registry=object())  # type: ignore[arg-type]
    assert empty.items == () and empty.item_count == 0 and empty.complete

    fresh_payload = {
        **genesis_payload(parse_vertex_file(arrival_vertex)),
        "protocol": 2,
        "runtime_epoch": "fresh-after-anchor-v1",
    }
    retained = _Opened(
        _Snapshot(
            arrival_vertex,
            (_fact("pre-epoch", 1), _fact("current", 3)),
            declaration_payload=fresh_payload,
            genesis_ordinal=2,
        ),
        _current_open(arrival_vertex, ()).basis,
    )
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: retained)
    history = read_all_facts(arrival_vertex, order="oldest", registry=object())  # type: ignore[arg-type]
    assert [item["id"] for item in history.items] == ["pre-epoch", "current"]


def test_history_keeps_resolved_descriptor_when_locator_changes(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = _current_open(arrival_vertex, (_fact("one", 2),))

    def open_original(_registry: Any, descriptor: Any, **_kwargs: Any) -> _Opened:
        assert descriptor.location == "opaque://tenant//original"
        arrival_vertex.write_text(
            'name "history"\nstore "legacy.db"\n', encoding="utf-8"
        )
        return opened

    monkeypatch.setattr("engine.arrival_consumer.open_read", open_original)
    result = read_all_facts(arrival_vertex, registry=object())  # type: ignore[arg-type]

    assert result.store is not None and result.store.location == "opaque://tenant//original"
    assert [item["id"] for item in result.items] == ["one"]
    assert opened.closed is True


@pytest.mark.parametrize("stage", ("declaration", "user"))
@pytest.mark.parametrize("fault", ("truncated", "cursor", "wrong-order"))
def test_history_refuses_incomplete_or_contradictory_pages_and_closes(
    arrival_vertex: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    fault: str,
) -> None:
    opened = _current_open(arrival_vertex, (_fact("one", 2),))
    original = opened.snapshot.facts

    def malformed(request: Any) -> FactPage:
        page = original(request)
        is_declaration = request.kind == "_decl"
        if (stage == "declaration") != is_declaration:
            return page
        if fault == "truncated":
            return FactPage(page.items, None, True, request.order)
        if fault == "cursor":
            return FactPage(page.items, FactCursor(2, 0, "one"), False, request.order)
        wrong_order = "oldest" if request.order == "newest" else "newest"
        return FactPage(page.items, None, False, wrong_order)

    monkeypatch.setattr(opened.snapshot, "facts", malformed)
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: opened)

    with pytest.raises(NotSupported):
        read_all_facts(arrival_vertex, registry=object())  # type: ignore[arg-type]
    assert opened.closed is True
    requested_kinds = [request.kind for request in opened.snapshot.requests]
    if stage == "declaration":
        assert requested_kinds == ["_decl"]
    else:
        assert requested_kinds == ["_decl", None]


def _real_history_target(tmp_path: Path) -> tuple[Path, ArrivalLog]:
    vertex = tmp_path / "history.vertex"
    initialized = init_vertex(vertex, store_type="arrival", observer="kyle")
    return vertex, ArrivalLog(vertex.parent / str(initialized.store_path))


def _append_real_fact(log: ArrivalLog, identifier: str, body: str, *, at: float) -> None:
    log.append(
        "fact",
        body_of_fact_row(
            (identifier, "item", at, "kyle", "fixture", json.dumps({"body": body}), None)
        ),
        observer="kyle",
        origin="fixture",
        at=at,
    )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"order": "sideways"},
        {"kind": 1},
        {"observer": 1},
        {"include_internal": 1},
    ),
)
def test_history_validates_request_before_opening(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read", lambda *_a, **_kw: pytest.fail("opened")
    )
    with pytest.raises(SdkValueError):
        read_all_facts(arrival_vertex, **kwargs)


def test_history_refuses_noncurrent_and_nonadopted_declarations_without_fallback(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sdk.read.resolve_target", lambda *_a: pytest.fail("legacy read"))
    stale = _current_open(arrival_vertex, ())
    stale.basis = ReadBasis(
        lineage="physical",
        captured_head=Head("physical", 100, "captured"),
        projected_through=Head("physical", 99, "previous"),
        view_generation="fixture",
    )
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: stale)
    with pytest.raises(ProjectionBehind):
        read_all_facts(arrival_vertex, registry=object())  # type: ignore[arg-type]
    assert stale.closed

    from engine.declaration import UnadoptedLineage

    class UnadoptedSnapshot(_Snapshot):
        @property
        def declaration_anchor(self) -> DeclarationAnchor:
            return DeclarationAnchor(own_lineage=None, genesis=None)

    unadopted = _Opened(
        UnadoptedSnapshot(arrival_vertex, ()), _current_open(arrival_vertex, ()).basis
    )
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: unadopted)
    with pytest.raises(UnadoptedLineage):
        read_all_facts(arrival_vertex, registry=object())  # type: ignore[arg-type]
    assert unadopted.closed


def test_history_refuses_unhistorized_and_effective_aggregate_without_fallback(
    arrival_vertex: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sdk.read.resolve_target", lambda *_a: pytest.fail("legacy read"))
    opened = _current_open(arrival_vertex, ())
    monkeypatch.setattr("engine.arrival_consumer.open_read", lambda *_a, **_kw: opened)
    monkeypatch.setattr(
        "sdk.history._arrival_declaration",
        lambda *_a, **_kw: (None, "unhistorized", (), "physical"),
    )
    with pytest.raises(NotSupported, match="adopted declaration"):
        read_all_facts(arrival_vertex, registry=object())  # type: ignore[arg-type]
    assert opened.closed and [request.kind for request in opened.snapshot.requests] == []

    aggregate = tmp_path / "aggregate.vertex"
    aggregate.write_text(
        'name "aggregate"\ncombine { vertex "child.vertex" as="child" }\n'
    )
    aggregate_opened = _current_open(
        arrival_vertex,
        (),
    )
    aggregate_opened.snapshot = _Snapshot(
        arrival_vertex,
        (),
        declaration_payload=genesis_payload(parse_vertex_file(aggregate)),
    )
    from sdk.read import _arrival_declaration

    monkeypatch.setattr("sdk.history._arrival_declaration", _arrival_declaration)
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read", lambda *_a, **_kw: aggregate_opened
    )
    with pytest.raises(TargetUnsupported, match="aggregate"):
        read_all_facts(arrival_vertex, registry=object())  # type: ignore[arg-type]
    assert aggregate_opened.closed


def test_history_real_file_projection_refusals_do_not_repair_custody(tmp_path: Path) -> None:
    vertex, log = _real_history_target(tmp_path)
    projection = file_projection_path(log.path)
    raw = log.path.read_bytes()
    projection.unlink()
    with pytest.raises(ProjectionAbsent):
        read_all_facts(vertex)
    assert not projection.exists() and log.path.read_bytes() == raw

    sync_target(vertex)
    _append_real_fact(log, "behind", "behind", at=2.0)
    raw = log.path.read_bytes()
    projection_bytes = projection.read_bytes()
    with pytest.raises(ProjectionBehind):
        read_all_facts(vertex)
    assert log.path.read_bytes() == raw and projection.read_bytes() == projection_bytes

    sync_target(vertex)
    raw = log.path.read_bytes()
    projection.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        read_all_facts(vertex)
    assert log.path.read_bytes() == raw and projection.read_bytes() == b"not sqlite"


def test_history_real_snapshot_excludes_projection_advanced_after_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _real_history_target(tmp_path)
    _append_real_fact(log, "before", "before body", at=2.0)
    sync_target(vertex)
    captured: list[Head] = []
    original_open_snapshot = FileQuery.open_snapshot

    def advance_before_snapshot(
        query: FileQuery, *, captured_head: Head, requirement: Any, continuation: Any = None
    ) -> Any:
        if not captured:
            captured.append(captured_head)
            _append_real_fact(log, "after", "after body", at=3.0)
            sync_target(vertex)
        return original_open_snapshot(
            query,
            captured_head=captured_head,
            requirement=requirement,
            continuation=continuation,
        )

    monkeypatch.setattr(FileQuery, "open_snapshot", advance_before_snapshot)
    result = read_all_facts(vertex, order="oldest")
    assert captured == [result.basis.captured_head]
    assert [item["id"] for item in result.items] == ["before"]
    assert [item["payload"]["body"] for item in result.items] == ["before body"]
    assert result.basis.projected_through == result.basis.captured_head
    assert result.basis.captured_head.ordinal < FileLedger(log).head().ordinal


def test_history_uses_injected_opaque_registry_and_closes_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locator = "opaque://tenant//history?projection=not-a-path"
    log_path = tmp_path / "opaque.arrival"
    calls: list[str] = []
    queries: list[FileQuery] = []
    registry = BackendRegistry()

    class TrackingQuery(FileQuery):
        closed = False

        def close(self) -> None:
            self.closed = True
            super().close()

    def open_opaque(descriptor: Any) -> tuple[FileLedger, FileQuery]:
        calls.append(descriptor.location)
        query = TrackingQuery(file_projection_path(log_path))
        queries.append(query)
        return FileLedger(ArrivalLog(log_path)), query

    registry.register(
        "opaque",
        open_opaque,
        maintenance_opener=lambda _descriptor: FileProjectionMaintenance(
            log_path, file_projection_path(log_path)
        ),
    )
    monkeypatch.setattr(
        BackendRegistry,
        "with_builtin_backends",
        classmethod(lambda _cls: pytest.fail("default registry used")),
    )
    vertex = tmp_path / "opaque.vertex"
    init_vertex(
        vertex,
        store_type="arrival",
        observer="kyle",
        backend="opaque",
        location=locator,
        registry=registry,
    )
    log = ArrivalLog(log_path)
    _append_real_fact(log, "opaque-fact", "opaque body", at=2.0)
    sync_target(vertex, registry=registry)
    calls.clear()
    queries.clear()

    result = read_all_facts(vertex, registry=registry)
    assert calls == [locator]
    assert result.store is not None and result.store.location == locator
    assert [item["id"] for item in result.items] == ["opaque-fact"]
    assert queries and all(query.closed for query in queries)


def test_history_never_falls_back_when_no_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "legacy.vertex"
    legacy.write_text('name "legacy"\nstore "legacy.db"\n', encoding="utf-8")
    monkeypatch.setattr(
        "sdk.history._arrival_descriptor", lambda _target: None
    )
    with pytest.raises(TargetUnsupported, match="explicit Arrival descriptor"):
        read_all_facts(legacy)
