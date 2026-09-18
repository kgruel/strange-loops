"""SDK aggregate reads consume frozen per-occurrence Arrival snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from atoms import Fact as AtomFact
from custody.signing import ARRIVAL_DOMAIN
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import Fact, Head, ReadBasis
from engine.arrival_maintenance import sync_projection
from engine.arrival_registry import BackendRegistry, descriptor_for
from engine.arrival_store import ArrivalStore
from engine.declaration import RuntimeEpoch
from engine.residence import index_path_for
from lang import genesis_payload, parse_vertex, parse_vertex_file
from sign import ed25519

from sdk import read_state, read_summary, read_timeline, sync_target
from sdk.aggregate import AggregateRead, _Observation
from sdk.read import _aggregate_state_from


def _member(
    tmp_path: Path, name: str, *, latest: bool = False
) -> tuple[Path, ArrivalLog, object]:
    keypair = ed25519.load_or_generate(tmp_path / f"{name}-keys")

    def sign(_observer: str, commitment: str) -> str:
        return ed25519.sign(keypair, commitment.encode(), domain=ARRIVAL_DOMAIN)

    log = ArrivalLog.mint(
        tmp_path / f"{name}.arrival",
        observer="kyle",
        signer=sign,
        key=keypair.public_b64,
    )
    vertex = tmp_path / f"{name}.vertex"
    fold = 'value "latest"' if latest else 'n "count"'
    vertex.write_text(
        f'name "{name}"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        f'loops {{ note {{ fold {{ {fold} }} }} }}\n',
        encoding="utf-8",
    )
    store = ArrivalStore(
        path=index_path_for(log.path),
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=sign,
    )
    try:
        store.absorb_genesis(
            genesis_payload(parse_vertex_file(vertex))["documents"],
            observer="kyle",
            fact_signer=sign,
        )
    finally:
        store.close()
    return vertex, log, sign


def _append(
    vertex: Path,
    log: ArrivalLog,
    signer,
    *,
    fact_id: str,
    ts: float,
    observer: str = "alice",
    use_sdk_sync: bool = True,
) -> None:
    log.append(
        "fact",
        body_of_fact_row(
            (fact_id, "note", ts, observer, "fixture", json.dumps({"value": fact_id}), None)
        ),
        observer=observer,
        origin="fixture",
        at=ts,
        signer=signer,
    )
    if use_sdk_sync:
        sync_target(vertex)
    else:
        descriptor = descriptor_for(parse_vertex_file(vertex), vertex)
        assert descriptor is not None
        sync_projection(BackendRegistry.with_builtin_backends(), descriptor)


def test_two_arrival_members_compose_summary_state_timeline_and_basis(tmp_path: Path) -> None:
    left, left_log, left_signer = _member(tmp_path, "left")
    right, right_log, right_signer = _member(tmp_path, "right")
    _append(left, left_log, left_signer, fact_id="left-fact", ts=20.0)
    _append(right, right_log, right_signer, fact_id="right-fact", ts=10.0)
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine {\n'
        f'  vertex "{left.name}" as="left"\n'
        f'  vertex "{right.name}" as="right"\n'
        '}\n',
        encoding="utf-8",
    )

    summary = read_summary(root)
    state = read_state(root)
    timeline = read_timeline(root)

    assert summary.read_path == "arrival-aggregate"
    assert summary.basis is None and summary.store is None
    assert summary.fact_total == 2 and summary.kinds["note"]["count"] == 2
    assert len(summary.aggregate_members) == 2
    assert {item["basis"].lineage for item in summary.aggregate_members} == {
        left_log.lineage(),
        right_log.lineage(),
    }
    assert state.read_path == "arrival-aggregate"
    assert state.sections["note"]["n"] == 2
    assert [event.id for event in timeline.events] == ["right-fact", "left-fact"]
    assert len(timeline.aggregate_definitions) == 3
    json.dumps(summary.as_dict(), allow_nan=False)
    json.dumps(state.as_dict(), allow_nan=False)
    json.dumps(timeline.as_dict(), allow_nan=False)


def test_same_lineage_repeated_occurrences_are_not_deduplicated(tmp_path: Path) -> None:
    child, log, signer = _member(tmp_path, "child")
    _append(child, log, signer, fact_id="same-fact", ts=10.0)
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine {\n'
        f'  vertex "{child.name}" as="first"\n'
        f'  vertex "{child.name}" as="second"\n'
        '}\n',
        encoding="utf-8",
    )

    summary = read_summary(root)
    timeline = read_timeline(root)

    assert summary.fact_total == 2
    assert len(summary.aggregate_members) == 2
    assert {item["basis"].lineage for item in summary.aggregate_members} == {log.lineage()}
    assert [event.id for event in timeline.events] == ["same-fact", "same-fact"]


def test_effective_discover_and_own_overlay_shadow_cached_children(tmp_path: Path) -> None:
    cached_dir = tmp_path / "cached"
    effective_dir = tmp_path / "effective"
    cached_dir.mkdir()
    effective_dir.mkdir()
    cached, cached_log, cached_signer = _member(cached_dir, "cached")
    selected, selected_log, selected_signer = _member(effective_dir, "selected")
    _append(cached, cached_log, cached_signer, fact_id="cached-row", ts=1.0)
    _append(selected, selected_log, selected_signer, fact_id="selected-row", ts=2.0)

    keypair = ed25519.load_or_generate(tmp_path / "root-keys")

    def root_sign(_observer: str, commitment: str) -> str:
        return ed25519.sign(keypair, commitment.encode(), domain=ARRIVAL_DOMAIN)

    root_log = ArrivalLog.mint(
        tmp_path / "root.arrival",
        observer="kyle",
        signer=root_sign,
        key=keypair.public_b64,
    )
    root = tmp_path / "root.vertex"
    root.write_text(
        f'name "root"\nstore "{root_log.path}" backend="file" '
        f'lineage="{root_log.lineage()}" role="authority"\n'
        # The local cache no longer declares discovery.  The captured bounded
        # declaration still does, so routing must not fall back to a simple read.
        'loops { note { fold { n "count" } } }\n',
        encoding="utf-8",
    )
    effective = parse_vertex(
        f'name "root"\nstore "{root_log.path}" backend="file" '
        f'lineage="{root_log.lineage()}" role="authority"\n'
        'discover "effective/*.vertex"\nloops { note { fold { n "count" } } }\n',
        path=root,
    )
    store = ArrivalStore(
        path=index_path_for(root_log.path),
        log_path=root_log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=root_sign,
    )
    try:
        store.absorb_genesis(
            genesis_payload(effective)["documents"], observer="kyle", fact_signer=root_sign
        )
    finally:
        store.close()
    _append(root, root_log, root_sign, fact_id="root-row", ts=3.0, use_sdk_sync=False)

    summary = read_summary(root)
    state = read_state(root)
    timeline = read_timeline(root)

    assert summary.fact_total == 2
    assert [item["locator"] for item in summary.aggregate_members] == [
        str(root),
        str(selected),
    ]
    assert state.sections["note"]["n"] == 1  # own overlay shadows child note rows
    assert [event.id for event in timeline.events] == ["selected-row", "root-row"]


def test_unadopted_local_discover_does_not_change_descriptor_read_shape(tmp_path: Path) -> None:
    """A locator edit cannot activate membership before its declaration lands."""
    children = tmp_path / "children"
    children.mkdir()
    child, child_log, child_signer = _member(children, "child")
    _append(child, child_log, child_signer, fact_id="local-only-child", ts=1.0)

    keypair = ed25519.load_or_generate(tmp_path / "root-keys")

    def root_sign(_observer: str, commitment: str) -> str:
        return ed25519.sign(keypair, commitment.encode(), domain=ARRIVAL_DOMAIN)

    root_log = ArrivalLog.mint(
        tmp_path / "root.arrival",
        observer="kyle",
        signer=root_sign,
        key=keypair.public_b64,
    )
    root = tmp_path / "root.vertex"
    root.write_text(
        f'name "root"\nstore "{root_log.path}" backend="file" '
        f'lineage="{root_log.lineage()}" role="authority"\n'
        'discover "children/*.vertex"\nloops { note { fold { n "count" } } }\n',
        encoding="utf-8",
    )
    adopted = parse_vertex(
        f'name "root"\nstore "{root_log.path}" backend="file" '
        f'lineage="{root_log.lineage()}" role="authority"\n'
        'loops { note { fold { n "count" } } }\n',
        path=root,
    )
    store = ArrivalStore(
        path=index_path_for(root_log.path),
        log_path=root_log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=root_sign,
    )
    try:
        store.absorb_genesis(
            genesis_payload(adopted)["documents"], observer="kyle", fact_signer=root_sign
        )
    finally:
        store.close()
    _append(root, root_log, root_sign, fact_id="adopted-root", ts=2.0, use_sdk_sync=False)

    summary = read_summary(root)
    state = read_state(root)
    timeline = read_timeline(root)

    assert summary.read_path == "arrival"
    assert summary.fact_total == 1
    assert state.read_path == "arrival"
    assert state.sections["note"]["n"] == 1
    assert timeline.read_path == "arrival"
    assert [event.id for event in timeline.events] == ["adopted-root"]


def test_multi_member_timeline_uses_id_before_occurrence_for_equal_timestamps(
    tmp_path: Path,
) -> None:
    first, first_log, first_signer = _member(tmp_path, "first")
    second, second_log, second_signer = _member(tmp_path, "second")
    _append(first, first_log, first_signer, fact_id="z-id", ts=10.0)
    _append(second, second_log, second_signer, fact_id="a-id", ts=10.0)
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine {\n'
        f'  vertex "{first.name}" as="first"\n'
        f'  vertex "{second.name}" as="second"\n'
        '}\n',
        encoding="utf-8",
    )

    assert [event.id for event in read_timeline(root).events] == ["a-id", "z-id"]


def test_state_uses_multi_member_by_timestamp_when_second_member_is_empty(tmp_path: Path) -> None:
    first, first_log, first_signer = _member(tmp_path, "first", latest=True)
    second, _second_log, _second_signer = _member(tmp_path, "second", latest=True)
    _append(first, first_log, first_signer, fact_id="newer", ts=20.0)
    _append(first, first_log, first_signer, fact_id="backdated", ts=10.0)
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine {\n'
        f'  vertex "{first.name}" as="first"\n'
        f'  vertex "{second.name}" as="second"\n'
        '}\n',
        encoding="utf-8",
    )

    assert read_state(root).sections["note"]["value"] == 20.0


def test_state_keeps_structural_multi_member_axis_after_observer_filter(tmp_path: Path) -> None:
    first, first_log, first_signer = _member(tmp_path, "first", latest=True)
    second, second_log, second_signer = _member(tmp_path, "second", latest=True)
    _append(first, first_log, first_signer, fact_id="newer", ts=20.0, observer="alice")
    _append(first, first_log, first_signer, fact_id="backdated", ts=10.0, observer="alice")
    _append(second, second_log, second_signer, fact_id="other", ts=30.0, observer="bob")
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine {\n'
        f'  vertex "{first.name}" as="first"\n'
        f'  vertex "{second.name}" as="second"\n'
        '}\n',
        encoding="utf-8",
    )

    assert read_state(root, observer="alice").sections["note"]["value"] == 20.0


def test_mixed_explicit_arrival_and_implicit_storage_refuses(tmp_path: Path) -> None:
    arrival, _log, _signer = _member(tmp_path, "arrival")
    legacy = tmp_path / "legacy.vertex"
    legacy.write_text(
        'name "legacy"\nstore ".loops/data/legacy.db"\n'
        'loops { note { fold { n "count" } } }\n',
        encoding="utf-8",
    )
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine {\n'
        f'  vertex "{arrival.name}" as="arrival"\n'
        f'  vertex "{legacy.name}" as="legacy"\n'
        '}\n',
        encoding="utf-8",
    )

    from engine.arrival_aggregate import AggregateCaptureRefused

    with pytest.raises(AggregateCaptureRefused, match="without an explicit Arrival descriptor"):
        read_summary(root)


def test_aggregate_runtime_epoch_filters_only_fold_state_and_reports_member_basis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fresh_member = SimpleNamespace(
        identity=SimpleNamespace(path=(), locator="fresh", role="member"),
        runtime_epoch=RuntimeEpoch("fresh", 3),
        basis=ReadBasis(
            lineage="fresh-lineage",
            captured_head=Head("fresh-lineage", 4, "fresh-head"),
            projected_through=Head("fresh-lineage", 4, "fresh-head"),
            view_generation="fresh-view",
        ),
    )
    before = Fact(
        id="before",
        kind="note",
        ts=1.0,
        observer="alice",
        origin="test",
        payload={"value": "before"},
        arrival_ordinal=2,
        arrival_seq=0,
    )
    after = Fact(
        id="after",
        kind="note",
        ts=2.0,
        observer="alice",
        origin="test",
        payload={"value": "after"},
        arrival_ordinal=4,
        arrival_seq=0,
    )
    ordered = object.__new__(AggregateRead)
    ordered.capture = SimpleNamespace(definitions=(object(),))
    monkeypatch.setattr(ordered, "specs", lambda: {"note": object()})
    monkeypatch.setattr(
        ordered, "_eligible_members", lambda _definition, _kind: (fresh_member,)
    )
    monkeypatch.setattr(
        ordered,
        "observations",
        lambda *, observer=None: (
            _Observation(fresh_member, before),
            _Observation(fresh_member, after),
        ),
    )

    assert [fact.id for fact in ordered.ordered_for_kind("note")] == ["before", "after"]
    assert [
        fact.id for fact in ordered.ordered_for_kind("note", runtime_epoch_only=True)
    ] == ["after"]

    calls: dict[str, bool] = {}

    class _Spec:
        def replay(self, payloads):
            return {"count": len(payloads)}

    aggregate = SimpleNamespace(
        specs=lambda: {"note": _Spec()},
        ordered_for_kind=lambda _kind, *, observer, runtime_epoch_only: (
            calls.setdefault("runtime_epoch_only", runtime_epoch_only) and [after]
        ),
        root=SimpleNamespace(effective_declaration=SimpleNamespace(name="root")),
        capture=SimpleNamespace(members=(fresh_member,)),
        member_evidence=lambda: [],
        definition_evidence=lambda: [],
    )
    state = _aggregate_state_from(
        aggregate, tmp_path / "root.vertex", kind=None, observer=None, runtime_epoch_only=True
    )

    assert calls["runtime_epoch_only"] is True
    assert state.sections["note"]["count"] == 1
    assert state.generation["runtime_epochs"] == [
        {"lineage": "fresh-lineage", "mode": "fresh", "anchor_ordinal": 3}
    ]
