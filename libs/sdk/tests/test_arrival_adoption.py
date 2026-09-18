"""SDK boundary contract for explicit Arrival declaration adoption."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.arrival_adoption import AdoptionRecoveryRequired
from engine.arrival_contract import Head, Profile, StoreDescriptor
from engine.credentials import WriteCredentials
from sign import ed25519

from sdk import (
    ArrivalRefusal,
    SdkValueError,
    adopt_arrival,
    normalize_exception,
    recover_arrival_adoption,
)


def _mapped_credentials() -> WriteCredentials:
    return WriteCredentials(
        binding_namespace="tenant-a",
        binding_resolver=lambda _request: None,
        signature_verifier=lambda _domain, _key, _signature, _digest: False,
    )


def _target(tmp_path: Path) -> tuple[Path, str]:
    target = tmp_path / "adopt.vertex"
    text = (
        'name "adopt"\n'
        'store "ledger.arrival" backend="file" lineage="lineage-a" role="authority"\n'
        "observers {\n"
        '  alice { key "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" }\n'
        "}\n"
        "loops {\n"
        '  item { fold { items "collect" 100 } }\n'
        "}\n"
    )
    target.write_text(text, encoding="utf-8")
    return target, text


def _raw_result(target: Path):
    head = Head("lineage-a", 4, "head-after")
    return SimpleNamespace(
        status="applied",
        target_path=target,
        descriptor=StoreDescriptor(
            backend="file",
            location=str(target.parent / "ledger.arrival"),
            lineage="lineage-a",
            role=Profile.AUTHORITY,
        ),
        basis=None,
        lineage="lineage-a",
        captured_head=Head("lineage-a", 3, "head-before"),
        head=head,
        commit=None,
        fact_id="lineage-a",
        intent_path=target.with_name(target.name + ".arrival-adopt.intent"),
        phase="completed",
        file_written=True,
        projection=None,
        credential_bindings=(),
        observed_head=None,
    )


def test_adoption_forwards_the_reviewed_and_published_snapshots_with_mapped_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, declaration_text = _target(tmp_path)
    reviewed_text = declaration_text.replace(
        'store "ledger.arrival" backend="file" lineage="lineage-a" role="authority"',
        'store "legacy.jsonl"',
    )
    selected = Head("lineage-a", 3, "head-before")
    calls: dict[str, object] = {}
    module = ModuleType("engine.arrival_adoption")

    def prepare(_registry, descriptor, **kwargs):
        calls["descriptor"] = descriptor
        calls.update(kwargs)
        return SimpleNamespace(target_path=target)

    def apply(_registry, plan):
        assert plan.target_path == target
        return _raw_result(target)

    module.prepare_arrival_adoption = prepare
    module.apply_arrival_adoption = apply
    monkeypatch.setitem(sys.modules, "engine.arrival_adoption", module)

    result = adopt_arrival(
        target,
        selected_head=selected,
        reviewed_text=reviewed_text,
        reviewed_sha256=hashlib.sha256(reviewed_text.encode()).hexdigest(),
        declaration_text=declaration_text,
        observer="alice",
        credentials=_mapped_credentials(),
    )

    assert calls["selected_head"] is selected
    assert calls["reviewed_text"] == reviewed_text
    assert calls["reviewed_sha256"] == hashlib.sha256(reviewed_text.encode()).hexdigest()
    assert calls["declaration_text"] == declaration_text
    assert calls["observer"] == "alice"
    assert calls["credentials"].mapped is True
    assert callable(calls["fact_verify"])
    assert callable(calls["arrival_verify"])
    assert calls["descriptor"].role is Profile.AUTHORITY
    assert result.fact_id == "lineage-a"
    assert result.captured_head == selected
    assert result.reviewed_sha256 == hashlib.sha256(reviewed_text.encode()).hexdigest()
    assert result.declaration_sha256 == hashlib.sha256(declaration_text.encode()).hexdigest()
    assert result.as_dict()["intent_path"].endswith(".arrival-adopt.intent")


def test_sdk_passes_independent_fact_and_arrival_verifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, declaration_text = _target(tmp_path)
    reviewed_text = declaration_text.replace(
        'store "ledger.arrival" backend="file" lineage="lineage-a" role="authority"',
        'store "legacy.jsonl"',
    )
    key = ed25519.load_or_generate(tmp_path / "public-verifier-key")
    calls: dict[str, object] = {}
    module = ModuleType("engine.arrival_adoption")

    def prepare(_registry, _descriptor, **kwargs):
        calls.update(kwargs)
        return SimpleNamespace(target_path=target)

    module.prepare_arrival_adoption = prepare
    module.apply_arrival_adoption = lambda _registry, _plan: _raw_result(target)
    monkeypatch.setitem(sys.modules, "engine.arrival_adoption", module)

    adopt_arrival(
        target,
        selected_head=Head("lineage-a", 3, "head-before"),
        reviewed_text=reviewed_text,
        reviewed_sha256=hashlib.sha256(reviewed_text.encode()).hexdigest(),
        declaration_text=declaration_text,
        observer="alice",
        credentials=_mapped_credentials(),
    )

    digest = "reviewed-adoption-digest"
    fact_signature = ed25519.sign(key, digest.encode(), domain=FACT_DOMAIN)
    arrival_signature = ed25519.sign(key, digest.encode(), domain=ARRIVAL_DOMAIN)
    fact_verify = calls["fact_verify"]
    arrival_verify = calls["arrival_verify"]
    assert fact_verify(key.public_b64, fact_signature, digest)
    assert arrival_verify(key.public_b64, arrival_signature, digest)
    assert not fact_verify(key.public_b64, arrival_signature, digest)
    assert not arrival_verify(key.public_b64, fact_signature, digest)


def test_adoption_refuses_legacy_signers_before_engine_import(tmp_path: Path) -> None:
    target, declaration_text = _target(tmp_path)

    with pytest.raises(SdkValueError, match="pre-created mapped"):
        adopt_arrival(
            target,
            selected_head=Head("lineage-a", 3, "head-before"),
            reviewed_text=declaration_text,
            reviewed_sha256=hashlib.sha256(declaration_text.encode()).hexdigest(),
            declaration_text=declaration_text,
            observer="alice",
            credentials=WriteCredentials(fact_signer=lambda _author, _digest: "legacy"),
        )


def test_adoption_wraps_provider_resolution_failure_as_sdk_input_error(tmp_path: Path) -> None:
    target, declaration_text = _target(tmp_path)

    class BrokenProvider:
        def for_write(self, _vertex: Path):
            raise RuntimeError("custody unavailable")

    with pytest.raises(SdkValueError, match="could not resolve"):
        adopt_arrival(
            target,
            selected_head=Head("lineage-a", 3, "head-before"),
            reviewed_text=declaration_text,
            reviewed_sha256=hashlib.sha256(declaration_text.encode()).hexdigest(),
            declaration_text=declaration_text,
            observer="alice",
            credentials=BrokenProvider(),
        )


def test_recovery_does_not_resolve_or_resign_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _declaration_text = _target(tmp_path)
    intent = target.with_name(target.name + ".arrival-adopt.intent")
    module = ModuleType("engine.arrival_adoption")
    calls: list[Path] = []

    def recover(_registry, supplied_intent, *, fact_verify, arrival_verify):
        calls.append(Path(supplied_intent))
        assert callable(fact_verify)
        assert callable(arrival_verify)
        return _raw_result(target)

    module.recover_arrival_adoption = recover
    monkeypatch.setitem(sys.modules, "engine.arrival_adoption", module)

    result = recover_arrival_adoption(intent)

    assert calls == [intent]
    assert result.status == "applied"


def test_preappend_recovery_requirement_retains_its_intent_coordinate(tmp_path: Path) -> None:
    intent = tmp_path / "adopt.vertex.arrival-adopt.intent"

    normalized = normalize_exception(
        AdoptionRecoveryRequired(
            "recover the prepared adoption", intent_path=intent, cause=RuntimeError("fault")
        )
    )

    assert isinstance(normalized, ArrivalRefusal)
    assert normalized.source_type == "AdoptionRecoveryRequired"
    assert normalized.details["intent_path"] == str(intent)


@pytest.mark.parametrize(
    "content",
    ["[]", "null", '"not an intent"', '{"descriptor":"not a descriptor"}'],
)
def test_malformed_adoption_intent_stays_in_the_sdk_error_family(
    tmp_path: Path, content: str
) -> None:
    intent = tmp_path / "adopt.vertex.arrival-adopt.intent"
    intent.write_text(content, encoding="utf-8")

    with pytest.raises(ArrivalRefusal) as raised:
        recover_arrival_adoption(intent)

    assert raised.value.source_type == "AdoptionApplyError"
