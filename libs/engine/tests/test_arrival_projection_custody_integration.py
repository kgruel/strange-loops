"""Real file evidence for projection advance after custody capture."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest
from lang import genesis_payload, parse_vertex
from lang.ast import VertexFile

from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_consumer import open_read
from engine.arrival_contract import FactRequest, Head, Profile, StoreDescriptor
from engine.arrival_declarations import prepare_declaration_edit
from engine.arrival_file_backend import FileLedger
from engine.arrival_maintenance import sync_projection
from engine.arrival_registry import BackendRegistry
from engine.residence import index_path_for
from engine.runtime_write import capture_runtime


@dataclass(frozen=True)
class _Target:
    vertex: Path
    source: str
    locator: VertexFile
    log: ArrivalLog
    descriptor: StoreDescriptor
    registry: BackendRegistry


def _make_target(tmp_path, monkeypatch, keys, signer) -> _Target:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    log = ArrivalLog.mint(
        tmp_path / "advance.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
        at=1.0,
    )
    vertex = tmp_path / "advance.vertex"
    source = (
        'name "advance"\n'
        f'store "{log.path}" backend="file" lineage="{log.lineage()}" '
        'role="authority"\n'
        "observers { kyle { } }\n"
        "loops {\n"
        "  note {\n"
        '    fold { items "collect" 20 }\n'
        "  }\n"
        "}\n"
    )
    vertex.write_text(source, encoding="utf-8")
    locator = parse_vertex(source, vertex)
    declaration = json.dumps(genesis_payload(locator))
    declaration_signature = signer(
        "kyle",
        fact_commitment_hash(
            "_decl.genesis", 2.0, "kyle", "test", declaration
        ),
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "kyle",
                "test",
                declaration,
                declaration_signature,
            )
        ),
        observer="kyle",
        origin="test",
        at=2.0,
        signer=signer,
    )
    descriptor = StoreDescriptor(
        "file",
        str(log.path),
        lineage=log.lineage(),
        role=Profile.AUTHORITY,
    )
    registry = BackendRegistry.with_builtin_backends()
    sync_projection(registry, descriptor, through=FileLedger(log).head())
    return _Target(vertex, source, locator, log, descriptor, registry)


class _AdvanceBeforeSnapshotRegistry:
    def __init__(self, target: _Target, signer):
        self._target = target
        self._signer = signer
        self.captured: Head | None = None
        self.advanced: Head | None = None
        self.represented_ordinal: int | None = None

    def open(self, descriptor):
        ledger, query = self._target.registry.open(descriptor)
        self.captured = ledger.opened.comparison.presented
        owner = self

        class Query:
            def open_snapshot(self, **kwargs):
                assert kwargs["captured_head"] == owner.captured
                payload = json.dumps({"value": "after-capture"})
                signature = owner._signer(
                    "kyle",
                    fact_commitment_hash(
                        "note", 3.0, "kyle", "test", payload
                    ),
                )
                owner._target.log.append(
                    "fact",
                    body_of_fact_row(
                        (
                            "after-capture",
                            "note",
                            3.0,
                            "kyle",
                            "test",
                            payload,
                            signature,
                        )
                    ),
                    observer="kyle",
                    origin="test",
                    at=3.0,
                    signer=owner._signer,
                )
                owner.advanced = FileLedger(owner._target.log).head()
                sync_projection(
                    owner._target.registry,
                    owner._target.descriptor,
                    through=owner.advanced,
                )
                snapshot = query.open_snapshot(**kwargs)
                assert snapshot.represented is not None
                owner.represented_ordinal = snapshot.represented.ordinal
                return snapshot

            def close(self):
                query.close()

        return ledger, Query()


@pytest.mark.parametrize("operation", ("read", "runtime", "declaration"))
def test_real_file_projection_advance_after_capture_is_vouched_and_bounded(
    tmp_path, monkeypatch, keys, signer, operation
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    registry = _AdvanceBeforeSnapshotRegistry(target, signer)

    if operation == "read":
        with open_read(registry, target.descriptor) as opened:
            basis = opened.basis
            ids = {
                fact.id
                for fact in opened.snapshot.facts(
                    FactRequest(limit=None, include_internal=True, order="oldest")
                ).items
            }
        assert "after-capture" not in ids
    elif operation == "runtime":
        capture = capture_runtime(registry, target.descriptor, target.locator)
        basis = capture.basis
        ids = {fact.id for fact in capture._facts}
        assert "after-capture" not in ids
    else:
        plan = prepare_declaration_edit(
            registry,
            target.descriptor,
            target=target.vertex,
            proposed_text=target.source,
            observer="kyle",
            credentials=None,
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )
        basis = plan.basis
        assert plan.status == "noop"

    assert registry.captured is not None
    assert registry.advanced is not None
    assert registry.advanced.ordinal > registry.captured.ordinal
    assert registry.represented_ordinal == registry.advanced.ordinal
    assert basis.captured_head == registry.captured
    assert basis.projected_through == registry.captured
    assert FileLedger(target.log).head() == registry.advanced
    with sqlite3.connect(index_path_for(target.log.path)) as connection:
        projected_ordinal = connection.execute(
            "SELECT value FROM store_meta WHERE key = 'arrival_ordinal'"
        ).fetchone()[0]
    assert int(projected_ordinal) == registry.advanced.ordinal
