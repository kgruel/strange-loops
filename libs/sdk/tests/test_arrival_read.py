"""Descriptor-first SDK reads use one attested, bounded engine snapshot."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_batch, body_of_fact_row
from engine.arrival_contract import (
    Continuation,
    DeclarationAnchor,
    Fact,
    FactCursor,
    FactPage,
    FactRequest,
    Head,
    InvalidContinuation,
    ProjectionRequirement,
    ReadBasis,
    Summary,
    Tick,
    UnknownBackend,
)
from engine.declaration import RuntimeEpoch
from lang import genesis_payload, parse_vertex, parse_vertex_file

from sdk import (
    FactLookupResult,
    SdkValueError,
    TargetUnsupported,
    TickReadResult,
    emit_fact,
    init_vertex,
    read_fact_by_id,
    read_facts,
    read_state,
    read_summary,
    read_ticks,
    read_timeline,
    resolve_entity,
    search_facts,
    sync_target,
)
from sdk.errors import ArrivalRefusal


@pytest.fixture
def arrival_vertex(tmp_path: Path) -> Path:
    path = tmp_path / "arrival.vertex"
    path.write_text(
        'name "arrival"\n'
        'store "svc://tenant//ledger?q=a%2Fb" backend="remote" '
        'lineage="physical-lineage" role="replica"\n'
        'loops { item { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    return path


class _Snapshot:
    def __init__(self, vertex: Path, continuation: Continuation | None = None) -> None:
        self.bound_request = continuation.request if continuation is not None else None
        self.requests: list[FactRequest] = []
        ast = parse_vertex_file(vertex)
        self.genesis = Fact(
            id="decl-lineage",
            kind="_decl.genesis",
            ts=1.0,
            observer="system",
            origin="test",
            payload=genesis_payload(ast),
            arrival_ordinal=0,
            arrival_seq=0,
        )
        self.fact = Fact(
            id="01FACT",
            kind="item",
            ts=2.0,
            observer="alice",
            origin="test",
            payload={"title": "bounded"},
            arrival_ordinal=1,
            arrival_seq=0,
            payload_text=' { "title": "bounded" } ',
            signature="fact-signature",
        )

    @property
    def declaration_anchor(self) -> DeclarationAnchor:
        return DeclarationAnchor(own_lineage="decl-lineage", genesis=self.genesis)

    def facts(self, request: FactRequest) -> FactPage:
        self.requests.append(request)
        if self.bound_request is not None and request != self.bound_request:
            raise InvalidContinuation(
                "continuation request does not match this facts request"
            )
        available = (self.genesis, self.fact)
        if request.fact_id is not None:
            matches = tuple(
                fact
                for fact in available
                if fact.id.startswith(request.fact_id)
                and (request.include_internal or not fact.kind.startswith("_decl."))
            )
            return FactPage(items=matches, cursor=None, truncated=False, order=request.order)
        if request.limit is None and request.include_internal:
            matches = available
            if request.kind is not None:
                matches = tuple(
                    fact
                    for fact in matches
                    if fact.kind == request.kind
                    or fact.kind.startswith(request.kind + ".")
                )
            return FactPage(
                items=matches, cursor=None, truncated=False, order=request.order
            )
        return FactPage(
            items=(self.fact,),
            cursor=FactCursor(1, 0, self.fact.id),
            truncated=True,
            order=request.order,
        )

    def ticks(self, _request: Any) -> tuple[Tick, ...]:
        return (
            Tick(
                id="01TICK",
                name="daily",
                ts=3.0,
                since=2.0,
                origin="test",
                payload={"count": 1},
                arrival_ordinal=2,
                arrival_seq=0,
                payload_text=' { "count": 1 } ',
                prev_hash="previous-tick-hash",
                window_start="window-start-id",
                fact_cursor="01FACT",
                window_hash="window-hash",
                signature="tick-signature",
            ),
        )

    def summary(self, _request: Any) -> Summary:
        return Summary(
            fact_total=1,
            tick_total=1,
            signed_count=0,
            unsigned_count=1,
            fact_kinds={"item": {"count": 1, "earliest": 2.0, "latest": 2.0}},
            tick_names={"daily": {"count": 1, "earliest": 3.0, "latest": 3.0}},
        )


@dataclass
class _Opened:
    snapshot: _Snapshot
    basis: ReadBasis
    closed: bool = False

    def runtime_epoch(self) -> RuntimeEpoch:
        return RuntimeEpoch("strict", None)

    def continuation(self, request: FactRequest, page: FactPage) -> Continuation | None:
        if page.cursor is None or self.basis.projected_through is None:
            return None
        return Continuation(
            captured_head=self.basis.captured_head,
            projected_through=self.basis.projected_through,
            request=request,
            cursor=page.cursor,
            view_generation=self.basis.view_generation,
        )

    def close(self) -> None:
        self.closed = True


def test_descriptor_reads_share_typed_basis_and_close(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )
    opened: list[_Opened] = []
    calls: list[tuple[Any, Any, ProjectionRequirement, Continuation | None]] = []
    registry = object()

    def fake_open_read(
        actual_registry: Any,
        descriptor: Any,
        *,
        requirement: ProjectionRequirement,
        continuation: Continuation | None = None,
    ) -> _Opened:
        calls.append((actual_registry, descriptor, requirement, continuation))
        result = _Opened(_Snapshot(arrival_vertex), basis)
        opened.append(result)
        return result

    monkeypatch.setattr("engine.arrival_consumer.open_read", fake_open_read)
    monkeypatch.setattr(
        "sdk.read.resolve_target",
        lambda _target: pytest.fail("Arrival read fell through to legacy target probing"),
    )

    summary = read_summary(arrival_vertex, registry=registry)  # type: ignore[arg-type]
    page = read_facts(arrival_vertex, limit=1, registry=registry)  # type: ignore[arg-type]
    ticks = read_ticks(arrival_vertex, registry=registry)  # type: ignore[arg-type]
    lookup = read_fact_by_id(arrival_vertex, "01FACT", registry=registry)  # type: ignore[arg-type]
    state = read_state(arrival_vertex, registry=registry)  # type: ignore[arg-type]

    assert summary.read_path == page.read_path == state.read_path == "arrival"
    assert summary.basis == page.basis == ticks.basis == lookup.basis == state.basis == basis
    assert summary.canonical_mode is None
    assert summary.canonical_path is None
    assert summary.index_path is None
    assert summary.unfolded_kinds == []
    assert page.items[0]["arrival_ordinal"] == 1
    assert isinstance(page.next_cursor, Continuation)
    assert isinstance(ticks, TickReadResult)
    assert ticks.items[0]["name"] == "daily"
    assert isinstance(lookup, FactLookupResult)
    assert lookup.fact is not None and lookup.fact["id"] == "01FACT"
    assert state.sections["item"]["items"][0]["title"] == "bounded"
    assert state.generation["lineage"] == "decl-lineage"
    assert state.generation["runtime_epoch"] == {
        "mode": "strict", "anchor_ordinal": None
    }
    assert all(call[0] is registry for call in calls)
    assert all(call[2] is ProjectionRequirement.CURRENT for call in calls)
    assert all(item.closed for item in opened)
    assert all(call[1].location == "svc://tenant//ledger?q=a%2Fb" for call in calls)
    assert sum(
        request.kind == "_decl"
        for item in opened
        for request in item.snapshot.requests
    ) == 4


def test_arrival_fresh_epoch_filters_runtime_state_but_not_history_reads(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )

    class _FreshOpened(_Opened):
        def runtime_epoch(self) -> RuntimeEpoch:
            return RuntimeEpoch("fresh", 1)

    monkeypatch.setattr(
        "engine.arrival_consumer.open_read",
        lambda *_args, **_kwargs: _FreshOpened(_Snapshot(arrival_vertex), basis),
    )

    state = read_state(arrival_vertex, registry=object())  # type: ignore[arg-type]
    summary = read_summary(arrival_vertex, registry=object())  # type: ignore[arg-type]

    assert state.sections["item"]["items"] == []
    assert state.generation["runtime_epoch"] == {
        "mode": "fresh", "anchor_ordinal": 1
    }
    assert summary.fact_total == 1


def test_arrival_fact_lookup_keeps_internal_namespace_hidden(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read",
        lambda *_args, **_kwargs: _Opened(_Snapshot(arrival_vertex), basis),
    )

    result = read_fact_by_id(
        arrival_vertex, "decl-lineage", registry=object()  # type: ignore[arg-type]
    )

    assert result.basis == basis
    assert result.fact is None


def test_arrival_continuation_is_passed_back_to_engine(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )
    seen: list[Continuation | None] = []

    def fake_open_read(
        _registry: Any,
        _descriptor: Any,
        *,
        requirement: ProjectionRequirement,
        continuation: Continuation | None = None,
    ) -> _Opened:
        assert requirement is ProjectionRequirement.CURRENT
        seen.append(continuation)
        return _Opened(_Snapshot(arrival_vertex, continuation), basis)

    monkeypatch.setattr("engine.arrival_consumer.open_read", fake_open_read)
    first = read_facts(arrival_vertex, limit=1, registry=object())  # type: ignore[arg-type]
    assert isinstance(first.next_cursor, Continuation)
    read_facts(
        arrival_vertex,
        limit=1,
        before=first.next_cursor,
        registry=object(),  # type: ignore[arg-type]
    )
    assert seen == [None, first.next_cursor]


def test_arrival_page_dict_does_not_serialize_engine_continuation(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read",
        lambda *_args, **_kwargs: _Opened(_Snapshot(arrival_vertex), basis),
    )

    result = read_facts(arrival_vertex, limit=1, registry=object())  # type: ignore[arg-type]
    serialized = result.as_dict()

    assert isinstance(result.next_cursor, Continuation)
    assert serialized["next_cursor"] is None
    assert serialized["has_continuation"] is True
    assert "request" not in serialized
    assert "cursor" not in serialized


def test_arrival_state_uses_snapshot_declaration_not_current_file(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored_snapshot = _Snapshot(arrival_vertex)
    arrival_vertex.write_text(
        'name "arrival"\n'
        'store "svc://tenant//ledger?q=a%2Fb" backend="remote" '
        'lineage="physical-lineage" role="replica"\n'
        'loops { edited_after_genesis { fold { total "count" } } }\n',
        encoding="utf-8",
    )
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )
    opened = _Opened(stored_snapshot, basis)
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read",
        lambda *_args, **_kwargs: opened,
    )

    state = read_state(arrival_vertex, registry=object())  # type: ignore[arg-type]

    assert "item" in state.sections
    assert "edited_after_genesis" not in state.sections
    assert opened.closed is True


def test_arrival_read_closes_opened_snapshot_when_query_refuses(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )
    opened = _Opened(_Snapshot(arrival_vertex), basis)

    def refuse_summary(_request: Any) -> Summary:
        raise RuntimeError("query refused")

    monkeypatch.setattr(opened.snapshot, "summary", refuse_summary)
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read",
        lambda *_args, **_kwargs: opened,
    )

    with pytest.raises(RuntimeError, match="query refused"):
        read_summary(arrival_vertex, registry=object())  # type: ignore[arg-type]
    assert opened.closed is True


def test_arrival_sync_materializes_attested_projection_for_current_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    log_path = tmp_path / "source.arrival"

    def signer(_observer: str, commitment: str) -> str:
        return "test-signature:" + commitment

    log = ArrivalLog.mint(
        log_path,
        observer="alice",
        signer=signer,
        key=base64.b64encode(b"k" * 32).decode(),
        at=1.0,
    )
    vertex = tmp_path / "source.vertex"
    vertex.write_text(
        f'name "source"\nstore "{log_path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        'loops { note { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    declaration = json.dumps(genesis_payload(parse_vertex_file(vertex)))
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "alice",
                "test",
                declaration,
                None,
            )
        ),
        observer="alice",
        origin="test",
        at=2.0,
        signer=signer,
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                "fact-1",
                "note",
                3.0,
                "alice",
                "test",
                json.dumps({"title": "projected"}),
                None,
            )
        ),
        observer="alice",
        origin="test",
        at=3.0,
        signer=signer,
    )
    physical_before = log_path.read_bytes()

    synced = sync_target(vertex)

    assert synced.schema == "loops.sdk/sync-result/v2"
    assert synced.read_path == "arrival"
    assert synced.status == "caught-up"
    assert synced.store is not None and synced.store.backend == "file"
    assert synced.projected_before is None
    assert synced.projected_after == synced.target == synced.captured_head
    assert synced.view_generation is not None
    assert synced.changed is True
    assert synced.rebuilt is False
    assert synced.indexed_facts is None
    assert synced.agreement is True
    assert log_path.read_bytes() == physical_before

    current = read_summary(vertex)
    assert current.read_path == "arrival"
    assert current.fact_total == 1
    assert current.basis is not None
    assert current.basis.projected_through == synced.projected_after

    repeated = sync_target(vertex)
    assert repeated.status == "current"
    assert repeated.changed is False
    assert repeated.projected_before == repeated.projected_after


def test_snapshot_declaration_that_becomes_aggregate_refuses_partial_read(
    arrival_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _Snapshot(arrival_vertex)
    aggregate_ast = parse_vertex('name "arrival"\ndiscover "members/*.vertex"\n')
    snapshot.genesis = Fact(
        id="decl-lineage",
        kind="_decl.genesis",
        ts=1.0,
        observer="system",
        origin="test",
        payload=genesis_payload(aggregate_ast),
        arrival_ordinal=0,
        arrival_seq=0,
    )
    basis = ReadBasis(
        lineage="physical-lineage",
        captured_head=Head("physical-lineage", 2, "hash-2"),
        projected_through=Head("physical-lineage", 2, "hash-2"),
        view_generation="projection-1",
    )
    opened = _Opened(snapshot, basis)
    monkeypatch.setattr(
        "engine.arrival_consumer.open_read",
        lambda *_args, **_kwargs: opened,
    )

    with pytest.raises(TargetUnsupported, match="bounded Arrival declaration is an aggregate"):
        read_facts(arrival_vertex, registry=object())  # type: ignore[arg-type]
    assert opened.closed is True


@pytest.mark.parametrize(
    "invoke",
    [
        read_facts,
        read_ticks,
        lambda path: read_fact_by_id(path, "01FACT"),
        lambda path: search_facts(path, "term"),
        lambda path: resolve_entity(path, "item", "id", "1"),
        sync_target,
    ],
)
def test_legacy_aggregate_refuses_descriptor_backed_member(
    tmp_path: Path, invoke: Any
) -> None:
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store "opaque:member" backend="remote" lineage="lin-1" role="replica"\n'
        'loops { item { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    parent = tmp_path / "parent.vertex"
    parent.write_text(
        f'name "parent"\ncombine {{ vertex "{child}" as="child" }}\n',
        encoding="utf-8",
    )

    with pytest.raises(TargetUnsupported, match="descriptor-backed member"):
        invoke(parent)


@pytest.mark.parametrize("invoke", [read_summary, read_state, read_timeline])
def test_descriptor_aggregate_preserves_registered_backend_refusal(
    tmp_path: Path, invoke: Any
) -> None:
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store "opaque:member" backend="remote" lineage="lin-1" role="replica"\n'
        'loops { item { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    parent = tmp_path / "parent.vertex"
    parent.write_text(
        f'name "parent"\ncombine {{ vertex "{child}" as="child" }}\n',
        encoding="utf-8",
    )

    with pytest.raises(UnknownBackend, match="backend 'remote'"):
        invoke(parent)


def test_nested_legacy_aggregate_refuses_descriptor_backed_descendant(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child.vertex"
    child.write_text(
        'name "child"\n'
        'store "opaque:member" backend="remote" lineage="lin-1" role="replica"\n'
        'loops { item { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    middle = tmp_path / "middle.vertex"
    middle.write_text(
        f'name "middle"\ncombine {{ vertex "{child}" as="child" }}\n',
        encoding="utf-8",
    )
    root = tmp_path / "root.vertex"
    root.write_text(
        f'name "root"\ncombine {{ vertex "{middle}" as="middle" }}\n',
        encoding="utf-8",
    )

    with pytest.raises(UnknownBackend, match="backend 'remote'"):
        read_summary(root)


def test_arrival_search_refuses_open_failure_without_legacy_fallback(
    arrival_vertex: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sdk.read.resolve_target",
        lambda _target: pytest.fail("explicit descriptor fell through to legacy path"),
    )

    with pytest.raises(ArrivalRefusal) as raised:
        search_facts(arrival_vertex, "term")
    assert raised.value.source_type == "UnknownBackend"



def test_sdk_arrival_fact_pagination_hard_bounds_packed_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK continuations retain every row when a single wire batch spans pages."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    vertex = tmp_path / "page.vertex"
    initialized = init_vertex(vertex, store_type="arrival", observer="kyle")
    log = ArrivalLog(vertex.parent / str(initialized.store_path))
    log.append(
        "batch",
        body_of_batch(
            [
                ("page-0", "note", 10.0, "kyle", "", json.dumps({"n": 0})),
                ("page-1", "note", 11.0, "kyle", "", json.dumps({"n": 1})),
                ("page-2", "note", 12.0, "kyle", "", json.dumps({"n": 2})),
            ]
        ),
        observer="kyle",
        at=12.0,
    )
    sync_target(vertex)

    first = read_facts(vertex, limit=1, order="oldest")
    assert [item["id"] for item in first.items] == ["page-0"]
    assert first.truncated is True and isinstance(first.next_cursor, Continuation)
    token = first.next_cursor
    original_basis = first.basis
    assert original_basis is not None
    assert token.captured_head == original_basis.captured_head
    assert token.projected_through == original_basis.projected_through

    log.append(
        "batch",
        body_of_batch(
            [
                ("later-0", "note", 20.0, "kyle", "", json.dumps({"n": 3})),
                ("later-1", "note", 21.0, "kyle", "", json.dumps({"n": 4})),
            ]
        ),
        observer="kyle",
        at=21.0,
    )
    advanced = sync_target(vertex)
    assert advanced.captured_head.ordinal > original_basis.captured_head.ordinal
    assert advanced.projected_after.ordinal > original_basis.projected_through.ordinal

    second = read_facts(vertex, limit=1, order="oldest", after=token)
    assert [item["id"] for item in second.items] == ["page-1"]
    assert second.truncated is True and isinstance(second.next_cursor, Continuation)
    third = read_facts(vertex, limit=1, order="oldest", after=second.next_cursor)
    assert [item["id"] for item in third.items] == ["page-2"]
    assert third.truncated is False and third.next_cursor is None
    assert third.basis is not None and third.basis == original_basis

    current = read_facts(vertex, limit=10, order="oldest")
    assert [item["id"] for item in current.items] == [
        "page-0",
        "page-1",
        "page-2",
        "later-0",
        "later-1",
    ]


def test_sdk_arrival_fact_lookup_accepts_literal_arbitrary_id_prefixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    vertex = tmp_path / "lookup.vertex"
    init_vertex(vertex, store_type="arrival", observer="kyle")
    fact_ids = (
        "exact",
        "exact-long",
        "unicode-é",
        "tilde-~",
        "percent-%",
        "underscore-_",
        "bracket-[",
        "nul-\0tail",
        "amb-é",
        "amb-~",
    )
    for fact_id in fact_ids:
        receipt = emit_fact(
            vertex,
            "item",
            {"name": fact_id},
            observer="kyle",
            id_override=fact_id,
        )
        assert receipt.id == fact_id

    exact = read_fact_by_id(vertex, "exact")
    assert exact.fact is not None and exact.fact["id"] == "exact"
    for prefix, expected in (
        ("unicode-", "unicode-é"),
        ("tilde-", "tilde-~"),
        ("percent-", "percent-%"),
        ("underscore-", "underscore-_"),
        ("bracket-", "bracket-["),
        ("nul-", "nul-\0tail"),
    ):
        found = read_fact_by_id(vertex, prefix)
        assert found.fact is not None and found.fact["id"] == expected

    with pytest.raises(SdkValueError, match="Ambiguous ID prefix"):
        read_fact_by_id(vertex, "amb-")
