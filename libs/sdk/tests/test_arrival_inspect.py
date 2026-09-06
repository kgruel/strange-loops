"""Arrival declaration inspection is bounded to one attested snapshot."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import Head, ProjectionAbsent, ProjectionBehind
from engine.arrival_file_backend import FileQuery
from engine.residence import index_path_for
from lang import genesis_payload, parse_vertex_file

from sdk import inspect_declaration, sync_target


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
        tmp_path / "inspect.arrival",
        observer="physical-custodian",
        signer=_sign,
        key=base64.b64encode(b"k" * 32).decode(),
        at=1.0,
    )
    vertex = tmp_path / "inspect.vertex"
    vertex.write_text(
        f'name "locator"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        "strict true\n"
        "observers { alice { } }\n"
        "loops { note { fold { items \"collect\" 5 } } }\n",
        encoding="utf-8",
    )
    declaration = json.dumps(genesis_payload(parse_vertex_file(vertex)))
    log.append(
        "fact",
        _signed_fact_body(
            log.lineage(),
            "_decl.genesis",
            2.0,
            "physical-custodian",
            "test",
            declaration,
        ),
        observer="physical-custodian",
        origin="test",
        at=2.0,
        signer=_sign,
    )
    sync_target(vertex)
    return vertex, log


def _later_kind_payload(log: ArrivalLog) -> str:
    documents = genesis_payload(parse_vertex_file(log.path.parent / "inspect.vertex"))["documents"]
    document = next(
        document
        for document in documents
        if document["kind"] == "_decl.kind-defined"
    )
    payload = dict(document["payload"])
    payload["order"] = 1
    return json.dumps(
        {
            "lineage": log.lineage(),
            "subject": "later",
            "change": "added",
            "payload": payload,
        }
    )


def _append_later_kind(log: ArrivalLog) -> None:
    log.append(
        "fact",
        _signed_fact_body(
            "later-kind",
            "_decl.kind-defined",
            3.0,
            "physical-custodian",
            "test",
            _later_kind_payload(log),
        ),
        observer="physical-custodian",
        origin="test",
        at=3.0,
        signer=_sign,
    )


def test_arrival_inspect_uses_effective_snapshot_not_locator_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _arrival_target(tmp_path, monkeypatch)
    matching = inspect_declaration(vertex)
    assert matching.local_status == "matches-effective"
    assert matching.local_fingerprint == matching.effective_fingerprint

    vertex.write_text(
        vertex.read_text(encoding="utf-8")
        .replace("strict true", "strict false")
        .replace("note {", "local-only {"),
        encoding="utf-8",
    )

    result = inspect_declaration(vertex)

    assert result.read_path == "arrival"
    assert result.store is not None and result.basis is not None
    assert result.status == result.effective_status == "store"
    assert result.local_status == "drifted" and result.syntax_valid
    assert result.local_fingerprint != result.effective_fingerprint
    assert result.declared_kinds == ["note"]
    assert result.declared_observers == ["alice"]
    assert result.strict is True
    json.dumps(result.as_dict(), allow_nan=False)


def test_arrival_inspect_capture_excludes_later_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _arrival_target(tmp_path, monkeypatch)
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
            _append_later_kind(log)
            sync_target(vertex)
        return original_open_snapshot(
            query,
            captured_head=captured_head,
            requirement=requirement,
            continuation=continuation,
        )

    monkeypatch.setattr(FileQuery, "open_snapshot", append_before_snapshot)

    captured_read = inspect_declaration(vertex)
    assert injected and captured == [captured_read.basis.captured_head]
    assert captured_read.declared_kinds == ["note"]

    subsequent_read = inspect_declaration(vertex)
    assert subsequent_read.declared_kinds == ["later", "note"]
    assert subsequent_read.basis.captured_head.ordinal > captured_read.basis.captured_head.ordinal


@pytest.mark.parametrize(
    ("mode", "refusal"),
    [("missing", ProjectionAbsent), ("behind", ProjectionBehind)],
)
def test_arrival_inspect_refuses_current_projection_without_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    refusal: type[Exception],
) -> None:
    vertex, log = _arrival_target(tmp_path, monkeypatch)
    index = index_path_for(log.path)
    if mode == "missing":
        index.unlink()
    else:
        _append_later_kind(log)
    ledger_before = log.path.read_bytes()
    index_before = None if mode == "missing" else index.read_bytes()

    with pytest.raises(refusal):
        inspect_declaration(vertex)

    assert log.path.read_bytes() == ledger_before
    if mode == "missing":
        assert not index.exists()
    else:
        assert index.read_bytes() == index_before
