"""C1: descriptor reads use the caller's registry, never a legacy fallback."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import UnknownBackend
from engine.arrival_file_backend import FileLedger, FileProjectionMaintenance, FileQuery
from engine.arrival_registry import BackendRegistry
from engine.residence import index_path_for
from lang import genesis_payload, parse_vertex_file

from sdk import inspect_declaration, read_timeline, resolve_entity


def _sign(_observer: str, commitment: str) -> str:
    return "test-signature:" + commitment


def _fact_body(
    identifier: str,
    kind: str,
    ts: float,
    observer: str,
    origin: str,
    payload: dict,
) -> dict:
    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return body_of_fact_row(
        (
            identifier,
            kind,
            ts,
            observer,
            origin,
            payload_text,
            _sign(observer, fact_commitment_hash(kind, ts, observer, origin, payload_text)),
        )
    )


def _project(log: ArrivalLog) -> None:
    maintenance = FileProjectionMaintenance(log.path, index_path_for(log.path))
    try:
        maintenance.catch_up(FileLedger(log).head())
    finally:
        maintenance.close()


def _vertex(
    tmp_path: Path,
    *,
    name: str,
    locator: str,
    body: str = 'loops { note { fold { items "collect" 5 } } }\n',
) -> tuple[Path, ArrivalLog]:
    log = ArrivalLog.mint(
        tmp_path / f"{name}.arrival",
        observer="custodian",
        signer=_sign,
        key=base64.b64encode(b"k" * 32).decode(),
        at=1.0,
    )
    path = tmp_path / f"{name}.vertex"
    path.write_text(
        f'name "{name}"\n'
        f'store "{locator}" backend="opaque" lineage="{log.lineage()}" role="authority"\n'
        "observers { alice { } }\n"
        + body,
        encoding="utf-8",
    )
    declaration = genesis_payload(parse_vertex_file(path))["documents"]
    log.append(
        "fact",
        _fact_body(
            log.lineage(),
            "_decl.genesis",
            2.0,
            "custodian",
            "fixture",
            {"protocol": 1, "documents": declaration},
        ),
        observer="custodian",
        origin="fixture",
        at=2.0,
        signer=_sign,
    )
    _project(log)
    return path, log


def _opaque_registry(
    targets: dict[str, ArrivalLog], calls: list[str] | None = None
) -> BackendRegistry:
    registry = BackendRegistry()

    def open_opaque(descriptor):
        if calls is not None:
            calls.append(descriptor.location)
        log = targets[descriptor.location]
        return FileLedger(log), FileQuery(index_path_for(log.path))

    registry.register("opaque", open_opaque)
    return registry


def _forbid_builtin_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit registry must be used; a default would hide this regression."""
    monkeypatch.setattr(
        BackendRegistry,
        "with_builtin_backends",
        classmethod(lambda _cls: pytest.fail("explicit registry was ignored")),
    )


@pytest.fixture(autouse=True)
def _isolated_attestation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_registered_opaque_backend_serves_single_entity_timeline_and_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locator = "opaque://tenant//ledger?projection=not-a-path"
    vertex, log = _vertex(tmp_path, name="single", locator=locator)
    log.append(
        "fact",
        _fact_body("item-1", "note", 3.0, "alice", "fixture", {"key": "one"}),
        observer="alice",
        origin="fixture",
        at=3.0,
        signer=_sign,
    )
    _project(log)
    registry = _opaque_registry({locator: log})
    _forbid_builtin_registry(monkeypatch)
    monkeypatch.setattr("sdk.read.resolve_target", lambda _target: pytest.fail("legacy read"))
    monkeypatch.setattr("sdk.declare.probe_target", lambda _target: pytest.fail("legacy inspect"))

    entity = resolve_entity(vertex, "note", "key", "one", registry=registry)
    timeline = read_timeline(vertex, registry=registry)
    inspection = inspect_declaration(vertex, registry=registry)

    assert entity.found and entity.fact_id == "item-1"
    assert entity.store is not None and entity.store.backend == "opaque"
    assert entity.store.location == locator and entity.basis is not None
    assert [event.id for event in timeline.events] == ["item-1"]
    assert timeline.basis is not None and timeline.store is not None
    assert inspection.store is not None and inspection.store.backend == "opaque"
    assert inspection.store.location == locator and inspection.basis is not None


@pytest.mark.parametrize("backend", ("opaque", "file"))
@pytest.mark.parametrize("operation", ("entity", "timeline", "inspection"))
def test_unknown_descriptor_backend_never_falls_back_to_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str, operation: str
) -> None:
    opaque_locator = "opaque://unknown//ledger?projection=not-a-path"
    vertex, log = _vertex(tmp_path, name="unknown", locator=opaque_locator)
    if backend == "file":
        vertex.write_text(
            vertex.read_text(encoding="utf-8")
            .replace(opaque_locator, str(log.path))
            .replace('backend="opaque"', 'backend="file"'),
            encoding="utf-8",
        )
    registry = BackendRegistry()
    _forbid_builtin_registry(monkeypatch)
    monkeypatch.setattr("sdk.read.resolve_target", lambda _target: pytest.fail("legacy read"))
    monkeypatch.setattr("sdk.declare.probe_target", lambda _target: pytest.fail("legacy inspect"))

    operation_call: dict[str, Callable[[], object]] = {
        "entity": lambda: resolve_entity(vertex, "note", "key", "one", registry=registry),
        "timeline": lambda: read_timeline(vertex, registry=registry),
        "inspection": lambda: inspect_declaration(vertex, registry=registry),
    }
    with pytest.raises(UnknownBackend, match=backend):
        operation_call[operation]()


def test_storeless_aggregate_opens_opaque_member_through_supplied_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locator = "opaque://member//ledger"
    child, log = _vertex(tmp_path, name="child", locator=locator)
    log.append(
        "fact",
        _fact_body("child-1", "note", 3.0, "alice", "fixture", {"key": "child"}),
        observer="alice",
        origin="fixture",
        at=3.0,
        signer=_sign,
    )
    _project(log)
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine { vertex "child.vertex" as="child" }\n', encoding="utf-8"
    )
    calls: list[str] = []
    _forbid_builtin_registry(monkeypatch)
    result = read_timeline(root, registry=_opaque_registry({locator: log}, calls))

    assert [event.id for event in result.events] == ["child-1"]
    assert calls == [locator]
    assert result.aggregate_members
    assert result.aggregate_members[0]["basis"].lineage == log.lineage()


def test_effective_aggregate_root_reuses_its_opened_opaque_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child_locator = "opaque://child//ledger"
    child, child_log = _vertex(tmp_path, name="child", locator=child_locator)
    child_log.append(
        "fact",
        _fact_body("child-1", "note", 3.0, "alice", "fixture", {"key": "child"}),
        observer="alice",
        origin="fixture",
        at=3.0,
        signer=_sign,
    )
    _project(child_log)

    root_locator = "opaque://root//ledger"
    root, root_log = _vertex(
        tmp_path,
        name="root",
        locator=root_locator,
        body=(
            'discover "child.vertex"\n'
            'loops { note { fold { items "collect" 5 } } }\n'
        ),
    )
    # The locator cache has become plain. The bounded adopted declaration still
    # composes the child, so execution must use the root's first captured read.
    root.write_text(
        f'name "root"\nstore "{root_locator}" backend="opaque" '
        f'lineage="{root_log.lineage()}" role="authority"\n'
        'loops { note { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    calls: list[str] = []
    _forbid_builtin_registry(monkeypatch)
    result = read_timeline(
        root,
        registry=_opaque_registry(
            {root_locator: root_log, child_locator: child_log}, calls
        ),
    )

    assert [event.id for event in result.events] == ["child-1"]
    assert calls.count(root_locator) == 1
    assert calls.count(child_locator) == 1


def test_storeless_aggregate_unknown_member_never_uses_default_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locator = "opaque://unknown-member//ledger"
    _child, _log = _vertex(tmp_path, name="child", locator=locator)
    root = tmp_path / "root.vertex"
    root.write_text(
        'name "root"\ncombine { vertex "child.vertex" as="child" }\n', encoding="utf-8"
    )
    _forbid_builtin_registry(monkeypatch)

    with pytest.raises(UnknownBackend, match="opaque"):
        read_timeline(root, registry=BackendRegistry())
