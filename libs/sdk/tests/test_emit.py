from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from atoms import Fact
from custody import ensure_signing_key
from engine.handle import CredentialProvider, ReceiveCommittedError, WriteCredentials

from sdk import (
    AdmissionFailed,
    CommittedEmissionError,
    EmissionFailed,
    EmitPreviewResult,
    EmitReceipt,
    InvalidEmissionRequest,
    TargetNotFound,
    TargetUnsupported,
    emit_batch,
    emit_fact,
    preview_emission,
    read_facts,
    read_summary,
)
from sdk.emit import CustodyCredentialProvider


def test_emit_fact_declared_kind(sample_vertex: Path) -> None:
    """Emitting a declared kind persists the fact and returns an EmitReceipt."""
    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Declared Note", "content": "Hello World"},
        observer="alice",
    )

    assert isinstance(receipt, EmitReceipt)
    assert receipt.stored is True
    assert receipt.id != ""
    assert receipt.observer == "alice"
    assert receipt.state_change is True
    assert receipt.delta_count >= 1
    assert receipt.affected_sections == ["note"]
    assert receipt.predicted_state_change is False

    # Verify fact appears in store
    page = read_facts(sample_vertex, limit=10)
    assert len(page.items) == 1
    assert page.items[0]["id"] == receipt.id
    assert page.items[0]["payload"]["title"] == "Declared Note"


def test_emit_fact_undeclared_kind_rejected_by_default(strict_vertex: Path) -> None:
    """Emitting an undeclared kind on a strict vertex raises AdmissionFailed."""
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_fact(
            strict_vertex,
            "undeclared_custom_kind",
            {"key": "value"},
            observer="alice",
        )
    assert exc_info.value.observer == "alice"
    assert exc_info.value.kind == "undeclared_custom_kind"
    assert exc_info.value.vertex == "strict"
    assert "undeclared" in str(exc_info.value).lower() or "admission" in str(exc_info.value).lower()


def test_emit_fact_accepts_fact_atom_directly(sample_vertex: Path) -> None:
    """emit_fact accepts a pre-constructed Fact atom directly."""
    from atoms import Fact

    fact = Fact.of("note", "bob", origin="agent-direct", title="Direct Fact")
    receipt = emit_fact(sample_vertex, fact)

    assert receipt.stored is True
    assert receipt.observer == "bob"

    page = read_facts(sample_vertex, limit=1)
    stored_fact = page.items[0]
    assert stored_fact["id"] == receipt.id
    assert stored_fact["observer"] == "bob"
    assert stored_fact["origin"] == "agent-direct"
    assert stored_fact["payload"]["title"] == "Direct Fact"


def test_emit_fact_with_id_override(sample_vertex: Path) -> None:
    """emit_fact respects deterministic id_override."""
    custom_id = "01M01DETERMINISTIC00000001"
    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Custom ID test"},
        observer="alice",
        id_override=custom_id,
    )
    assert receipt.stored is True
    assert receipt.id == custom_id

    fact = read_facts(sample_vertex, limit=1).items[0]
    assert fact["id"] == custom_id


def test_emit_fact_missing_observer_raises_value_error(sample_vertex: Path) -> None:
    """Emitting by kind without observer raises InvalidEmissionRequest."""
    from sdk import InvalidEmissionRequest

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_fact(sample_vertex, "note", {"title": "No observer"})
    assert "observer is required" in str(exc_info.value)
    assert isinstance(exc_info.value, ValueError)


def test_emit_fact_admit_undeclared_override(sample_vertex: Path) -> None:
    """Emitting undeclared kind with admit_undeclared=True succeeds."""
    receipt = emit_fact(
        sample_vertex,
        "custom_kind",
        {"metric": 42},
        observer="alice",
        admit_undeclared=True,
    )
    assert receipt.stored is True
    assert receipt.id != ""

    summary = read_summary(sample_vertex)
    assert "custom_kind" in summary.unfolded_kinds
    assert summary.kinds["custom_kind"]["count"] == 1


def test_emit_fact_signed_with_custody_key(sample_vertex: Path) -> None:
    """Emitting when custody keys exist produces signed receipts."""
    ensure_signing_key(sample_vertex)
    ensure_signing_key(sample_vertex, "trusted_observer")

    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Signed note"},
        observer="trusted_observer",
    )
    assert receipt.stored is True
    assert receipt.signed is True
    assert receipt.observer == "trusted_observer"
    assert receipt.tick_id is None
    assert receipt.tick_mark is None
    assert receipt.state_change is True
    assert receipt.delta_count >= 1
    assert receipt.affected_sections == ["note"]
    assert receipt.predicted_state_change is False


def test_emit_fact_unsupported_on_non_vertex(tmp_path: Path) -> None:
    """emit_fact raises TargetUnsupported when given a non-vertex target."""
    log_path = tmp_path / "standalone.jsonl"
    log_path.write_text('{"kind": "note"}\n', encoding="utf-8")

    with pytest.raises(TargetUnsupported) as exc_info:
        emit_fact(
            log_path,
            "note",
            {"body": "test"},
            observer="tester",
        )
    assert "emit_fact requires a .vertex target" in str(exc_info.value)


def test_emit_fact_nonexistent_vertex_raises_target_not_found(tmp_path: Path) -> None:
    """emit_fact raises TargetNotFound when the target vertex file does not exist."""
    missing = tmp_path / "ghost.vertex"
    with pytest.raises(TargetNotFound):
        emit_fact(
            missing,
            "note",
            {"body": "test"},
            observer="tester",
        )


def test_custody_credential_provider_for_write(sample_vertex: Path) -> None:
    """CustodyCredentialProvider returns valid WriteCredentials with signers."""

    # Without keys, signers are None
    provider = CustodyCredentialProvider()
    creds_empty = provider.for_write(sample_vertex)
    assert creds_empty.fact_signer is None
    assert creds_empty.tick_signer is None

    # After creating vertex and observer signing keys, signers become callable
    ensure_signing_key(sample_vertex)
    ensure_signing_key(sample_vertex, "admin")
    creds_with_key = provider.for_write(sample_vertex)
    assert callable(creds_with_key.fact_signer)
    assert callable(creds_with_key.tick_signer)


def test_emit_fact_preserves_custom_origin_and_ts(sample_vertex: Path) -> None:
    """emit_fact correctly forwards origin and ts to the stored fact."""
    fixed_ts = 1712345678.0
    custom_origin = "agent-alpha-9"

    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Provenance test"},
        observer="alice",
        origin=custom_origin,
        ts=fixed_ts,
    )
    assert receipt.stored is True

    page = read_facts(sample_vertex, limit=1)
    fact = page.items[0]
    assert fact["id"] == receipt.id
    assert fact["origin"] == custom_origin
    assert fact["ts"].timestamp() == fixed_ts


def test_emit_fact_default_ts_is_utc_now(sample_vertex: Path) -> None:
    """emit_fact with ts=None defaults to current UTC timestamp."""

    before = datetime.now(UTC).timestamp()
    emit_fact(
        sample_vertex,
        "note",
        {"title": "Timestamp test"},
        observer="alice",
    )
    after = datetime.now(UTC).timestamp()

    page = read_facts(sample_vertex, limit=1)
    fact_ts = page.items[0]["ts"].timestamp()
    assert before <= fact_ts <= after + 1.0


def test_emit_fact_custom_credentials_provider(sample_vertex: Path) -> None:
    """emit_fact respects custom CredentialProvider instances."""
    from engine.handle import WriteCredentials

    called = False

    class MockProvider(CredentialProvider):
        def for_write(self, vertex: Path) -> WriteCredentials:
            nonlocal called
            called = True
            return WriteCredentials(
                tick_signer=lambda data, dt=None: None,
                fact_signer=lambda obs, hash_bytes: None,
            )

    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Custom cred test"},
        observer="alice",
        credentials=MockProvider(),
    )
    assert called is True
    assert receipt.stored is True


def test_emit_fact_corrupt_vertex_raises_emission_failed(tmp_path: Path) -> None:
    """emit_fact raises EmissionFailed if vertex cannot be opened."""
    from sdk import EmissionFailed

    corrupt_vertex = tmp_path / "corrupt.vertex"
    corrupt_vertex.write_text("invalid { [ unclosed", encoding="utf-8")

    with pytest.raises(EmissionFailed) as exc_info:
        emit_fact(
            corrupt_vertex,
            "note",
            {"body": "test"},
            observer="tester",
        )
    assert "could not open vertex" in str(exc_info.value)


# =============================================================================
# 2. Preview & Dry-Run Tests
# =============================================================================


def test_preview_emission_declared_kind(sample_vertex: Path) -> None:
    """preview_emission evaluates declared kind and fold key without disk writes."""
    from sdk import preview_emission

    preview = preview_emission(
        sample_vertex,
        "note",
        {"title": "Preview Note", "body": "Not saved"},
        observer="alice",
    )

    assert isinstance(preview, EmitPreviewResult)
    assert preview.target == str(sample_vertex.resolve())
    assert preview.kind == "note"
    assert preview.observer == "alice"
    assert preview.origin == ""
    assert preview.ts > 0
    assert preview.payload == {"title": "Preview Note", "body": "Not saved"}
    assert preview.kind_declared is True
    assert preview.fold_key_field is None
    assert preview.fold_key_present is True
    assert preview.fold_key_value is None
    assert preview.admitted is True
    assert preview.reason is None
    assert preview.strict is False
    assert preview.would_store is True
    assert preview.would_fold is True

    # Prove store remains completely empty
    summary = read_summary(sample_vertex)
    assert summary.fact_total == 0


def test_preview_emission_strict_rejection(strict_vertex: Path) -> None:
    """preview_emission returns admitted=False when strict vertex rejects kind."""
    preview = preview_emission(
        strict_vertex,
        "unregistered_kind",
        {"k": "v"},
        observer="alice",
        origin="strict-prov",
    )
    assert preview.target == str(strict_vertex.resolve())
    assert preview.kind == "unregistered_kind"
    assert preview.observer == "alice"
    assert preview.origin == "strict-prov"
    assert preview.ts > 0
    assert preview.payload == {"k": "v"}
    assert preview.kind_declared is False
    assert preview.fold_key_field is None
    assert preview.fold_key_present is True
    assert preview.fold_key_value is None
    assert preview.admitted is False
    expected_reason = (
        "vertex 'strict' declares strict — kind 'unregistered_kind' is not declared"
    )
    assert preview.reason == expected_reason
    assert preview.strict is True
    assert preview.would_store is False
    assert preview.would_fold is False


def test_emit_fact_dry_run_returns_uncommitted_receipt(sample_vertex: Path) -> None:
    """emit_fact with dry_run=True performs preflight without storing facts."""
    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Dry run note"},
        observer="alice",
        dry_run=True,
    )

    assert receipt.stored is False
    assert receipt.id == ""
    assert receipt.signed is None
    assert receipt.observer == "alice"
    assert receipt.tick_mark is None
    assert receipt.tick_id is None
    assert receipt.state_change is False
    assert receipt.predicted_state_change is True
    assert receipt.affected_sections == ["note"]
    assert receipt.delta_count == 0

    # Store remains empty
    summary = read_summary(sample_vertex)
    assert summary.fact_total == 0


def test_emit_fact_dry_run_never_claims_stored_or_committed_state_change(
    sample_vertex: Path,
) -> None:
    """Dry-run emissions must never claim stored=True or committed state_change=True."""
    # Case 1: Declared kind that would fold
    receipt_folding = emit_fact(
        sample_vertex,
        "note",
        {"title": "Folding dry run"},
        observer="alice",
        dry_run=True,
    )
    assert receipt_folding.stored is False
    assert receipt_folding.id == ""
    assert receipt_folding.signed is None
    assert receipt_folding.observer == "alice"
    assert receipt_folding.tick_mark is None
    assert receipt_folding.tick_id is None
    assert receipt_folding.state_change is False
    assert receipt_folding.predicted_state_change is True
    assert receipt_folding.delta_count == 0
    assert receipt_folding.affected_sections == ["note"]

    # Case 2: Undeclared kind with admit_undeclared=True (not declared in loops, does not fold)
    receipt_non_folding = emit_fact(
        sample_vertex,
        "custom_unfolded",
        {"data": "Unfolded dry run"},
        observer="alice",
        admit_undeclared=True,
        dry_run=True,
    )
    assert receipt_non_folding.stored is False
    assert receipt_non_folding.id == ""
    assert receipt_non_folding.signed is None
    assert receipt_non_folding.observer == "alice"
    assert receipt_non_folding.tick_mark is None
    assert receipt_non_folding.tick_id is None
    assert receipt_non_folding.state_change is False
    assert receipt_non_folding.predicted_state_change is False
    assert receipt_non_folding.delta_count == 0
    assert receipt_non_folding.affected_sections == []

    # Case 3: Dry run with explicit id_override and timestamp
    receipt_custom = emit_fact(
        sample_vertex,
        "note",
        {"title": "Custom ID dry run"},
        observer="alice",
        id_override="01M01DETERMINISTIC00000001",
        ts=1700000000.0,
        dry_run=True,
    )
    assert receipt_custom.stored is False
    assert receipt_custom.state_change is False
    assert receipt_custom.predicted_state_change is True
    assert receipt_custom.id == ""

    # Ensure store remains completely empty across all dry-run executions
    summary = read_summary(sample_vertex)
    assert summary.fact_total == 0


# =============================================================================
# 3. Batch Emission & Delta Metadata Tests
# =============================================================================


def test_emit_batch_multiple_shapes(sample_vertex: Path) -> None:
    """emit_batch commits a sequence of facts under a single handle session."""
    from atoms import Fact

    from sdk import emit_batch

    items = [
        Fact.of("note", "alice", title="First batch note"),
        ("note", {"title": "Second batch note"}),
        {"kind": "note", "payload": {"title": "Third batch note"}, "observer": "bob"},
    ]

    receipts = emit_batch(sample_vertex, items, observer="alice")

    assert len(receipts) == 3
    assert all(r.stored for r in receipts)
    assert receipts[0].observer == "alice"
    assert receipts[1].observer == "alice"
    assert receipts[2].observer == "bob"

    # All three are in store
    page = read_facts(sample_vertex, limit=10, order="oldest")
    assert len(page.items) == 3
    assert page.items[0]["payload"]["title"] == "First batch note"
    assert page.items[1]["payload"]["title"] == "Second batch note"
    assert page.items[2]["payload"]["title"] == "Third batch note"


def test_emit_fact_delta_metadata(sample_vertex: Path) -> None:
    """EmitReceipt includes affected_sections and delta_count on state changes."""
    receipt = emit_fact(
        sample_vertex,
        "note",
        {"title": "Delta test note"},
        observer="alice",
    )

    assert receipt.stored is True
    assert receipt.state_change is True
    assert isinstance(receipt.affected_sections, list)
    assert receipt.delta_count >= 1
    assert receipt.affected_sections == ["note"]
    assert receipt.predicted_state_change is False


def test_preview_emission_with_fact_atom(sample_vertex: Path) -> None:
    """preview_emission accepts Fact atom and extracts properties."""
    from atoms import Fact

    from sdk import preview_emission

    fact = Fact.of("note", "alice", origin="preview-prov", title="Atom preview")
    preview = preview_emission(sample_vertex, fact)

    assert preview.target == str(sample_vertex.resolve())
    assert preview.kind == "note"
    assert preview.observer == "alice"
    assert preview.origin == "preview-prov"
    assert preview.ts == fact.ts
    assert preview.payload == {"title": "Atom preview"}
    assert preview.kind_declared is True
    assert preview.fold_key_field is None
    assert preview.fold_key_present is True
    assert preview.fold_key_value is None
    assert preview.admitted is True
    assert preview.reason is None
    assert preview.strict is False
    assert preview.would_store is True
    assert preview.would_fold is True


def test_preview_emission_fold_by_matching(tmp_path: Path) -> None:
    """preview_emission detects FoldBy key presence and missing status."""
    from sdk import preview_emission

    vertex = tmp_path / "keyed.vertex"
    vertex.write_text(
        'name "keyed"\nloops {\n  task {\n    fold {\n      items "by" "task_id"\n    }\n  }\n}\n',
        encoding="utf-8",
    )

    # Key present -> would_fold True
    preview_ok = preview_emission(
        vertex, "task", {"task_id": "T-100", "title": "Keyed"}, observer="alice"
    )
    assert preview_ok.target == str(vertex.resolve())
    assert preview_ok.kind == "task"
    assert preview_ok.observer == "alice"
    assert preview_ok.fold_key_field == "task_id"
    assert preview_ok.fold_key_present is True
    assert preview_ok.fold_key_value == "T-100"
    assert preview_ok.admitted is True
    assert preview_ok.would_store is True
    assert preview_ok.would_fold is True

    # Key missing -> would_fold False
    preview_missing = preview_emission(vertex, "task", {"title": "Missing key"}, observer="alice")
    assert preview_missing.target == str(vertex.resolve())
    assert preview_missing.kind == "task"
    assert preview_missing.observer == "alice"
    assert preview_missing.fold_key_field == "task_id"
    assert preview_missing.fold_key_present is False
    assert preview_missing.fold_key_value is None
    assert preview_missing.admitted is True
    assert preview_missing.would_store is True
    assert preview_missing.would_fold is False


def test_preview_emission_target_unsupported(tmp_path: Path) -> None:
    """preview_emission raises TargetUnsupported on non-vertex."""
    from sdk import preview_emission

    log = tmp_path / "bare.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    with pytest.raises(TargetUnsupported) as exc_info:
        preview_emission(log, "note", observer="alice")
    assert "preview_emission requires a .vertex target" in str(exc_info.value)


def test_preview_emission_missing_observer_raises_value_error(sample_vertex: Path) -> None:
    """preview_emission requires observer when kind string is given."""
    from sdk import InvalidEmissionRequest, preview_emission

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        preview_emission(sample_vertex, "note")
    assert str(exc_info.value) == "observer is required when previewing by kind name"
    assert isinstance(exc_info.value, ValueError)


def test_preview_emission_corrupt_vertex_raises_emission_failed(tmp_path: Path) -> None:
    """preview_emission raises EmissionFailed on corrupt vertex declaration."""
    from sdk import EmissionFailed, preview_emission

    corrupt = tmp_path / "corrupt.vertex"
    corrupt.write_text("invalid [ { kdl", encoding="utf-8")

    with pytest.raises(EmissionFailed) as exc_info:
        preview_emission(corrupt, "note", observer="alice")
    assert "could not load vertex declaration" in str(exc_info.value)


def test_emit_batch_target_unsupported(tmp_path: Path) -> None:
    """emit_batch raises TargetUnsupported on non-vertex."""
    from sdk import emit_batch

    log = tmp_path / "bare.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    with pytest.raises(TargetUnsupported) as exc_info:
        emit_batch(log, [("note", {})], observer="alice")
    assert "emit_batch requires a .vertex target" in str(exc_info.value)


def test_emit_batch_corrupt_vertex_raises_emission_failed(tmp_path: Path) -> None:
    """emit_batch raises EmissionFailed on corrupt vertex."""
    from sdk import EmissionFailed, emit_batch

    corrupt = tmp_path / "corrupt.vertex"
    corrupt.write_text("invalid [ { kdl", encoding="utf-8")

    with pytest.raises(EmissionFailed) as exc_info:
        emit_batch(corrupt, [("note", {})], observer="alice")
    assert "could not open vertex" in str(exc_info.value)


def test_emit_batch_missing_observer_tuple_raises_value_error(sample_vertex: Path) -> None:
    """emit_batch with tuples requires default observer."""
    from sdk import InvalidEmissionRequest, emit_batch

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_batch(sample_vertex, [("note", {"title": "No obs"})])
    assert str(exc_info.value) == "observer is required when passing (kind, payload) tuples"
    assert isinstance(exc_info.value, ValueError)


def test_emit_batch_missing_observer_dict_raises_value_error(sample_vertex: Path) -> None:
    """emit_batch with dict item requires observer in dict or default."""
    from sdk import InvalidEmissionRequest, emit_batch

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_batch(sample_vertex, [{"kind": "note", "payload": {"title": "No obs"}}])
    assert str(exc_info.value) == "observer is required for dict fact"
    assert isinstance(exc_info.value, ValueError)


def test_emit_batch_unsupported_shape_raises_value_error(sample_vertex: Path) -> None:
    """emit_batch rejects invalid item shapes."""
    from sdk import InvalidEmissionRequest, emit_batch

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_batch(sample_vertex, [12345])  # type: ignore[list-item]
    assert "unsupported batch fact item shape" in str(exc_info.value)
    assert isinstance(exc_info.value, ValueError)


def test_emit_batch_dict_custom_id_and_ts(sample_vertex: Path) -> None:
    """emit_batch supports dict items with custom id, origin, and ts."""
    from sdk import emit_batch

    custom_id = "01M01BATCHCUSTOMID00000001"
    items = [
        {
            "kind": "note",
            "payload": {"title": "Custom dict fact"},
            "observer": "agent-z",
            "origin": "batch-importer",
            "ts": 1712345678.0,
            "id": custom_id,
        }
    ]

    receipts = emit_batch(sample_vertex, items)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.id == custom_id
    assert receipt.observer == "agent-z"

    fact = read_facts(sample_vertex, limit=1).items[0]
    assert fact["id"] == custom_id
    assert fact["observer"] == "agent-z"
    assert fact["origin"] == "batch-importer"
    assert fact["ts"].timestamp() == 1712345678.0


def test_emit_batch_strict_rejection_raises_admission_failed(strict_vertex: Path) -> None:
    """emit_batch raises AdmissionFailed when strict vertex rejects kind."""
    items = [("undeclared_kind", {"key": "val"})]
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_batch(strict_vertex, items, observer="alice")
    assert exc_info.value.observer == "alice"
    assert exc_info.value.kind == "undeclared_kind"
    assert exc_info.value.vertex == "strict"
    assert "undeclared_kind" in str(exc_info.value)


# =============================================================================
# 4. Additional Survivor Burn-down Tests
# =============================================================================


def test_preview_emission_custom_origin_and_ts(sample_vertex: Path) -> None:
    """preview_emission preserves explicit origin and timestamp."""
    fixed_ts = 1712345678.0
    preview = preview_emission(
        sample_vertex,
        "note",
        {"title": "Custom Preview"},
        observer="alice",
        origin="preview-origin",
        ts=fixed_ts,
    )
    assert preview.target == str(sample_vertex.resolve())
    assert preview.kind == "note"
    assert preview.observer == "alice"
    assert preview.origin == "preview-origin"
    assert preview.ts == fixed_ts
    assert preview.payload == {"title": "Custom Preview"}
    assert preview.kind_declared is True
    assert preview.fold_key_field is None
    assert preview.fold_key_present is True
    assert preview.fold_key_value is None
    assert preview.admitted is True
    assert preview.reason is None
    assert preview.strict is False
    assert preview.would_store is True
    assert preview.would_fold is True


def test_preview_emission_observer_admission_failure(tmp_path: Path) -> None:
    """preview_emission evaluates observer admission ACL grants."""
    vertex = tmp_path / "acl.vertex"
    content = (
        'name "acl_vertex"\n'
        'store ".loops/data/acl.db"\n'
        "observers {\n"
        "  bob\n"
        "}\n"
        "loops {\n"
        "  note {\n"
        "    fold {\n"
        '      items "collect" 100\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    vertex.write_text(content, encoding="utf-8")
    preview = preview_emission(
        vertex,
        "note",
        {"title": "Unauthorized"},
        observer="intruder",
        origin="outside",
        ts=1710000000.0,
    )
    assert preview.target == str(vertex.resolve())
    assert preview.kind == "note"
    assert preview.observer == "intruder"
    assert preview.origin == "outside"
    assert preview.ts == 1710000000.0
    assert preview.admitted is False
    assert preview.reason is not None
    assert "intruder" in preview.reason
    assert preview.would_store is False
    assert preview.would_fold is False
    assert preview.fold_key_field is None
    assert preview.fold_key_value is None


def test_preview_emission_strict_with_admit_undeclared(strict_vertex: Path) -> None:
    """preview_emission with admit_undeclared=True allows undeclared kinds on strict vertices."""
    preview = preview_emission(
        strict_vertex,
        "custom_kind",
        {"key": "val"},
        observer="alice",
        origin="sim",
        ts=1700000000.0,
        admit_undeclared=True,
    )
    assert preview.target == str(strict_vertex.resolve())
    assert preview.kind == "custom_kind"
    assert preview.observer == "alice"
    assert preview.origin == "sim"
    assert preview.ts == 1700000000.0
    assert preview.payload == {"key": "val"}
    assert preview.kind_declared is False
    assert preview.fold_key_field is None
    assert preview.fold_key_present is True
    assert preview.fold_key_value is None
    assert preview.admitted is True
    assert preview.reason is None
    assert preview.strict is True
    assert preview.would_store is True
    assert preview.would_fold is False


def test_preview_emission_non_strict_undeclared(sample_vertex: Path) -> None:
    """preview_emission on non-strict vertex admits undeclared kinds but flags would_fold=False."""
    preview = preview_emission(
        sample_vertex,
        "undeclared_kind",
        {"data": 123},
        observer="alice",
        origin="prov",
        ts=1700000000.0,
    )
    assert preview.target == str(sample_vertex.resolve())
    assert preview.kind == "undeclared_kind"
    assert preview.observer == "alice"
    assert preview.origin == "prov"
    assert preview.ts == 1700000000.0
    assert preview.payload == {"data": 123}
    assert preview.kind_declared is False
    assert preview.fold_key_field is None
    assert preview.fold_key_present is True
    assert preview.fold_key_value is None
    assert preview.admitted is True
    assert preview.reason is None
    assert preview.strict is False
    assert preview.would_store is True
    assert preview.would_fold is False


def test_preview_emission_strict_reason_uses_declared_ast_name(tmp_path: Path) -> None:
    """preview_emission strict rejection reason uses declared ast name over file stem."""
    v = tmp_path / "different_file_name.vertex"
    content = (
        'name "declared_name"\n'
        'store ".loops/data/named.db"\n'
        "strict true\n"
        "loops {\n"
        "  note {\n"
        "    fold {\n"
        '      items "collect" 10\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    v.write_text(content, encoding="utf-8")
    preview = preview_emission(v, "bad_kind", {}, observer="alice")
    assert preview.admitted is False
    expected_msg = (
        "vertex 'declared_name' declares strict — kind 'bad_kind' is not declared"
    )
    assert preview.reason == expected_msg
    assert preview.strict is True


def test_preview_emission_fact_empty_payload(tmp_path: Path) -> None:
    """preview_emission handles Fact atoms with None payload."""
    fact = Fact(
        kind="note",
        ts=1700000000.0,
        payload=None,
        observer="alice",
        origin="prov",
    )
    v = tmp_path / "test_fact.vertex"
    content = (
        'name "test"\n'
        'store ".loops/data/test.db"\n'
        "loops {\n"
        "  note {\n"
        "    fold {\n"
        '      items "collect" 10\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    v.write_text(content, encoding="utf-8")
    preview = preview_emission(v, fact)
    assert preview.payload == {}
    assert preview.origin == "prov"
    assert preview.ts == 1700000000.0


def test_emit_fact_dry_run_strict_rejection(strict_vertex: Path) -> None:
    """emit_fact in dry_run mode raises AdmissionFailed on strict rejection."""
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_fact(
            strict_vertex,
            "undeclared_kind",
            {"k": "v"},
            observer="alice",
            dry_run=True,
        )
    assert exc_info.value.observer == "alice"
    assert exc_info.value.kind == "undeclared_kind"
    assert "strict" in str(exc_info.value)


def test_emit_fact_dry_run_observer_rejection(tmp_path: Path) -> None:
    """emit_fact in dry_run mode raises AdmissionFailed on observer ACL rejection."""
    v = tmp_path / "acl.vertex"
    content = (
        'name "acl"\n'
        'store ".loops/data/acl.db"\n'
        "observers {\n"
        "  bob\n"
        "}\n"
        "loops {\n"
        "  note {\n"
        "    fold {\n"
        '      items "collect" 10\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    v.write_text(content, encoding="utf-8")
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_fact(v, "note", {"title": "X"}, observer="intruder", dry_run=True)
    assert exc_info.value.observer == "intruder"
    assert exc_info.value.kind == "note"
    assert "intruder" in str(exc_info.value)


def test_emit_fact_missing_payload_raises_invalid_emission_request(
    sample_vertex: Path,
) -> None:
    """emit_fact requires payload when emitting by kind name."""
    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_fact(sample_vertex, "note", None, observer="alice")
    assert str(exc_info.value) == "payload dictionary is required when emitting by kind name"
    assert isinstance(exc_info.value, ValueError)


def test_emit_fact_default_origin(sample_vertex: Path) -> None:
    """emit_fact defaults origin to empty string."""
    receipt = emit_fact(sample_vertex, "note", {"title": "No Origin"}, observer="alice")
    assert receipt.stored is True
    page = read_facts(sample_vertex, limit=1)
    assert page.items[0]["origin"] == ""


def test_emit_fact_receive_committed_error_handling(
    sample_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """emit_fact maps ReceiveCommittedError to CommittedEmissionError."""
    def fake_receive_as(*args: Any, **kwargs: Any) -> Any:
        raise ReceiveCommittedError(
            "01TESTFACTID0000000000000", None, RuntimeError("tick write failed")
        )

    monkeypatch.setattr("engine.handle.VertexHandle.receive_as", fake_receive_as)
    with pytest.raises(CommittedEmissionError) as exc_info:
        emit_fact(sample_vertex, "note", {"title": "Fail"}, observer="alice")
    assert exc_info.value.fact_id == "01TESTFACTID0000000000000"
    assert "01TESTFACTID0000000000000" in str(exc_info.value)
    assert "tick write failed" in str(exc_info.value)


def test_emit_fact_unhandled_exception_wrapped_in_emission_failed(
    sample_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """emit_fact wraps unexpected runtime errors in EmissionFailed."""
    def fake_receive_as(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database locked unexpectedly")

    monkeypatch.setattr("engine.handle.VertexHandle.receive_as", fake_receive_as)
    with pytest.raises(EmissionFailed) as exc_info:
        emit_fact(sample_vertex, "note", {"title": "Crash"}, observer="alice")
    assert "fact emission failed: database locked unexpectedly" in str(exc_info.value)


def test_emit_fact_unsigned_tick_fields_are_none(sample_vertex: Path) -> None:
    """emit_fact on an unsigned vertex returns tick_mark=None and tick_id=None."""
    receipt = emit_fact(sample_vertex, "note", {"title": "Unsigned"}, observer="alice")
    assert receipt.stored is True
    assert receipt.signed is False
    assert receipt.tick_mark is None
    assert receipt.tick_id is None
    assert receipt.state_change is True
    assert receipt.delta_count >= 1
    assert receipt.predicted_state_change is False


def test_emit_fact_atom_admission_failed_properties(strict_vertex: Path) -> None:
    """emit_fact with Fact atom carries observer, kind, and vertex on AdmissionFailed."""
    fact = Fact.of("bad_custom_kind", "bob")
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_fact(strict_vertex, fact)
    assert exc_info.value.observer == "bob"
    assert exc_info.value.kind == "bad_custom_kind"
    assert exc_info.value.vertex == "strict"


def test_emit_batch_empty_list_returns_empty_list(sample_vertex: Path) -> None:
    """emit_batch returns [] when given empty facts list."""
    receipts = emit_batch(sample_vertex, [])
    assert receipts == []


def test_emit_batch_3_tuple_item_with_ts_and_origin(sample_vertex: Path) -> None:
    """emit_batch supports (kind, payload, timestamp) 3-tuples."""
    fixed_ts = 1712345678.0
    items = [("note", {"title": "3-tuple Note"}, fixed_ts)]
    receipts = emit_batch(sample_vertex, items, observer="alice", origin="tuple-origin")
    assert len(receipts) == 1
    r = receipts[0]
    assert r.stored is True
    assert r.observer == "alice"
    assert r.predicted_state_change is False

    page = read_facts(sample_vertex, limit=1)
    fact = page.items[0]
    assert fact["payload"]["title"] == "3-tuple Note"
    assert fact["origin"] == "tuple-origin"
    assert fact["ts"].timestamp() == fixed_ts


def test_emit_batch_invalid_tuple_length_raises_invalid_emission_request(
    sample_vertex: Path,
) -> None:
    """emit_batch rejects 1-tuples or 4-tuples with InvalidEmissionRequest."""
    with pytest.raises(InvalidEmissionRequest) as exc1:
        emit_batch(sample_vertex, [("note",)], observer="alice")  # type: ignore[list-item]
    assert "unsupported batch fact item shape" in str(exc1.value)

    with pytest.raises(InvalidEmissionRequest) as exc4:
        emit_batch(sample_vertex, [("note", {}, 123.0, "extra")], observer="alice")  # type: ignore[list-item]
    assert "unsupported batch fact item shape" in str(exc4.value)


def test_emit_batch_dict_defaults_and_validation(sample_vertex: Path) -> None:
    """emit_batch validates dict items and applies defaults for missing fields."""
    # Missing kind key
    with pytest.raises(InvalidEmissionRequest) as exc_nokind:
        emit_batch(sample_vertex, [{"payload": {"a": 1}}], observer="alice")
    assert "batch item dict missing 'kind'" in str(exc_nokind.value)

    # Empty kind string
    with pytest.raises(InvalidEmissionRequest) as exc_emptykind:
        emit_batch(sample_vertex, [{"kind": ""}], observer="alice")
    assert "batch item dict missing 'kind'" in str(exc_emptykind.value)

    # Dict without payload or origin or ts - defaults applied
    items = [{"kind": "note"}]
    receipts = emit_batch(
        sample_vertex, items, observer="alice", origin="batch-def-origin"
    )
    assert len(receipts) == 1
    assert receipts[0].stored is True
    assert receipts[0].observer == "alice"

    page = read_facts(sample_vertex, limit=1)
    fact = page.items[0]
    assert fact["payload"] == {}
    assert fact["origin"] == "batch-def-origin"
    assert fact["observer"] == "alice"


def test_emit_batch_signed_receipt_fields(sample_vertex: Path) -> None:
    """emit_batch produces signed receipts with tick info when keys exist."""
    ensure_signing_key(sample_vertex)
    ensure_signing_key(sample_vertex, "trusted_observer")

    receipts = emit_batch(
        sample_vertex,
        [("note", {"title": "Signed Batch Note"})],
        observer="trusted_observer",
    )
    assert len(receipts) == 1
    r = receipts[0]
    assert r.stored is True
    assert r.signed is True
    assert r.tick_id is None
    assert r.tick_mark is None
    assert r.state_change is True
    assert r.affected_sections == ["note"]
    assert r.delta_count >= 1
    assert r.predicted_state_change is False


def test_emit_batch_unsigned_unfolded_receipt_fields(sample_vertex: Path) -> None:
    """emit_batch on an unsigned vertex with unfolded kind has state_change=True, delta_count=0."""
    receipts = emit_batch(
        sample_vertex,
        [("unfolded_custom", {"data": 123})],
        observer="alice",
        admit_undeclared=True,
    )
    assert len(receipts) == 1
    r = receipts[0]
    assert r.stored is True
    assert r.signed is False
    assert r.tick_id is None
    assert r.tick_mark is None
    assert r.state_change is True
    assert r.affected_sections == []
    assert r.delta_count == 0
    assert r.predicted_state_change is False


def test_emit_batch_receive_committed_error_handling(
    sample_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """emit_batch maps ReceiveCommittedError to CommittedEmissionError."""
    def fake_receive_as(*args: Any, **kwargs: Any) -> Any:
        raise ReceiveCommittedError(
            "01BATCHCOMMITID0000000000", None, RuntimeError("tick write failed")
        )

    monkeypatch.setattr("engine.handle.VertexHandle.receive_as", fake_receive_as)
    with pytest.raises(CommittedEmissionError) as exc_info:
        emit_batch(sample_vertex, [("note", {"title": "Fail"})], observer="alice")
    assert exc_info.value.fact_id == "01BATCHCOMMITID0000000000"
    assert "01BATCHCOMMITID0000000000" in str(exc_info.value)


def test_emit_fact_missing_observer_raises_invalid_emission_request(
    sample_vertex: Path,
) -> None:
    """emit_fact requires observer when emitting by kind name."""
    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_fact(sample_vertex, "note", {"title": "No Obs"}, observer=None)
    assert str(exc_info.value) == "observer is required when emitting by kind name"


def test_emit_fact_strict_admit_undeclared(strict_vertex: Path) -> None:
    """emit_fact on strict vertex with admit_undeclared=True succeeds."""
    receipt = emit_fact(
        strict_vertex,
        "undeclared_note",
        {"content": "bypassed"},
        observer="alice",
        admit_undeclared=True,
    )
    assert receipt.stored is True
    assert receipt.delta_count == 0
    assert receipt.state_change is True
    assert receipt.affected_sections == []
    assert receipt.predicted_state_change is False


def test_emit_fact_dry_run_with_admit_undeclared_on_strict(
    strict_vertex: Path,
) -> None:
    """emit_fact in dry_run mode respects admit_undeclared=True."""
    receipt = emit_fact(
        strict_vertex,
        "undeclared_dry",
        {"content": "dry"},
        observer="alice",
        origin="dry-origin",
        ts=1700000000.0,
        admit_undeclared=True,
        dry_run=True,
    )
    assert receipt.stored is False
    assert receipt.id == ""
    assert receipt.observer == "alice"
    assert receipt.signed is None
    assert receipt.tick_mark is None
    assert receipt.tick_id is None
    assert receipt.state_change is False
    assert receipt.affected_sections == []
    assert receipt.delta_count == 0
    assert receipt.predicted_state_change is False


def test_emit_fact_unknown_observer_admission_failed_properties(
    tmp_path: Path,
) -> None:
    """emit_fact captures observer, kind, and vertex from UnknownObserver."""
    v = tmp_path / "acl_fact.vertex"
    content = (
        'name "acl_fact_vertex"\n'
        'store ".loops/data/acl.db"\n'
        "observers {\n"
        "  bob\n"
        "}\n"
        "loops {\n"
        "  note {\n"
        "    fold {\n"
        '      items "collect" 10\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    v.write_text(content, encoding="utf-8")
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_fact(v, "note", {"title": "Secret"}, observer="intruder")
    assert exc_info.value.observer == "intruder"
    assert exc_info.value.kind == "note"
    assert exc_info.value.vertex == "acl_fact_vertex"


def test_emit_batch_strict_admit_undeclared(strict_vertex: Path) -> None:
    """emit_batch on strict vertex with admit_undeclared=True succeeds."""
    receipts = emit_batch(
        strict_vertex,
        [("custom_item", {"data": 1})],
        observer="alice",
        admit_undeclared=True,
    )
    assert len(receipts) == 1
    r = receipts[0]
    assert r.stored is True
    assert r.delta_count == 0
    assert r.state_change is True
    assert r.affected_sections == []


def test_emit_batch_default_origin_and_tuple_origin(sample_vertex: Path) -> None:
    """emit_batch defaults origin to empty string and applies origin to 2-tuples."""
    receipts1 = emit_batch(
        sample_vertex, [("note", {"title": "Default"})], observer="alice"
    )
    assert len(receipts1) == 1
    receipts2 = emit_batch(
        sample_vertex,
        [("note", {"title": "Custom"})],
        observer="alice",
        origin="batch-custom-prov",
    )
    assert len(receipts2) == 1

    page = read_facts(sample_vertex, limit=10)
    assert page.items[0]["origin"] == "batch-custom-prov"
    assert page.items[1]["origin"] == ""


def test_emit_batch_unknown_observer_admission_failed_properties(
    tmp_path: Path,
) -> None:
    """emit_batch captures observer, kind=None, and vertex from UnknownObserver."""
    v = tmp_path / "acl_batch.vertex"
    content = (
        'name "acl_batch_vertex"\n'
        'store ".loops/data/acl.db"\n'
        "observers {\n"
        "  bob\n"
        "}\n"
        "loops {\n"
        "  note {\n"
        "    fold {\n"
        '      items "collect" 10\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    v.write_text(content, encoding="utf-8")
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_batch(v, [("note", {"title": "Secret"})], observer="intruder")
    assert exc_info.value.observer == "intruder"
    assert exc_info.value.kind is None
    assert exc_info.value.vertex == "acl_batch_vertex"


def test_emit_batch_unhandled_exception_wrapped_in_emission_failed(
    sample_vertex: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """emit_batch wraps unexpected runtime errors in EmissionFailed."""
    def fake_receive_as(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("batch storage crashed")

    monkeypatch.setattr("engine.handle.VertexHandle.receive_as", fake_receive_as)
    with pytest.raises(EmissionFailed) as exc_info:
        emit_batch(sample_vertex, [("note", {"title": "Crash"})], observer="alice")
    assert str(exc_info.value) == "batch emission failed: batch storage crashed"


def test_emit_fact_firing_boundary_populates_tick_fields(tmp_path: Path) -> None:
    """A boundary-firing emission must not crash and must carry tick fields.

    Regression: emit_fact read ``receipt.tick.id`` but the in-memory engine
    Tick has no id (the store assigns it on the tick row), so every
    boundary-firing emission died with AttributeError.
    """
    vertex_path = tmp_path / "bounded.vertex"
    vertex_path.write_text(
        'name "bounded"\n'
        'store ".loops/data/bounded.db"\n'
        "\n"
        "loops {\n"
        "  event {\n"
        "    fold {\n"
        '      total "count"\n'
        "    }\n"
        "    boundary every=1\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    receipt = emit_fact(vertex_path, "event", {"n": 1}, observer="tester")
    assert receipt.stored is True
    assert receipt.tick_mark == "event"
    assert receipt.tick_id  # store-assigned id recovered from the ChangeBatch

    batch = emit_batch(vertex_path, [("event", {"n": 2}), ("event", {"n": 3})], observer="tester")
    for r in batch:
        assert r.stored is True
        assert r.tick_mark == "event"
        assert r.tick_id
