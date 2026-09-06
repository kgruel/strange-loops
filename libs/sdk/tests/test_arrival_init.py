"""Public SDK credential, recovery, and descriptor-boundary checks."""

from __future__ import annotations

from base64 import b64encode
from pathlib import Path

import pytest
from custody import arrival_signer_for, ensure_signing_key, fact_signer_for
from engine.arrival_contract import Profile, StoreDescriptor, UnknownBackend
from engine.arrival_initialization import (
    InitializationCommittedIncomplete,
    arrival_intent_path,
    initialize_arrival,
    new_lineage,
)
from engine.arrival_registry import BackendRegistry
from lang import parse_vertex, vertex_to_documents

from sdk import ArrivalRefusal, SdkValueError, init_vertex


def test_engine_bootstrap_declared_key_can_emit_through_sdk(tmp_path: Path) -> None:
    from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
    from engine.admission import fact_commitment_hash
    from engine.arrival import ArrivalLog, verify_authorship_records
    from sign import ed25519

    from sdk import emit_fact

    target = tmp_path / "bootstrap.vertex"
    alice = ensure_signing_key(target, observer="alice")
    bob = ensure_signing_key(target, observer="bob")
    descriptor = StoreDescriptor(
        "file", str(tmp_path / "bootstrap.arrival"), lineage=new_lineage(), role=Profile.AUTHORITY
    )
    text = (
        'name "bootstrap"\n'
        f'store "{descriptor.location}" backend="file" '
        f'lineage="{descriptor.lineage}" role="authority"\n'
        'loops { item { fold { items "collect" 100; } } }\n'
        'observers {\n'
        f'  alice {{ key "{alice.public_b64}"; }}\n'
        '  bob {\n'
        f'    key "{bob.public_b64}"\n'
        '    grant { potential "item"; }\n  }\n}\n'
    )
    documents = [doc.as_json() for doc in vertex_to_documents(parse_vertex(text, path=target))]
    initialize_arrival(
        BackendRegistry.with_builtin_backends(), descriptor, target=target,
        documents=documents, declaration_text=text, observer="alice",
        public_key=alice.public_b64, signer=arrival_signer_for(target),
        fact_signer=fact_signer_for(target), arrival_signer=arrival_signer_for(target),
    )
    emitted = emit_fact(target, "item", {"value": 3}, observer="bob")
    records = list(ArrivalLog(descriptor.location).walk())
    verify_authorship_records(
        records,
        lambda key, signature, digest: ed25519.verify(
            ed25519.public_key_from_b64(key), signature, digest.encode(), domain=ARRIVAL_DOMAIN
        ),
    )
    row = emitted.commit.records[-1]["body"]
    digest = fact_commitment_hash(
        row["kind"], row["ts"], row["observer"], row["origin"], row["payload"]
    )
    assert ed25519.verify(
        ed25519.public_key_from_b64(bob.public_b64), row["signature"],
        digest.encode(), domain=FACT_DOMAIN
    )


@pytest.fixture(autouse=True)
def _isolated_custody(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_custom_arrival_and_fact_signers_use_separate_domains(tmp_path: Path) -> None:
    target = tmp_path / "custom.vertex"
    keypair = ensure_signing_key(target, observer="alice")
    arrival = arrival_signer_for(target)
    fact = fact_signer_for(target)
    assert arrival is not None and fact is not None

    result = init_vertex(
        target,
        store_type="arrival",
        observer="alice",
        signer=arrival,
        fact_signer=fact,
        public_key=keypair.public_b64,
        location="custom.arrival",
    )

    assert result.read_path == "arrival"
    assert result.store is not None
    assert result.store.location == str((tmp_path / "custom.arrival").resolve())
    assert result.store.lineage == result.lineage


@pytest.mark.parametrize("name", ("item", "cite"))
def test_arrival_init_refuses_scaffold_or_implicit_loop_name_before_custody(
    tmp_path: Path, name: str
) -> None:
    """Arrival scaffolding reserves its explicit item and implicit cite loops."""
    target = tmp_path / f"{name}.vertex"

    with pytest.raises(SdkValueError) as caught:
        init_vertex(target, name=name, store_type="arrival", observer="alice")

    assert str(caught.value) == (
        f"Arrival runtime reserves vertex name {name!r} from the loop-name namespace"
    )
    assert not target.exists()
    assert not (target.parent / "keys").exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ("item", "cite"))
def test_legacy_init_keeps_colliding_name_compatibility(tmp_path: Path, name: str) -> None:
    """The Arrival restriction does not reinterpret existing legacy initialization."""
    target = tmp_path / f"{name}.vertex"

    result = init_vertex(target, name=name, store_type="sqlite")

    assert result.name == name
    assert target.exists()


def test_wrong_domain_and_mismatched_key_refuse_before_intent_or_mint(tmp_path: Path) -> None:
    target = tmp_path / "wrong-domain.vertex"
    keypair = ensure_signing_key(target, observer="alice")
    arrival = arrival_signer_for(target)
    fact = fact_signer_for(target)
    assert arrival is not None and fact is not None

    with pytest.raises(ArrivalRefusal, match="founding genesis signer"):
        init_vertex(
            target, store_type="arrival", observer="alice",
            signer=fact, fact_signer=fact, public_key=keypair.public_b64,
        )
    assert not target.exists()

    inner_target = tmp_path / "wrong-inner.vertex"
    inner_keypair = ensure_signing_key(inner_target, observer="alice")
    inner_arrival = arrival_signer_for(inner_target)
    inner_fact = fact_signer_for(inner_target)
    assert inner_arrival is not None and inner_fact is not None
    with pytest.raises(ArrivalRefusal, match="founding fact signer"):
        init_vertex(
            inner_target, store_type="arrival", observer="alice",
            signer=inner_arrival, fact_signer=inner_arrival,
            public_key=inner_keypair.public_b64,
        )
    assert not inner_target.exists()
    assert not (tmp_path / ".loops" / "data").exists()

    other = tmp_path / "other" / "other.vertex"
    other.parent.mkdir()
    other_key = ensure_signing_key(other, observer="alice")
    with pytest.raises(ArrivalRefusal, match="founding genesis signer"):
        init_vertex(
            target, store_type="arrival", observer="alice",
            signer=arrival, fact_signer=fact, public_key=other_key.public_b64,
        )
    assert not target.exists()


def test_partial_custom_credentials_and_conflicting_locations_refuse(tmp_path: Path) -> None:
    target = tmp_path / "partial.vertex"
    keypair = ensure_signing_key(target, observer="alice")
    arrival = arrival_signer_for(target)
    assert arrival is not None

    with pytest.raises(SdkValueError, match="custom credentials"):
        init_vertex(
            target, store_type="arrival", observer="alice",
            signer=arrival, public_key=keypair.public_b64,
        )
    with pytest.raises(SdkValueError, match="conflicting location"):
        init_vertex(
            target, store_type="arrival", observer="alice",
            location="one.arrival", store_path="two.arrival",
        )
    assert not target.exists()


def test_recovery_loads_reserved_observer_and_descriptor(tmp_path: Path) -> None:
    target = tmp_path / "recover.vertex"
    location = (tmp_path / "chosen.arrival").resolve()
    keypair = ensure_signing_key(target, observer="alice")
    arrival = arrival_signer_for(target)
    fact = fact_signer_for(target)
    assert arrival is not None and fact is not None
    lineage = new_lineage()
    descriptor = StoreDescriptor(
        "file", str(location), lineage=lineage, role=Profile.AUTHORITY
    )
    declaration_text = (
        f'name "recover-name"\n'
        f'store "{location}" backend="file" lineage="{lineage}" role="authority"\n'
        "loops { item { fold { items \"collect\" 10 } } }\n"
    )
    documents = [document.as_json() for document in vertex_to_documents(
        parse_vertex(declaration_text, path=target)
    )]

    def fail(stage: str) -> None:
        if stage == "after-mint":
            raise OSError("simulated process loss")

    with pytest.raises(InitializationCommittedIncomplete):
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text=declaration_text,
            observer="alice", public_key=keypair.public_b64,
            signer=arrival, fact_signer=fact, arrival_signer=arrival,
            authored_at=1.0, failure_hook=fail,
        )

    import shutil

    shutil.rmtree(target.parent / "keys")
    result = init_vertex(
        target, store_type="arrival", recover=True, location="chosen.arrival"
    )
    assert result.read_path == "arrival"
    assert result.name == "recover-name"
    assert result.store is not None
    assert result.store.location == str(location)
    assert result.store.lineage == lineage
    assert result.lineage == lineage
    assert not (target.parent / "keys").exists()


def test_non_key_shaped_custom_material_is_rejected_before_store(tmp_path: Path) -> None:
    target = tmp_path / "malformed.vertex"
    with pytest.raises(ArrivalRefusal, match="founding public key"):
        init_vertex(
            target, store_type="arrival", observer="alice",
            signer=lambda _observer, _digest: "signature",
            fact_signer=lambda _observer, _digest: "signature",
            public_key=b64encode(b"short").decode(),
        )
    assert not target.exists()


def test_invalid_observer_path_is_a_sdk_input_error(tmp_path: Path) -> None:
    target = tmp_path / "invalid-observer.vertex"
    with pytest.raises(SdkValueError, match="observer"):
        init_vertex(
            target,
            store_type="arrival",
            observer="../escape",
        )
    assert not target.exists()


def test_custom_registry_receives_opaque_dsn_without_builtin_fallback(tmp_path: Path) -> None:
    class RefusingRegistry:
        def __init__(self) -> None:
            self.opened: list[StoreDescriptor] = []
            self.failure = UnknownBackend("test registry refusal")

        def open(self, descriptor: StoreDescriptor):
            self.opened.append(descriptor)
            raise self.failure

    target = tmp_path / "remote.vertex"
    registry = RefusingRegistry()
    with pytest.raises(ArrivalRefusal, match="test registry refusal") as caught:
        init_vertex(
            target,
            store_type="arrival",
            observer="alice",
            backend="remote",
            location="service://cluster/arrival?tenant=a/b",
            registry=registry,
        )

    assert caught.value.__cause__ is registry.failure
    assert registry.opened
    assert all(item.backend == "remote" for item in registry.opened)
    assert all(
        item.location == "service://cluster/arrival?tenant=a/b"
        for item in registry.opened
    )
    assert not target.exists()


def test_arrival_init_reraises_unchanged_exception_with_original_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unmapped initialization failures retain identity and their existing cause."""
    import engine.arrival_initialization as initialization

    cause = OSError("underlying setup failure")
    failure = RuntimeError("unmapped initializer failure")
    failure.__cause__ = cause

    def fail_initialize(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(initialization, "initialize_arrival", fail_initialize)
    with pytest.raises(RuntimeError) as caught:
        init_vertex(
            tmp_path / "unchanged.vertex",
            store_type="arrival",
            observer="alice",
            signer=lambda _observer, _digest: "arrival-signature",
            fact_signer=lambda _observer, _digest: "fact-signature",
            public_key="unused-by-injected-failure",
        )

    assert caught.value is failure
    assert caught.value.__cause__ is cause


def test_arrival_init_enriches_unchanged_sdk_refusal_before_reraising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass-through SDK failures retain both existing diagnostics and init intent."""
    import engine.arrival_initialization as initialization

    cause = OSError("backend setup failure")
    failure = ArrivalRefusal(
        "injected SDK refusal", source_type="InjectedBackend", details={"marker": "kept"}
    )
    failure.__cause__ = cause

    def fail_initialize(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(initialization, "initialize_arrival", fail_initialize)
    target = tmp_path / "sdk-refusal.vertex"
    with pytest.raises(ArrivalRefusal) as caught:
        init_vertex(
            target,
            store_type="arrival",
            observer="alice",
            signer=lambda _observer, _digest: "arrival-signature",
            fact_signer=lambda _observer, _digest: "fact-signature",
            public_key="unused-by-injected-refusal",
        )

    assert caught.value is failure
    assert caught.value.__cause__ is cause
    assert caught.value.details == {
        "marker": "kept",
        "intent_path": str(arrival_intent_path(target)),
    }


def test_arrival_init_reraises_interrupt_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The initializer does not turn a process-control interrupt into an SDK error."""
    import engine.arrival_initialization as initialization

    interruption = KeyboardInterrupt()

    def interrupt_initialize(*_args, **_kwargs):
        raise interruption

    monkeypatch.setattr(initialization, "initialize_arrival", interrupt_initialize)
    with pytest.raises(KeyboardInterrupt) as caught:
        init_vertex(
            tmp_path / "interrupt.vertex",
            store_type="arrival",
            observer="alice",
            signer=lambda _observer, _digest: "arrival-signature",
            fact_signer=lambda _observer, _digest: "fact-signature",
            public_key="unused-by-injected-interrupt",
        )

    assert caught.value is interruption
    assert caught.value.__cause__ is None
