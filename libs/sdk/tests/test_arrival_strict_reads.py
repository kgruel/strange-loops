"""Strict Arrival-only inventory and bounded metadata page contracts."""

from __future__ import annotations

import base64
import contextlib
import json
from pathlib import Path

import pytest
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import (
    DeclarationAnchor,
    Fact,
    FactPage,
    Head,
    ProjectionAbsent,
    ProjectionBehind,
    ReadBasis,
    Summary,
)
from engine.residence import index_path_for
from lang import genesis_payload, parse_vertex, parse_vertex_file, vertex_to_documents

from sdk import TargetUnsupported, emit_fact, init_vertex, read_facts, read_summary, sync_target
from sdk import read as read_module


def _isolate_runtime(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("LOOPS_HOME", str(root / "loops"))
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(root / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(root / "cache"))


def test_arrival_only_refuses_without_legacy_or_aggregate_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "legacy.vertex"
    legacy.write_text('name "legacy"\nstore ".loops/data/legacy.db"\n', encoding="utf-8")
    storeless = tmp_path / "storeless.vertex"
    storeless.write_text('name "storeless"\n', encoding="utf-8")
    aggregate = tmp_path / "aggregate.vertex"
    aggregate.write_text('name "aggregate"\ndiscover "members/*.vertex"\n', encoding="utf-8")
    bare = tmp_path / "bare.db"
    bare.write_bytes(b"")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        pytest.fail("strict Arrival route touched a legacy or aggregate helper")

    monkeypatch.setattr(read_module, "resolve_target", forbidden)
    monkeypatch.setattr(read_module, "_refuse_arrival_aggregate_members", forbidden)
    monkeypatch.setattr(read_module, "has_local_descriptor_aggregate", forbidden)
    monkeypatch.setattr(read_module, "_aggregate_summary", forbidden)
    monkeypatch.setattr(read_module, "open_aggregate_read", forbidden)

    for target in (legacy, storeless, aggregate, bare):
        with pytest.raises(TargetUnsupported):
            read_summary(target, require_arrival=True)
        with pytest.raises(TargetUnsupported):
            read_facts(target, require_arrival=True)


def test_strict_reads_keep_one_resolved_descriptor_after_locator_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_runtime(monkeypatch, tmp_path)
    vertex = tmp_path / "captured.vertex"
    init_vertex(vertex, name="captured", store_type="arrival", observer="alice")
    emit_fact(vertex, "item", {"value": 1}, observer="alice")
    original_locator = vertex.read_bytes()
    resolver = read_module._arrival_descriptor
    original_open = read_module._open_arrival_read
    resolutions: list[tuple[Path, object, object]] = []
    opened_resolutions: list[tuple[Path, object, object]] = []

    def capture_resolution(*args: object, **kwargs: object):
        resolved = resolver(*args, **kwargs)
        assert resolved is not None
        resolutions.append(resolved)
        return resolved

    @contextlib.contextmanager
    def replace_locator(
        resolved: tuple[Path, object, object], **kwargs: object
    ):
        opened_resolutions.append(resolved)
        vertex.write_text('name "replacement"\nstore "legacy.db"\n', encoding="utf-8")
        with original_open(resolved, **kwargs) as opened:
            yield opened

    def forbidden(*_args: object, **_kwargs: object) -> object:
        pytest.fail("strict read fell through to a legacy or aggregate route")

    monkeypatch.setattr(read_module, "_arrival_descriptor", capture_resolution)
    monkeypatch.setattr(read_module, "_open_arrival_read", replace_locator)
    monkeypatch.setattr(read_module, "resolve_target", forbidden)
    monkeypatch.setattr(read_module, "_refuse_arrival_aggregate_members", forbidden)
    monkeypatch.setattr(read_module, "has_local_descriptor_aggregate", forbidden)
    monkeypatch.setattr(read_module, "_aggregate_summary", forbidden)
    monkeypatch.setattr(read_module, "open_aggregate_read", forbidden)

    summary = read_summary(vertex, require_arrival=True)
    assert len(resolutions) == len(opened_resolutions) == 1
    assert opened_resolutions[0] is resolutions[0]
    assert summary.read_path == "arrival"
    assert summary.vertex_name == "captured"
    assert summary.runtime_epoch == {"mode": "strict", "anchor_ordinal": None}
    assert summary.store is not None
    assert summary.store.location == resolutions[0][2].location

    vertex.write_bytes(original_locator)
    page = read_facts(vertex, limit=5, order="newest", require_arrival=True)
    assert len(resolutions) == len(opened_resolutions) == 2
    assert opened_resolutions[1] is resolutions[1]
    assert page.read_path == "arrival"
    assert page.store == summary.store
    assert page.basis == summary.basis
    assert page.items and page.items[0]["payload"] == {"value": 1}


def test_metadata_only_preserves_arrival_envelopes_and_legacy_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_runtime(monkeypatch, tmp_path)
    vertex = tmp_path / "metadata.vertex"
    init_vertex(vertex, store_type="arrival", observer="alice")
    for value in range(3):
        emit_fact(vertex, "item", {"value": value}, observer="alice")

    default_page = read_facts(vertex, limit=2, order="newest")
    metadata_page = read_facts(
        vertex, limit=2, order="newest", require_arrival=True, metadata_only=True
    )
    expected = [
        {key: value for key, value in item.items() if key != "payload"}
        for item in default_page.items
    ]
    assert default_page.metadata_only is False
    assert all("payload" in item for item in default_page.items)
    assert default_page.truncated is True
    assert metadata_page.read_path == "arrival"
    assert metadata_page.items == expected
    assert metadata_page.basis == default_page.basis
    assert metadata_page.store == default_page.store
    assert metadata_page.order == default_page.order == "newest"
    assert metadata_page.truncated is True
    assert metadata_page.metadata_only is True
    assert all(
        {"id", "kind", "ts", "observer", "origin", "arrival_ordinal", "arrival_seq"}
        <= item.keys()
        for item in metadata_page.items
    )
    wire = metadata_page.as_dict()
    assert wire["metadata_only"] is True
    assert wire["basis"] is not None and wire["store"] is not None
    wire["items"][0]["id"] = "mutated-wire-id"
    assert metadata_page.items[0]["id"] == default_page.items[0]["id"]

    legacy = tmp_path / "legacy.vertex"
    init_vertex(legacy, store_type="sqlite", observer="alice")
    for value in range(3):
        emit_fact(legacy, "item", {"value": value}, observer="alice")
    legacy_summary = read_summary(legacy)
    legacy_default = read_facts(legacy, limit=2, order="newest")
    legacy_metadata = read_facts(legacy, limit=2, order="newest", metadata_only=True)
    assert legacy_summary.read_path == "legacy"
    assert legacy_summary.fact_total == 3
    assert legacy_summary.basis is legacy_summary.store is legacy_summary.runtime_epoch is None
    assert legacy_default.read_path == legacy_metadata.read_path == "legacy"
    assert legacy_default.truncated is legacy_metadata.truncated is True
    assert all("payload" in item for item in legacy_default.items)
    assert legacy_metadata.items == [
        {key: value for key, value in item.items() if key != "payload"}
        for item in legacy_default.items
    ]
    assert legacy_metadata.metadata_only is True


@pytest.mark.parametrize("reader", [read_summary, read_facts])
def test_arrival_only_refuses_missing_projection_without_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: object
) -> None:
    _isolate_runtime(monkeypatch, tmp_path)
    vertex = tmp_path / "missing-projection.vertex"
    initialized = init_vertex(vertex, store_type="arrival", observer="alice")
    assert initialized.store_path is not None
    projection = index_path_for(vertex.parent / initialized.store_path)
    assert projection.exists()
    projection.unlink()

    with pytest.raises(ProjectionAbsent):
        reader(vertex, require_arrival=True)  # type: ignore[operator]
    assert not projection.exists()


@pytest.mark.parametrize("reader", [read_summary, read_facts])
def test_strict_reads_refuse_behind_projection_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: object
) -> None:
    _isolate_runtime(monkeypatch, tmp_path)
    vertex = tmp_path / "behind-projection.vertex"
    initialized = init_vertex(vertex, store_type="arrival", observer="alice")
    assert initialized.store_path is not None
    log = ArrivalLog(vertex.parent / initialized.store_path)
    projection = index_path_for(log.path)
    log.append(
        "fact",
        body_of_fact_row(
            ("behind", "item", 2.0, "alice", "test", json.dumps({"value": 2}), None)
        ),
        observer="alice",
        origin="test",
        at=2.0,
    )
    custody_before = log.path.read_bytes()
    projection_before = projection.read_bytes()

    with pytest.raises(ProjectionBehind):
        reader(vertex, require_arrival=True)  # type: ignore[operator]

    assert log.path.read_bytes() == custody_before
    assert projection.read_bytes() == projection_before


def test_strict_reads_refuse_captured_aggregate_without_legacy_or_aggregate_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_runtime(monkeypatch, tmp_path)
    vertex = tmp_path / "ordinary-locator.vertex"
    init_vertex(vertex, store_type="arrival", observer="alice")
    aggregate = parse_vertex('name "captured-aggregate"\ndiscover "members/*.vertex"\n')
    genesis = Fact(
        id="captured-lineage",
        kind="_decl.genesis",
        ts=1.0,
        observer="system",
        origin="test",
        payload=genesis_payload(aggregate),
        arrival_ordinal=1,
        arrival_seq=0,
    )

    class CapturedAggregateSnapshot:
        declaration_anchor = DeclarationAnchor(own_lineage=genesis.id, genesis=genesis)

        def facts(self, _request: object) -> FactPage:
            return FactPage((genesis,), None, False, "oldest")

        def summary(self, _request: object) -> Summary:
            return Summary(0, 0, 0, 0, {}, {})

    class CapturedAggregateOpened:
        def __init__(self) -> None:
            self.snapshot = CapturedAggregateSnapshot()
            self.basis = ReadBasis(
                lineage="captured-lineage",
                captured_head=Head("captured-lineage", 1, "captured"),
                projected_through=Head("captured-lineage", 1, "captured"),
                view_generation="test-view",
            )
            self.closed = False

        def close(self) -> None:
            self.closed = True

    opened: list[CapturedAggregateOpened] = []

    def open_captured_aggregate(*_args: object, **_kwargs: object) -> CapturedAggregateOpened:
        result = CapturedAggregateOpened()
        opened.append(result)
        return result

    def forbidden(*_args: object, **_kwargs: object) -> object:
        pytest.fail("strict captured-aggregate read touched a legacy or aggregate route")

    monkeypatch.setattr("engine.arrival_consumer.open_read", open_captured_aggregate)
    monkeypatch.setattr(read_module, "resolve_target", forbidden)
    monkeypatch.setattr(read_module, "_refuse_arrival_aggregate_members", forbidden)
    monkeypatch.setattr(read_module, "has_local_descriptor_aggregate", forbidden)
    monkeypatch.setattr(read_module, "_aggregate_summary", forbidden)
    monkeypatch.setattr(read_module, "open_aggregate_read", forbidden)

    for reader in (read_summary, read_facts):
        with pytest.raises(TargetUnsupported, match="aggregate"):
            reader(vertex, require_arrival=True)
    assert len(opened) == 2 and all(result.closed for result in opened)


def test_summary_reports_captured_fresh_epoch_without_filtering_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_runtime(monkeypatch, tmp_path)

    def sign(observer: str, commitment: str) -> str:
        return f"test-signature:{observer}:{commitment}"

    def fact_body(identifier: str, payload: str, *, at: float, observer: str) -> dict[str, object]:
        signature = sign(
            observer, fact_commitment_hash("item", at, observer, "fixture", payload)
        )
        return body_of_fact_row((identifier, "item", at, observer, "fixture", payload, signature))

    log = ArrivalLog.mint(
        tmp_path / "fresh.arrival",
        observer="custodian",
        signer=sign,
        key=base64.b64encode(b"k" * 32).decode(),
        at=0.0,
    )
    vertex = tmp_path / "fresh-captured.vertex"
    vertex.write_text(
        f'name "captured"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        'loops { item { fold { items "collect" 100 } } }\n',
        encoding="utf-8",
    )
    documents = [document.as_json() for document in vertex_to_documents(parse_vertex_file(vertex))]
    fresh_declaration = json.dumps(
        {
            "protocol": 2,
            "documents": documents,
            "runtime_epoch": "fresh-after-anchor-v1",
        },
        separators=(",", ":"),
    )
    log.append(
        "fact",
        fact_body("retained", json.dumps({"value": "before"}), at=1.0, observer="alice"),
        observer="alice",
        origin="fixture",
        at=1.0,
        signer=sign,
    )
    declaration_signature = sign(
        "custodian",
        fact_commitment_hash("_decl.genesis", 2.0, "custodian", "fixture", fresh_declaration),
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "custodian",
                "fixture",
                fresh_declaration,
                declaration_signature,
            )
        ),
        observer="custodian",
        origin="fixture",
        at=2.0,
        signer=sign,
    )
    log.append(
        "fact",
        fact_body("current", json.dumps({"value": "after"}), at=3.0, observer="alice"),
        observer="alice",
        origin="fixture",
        at=3.0,
        signer=sign,
    )
    sync_target(vertex)
    original_open = read_module._open_arrival_read

    @contextlib.contextmanager
    def replace_locator(*args: object, **kwargs: object):
        with original_open(*args, **kwargs) as opened:
            vertex.write_text('name "mutable"\nstore "legacy.db"\n', encoding="utf-8")
            yield opened

    monkeypatch.setattr(read_module, "_open_arrival_read", replace_locator)
    summary = read_summary(vertex, require_arrival=True)

    assert summary.vertex_name == "captured"
    assert summary.runtime_epoch == {"mode": "fresh", "anchor_ordinal": 2}
    assert summary.fact_total == 2
    assert summary.kinds["item"]["count"] == 2


def test_default_summary_keeps_ordinary_arrival_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_runtime(monkeypatch, tmp_path)
    vertex = tmp_path / "default-summary.vertex"
    init_vertex(vertex, store_type="arrival", observer="alice")
    emit_fact(vertex, "item", {"value": 1}, observer="alice")

    ordinary = read_summary(vertex)
    assert ordinary.read_path == "arrival"
    assert ordinary.fact_total == 1
    assert ordinary.declaration_status == "store"
    assert ordinary.runtime_epoch == {"mode": "strict", "anchor_ordinal": None}
