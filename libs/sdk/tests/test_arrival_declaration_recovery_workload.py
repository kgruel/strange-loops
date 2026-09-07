"""Public mapped-custody conformance for interrupted declaration recovery."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from engine import arrival_declarations
from engine.arrival_contract import ProjectionBehind

from sdk import (
    AdmissionFailed,
    ArrivalRefusal,
    CommittedIncomplete,
    CustodyCredentialProvider,
    MappedCredentialProvider,
    edit_declaration,
    emit_fact,
    init_vertex,
    inspect_declaration,
    read_facts,
    recover_declaration,
    verify_target,
)


@pytest.fixture(autouse=True)
def _isolated_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops-home"))


def _add_note_kind(declaration: str, *, collect_limit: int = 10) -> str:
    item = (
        "  item {\n"
        "    fold {\n"
        '      items "collect" 100\n'
        "    }\n"
        "  }\n"
    )
    note = (
        "  note {\n"
        "    fold {\n"
        f'      items "collect" {collect_limit}\n'
        "    }\n"
        "  }\n"
    )
    assert declaration.count(item) == 1
    return declaration.replace(item, item + note)


def test_mapped_declaration_recovery_restores_inspection_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MappedCredentialProvider(
        tmp_path / "custody",
        namespace="recovery-tenant",
        receipt_observer="alice",
    )
    provider.create_binding("alice", token="create-alice")
    vertex = tmp_path / "workflow.vertex"
    initialized = init_vertex(
        vertex,
        name="workflow",
        store_type="arrival",
        location=(tmp_path / "data" / "workflow.arrival").resolve(),
        observer="alice",
        strict=True,
        credentials=provider,
    )
    assert initialized.lineage is not None
    proposed = _add_note_kind(vertex.read_text(encoding="utf-8"))
    original_cache = vertex.read_bytes()
    baseline_inspection = inspect_declaration(vertex)
    assert baseline_inspection.basis is not None
    assert baseline_inspection.store == initialized.store
    assert baseline_inspection.local_status == "matches-effective"
    assert baseline_inspection.declared_kinds == ["item"]
    baseline_basis = asdict(baseline_inspection.basis)
    baseline_internal = read_facts(
        vertex,
        include_internal=True,
        limit=20,
        order="oldest",
    )
    baseline_ids = [item["id"] for item in baseline_internal.items]
    initial_verification = verify_target(vertex)
    assert initial_verification.claims == (
        "grammar",
        "density",
        "lineage",
        "hash-chain",
    )
    assert initial_verification.excludes == (
        "signature-authorship",
        "external-key-trust",
        "projection",
    )
    before_edit = initial_verification.verified_through
    assert before_edit is not None
    with pytest.raises(AdmissionFailed) as undeclared:
        emit_fact(
            vertex,
            "note",
            {"text": "before declaration"},
            observer="alice",
            origin="recovery-workflow",
            ts=9.0,
            id_override="note-before-declaration",
            credentials=provider,
        )
    assert undeclared.value.observer == "alice"
    assert undeclared.value.kind == "note"
    assert verify_target(vertex).verified_through == before_edit

    original_apply = arrival_declarations.apply_declaration_edit
    injected_phases: list[str] = []

    def interrupt_after_append(registry, plan):
        def fail(phase: str) -> None:
            if phase == "after-append":
                injected_phases.append(phase)
                raise OSError("injected declaration publication interruption")

        return original_apply(registry, plan, failure_hook=fail)

    monkeypatch.setattr(
        arrival_declarations,
        "apply_declaration_edit",
        interrupt_after_append,
    )
    with pytest.raises(CommittedIncomplete) as interrupted:
        edit_declaration(
            vertex,
            proposed,
            observer="alice",
            credentials=provider,
        )

    failure = interrupted.value
    encoded_failure = failure.as_dict()
    json.dumps(encoded_failure, allow_nan=False)
    assert injected_phases == ["after-append"]
    assert encoded_failure["outcome"] == "committed-incomplete"
    assert failure.source_type == "DeclarationCommittedIncomplete"
    assert failure.details["phase"] == "appended"
    assert failure.details["commit"]["before"] == {
        "lineage": before_edit.lineage,
        "ordinal": before_edit.ordinal,
        "record_hash": before_edit.record_hash,
    }
    durable_head = failure.details["commit"]["after"]
    assert durable_head["lineage"] == before_edit.lineage
    assert durable_head["ordinal"] == before_edit.ordinal + 1
    assert failure.details["head"] == durable_head
    assert failure.details["fact_ids"]
    intent = Path(failure.details["intent_path"])
    assert intent.exists()
    assert vertex.read_bytes() == original_cache
    assert verify_target(vertex).as_dict()["verified_through"] == durable_head

    with pytest.raises(ProjectionBehind):
        inspect_declaration(vertex)

    with pytest.raises(ArrivalRefusal) as pending:
        edit_declaration(
            vertex,
            _add_note_kind(
                vertex.read_text(encoding="utf-8"),
                collect_limit=11,
            ),
            observer="alice",
            credentials=provider,
        )
    assert pending.value.source_type == "DeclarationPreparationRefused"
    pending_evidence = pending.value.details["evidence"]
    assert pending_evidence["phase"] == "prepare"
    assert pending_evidence["effects"]["custody"] == {
        "state": "not-attempted",
        "attempt": "not-entered",
    }
    assert pending_evidence["cause"]["type"] == "ProjectionBehind"
    assert pending_evidence["basis"]["captured_head"] == durable_head
    assert intent.exists()
    assert verify_target(vertex).as_dict()["verified_through"] == durable_head

    with monkeypatch.context() as recovery_poison:
        recovery_poison.setattr(
            MappedCredentialProvider,
            "resolve",
            lambda *_args, **_kwargs: pytest.fail(
                "declaration recovery resolved mapped signing credentials"
            ),
        )
        recovery_poison.setattr(
            CustodyCredentialProvider,
            "for_write",
            lambda *_args, **_kwargs: pytest.fail(
                "declaration recovery acquired legacy signing credentials"
            ),
        )
        recovered = recover_declaration(intent)
    assert recovered.status == "recovered"
    assert recovered.phase == "published"
    assert recovered.commit is None
    assert recovered.changes is None
    assert recovered.file_written is True
    assert recovered.head == durable_head
    assert recovered.captured_head == failure.details["commit"]["before"]
    assert recovered.basis == baseline_basis
    assert recovered.fact_ids == tuple(failure.details["fact_ids"])
    assert not intent.exists()
    assert vertex.read_text(encoding="utf-8") == proposed
    assert verify_target(vertex).as_dict()["verified_through"] == durable_head
    json.dumps(recovered.as_dict(), allow_nan=False)

    recovered_internal = read_facts(
        vertex,
        include_internal=True,
        limit=20,
        order="oldest",
    )
    recovered_ids = [item["id"] for item in recovered_internal.items]
    assert recovered_ids == baseline_ids + list(recovered.fact_ids)
    assert all(recovered_ids.count(fact_id) == 1 for fact_id in recovered.fact_ids)
    recovered_rows = [
        item for item in recovered_internal.items if item["id"] in recovered.fact_ids
    ]
    assert len(recovered_rows) == len(recovered.fact_ids)
    note_declarations = [
        item
        for item in recovered_rows
        if item["kind"] == "_decl.kind-defined"
        and item["payload"]["subject"] == "note"
    ]
    assert len(note_declarations) == 1

    inspection = inspect_declaration(vertex)
    assert inspection.read_path == "arrival"
    assert inspection.syntax_valid is True
    assert inspection.status == inspection.effective_status == "store"
    assert inspection.local_status == "matches-effective"
    assert inspection.declared_kinds == ["item", "note"]
    assert inspection.basis is not None
    assert inspection.basis.lineage == initialized.lineage
    assert inspection.basis.captured_head == inspection.basis.projected_through
    assert inspection.basis.captured_head.ordinal == durable_head["ordinal"]
    assert inspection.basis.captured_head.record_hash == durable_head["record_hash"]
    json.dumps(inspection.as_dict(), allow_nan=False)

    monkeypatch.setattr(
        arrival_declarations,
        "apply_declaration_edit",
        original_apply,
    )
    repeated = edit_declaration(
        vertex,
        proposed,
        observer="alice",
        credentials=provider,
    )
    assert repeated.status == "noop"
    assert repeated.phase == "noop"
    assert repeated.head == durable_head
    assert repeated.commit is None
    assert repeated.file_written is False
    assert verify_target(vertex).as_dict()["verified_through"] == durable_head

    reopened_provider = MappedCredentialProvider(
        tmp_path / "custody",
        namespace="recovery-tenant",
        receipt_observer="alice",
    )
    continued = emit_fact(
        vertex,
        "note",
        {"text": "after recovery"},
        observer="alice",
        origin="recovery-workflow",
        ts=20.0,
        id_override="note-after-recovery",
        credentials=reopened_provider,
    )
    assert continued.stored is True
    assert continued.signed is True
    assert continued.commit is not None
    assert continued.commit.before.ordinal == durable_head["ordinal"]
    assert continued.commit.before.record_hash == durable_head["record_hash"]
    assert continued.commit.after.lineage == initialized.lineage
    assert continued.commit.after.ordinal > continued.commit.before.ordinal
    assert continued.witnessed is True
    assert continued.projection == "synced"

    page = read_facts(vertex, kind="note", limit=10, order="oldest")
    assert page.basis is not None
    assert page.basis.lineage == initialized.lineage
    assert page.basis.captured_head == continued.commit.after
    assert page.basis.projected_through == page.basis.captured_head
    assert [(item["id"], item["observer"], item["payload"]) for item in page.items] == [
        ("note-after-recovery", "alice", {"text": "after recovery"})
    ]
    verified = verify_target(vertex)
    assert verified.captured_head == continued.commit.after
    assert verified.verified_through == page.basis.captured_head
    assert verified.claims == initial_verification.claims
    assert verified.excludes == initial_verification.excludes
