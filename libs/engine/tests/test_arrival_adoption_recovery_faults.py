"""Adversarial recovery fault contracts for explicit Arrival adoption."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import engine.arrival_adoption as adoption
from engine.arrival import ArrivalLog, content_commitment
from engine.arrival_contract import RecordDraft
from engine.arrival_registry import (
    BackendRegistry,
    _file_binding,
    _open_file_backend,
)

_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "_arrival_adoption_helpers", Path(__file__).with_name("test_arrival_adoption.py")
)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)
_fixture = _HELPERS._fixture
_recovery_kwargs = _HELPERS._recovery_kwargs


@pytest.fixture(autouse=True)
def _isolated_witness_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops"))


class _LostReturnLedger:
    """Commit to the wrapped ledger, then lose the append response."""

    def __init__(self, ledger) -> None:
        self._ledger = ledger

    def __getattr__(self, name):
        return getattr(self._ledger, name)

    def append(self, *args, **kwargs):
        self._ledger.append(*args, **kwargs)
        raise OSError("append committed, response lost")


class _LostReturnRegistry:
    def __init__(self, registry: BackendRegistry) -> None:
        self._registry = registry
        self._opens = 0

    def open(self, descriptor):
        ledger, query = self._registry.open(descriptor)
        self._opens += 1
        # apply opens custody first, then its maintenance preflight opens an
        # attested handle.  Keep that second handle intact so the fault is
        # injected at the append response rather than at preflight.
        if self._opens == 2:
            return ledger, query
        return _LostReturnLedger(ledger), query

    def __getattr__(self, name):
        return getattr(self._registry, name)


def _append_interleaved(registry, descriptor, selected_head):
    ledger, query = registry.open(descriptor)
    try:
        body = adoption.body_of_fact_row(
            ("interleaved", "item", 3.0, "alice", "", "{}", None)
        )
        digest = content_commitment("fact", 3.0, "alice", "", body)
        return ledger.append(
            selected_head,
            (RecordDraft("fact", 3.0, "alice", "", body, f"arrival:{digest}"),),
        ).after
    finally:
        query.close()
        ledger.close()


def _record_count(descriptor) -> int:
    return len(tuple(ArrivalLog(Path(descriptor.location)).walk()))


def _reserve(registry, plan):
    def fail(phase):
        if phase == "after-intent":
            raise OSError("reserve only")

    with pytest.raises(adoption.AdoptionRecoveryRequired):
        adoption.apply_arrival_adoption(registry, plan, failure_hook=fail)
    return adoption.arrival_adoption_intent_path(plan.target_path)


def test_lost_append_response_recovers_exact_commit_before_sync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = adoption.prepare_arrival_adoption(registry, descriptor, **kwargs)

    with pytest.raises(adoption.AdoptionOutcomeUnknown):
        adoption.apply_arrival_adoption(_LostReturnRegistry(registry), plan)
    intent = adoption.arrival_adoption_intent_path(kwargs["target"])
    assert json.loads(intent.read_text())["phase"] == "append-unknown"

    def fail_sync(*_args, **_kwargs):
        raise OSError("maintenance offline")

    monkeypatch.setattr(adoption, "sync_projection", fail_sync)
    with pytest.raises(adoption.AdoptionCommittedIncomplete) as caught:
        adoption.recover_arrival_adoption(
            registry, intent, **_recovery_kwargs()
        )

    commit = caught.value.commit
    assert commit is not None
    assert commit.before == kwargs["selected_head"]
    assert commit.after.ordinal == kwargs["selected_head"].ordinal + 1
    assert caught.value.phase == "appended"
    assert json.loads(intent.read_text())["phase"] == "appended"
    assert _record_count(descriptor) == 2


def test_lost_append_response_phase_persistence_failure_keeps_exact_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = adoption.prepare_arrival_adoption(registry, descriptor, **kwargs)

    with pytest.raises(adoption.AdoptionOutcomeUnknown):
        adoption.apply_arrival_adoption(_LostReturnRegistry(registry), plan)
    intent = adoption.arrival_adoption_intent_path(kwargs["target"])
    original_replace = adoption._replace_json

    def fail_appended_phase(path, data):
        if data.get("phase") == "appended":
            raise OSError("intent phase persistence failed")
        return original_replace(path, data)

    monkeypatch.setattr(adoption, "_replace_json", fail_appended_phase)
    with pytest.raises(adoption.AdoptionCommittedIncomplete) as caught:
        adoption.recover_arrival_adoption(
            registry, intent, **_recovery_kwargs()
        )

    commit = caught.value.commit
    assert commit is not None
    assert commit.before == kwargs["selected_head"]
    assert commit.after.ordinal == kwargs["selected_head"].ordinal + 1
    assert caught.value.phase == "appended"
    assert json.loads(intent.read_text())["phase"] == "append-unknown"
    assert _record_count(descriptor) == 2


def test_proof_confirmed_different_row_retires_intent_and_allows_fresh_prepare(
    tmp_path: Path,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = adoption.prepare_arrival_adoption(registry, descriptor, **kwargs)
    intent = _reserve(registry, plan)
    next_head = _append_interleaved(registry, descriptor, kwargs["selected_head"])

    with pytest.raises(adoption.AdoptionStale):
        adoption.recover_arrival_adoption(
            registry, intent, **_recovery_kwargs()
        )
    assert not intent.exists()

    kwargs["selected_head"] = next_head
    fresh = adoption.prepare_arrival_adoption(registry, descriptor, **kwargs)
    result = adoption.apply_arrival_adoption(registry, fresh)
    assert result.commit is not None
    assert result.commit.before == next_head
    assert _record_count(descriptor) == 3


def test_transient_recovery_refusal_retains_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = adoption.prepare_arrival_adoption(registry, descriptor, **kwargs)
    intent = _reserve(registry, plan)

    original_open = registry.open

    def transient_open(_descriptor):
        raise OSError("temporary backend outage")

    monkeypatch.setattr(registry, "open", transient_open)
    with pytest.raises(adoption.AdoptionRecoveryRequired) as refused:
        adoption.recover_arrival_adoption(
            registry, intent, **_recovery_kwargs()
        )
    assert isinstance(refused.value.cause, OSError)
    assert "temporary backend outage" in str(refused.value.cause)
    assert intent.exists()
    monkeypatch.setattr(registry, "open", original_open)
    recovered = adoption.recover_arrival_adoption(
        registry, intent, **_recovery_kwargs()
    )
    assert recovered.commit is not None
    assert not intent.exists()


def test_recovery_preflights_maintenance_before_append_and_builtin_retry_succeeds(
    tmp_path: Path,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = adoption.prepare_arrival_adoption(registry, descriptor, **kwargs)
    intent = _reserve(registry, plan)

    # Recovery is a separate process boundary.  A registry that can open
    # custody but has no projection-maintenance authority must refuse before
    # the reserved anchor is appended, while leaving the durable intent for a
    # later retry with the complete registry.
    incomplete = BackendRegistry()
    incomplete.register(
        "file", _open_file_backend, binding_provider=_file_binding
    )
    with pytest.raises(adoption.AdoptionRecoveryRequired) as refused:
        adoption.recover_arrival_adoption(
            incomplete, intent, **_recovery_kwargs()
        )
    assert refused.value.intent_path == intent
    assert _record_count(descriptor) == 1
    assert intent.exists()

    recovered = adoption.recover_arrival_adoption(
        registry, intent, **_recovery_kwargs()
    )
    assert recovered.commit is not None
    assert recovered.commit.before == kwargs["selected_head"]
    assert recovered.commit.after.ordinal == kwargs["selected_head"].ordinal + 1
    assert _record_count(descriptor) == 2
    assert not intent.exists()


@pytest.mark.parametrize(
    "mutation",
    (
        "list-root", "null-root", "string-root", "descriptor-string",
        "drafts-object", "exact-mismatch",
    ),
)
def test_malformed_intent_shapes_are_adoption_errors_without_custody_writes(
    tmp_path: Path, mutation: str,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = adoption.prepare_arrival_adoption(registry, descriptor, **kwargs)
    intent = _reserve(registry, plan)
    authentic = intent.read_bytes()
    data = json.loads(authentic)

    if mutation == "list-root":
        value = []
    elif mutation == "null-root":
        value = None
    elif mutation == "string-root":
        value = "malformed"
    else:
        value = data
        if mutation == "descriptor-string":
            value["descriptor"] = "malformed"
        elif mutation == "drafts-object":
            value["drafts"] = {"kind": "fact"}
        else:
            value["drafts"][0]["signature"] = "changed-without-updating-exact"

    intent.write_text(json.dumps(value))
    with pytest.raises(adoption.AdoptionApplyError):
        adoption.recover_arrival_adoption(
            registry, intent, **_recovery_kwargs()
        )
    assert _record_count(descriptor) == 1
    intent.write_bytes(authentic)
