"""Integration and contract tests for client fact emission operations."""

from __future__ import annotations

from pathlib import Path

import pytest
from client import (
    AdmissionFailed,
    EmitReceipt,
    TargetNotFound,
    TargetUnsupported,
    emit_fact,
    read_facts,
    read_summary,
)
from custody import ensure_signing_key


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
    """Emitting an undeclared kind on a strict vertex without admit_undeclared raises AdmissionFailed."""
    with pytest.raises(AdmissionFailed) as exc_info:
        emit_fact(
            strict_vertex,
            "undeclared_custom_kind",
            {"key": "value"},
            observer="alice",
        )
    assert "undeclared" in str(exc_info.value).lower() or "admission" in str(exc_info.value).lower()


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
    receipt = emit_fact(
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
