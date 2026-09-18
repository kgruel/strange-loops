"""Focused custody and recovery tests for explicit migrated-log adoption."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from engine.arrival import ArrivalLog, content_commitment
from engine.arrival_adoption import (
    AdoptionApplyError,
    AdoptionCommittedIncomplete,
    AdoptionPreparationRefused,
    AdoptionRecoveryRequired,
    AdoptionStale,
    apply_arrival_adoption,
    arrival_adoption_intent_path,
    prepare_arrival_adoption,
    recover_arrival_adoption,
)
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import Profile, RecordDraft, StoreDescriptor
from engine.arrival_registry import BackendRegistry
from engine.credentials import (
    CredentialBindingEvidence,
    ResolvedCredential,
    WriteCredentials,
)

KEY = base64.b64encode(bytes(range(32))).decode("ascii")
OTHER_KEY = base64.b64encode(bytes(range(1, 33))).decode("ascii")


@pytest.fixture(autouse=True)
def _isolated_witness_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _fixture(tmp_path: Path, *, bad_genesis: bool = False, selected_key: str | None = None):
    descriptor = StoreDescriptor(
        "file", str(tmp_path / "copied.arrival"),
        lineage="01J00000000000000000000000", role=Profile.AUTHORITY,
    )
    target = tmp_path / "copied.vertex"
    reviewed = (
        'name "copied"\nstore "old.jsonl"\n'
        'loops { item { fold { items "collect" 100 } } }\n'
    )
    published = reviewed.replace(
        'store "old.jsonl"',
        f'store "{descriptor.location}" backend="file" '
        f'lineage="{descriptor.lineage}" role="authority"',
    )
    target.write_text(published)
    registry = BackendRegistry.with_builtin_backends()
    ledger, query = registry.open(descriptor)
    try:
        head = ledger.mint({
            "lineage": descriptor.lineage, "observer": "alice", "key": KEY,
            "at": 1.0, "origin": "",
            "signer": lambda _observer, digest: (
                "wrong-signature" if bad_genesis else f"arrival:{digest}"
            ),
        })
    finally:
        query.close()
        ledger.close()

    def resolver(request):
        key = KEY if selected_key is None else selected_key
        return ResolvedCredential(
            CredentialBindingEvidence(request, "mapped-alice", "test", key, "pre-created"),
            lambda digest: f"{request.domain.value}:{digest}",
        )

    credentials = WriteCredentials(
        binding_namespace="adopt-test", binding_resolver=resolver,
        signature_verifier=lambda domain, key, sig, digest: (
            key in {KEY, OTHER_KEY} and sig == f"{domain.value}:{digest}"
        ),
    )
    kwargs = {
        "target": target, "selected_head": head, "reviewed_text": reviewed,
        "reviewed_sha256": hashlib.sha256(reviewed.encode()).hexdigest(),
        "declaration_text": published, "observer": "alice",
        "credentials": credentials,
        "arrival_verify": lambda key, signature, digest: (
            key == KEY and signature == f"arrival:{digest}"
        ),
        "authored_at": 2.0,
    }
    return registry, descriptor, kwargs


def _recovery_kwargs():
    return {
        "fact_verify": lambda key, signature, digest: (
            key == KEY and signature == f"fact:{digest}"
        ),
        "arrival_verify": lambda key, signature, digest: (
            key == KEY and signature == f"arrival:{digest}"
        ),
    }


def test_adoption_appends_one_initializer_anchor_and_syncs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = prepare_arrival_adoption(registry, descriptor, **kwargs)
    assert len(plan.credential_bindings) == 2
    result = apply_arrival_adoption(registry, plan)
    assert result.commit is not None
    assert result.commit.before == kwargs["selected_head"]
    assert result.commit.after == result.head
    assert result.head.ordinal == 1
    assert result.projection is not None
    assert result.projection.projected_after == result.head
    assert not arrival_adoption_intent_path(kwargs["target"]).exists()
    records = tuple(ArrivalLog(Path(descriptor.location)).walk())
    assert len(records) == 2
    assert records[1]["body"]["id"] == descriptor.lineage
    assert records[1]["body"]["kind"] == "_decl.genesis"
    assert kwargs["target"].read_text() == kwargs["declaration_text"]


def test_adoption_recovery_reuses_exact_committed_anchor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = prepare_arrival_adoption(registry, descriptor, **kwargs)

    def fail(phase):
        if phase == "after-append":
            raise OSError("simulated phase failure")

    with pytest.raises(AdoptionCommittedIncomplete) as caught:
        apply_arrival_adoption(registry, plan, failure_hook=fail)
    assert caught.value.commit is not None
    before = Path(descriptor.location).read_bytes()
    recovered = recover_arrival_adoption(
        registry, arrival_adoption_intent_path(kwargs["target"]),
        **_recovery_kwargs(),
    )
    assert recovered.commit is not None
    assert recovered.commit.before == kwargs["selected_head"]
    assert recovered.commit.after == caught.value.commit.after
    assert recovered.head == caught.value.commit.after
    assert recovered.projection is not None
    assert Path(descriptor.location).read_bytes() == before
    assert len(tuple(ArrivalLog(Path(descriptor.location)).walk())) == 2


def test_reserved_adoption_recovers_without_resigning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = prepare_arrival_adoption(registry, descriptor, **kwargs)

    def fail(phase):
        if phase == "after-intent":
            raise OSError("simulated interruption")

    with pytest.raises(AdoptionRecoveryRequired):
        apply_arrival_adoption(registry, plan, failure_hook=fail)
    recovered = recover_arrival_adoption(
        registry, arrival_adoption_intent_path(kwargs["target"]),
        **_recovery_kwargs(),
    )
    assert recovered.head.ordinal == 1
    assert recovered.commit is not None
    assert recovered.commit.records[0]["body"] == dict(plan.draft.body)


@pytest.mark.parametrize("tamper", ("binding-key", "fact-signature", "arrival-signature"))
def test_recovery_refuses_self_consistent_tampered_intent(
    tmp_path: Path, tamper: str,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = prepare_arrival_adoption(registry, descriptor, **kwargs)

    def fail(phase):
        if phase == "after-intent":
            raise OSError("reserve only")

    with pytest.raises(AdoptionRecoveryRequired):
        apply_arrival_adoption(registry, plan, failure_hook=fail)
    intent = arrival_adoption_intent_path(kwargs["target"])
    data = json.loads(intent.read_text())
    if tamper == "binding-key":
        data["bindings"][0]["public_key"] = OTHER_KEY
    elif tamper == "fact-signature":
        data["drafts"][0]["body"]["signature"] = "forged-inner"
        data["exact_drafts"] = json.dumps(
            data["drafts"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        )
    else:
        data["drafts"][0]["signature"] = "forged-outer"
        data["exact_drafts"] = json.dumps(
            data["drafts"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        )
    intent.write_text(json.dumps(data))
    with pytest.raises(AdoptionApplyError):
        recover_arrival_adoption(registry, intent, **_recovery_kwargs())
    assert len(tuple(ArrivalLog(Path(descriptor.location)).walk())) == 1


@pytest.mark.parametrize("change", ("bad-genesis", "wrong-key", "changed-review", "changed-cache"))
def test_adoption_refuses_untrusted_or_drifted_basis(
    tmp_path: Path, change: str,
) -> None:
    registry, descriptor, kwargs = _fixture(
        tmp_path, bad_genesis=change == "bad-genesis",
        selected_key=OTHER_KEY if change == "wrong-key" else None,
    )
    if change == "changed-review":
        kwargs["reviewed_sha256"] = "0" * 64
    if change == "changed-cache":
        kwargs["target"].write_text(kwargs["declaration_text"] + "\n")
    with pytest.raises(AdoptionPreparationRefused):
        prepare_arrival_adoption(registry, descriptor, **kwargs)
    assert len(tuple(ArrivalLog(Path(descriptor.location)).walk())) == 1


def test_adoption_refuses_existing_lineage_fact_id(tmp_path: Path) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    ledger, query = registry.open(descriptor)
    try:
        body = body_of_fact_row((
            descriptor.lineage, "event", 1.5, "alice", "", "{}", None,
        ))
        digest = content_commitment("fact", 1.5, "alice", "", body)
        commit = ledger.append(kwargs["selected_head"], (
            RecordDraft("fact", 1.5, "alice", "", body, f"arrival:{digest}"),
        ))
    finally:
        query.close()
        ledger.close()
    kwargs["selected_head"] = commit.after
    with pytest.raises(AdoptionPreparationRefused, match="fact ID"):
        prepare_arrival_adoption(registry, descriptor, **kwargs)


def test_adoption_cas_refuses_changed_head_after_prepare(tmp_path: Path) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    plan = prepare_arrival_adoption(registry, descriptor, **kwargs)
    ledger, query = registry.open(descriptor)
    try:
        body = body_of_fact_row((
            "01J00000000000000000000001", "event", 1.5, "alice", "", "{}", None,
        ))
        digest = content_commitment("fact", 1.5, "alice", "", body)
        ledger.append(kwargs["selected_head"], (
            RecordDraft("fact", 1.5, "alice", "", body, f"arrival:{digest}"),
        ))
    finally:
        query.close()
        ledger.close()
    with pytest.raises(AdoptionStale):
        apply_arrival_adoption(registry, plan)
    assert not arrival_adoption_intent_path(kwargs["target"]).exists()


@pytest.mark.parametrize("kind", ("overlay", "foreign-genesis", "bad-key"))
def test_adoption_refuses_conflicting_declaration_or_bad_registry_signature(
    tmp_path: Path, kind: str,
) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    ledger, query = registry.open(descriptor)
    try:
        if kind == "bad-key":
            draft = RecordDraft(
                "key", 1.5, "alice", "",
                {"observer": "bob", "key": OTHER_KEY}, "wrong-signature",
            )
        else:
            payload = (
                '{"lineage":"' + descriptor.lineage + '","subject":"item"}'
                if kind == "overlay" else '{"protocol":1,"documents":[]}'
            )
            fact_kind = "_decl.kind-defined" if kind == "overlay" else "_decl.genesis"
            body = body_of_fact_row((
                "01J00000000000000000000002", fact_kind, 1.5,
                "alice", "", payload, None,
            ))
            digest = content_commitment("fact", 1.5, "alice", "", body)
            draft = RecordDraft(
                "fact", 1.5, "alice", "", body, f"arrival:{digest}"
            )
        commit = ledger.append(kwargs["selected_head"], (draft,))
    finally:
        query.close()
        ledger.close()
    kwargs["selected_head"] = commit.after
    if kind == "foreign-genesis":
        # A retained foreign declaration is inert; it does not claim this lineage.
        plan = prepare_arrival_adoption(registry, descriptor, **kwargs)
        assert plan.captured_head == commit.after
    else:
        with pytest.raises(AdoptionPreparationRefused):
            prepare_arrival_adoption(registry, descriptor, **kwargs)


def test_adoption_refuses_new_selected_observer_key(tmp_path: Path) -> None:
    registry, descriptor, kwargs = _fixture(tmp_path)
    block = (
        f'observers {{\n  bob {{\n    key "{OTHER_KEY}"\n'
        '    grant { potential "item"; }\n  }\n}\n'
    )
    kwargs["reviewed_text"] += block
    kwargs["reviewed_sha256"] = hashlib.sha256(
        kwargs["reviewed_text"].encode()
    ).hexdigest()
    kwargs["declaration_text"] += block
    kwargs["target"].write_text(kwargs["declaration_text"])
    with pytest.raises(AdoptionPreparationRefused, match="not valid"):
        prepare_arrival_adoption(registry, descriptor, **kwargs)
