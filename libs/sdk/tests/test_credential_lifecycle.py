"""Public outcomes for explicit mapped-credential lifecycle mutations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from custody import ensure_signing_key
from engine.credentials import CredentialPurpose, CredentialRequest, SigningDomain

from sdk import (
    CredentialBindingConflict,
    CredentialBindingIncomplete,
    CredentialBindingRecoveryRequired,
    CredentialBindingResult,
    MappedCredentialProvider,
    SdkValueError,
)


@pytest.fixture(autouse=True)
def _isolated_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops"))


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _provider(tmp_path: Path) -> MappedCredentialProvider:
    return MappedCredentialProvider(
        tmp_path / "bindings", namespace="tenant/a", receipt_observer="alice"
    )


def test_lifecycle_results_are_serializable_and_resolution_stays_read_only(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    created = provider.create_binding("alice", token="create-alice")

    assert isinstance(created, CredentialBindingResult)
    assert created.operation == "create"
    assert created.namespace == "tenant/a"
    assert created.observer == "alice"
    assert created.binding_created is True
    serialized = created.as_dict()
    assert serialized["schema"] == "loops.sdk/credential-binding/v1"
    assert serialized["key_ref"] == created.key_ref
    assert json.loads(json.dumps(serialized, allow_nan=False)) == serialized
    private = (provider.root / "keys-v1" / created.key_ref / "ed25519.key").read_text()
    assert private not in json.dumps(serialized)
    assert "bindings-v1" not in json.dumps(serialized)

    before = _files(provider.root)
    resolved = provider.resolve(
        CredentialRequest(
            provider.namespace,
            "alice",
            SigningDomain.FACT,
            CredentialPurpose.AUTHORSHIP,
        )
    )
    assert resolved is not None and resolved.evidence.key_ref == created.key_ref
    assert _files(provider.root) == before

    repeated = provider.create_binding("alice", token="create-alice")
    assert repeated.key_ref == created.key_ref
    assert repeated.public_key == created.public_key
    assert repeated.binding_created is False
    assert repeated.key_created is False


def test_lifecycle_incomplete_retains_reconciliation_evidence(tmp_path: Path) -> None:
    provider = _provider(tmp_path)

    def interrupt(phase: str, _intent: dict[str, object]) -> None:
        if phase == "binding-published":
            raise OSError("injected publication interruption")

    provider._creation_hook = interrupt
    with pytest.raises(CredentialBindingIncomplete) as raised:
        provider.create_binding("alice", token="recover-alice")

    error = raised.value
    assert error.operation == "create"
    assert error.namespace == provider.namespace
    assert error.observer == "alice"
    assert error.token == "recover-alice"
    assert error.key_ref is not None
    assert error.phase == "binding-published"
    assert error.source_type == "BindingMutationIncomplete"
    assert error.outcome == "incomplete"
    assert error.recovery_action == "reconcile"
    assert error.as_dict()["phase"] == "binding-published"
    assert "commit" not in error.as_dict()
    assert json.loads(json.dumps(error.as_dict(), allow_nan=False)) == error.as_dict()

    provider._creation_hook = None
    recovered = provider.recover_binding("alice", token="recover-alice")
    assert recovered.operation == "recover"
    assert recovered.key_ref == error.key_ref
    assert recovered.binding_created is False


def test_lifecycle_conflict_recovery_and_input_errors_are_typed(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    alice = provider.create_binding("alice", token="alice-token")

    pending_provider = MappedCredentialProvider(
        tmp_path / "pending-bindings", namespace="tenant/a"
    )

    def interrupt(phase: str, _intent: dict[str, object]) -> None:
        if phase == "intent-published":
            raise OSError("leave pending intent")

    pending_provider._creation_hook = interrupt
    with pytest.raises(CredentialBindingIncomplete):
        pending_provider.create_binding("alice", token="pending-token")
    pending_provider._creation_hook = None
    pending_before = _files(pending_provider.root)
    with pytest.raises(CredentialBindingRecoveryRequired) as recovery:
        pending_provider.create_binding("alice", token="different-token")
    assert recovery.value.as_dict()["operation"] == "create"
    assert recovery.value.as_dict()["token"] == "different-token"
    assert recovery.value.as_dict()["outcome"] == "refused"
    assert _files(pending_provider.root) == pending_before

    before_token_conflict = _files(provider.root)
    with pytest.raises(CredentialBindingConflict) as conflict:
        provider.create_binding("bob", token="alice-token")
    assert conflict.value.as_dict()["observer"] == "bob"
    assert conflict.value.as_dict()["recovery_action"] == "reconcile"
    assert _files(provider.root) == before_token_conflict

    before_wrong_key = _files(provider.root)
    with pytest.raises(CredentialBindingIncomplete) as wrong_key:
        provider.bind_existing_ref(
            "carol", alice.key_ref, "not-the-managed-public-key", token="wrong-key"
        )
    assert wrong_key.value.source_type == "ValueError"
    assert _files(provider.root) == before_wrong_key
    assert provider.resolve(
        CredentialRequest(
            provider.namespace,
            "carol",
            SigningDomain.FACT,
            CredentialPurpose.AUTHORSHIP,
        )
    ) is None

    shared = provider.bind_existing_ref(
        "bob", alice.key_ref, alice.public_key, token="share-alice"
    )
    assert shared.operation == "bind-existing-ref"
    assert shared.key_ref == alice.key_ref
    with pytest.raises(SdkValueError, match="key_ref must be a non-empty string"):
        provider.bind_existing_ref("carol", None, alice.public_key, token="bad")  # type: ignore[arg-type]
    with pytest.raises(SdkValueError, match="vertex_path must be a path string or Path"):
        provider.import_legacy(None, "carol", token="bad")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("failure_type", "source_type"),
    [(OSError, "OSError"), (TypeError, "TypeError")],
)
def test_raw_post_marker_custody_failures_keep_unknown_phase_and_reconcile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[Exception],
    source_type: str,
) -> None:
    provider = _provider(tmp_path)
    original_index = provider._ensure_token_index

    def interrupt_index(_intent: dict[str, object]) -> None:
        raise failure_type("injected token-index failure")

    monkeypatch.setattr(provider, "_ensure_token_index", interrupt_index)
    with pytest.raises(CredentialBindingIncomplete) as raised:
        provider.create_binding("alice", token="index-token")
    error = raised.value
    assert error.operation == "create"
    assert error.namespace == provider.namespace
    assert error.observer == "alice"
    assert error.token == "index-token"
    assert error.phase == "unknown"
    assert error.source_type == source_type
    assert error.key_ref is None
    pending = json.loads(next((provider.root / "pending-v1").glob("*.json")).read_text())
    assert pending.pop("key_ref")
    assert pending == {
        "expected_public_key": None,
        "namespace": provider.namespace,
        "observer": "alice",
        "provenance": "created",
        "schema": "loops.custody/binding-intent/v1",
        "stage": "pending",
        "token": "index-token",
    }
    assert json.loads(json.dumps(error.as_dict(), allow_nan=False)) == error.as_dict()

    monkeypatch.setattr(provider, "_ensure_token_index", original_index)
    recovered = provider.recover_binding("alice", token="index-token")
    assert recovered.operation == "recover"
    assert recovered.observer == "alice"

    binding = next((provider.root / "bindings-v1").glob("*.json"))
    binding.write_text("{malformed binding record")
    before_corrupt = _files(provider.root)
    with pytest.raises(CredentialBindingIncomplete) as corrupt:
        provider.create_binding("alice", token="fresh-token")
    assert corrupt.value.phase == "unknown"
    assert corrupt.value.source_type == "ValueError"
    assert _files(provider.root) == before_corrupt


@pytest.mark.parametrize("record_kind", ["pending", "intent"])
def test_corrupt_pending_or_intent_record_is_lifecycle_incomplete_without_mutation(
    tmp_path: Path, record_kind: str
) -> None:
    provider = _provider(tmp_path)
    token = "pending-corrupt"
    if record_kind == "pending":
        record = provider.root / "pending-v1" / "corrupt.json"
    else:
        record = provider._intent_path(token)
    record.parent.mkdir(parents=True)
    record.write_text("[]")
    # Entering a custody mutation normally creates this advisory lock. Seed it
    # so the unchanged-byte assertion isolates record handling from that
    # established lock-file side effect.
    (provider.root / ".bindings-v1.lock").touch()
    before = _files(provider.root)

    with pytest.raises(CredentialBindingIncomplete) as raised:
        provider.create_binding("alice", token=token)

    error = raised.value
    assert error.operation == "create"
    assert error.namespace == provider.namespace
    assert error.observer == "alice"
    assert error.token == token
    assert error.key_ref is None
    assert error.phase == "unknown"
    assert error.source_type == "TypeError"
    assert json.loads(json.dumps(error.as_dict(), allow_nan=False)) == error.as_dict()
    assert _files(provider.root) == before


def test_import_legacy_returns_the_same_public_result_shape(tmp_path: Path) -> None:
    legacy_vertex = tmp_path / "legacy.vertex"
    pair = ensure_signing_key(legacy_vertex, observer="legacy")
    provider = _provider(tmp_path)

    imported = provider.import_legacy(legacy_vertex, "legacy", token="import-legacy")
    assert isinstance(imported, CredentialBindingResult)
    assert imported.operation == "import-legacy"
    assert imported.provenance == "legacy-import"
    assert imported.public_key == pair.public_b64
    assert json.loads(json.dumps(imported.as_dict(), allow_nan=False)) == imported.as_dict()


def test_legacy_import_recovery_requires_its_missing_candidate(tmp_path: Path) -> None:
    legacy_vertex = tmp_path / "legacy.vertex"
    ensure_signing_key(legacy_vertex, observer="legacy")
    provider = _provider(tmp_path)

    def interrupt(phase: str, _intent: dict[str, object]) -> None:
        if phase == "intent-published":
            raise OSError("retain import intent without a candidate")

    provider._creation_hook = interrupt
    with pytest.raises(CredentialBindingIncomplete):
        provider.import_legacy(legacy_vertex, "legacy", token="import-recover")
    provider._creation_hook = None

    with pytest.raises(CredentialBindingRecoveryRequired) as raised:
        provider.recover_binding("legacy", token="import-recover")
    error = raised.value
    assert error.operation == "recover"
    assert error.namespace == provider.namespace
    assert error.observer == "legacy"
    assert error.token == "import-recover"
