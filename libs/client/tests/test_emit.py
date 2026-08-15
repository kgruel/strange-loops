"""Integration and contract tests for client fact emission operations."""

from __future__ import annotations

from pathlib import Path

import pytest
from custody import ensure_signing_key

from client import (
    AdmissionFailed,
    EmitReceipt,
    TargetNotFound,
    TargetUnsupported,
    emit_fact,
    read_facts,
    read_summary,
)


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
    from client import InvalidEmissionRequest

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


def test_emit_fact_unsupported_on_non_vertex(tmp_path: Path) -> None:
    """emit_fact raises TargetUnsupported when given a non-vertex target."""
    log_path = tmp_path / "standalone.jsonl"
    log_path.write_text('{"kind": "note"}\n', encoding="utf-8")

    with pytest.raises(TargetUnsupported):
        emit_fact(
            log_path,
            "note",
            {"body": "test"},
            observer="tester",
        )


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
    from client.emit import CustodyCredentialProvider

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
    from datetime import UTC, datetime

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
    from engine.handle import CredentialProvider, WriteCredentials

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
    from client import EmissionFailed

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
    from client import EmitPreviewResult, preview_emission

    preview = preview_emission(
        sample_vertex,
        "note",
        {"title": "Preview Note", "body": "Not saved"},
        observer="alice",
    )

    assert isinstance(preview, EmitPreviewResult)
    assert preview.kind == "note"
    assert preview.observer == "alice"
    assert preview.kind_declared is True
    assert preview.admitted is True
    assert preview.would_store is True
    assert preview.would_fold is True

    # Prove store remains completely empty
    summary = read_summary(sample_vertex)
    assert summary.fact_total == 0


def test_preview_emission_strict_rejection(strict_vertex: Path) -> None:
    """preview_emission returns admitted=False when strict vertex rejects kind."""
    from client import preview_emission

    preview = preview_emission(
        strict_vertex,
        "unregistered_kind",
        {"k": "v"},
        observer="alice",
    )
    assert preview.admitted is False
    assert preview.kind == "unregistered_kind"
    assert preview.would_store is False
    assert "strict" in (preview.reason or "")


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
    assert receipt.state_change is True
    assert "note" in receipt.affected_sections

    # Store remains empty
    summary = read_summary(sample_vertex)
    assert summary.fact_total == 0


# =============================================================================
# 3. Batch Emission & Delta Metadata Tests
# =============================================================================


def test_emit_batch_multiple_shapes(sample_vertex: Path) -> None:
    """emit_batch commits a sequence of facts under a single handle session."""
    from atoms import Fact

    from client import emit_batch

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
    assert "note" in receipt.affected_sections


def test_preview_emission_with_fact_atom(sample_vertex: Path) -> None:
    """preview_emission accepts Fact atom and extracts properties."""
    from atoms import Fact

    from client import preview_emission

    fact = Fact.of("note", "alice", origin="preview-prov", title="Atom preview")
    preview = preview_emission(sample_vertex, fact)

    assert preview.kind == "note"
    assert preview.observer == "alice"
    assert preview.origin == "preview-prov"
    assert preview.payload["title"] == "Atom preview"
    assert preview.admitted is True


def test_preview_emission_fold_by_matching(tmp_path: Path) -> None:
    """preview_emission detects FoldBy key presence and missing status."""
    from client import preview_emission

    vertex = tmp_path / "keyed.vertex"
    vertex.write_text(
        'name "keyed"\nloops {\n  task {\n    fold {\n      items "by" "task_id"\n    }\n  }\n}\n',
        encoding="utf-8",
    )

    # Key present -> would_fold True
    preview_ok = preview_emission(
        vertex, "task", {"task_id": "T-100", "title": "Keyed"}, observer="alice"
    )
    assert preview_ok.fold_key_field == "task_id"
    assert preview_ok.fold_key_present is True
    assert preview_ok.fold_key_value == "T-100"
    assert preview_ok.would_fold is True

    # Key missing -> would_fold False
    preview_missing = preview_emission(vertex, "task", {"title": "Missing key"}, observer="alice")
    assert preview_missing.fold_key_field == "task_id"
    assert preview_missing.fold_key_present is False
    assert preview_missing.fold_key_value is None
    assert preview_missing.would_fold is False


def test_preview_emission_target_unsupported(tmp_path: Path) -> None:
    """preview_emission raises TargetUnsupported on non-vertex."""
    from client import preview_emission

    log = tmp_path / "bare.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    with pytest.raises(TargetUnsupported) as exc_info:
        preview_emission(log, "note", observer="alice")
    assert "preview_emission requires a .vertex target" in str(exc_info.value)


def test_preview_emission_missing_observer_raises_value_error(sample_vertex: Path) -> None:
    """preview_emission requires observer when kind string is given."""
    from client import InvalidEmissionRequest, preview_emission

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        preview_emission(sample_vertex, "note")
    assert "observer is required" in str(exc_info.value)
    assert isinstance(exc_info.value, ValueError)


def test_preview_emission_corrupt_vertex_raises_emission_failed(tmp_path: Path) -> None:
    """preview_emission raises EmissionFailed on corrupt vertex declaration."""
    from client import EmissionFailed, preview_emission

    corrupt = tmp_path / "corrupt.vertex"
    corrupt.write_text("invalid [ { kdl", encoding="utf-8")

    with pytest.raises(EmissionFailed) as exc_info:
        preview_emission(corrupt, "note", observer="alice")
    assert "could not load vertex declaration" in str(exc_info.value)


def test_emit_batch_target_unsupported(tmp_path: Path) -> None:
    """emit_batch raises TargetUnsupported on non-vertex."""
    from client import emit_batch

    log = tmp_path / "bare.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    with pytest.raises(TargetUnsupported) as exc_info:
        emit_batch(log, [("note", {})], observer="alice")
    assert "emit_batch requires a .vertex target" in str(exc_info.value)


def test_emit_batch_corrupt_vertex_raises_emission_failed(tmp_path: Path) -> None:
    """emit_batch raises EmissionFailed on corrupt vertex."""
    from client import EmissionFailed, emit_batch

    corrupt = tmp_path / "corrupt.vertex"
    corrupt.write_text("invalid [ { kdl", encoding="utf-8")

    with pytest.raises(EmissionFailed) as exc_info:
        emit_batch(corrupt, [("note", {})], observer="alice")
    assert "could not open vertex" in str(exc_info.value)


def test_emit_batch_missing_observer_tuple_raises_value_error(sample_vertex: Path) -> None:
    """emit_batch with tuples requires default observer."""
    from client import InvalidEmissionRequest, emit_batch

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_batch(sample_vertex, [("note", {"title": "No obs"})])
    assert "observer is required when passing (kind, payload) tuples" in str(exc_info.value)
    assert isinstance(exc_info.value, ValueError)


def test_emit_batch_missing_observer_dict_raises_value_error(sample_vertex: Path) -> None:
    """emit_batch with dict item requires observer in dict or default."""
    from client import InvalidEmissionRequest, emit_batch

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_batch(sample_vertex, [{"kind": "note", "payload": {"title": "No obs"}}])
    assert "observer is required for dict fact" in str(exc_info.value)
    assert isinstance(exc_info.value, ValueError)


def test_emit_batch_unsupported_shape_raises_value_error(sample_vertex: Path) -> None:
    """emit_batch rejects invalid item shapes."""
    from client import InvalidEmissionRequest, emit_batch

    with pytest.raises(InvalidEmissionRequest) as exc_info:
        emit_batch(sample_vertex, [12345])  # type: ignore[list-item]
    assert "unsupported batch fact item shape" in str(exc_info.value)
    assert isinstance(exc_info.value, ValueError)


def test_emit_batch_dict_custom_id_and_ts(sample_vertex: Path) -> None:
    """emit_batch supports dict items with custom id, origin, and ts."""
    from client import emit_batch

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
    from client import emit_batch

    items = [("undeclared_kind", {"key": "val"})]
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_batch(strict_vertex, items, observer="alice")
    assert "undeclared" in str(exc_info.value).lower() or "strict" in str(exc_info.value).lower()
