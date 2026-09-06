"""Independent C7 contract checks for bounded Arrival inspection."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import UnknownBackend
from engine.arrival_file_backend import (
    FileLedger,
    FileProjectionMaintenance,
    FileQuery,
)
from engine.arrival_registry import BackendRegistry
from engine.residence import index_path_for
from lang import genesis_payload, parse_vertex_file

from sdk import SdkError, SdkValueError, inspect_declaration


@pytest.fixture(autouse=True)
def _isolated_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep opaque binding journals inside pytest's disposable directory."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _sign(_observer: str, commitment: str) -> str:
    return "test-signature:" + commitment


def _append_genesis(log: ArrivalLog, vertex: Path) -> None:
    documents = genesis_payload(parse_vertex_file(vertex))["documents"]
    payload = json.dumps(
        {"protocol": 1, "documents": documents},
        sort_keys=True,
        separators=(",", ":"),
    )
    commitment = fact_commitment_hash(
        "_decl.genesis", 2.0, "custodian", "contract-test", payload
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "custodian",
                "contract-test",
                payload,
                _sign("custodian", commitment),
            )
        ),
        observer="custodian",
        origin="contract-test",
        at=2.0,
        signer=_sign,
    )
    maintenance = FileProjectionMaintenance(log.path, index_path_for(log.path))
    try:
        maintenance.catch_up(FileLedger(log).head())
    finally:
        maintenance.close()


def _opaque_root(
    tmp_path: Path, *, effective_aggregate: bool = False
) -> tuple[Path, ArrivalLog, str]:
    log = ArrivalLog.mint(
        tmp_path / "root.arrival",
        observer="custodian",
        signer=_sign,
        key=base64.b64encode(b"k" * 32).decode(),
        at=1.0,
    )
    # Keep the binding identity unique across parametrized tests: the
    # attestation journal is intentionally persistent for an opaque locator.
    locator = f"opaque://tenant//root-{tmp_path.name}?projection=contract"
    vertex = tmp_path / "root.vertex"
    shape = 'discover "missing/*.vertex"\n' if effective_aggregate else ""
    vertex.write_text(
        f'name "root"\nstore "{locator}" backend="opaque" '
        f'lineage="{log.lineage()}" role="authority"\n'
        + shape
        + 'loops { note { fold { items "collect" 5 } } }\n',
        encoding="utf-8",
    )
    _append_genesis(log, vertex)
    return vertex, log, locator


class _TrackingLedger(FileLedger):
    def __init__(self, log: ArrivalLog, events: list[str]) -> None:
        super().__init__(log)
        self._events = events

    def close(self) -> None:
        self._events.append("ledger")
        super().close()


class _TrackingQuery(FileQuery):
    def __init__(self, path: Path, events: list[str]) -> None:
        super().__init__(path)
        self._events = events

    def close(self) -> None:
        self._events.append("query")
        super().close()


def _registry(
    locator: str, log: ArrivalLog, events: list[str], calls: list[str]
) -> BackendRegistry:
    registry = BackendRegistry()

    def opener(descriptor):
        calls.append(descriptor.location)
        if descriptor.location != locator:
            raise AssertionError(f"member open attempted: {descriptor.location!r}")
        return _TrackingLedger(log, events), _TrackingQuery(
            index_path_for(log.path), events
        )

    registry.register("opaque", opener)
    return registry


@pytest.mark.parametrize("effective_aggregate", (False, True))
def test_inspection_opens_only_root_and_closes_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    effective_aggregate: bool,
) -> None:
    vertex, log, locator = _opaque_root(
        tmp_path, effective_aggregate=effective_aggregate
    )
    if effective_aggregate:
        # The adopted declaration is aggregate, while the current locator is
        # plain. Inspection must report both shapes without resolving a child.
        vertex.write_text(
            vertex.read_text(encoding="utf-8").replace(
                'discover "missing/*.vertex"\n', ""
            ),
            encoding="utf-8",
        )
    else:
        # The current locator is aggregate, while the adopted declaration is
        # plain. A missing child must remain completely outside this read.
        vertex.write_text(
            vertex.read_text(encoding="utf-8")
            + 'discover "missing/*.vertex"\n',
            encoding="utf-8",
        )

    events: list[str] = []
    calls: list[str] = []
    monkeypatch.setattr(
        Path,
        "glob",
        lambda *_args, **_kwargs: pytest.fail(
            "bounded inspection attempted discover/member glob"
        ),
    )
    result = inspect_declaration(
        vertex, registry=_registry(locator, log, events, calls)
    )

    assert calls == [locator]
    assert events == ["query", "ledger"]
    assert result.basis is not None
    assert result.store is not None and result.store.location == locator
    assert result.local_status == "drifted"
    assert result.local_fingerprint != result.effective_fingerprint
    assert result.effective_discover == (
        "missing/*.vertex" if effective_aggregate else None
    )
    assert result.local_discover == (
        None if effective_aggregate else "missing/*.vertex"
    )
    assert result.effective_combine is None
    assert result.local_combine is None
    json.dumps(result.as_dict(), allow_nan=False)


def test_inspection_closes_root_when_effective_declaration_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log, locator = _opaque_root(tmp_path)
    events: list[str] = []
    calls: list[str] = []

    def refuse(*_args, **_kwargs):
        raise SdkError("effective declaration refused")

    monkeypatch.setattr("sdk.read._arrival_declaration", refuse)
    with pytest.raises(SdkError, match="effective declaration refused"):
        inspect_declaration(vertex, registry=_registry(locator, log, events, calls))

    assert calls == [locator]
    assert events == ["query", "ledger"]


def test_inspection_role_and_unknown_backend_refuse_before_legacy_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_role = tmp_path / "missing-role.vertex"
    missing_role.write_text(
        'name "root"\nstore "opaque://root" backend="opaque" '
        'lineage="lineage"\ndiscover "missing/*.vertex"\n',
        encoding="utf-8",
    )
    unknown_backend = tmp_path / "unknown.vertex"
    unknown_backend.write_text(
        'name "root"\nstore "remote://root" backend="remote" '
        'lineage="lineage" role="authority"\n'
        'discover "missing/*.vertex"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sdk.declare.probe_target",
        lambda _path: pytest.fail("descriptor refusal fell through to legacy probe"),
    )

    with pytest.raises(SdkValueError, match="must declare store role"):
        inspect_declaration(missing_role, registry=BackendRegistry())
    with pytest.raises(UnknownBackend, match="remote"):
        inspect_declaration(unknown_backend, registry=BackendRegistry())


def test_storeless_discover_never_uses_legacy_probe_or_store_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex = tmp_path / "storeless.vertex"
    vertex.write_text(
        'name "root"\ndiscover "missing/*.vertex"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        "sdk.declare.probe_target",
        lambda _path: pytest.fail("storeless root was sent through probe_target"),
    )
    monkeypatch.setattr(
        "sdk.declare.load_declaration_status",
        lambda *_args, **_kwargs: pytest.fail(
            "storeless root was sent through load_declaration_status"
        ),
    )

    result = inspect_declaration(vertex)

    assert result.read_path == "local-frozen"
    assert result.store is None and result.basis is None
    assert result.local_discover == result.effective_discover == "missing/*.vertex"
    assert result.local_combine is result.effective_combine is None
    json.dumps(result.as_dict(), allow_nan=False)
