"""Acceptance tests for the registry-backed fresh Arrival initializer."""

from __future__ import annotations

from base64 import b64encode
from pathlib import Path

import pytest
from custody import arrival_signer_for, ensure_signing_key, fact_signer_for
from lang import parse_vertex, vertex_to_documents
from ulid import ULID

from engine.arrival import GenesisRefused
from engine.arrival_contract import (
    Capabilities,
    DurabilityProfile,
    Full,
    Profile,
    ProjectionRequirement,
    StoreDescriptor,
    VerificationLevel,
)
from engine.arrival_initialization import (
    InitializationCommittedIncomplete,
    InitializationConflict,
    InitializationOutcomeUnknown,
    InitializationUnwitnessed,
    arrival_intent_path,
    initialize_arrival,
    recover_arrival_initialization,
)
from engine.arrival_registry import BackendRegistry


@pytest.fixture(autouse=True)
def _isolated_witness_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _inputs(tmp_path: Path):
    target = tmp_path / "arrival.vertex"
    location = tmp_path / "arrival.arrival"
    keypair = ensure_signing_key(target, observer="alice")
    arrival_signer = arrival_signer_for(target)
    fact_signer = fact_signer_for(target)
    assert arrival_signer is not None and fact_signer is not None
    descriptor = StoreDescriptor(
        "file", str(location), lineage=str(ULID()), role=Profile.AUTHORITY
    )
    declaration_text = _declaration(descriptor)
    documents = [document.as_json() for document in vertex_to_documents(
        parse_vertex(declaration_text, path=target)
    )]
    return (
        target,
        location,
        keypair.public_b64,
        arrival_signer,
        fact_signer,
        descriptor,
        documents,
        declaration_text,
    )


def _declaration(descriptor: StoreDescriptor, name: str = "arrival") -> str:
    return (
        f'name "{name}"\n'
        f'store "{descriptor.location}" backend="{descriptor.backend}" '
        f'lineage="{descriptor.lineage}" role="authority"\n'
        "loops {\n"
        "  item {\n"
        "    fold { items \"collect\" 100 }\n"
        "  }\n"
        "}\n"
    )


def _initialize(tmp_path: Path, **kwargs):
    (
        target, location, public, arrival_signer, fact_signer, descriptor,
        documents, declaration_text,
    ) = _inputs(tmp_path)
    result = initialize_arrival(
        BackendRegistry.with_builtin_backends(),
        descriptor,
        target=target,
        documents=documents,
        declaration_text=declaration_text,
        observer="alice",
        public_key=public,
        signer=arrival_signer,
        fact_signer=fact_signer,
        arrival_signer=arrival_signer,
        **kwargs,
    )
    return result, target, location


def test_fresh_init_mints_signed_genesis_and_declaration(tmp_path: Path) -> None:
    result, target, location = _initialize(tmp_path)

    assert result.head.ordinal == 1
    assert result.head.lineage == result.lineage
    assert target.read_text() == _declaration(
        StoreDescriptor("file", str(location), lineage=result.lineage, role=Profile.AUTHORITY)
    )
    assert not arrival_intent_path(target).exists()

    ledger, query = BackendRegistry.with_builtin_backends().open(
        StoreDescriptor("file", str(location), lineage=result.lineage, role=Profile.AUTHORITY)
    )
    try:
        assert ledger.verify(Full(through=result.head)) == result.head
        assert ledger.read(0)["body"]["lineage"] == result.lineage
        assert ledger.read(1)["body"]["id"] == result.lineage
        assert query.open_snapshot(
            captured_head=result.head, requirement=ProjectionRequirement.CURRENT
        )
    finally:
        query.close()
        ledger.close()


def _initialize_with_declared_key(
    tmp_path: Path, *, failure_hook=None, declared_observer="bob", key_override=None
):
    target, location, public, arrival, fact, descriptor, _documents, text = _inputs(tmp_path)
    bob = ensure_signing_key(target, observer="bob")
    text += (
        f'observers {{\n  {declared_observer} {{\n'
        f'    key "{bob.public_b64 if key_override is None else key_override}"\n'
        '    grant { potential "item"; }\n  }\n}\n'
    )
    documents = [doc.as_json() for doc in vertex_to_documents(parse_vertex(text, path=target))]
    result = initialize_arrival(
        BackendRegistry.with_builtin_backends(), descriptor, target=target,
        documents=documents, declaration_text=text, observer="alice", public_key=public,
        signer=arrival, fact_signer=fact, arrival_signer=arrival, failure_hook=failure_hook,
    )
    return result, descriptor, target, location, bob.public_b64


def test_initializer_introduces_other_declared_keys_before_declaration(tmp_path: Path):
    from custody.signing import ARRIVAL_DOMAIN
    from sign import ed25519

    from engine.arrival import ArrivalLog, key_registry_from_records

    result, _descriptor, _target, location, bob_key = _initialize_with_declared_key(tmp_path)
    records = list(ArrivalLog(location).walk())
    assert [row["k"] for row in records] == ["genesis", "key", "fact"]
    assert records[2]["body"]["id"] == result.lineage
    keys, _evidence = key_registry_from_records(
        records,
        lambda key, signature, digest: ed25519.verify(
            ed25519.public_key_from_b64(key), signature, digest.encode(), domain=ARRIVAL_DOMAIN
        ),
    )
    assert (bob_key, 1) in keys.keys_valid_at("bob", 2)


def test_declared_key_recovery_uses_reserved_bootstrap_without_duplicate_controls(tmp_path: Path):
    from engine.arrival import ArrivalLog

    def fail(phase):
        if phase == "after-declaration":
            raise OSError("injected interrupted bootstrap")

    with pytest.raises(InitializationCommittedIncomplete) as caught:
        _initialize_with_declared_key(tmp_path, failure_hook=fail)
    target = tmp_path / "arrival.vertex"
    location = tmp_path / "arrival.arrival"
    before = location.read_bytes()
    recovered = recover_arrival_initialization(
        BackendRegistry.with_builtin_backends(), arrival_intent_path(target)
    )
    assert recovered.head == caught.value.captured_head
    assert location.read_bytes() == before
    assert len(list(ArrivalLog(location).walk())) == 3


def test_declared_key_atomic_limit_refuses_before_mint(tmp_path: Path, monkeypatch):
    from dataclasses import replace

    from engine.arrival_contract import AtomicLimitExceeded
    from engine.arrival_file_backend import FileLedger

    original = FileLedger.capabilities
    monkeypatch.setattr(
        FileLedger, "capabilities", lambda self: replace(original(self), max_atomic_records=1)
    )
    with pytest.raises(AtomicLimitExceeded):
        _initialize_with_declared_key(tmp_path)
    assert not (tmp_path / "arrival.arrival").exists()
    assert not arrival_intent_path(tmp_path / "arrival.vertex").exists()


@pytest.mark.parametrize(
    "kwargs, reason",
    [({"key_override": "not-a-key"}, "malformed public key"),
     ({"declared_observer": "alice"}, "founding key differs")],
)
def test_inconsistent_declared_key_refuses_before_mint(tmp_path: Path, kwargs, reason):
    with pytest.raises(InitializationConflict, match=reason):
        _initialize_with_declared_key(tmp_path, **kwargs)
    assert not (tmp_path / "arrival.arrival").exists()
    assert not arrival_intent_path(tmp_path / "arrival.vertex").exists()


@pytest.mark.parametrize("after_mint", [False, True])
def test_directory_open_failure_cannot_report_durable_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_mint: bool
) -> None:
    import os

    from engine import arrival_initialization as initialization

    (
        target, location, public, signer, fact_signer, descriptor,
        documents, declaration_text,
    ) = _inputs(tmp_path)
    original_open = os.open
    fail_directory = not after_mint

    def gated_open(path, flags, *args, **kwargs):
        if fail_directory and Path(path) == tmp_path and flags == os.O_RDONLY:
            raise PermissionError("injected directory open failure")
        return original_open(path, flags, *args, **kwargs)

    def after_phase(phase: str) -> None:
        nonlocal fail_directory
        if phase == "after-mint":
            fail_directory = True

    monkeypatch.setattr(initialization.os, "open", gated_open)
    expected = InitializationCommittedIncomplete if after_mint else PermissionError
    with pytest.raises(expected) as caught:
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text=declaration_text,
            observer="alice", public_key=public, signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
            failure_hook=after_phase if after_mint else None,
        )
    assert not target.exists()
    if after_mint:
        assert caught.value.captured_head is not None
        assert location.exists()
        assert arrival_intent_path(target).exists()
        monkeypatch.setattr(initialization.os, "open", original_open)
        recovered = recover_arrival_initialization(
            BackendRegistry.with_builtin_backends(), arrival_intent_path(target)
        )
        assert recovered.lineage == descriptor.lineage
        assert target.read_text() == declaration_text
    else:
        assert not location.exists()
        assert not arrival_intent_path(target).exists()


def test_wrong_role_refuses_before_intent_or_store(tmp_path: Path) -> None:
    target, location, public, signer, fact_signer, descriptor, documents, _text = _inputs(tmp_path)
    replica = StoreDescriptor("file", str(location), role=Profile.REPLICA)
    with pytest.raises(InitializationConflict, match="Authority"):
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), replica,
            target=target, documents=documents, declaration_text="x",
            observer="alice", public_key=public, signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
        )
    assert not location.exists()
    assert not arrival_intent_path(target).exists()


def test_descriptor_lineage_pin_is_used_when_argument_is_omitted(tmp_path: Path) -> None:
    target, location, public, signer, fact_signer, descriptor, documents, _text = _inputs(tmp_path)
    pinned = str(ULID())
    descriptor = StoreDescriptor(
        "file", str(location), lineage=pinned, role=Profile.AUTHORITY
    )
    result = initialize_arrival(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, documents=documents, declaration_text=_declaration(descriptor),
        observer="alice", public_key=public, signer=signer,
        fact_signer=fact_signer, arrival_signer=signer,
    )
    assert result.lineage == pinned


def test_malformed_public_key_refuses_before_intent(tmp_path: Path) -> None:
    target, location, _public, signer, fact_signer, descriptor, documents, _text = _inputs(tmp_path)
    with pytest.raises(InitializationConflict, match="raw-32-byte base64"):
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text="x",
            observer="alice", public_key="malformed", signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
        )
    assert not location.exists()
    assert not arrival_intent_path(target).exists()


def test_declaration_grammar_and_descriptor_mismatch_refuse_before_mint(tmp_path: Path) -> None:
    target, location, public, signer, fact_signer, descriptor, documents, _text = _inputs(tmp_path)
    mismatched = _declaration(descriptor).replace('backend="file"', 'backend="remote"')
    with pytest.raises(InitializationConflict, match="requested backend"):
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text=mismatched,
            observer="alice", public_key=public, signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
        )
    assert not location.exists()
    assert not arrival_intent_path(target).exists()


def test_semantic_declaration_error_refuses_before_intent(tmp_path: Path) -> None:
    target, location, public, signer, fact_signer, descriptor, _documents, _text = _inputs(tmp_path)
    declaration_text = _declaration(descriptor).replace(
        'fold { items "collect" 100 }', ""
    )
    documents = [document.as_json() for document in vertex_to_documents(
        parse_vertex(declaration_text, path=target)
    )]
    with pytest.raises(InitializationConflict, match="no fold declarations"):
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text=declaration_text,
            observer="alice", public_key=public, signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
        )
    assert not location.exists()
    assert not arrival_intent_path(target).exists()


class _NoHeadQuery:
    def close(self) -> None:
        return None


class _NoHeadLedger:
    def __init__(self, *, mint_error: BaseException | None = None) -> None:
        self.value = None
        self.mint_error = mint_error

    def capabilities(self) -> Capabilities:
        return Capabilities(
            protocol_version=1,
            profiles=frozenset({Profile.AUTHORITY}),
            durability=DurabilityProfile.HOST,
            verification_levels=frozenset({VerificationLevel.OPEN}),
            writer_concurrency="test",
            snapshot="test",
            watermark="test",
        )

    def verify(self, _scope):
        raise RuntimeError("remote has no current head")

    def mint(self, options):
        if self.mint_error is not None:
            raise self.mint_error
        from engine.arrival_contract import Head

        self.value = Head(options["lineage"], 0, "remote-genesis")
        return self.value

    def append(self, _expected, _drafts):
        raise RuntimeError("adapter append transport failed")

    def head(self, _lineage=None):
        if self.value is None:
            raise RuntimeError("remote has no current head")
        return self.value

    def close(self) -> None:
        return None


def test_nonfile_nohead_refusal_is_not_interpreted_as_filesystem_absence(tmp_path: Path) -> None:
    target = tmp_path / "remote.vertex"
    ledger = _NoHeadLedger()
    registry = BackendRegistry()
    registry.register("remote", lambda _descriptor: (ledger, _NoHeadQuery()))
    descriptor = StoreDescriptor(
        "remote", "service://cluster/arrival", lineage=str(ULID()), role=Profile.AUTHORITY
    )
    key = b64encode(b"k" * 32).decode()
    def sign(_observer, _digest):
        return "signature"
    declaration_text = _declaration(descriptor, "remote")
    docs = [document.as_json() for document in vertex_to_documents(
        parse_vertex(declaration_text, path=target)
    )]

    with pytest.raises(InitializationCommittedIncomplete) as raised:
        initialize_arrival(
            registry, descriptor, target=target, documents=docs,
            declaration_text=declaration_text, observer="alice", public_key=key,
            signer=sign, fact_signer=sign, arrival_signer=sign,
            failure_hook=lambda stage: (_ for _ in ()).throw(RuntimeError("injected"))
            if stage == "after-mint" else None,
        )
    assert isinstance(raised.value.cause, RuntimeError)
    assert raised.value.captured_head is not None
    assert raised.value.captured_head.ordinal == 0
    assert ledger.value is not None
    assert not target.exists()
    assert "service://cluster/arrival" in descriptor.location


def test_unknown_append_retains_intent_and_stable_identity(tmp_path: Path) -> None:
    target = tmp_path / "remote.vertex"
    ledger = _NoHeadLedger()
    registry = BackendRegistry()
    registry.register("remote", lambda _descriptor: (ledger, _NoHeadQuery()))
    descriptor = StoreDescriptor(
        "remote", "service://cluster/arrival", lineage=str(ULID()), role=Profile.AUTHORITY
    )
    key = b64encode(b"k" * 32).decode()

    def sign(_observer, _digest):
        return "signature"

    declaration_text = _declaration(descriptor, "remote")
    docs = [document.as_json() for document in vertex_to_documents(
        parse_vertex(declaration_text, path=target)
    )]

    with pytest.raises(InitializationOutcomeUnknown) as raised:
        initialize_arrival(
            registry, descriptor, target=target,
            documents=docs, declaration_text=declaration_text,
            observer="alice", public_key=key,
            signer=sign, fact_signer=sign, arrival_signer=sign,
        )
    error = raised.value
    assert error.lineage == error.captured_head.lineage
    assert error.fact_id
    assert Path(error.intent_path).exists()
    assert not target.exists()


def test_existing_corrupt_file_is_refused_by_mint_without_replacement(tmp_path: Path) -> None:
    target, location, public, signer, fact_signer, descriptor, documents, _text = _inputs(tmp_path)
    original = b"operator bytes\n"
    location.write_bytes(original)
    with pytest.raises(GenesisRefused):
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text=_declaration(descriptor),
            observer="alice", public_key=public, signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
        )
    assert location.read_bytes() == original


def test_recovery_after_mint_keeps_lineage_and_does_not_duplicate(tmp_path: Path) -> None:
    target, location, public, signer, fact_signer, descriptor, documents, _text = _inputs(tmp_path)

    def fail(stage: str) -> None:
        if stage == "after-mint":
            raise RuntimeError("injected crash")

    with pytest.raises(InitializationCommittedIncomplete) as raised:
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text=_declaration(descriptor),
            observer="alice", public_key=public, signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
            authored_at=1.0,
            failure_hook=fail,
        )
    assert isinstance(raised.value.cause, RuntimeError)
    assert raised.value.captured_head is not None
    assert raised.value.captured_head.ordinal == 0
    intent = arrival_intent_path(target)
    assert intent.exists() and location.exists()

    first = recover_arrival_initialization(
        BackendRegistry.with_builtin_backends(), intent,
        signer=signer, fact_signer=fact_signer, arrival_signer=signer,
    )
    second = recover_arrival_initialization if intent.exists() else None
    assert first.head.ordinal == 1
    assert not intent.exists()
    assert second is None

    ledger, query = BackendRegistry.with_builtin_backends().open(
        StoreDescriptor("file", str(location), lineage=first.lineage, role=Profile.AUTHORITY)
    )
    try:
        assert ledger.head().ordinal == 1
    finally:
        query.close()
        ledger.close()


def test_mint_transport_unknown_keeps_intent_without_head_claim(tmp_path: Path) -> None:
    target = tmp_path / "remote.vertex"
    ledger = _NoHeadLedger(mint_error=OSError("transport dropped during mint"))
    registry = BackendRegistry()
    registry.register("remote", lambda _descriptor: (ledger, _NoHeadQuery()))
    descriptor = StoreDescriptor(
        "remote", "service://cluster/arrival", lineage=str(ULID()), role=Profile.AUTHORITY
    )
    key = b64encode(b"k" * 32).decode()

    def sign(_observer, _digest):
        return "signature"

    declaration_text = _declaration(descriptor, "remote")
    docs = [document.as_json() for document in vertex_to_documents(
        parse_vertex(declaration_text, path=target)
    )]

    with pytest.raises(InitializationOutcomeUnknown) as raised:
        initialize_arrival(
            registry, descriptor, target=target,
            documents=docs, declaration_text=declaration_text,
            observer="alice", public_key=key,
            signer=sign, fact_signer=sign, arrival_signer=sign,
        )
    error = raised.value
    assert error.captured_head is None
    assert error.lineage
    assert error.fact_id == error.lineage
    assert Path(error.intent_path).exists()
    assert not target.exists()


def test_mint_not_witnessed_preserves_head_without_fabricating_commit(tmp_path: Path) -> None:
    from engine.arrival_contract import Head
    from engine.arrival_head_seam import NotWitnessed

    target = tmp_path / "remote.vertex"
    minted_head = Head(str(ULID()), 0, "remote-genesis")
    ledger = _NoHeadLedger(mint_error=NotWitnessed("journal unavailable", head=minted_head))
    registry = BackendRegistry()
    registry.register("remote", lambda _descriptor: (ledger, _NoHeadQuery()))
    descriptor = StoreDescriptor(
        "remote", "service://cluster/arrival", lineage=minted_head.lineage,
        role=Profile.AUTHORITY,
    )
    key = b64encode(b"k" * 32).decode()

    declaration_text = _declaration(descriptor, "remote")
    docs = [document.as_json() for document in vertex_to_documents(
        parse_vertex(declaration_text, path=target)
    )]
    with pytest.raises(InitializationUnwitnessed) as raised:
        initialize_arrival(
            registry, descriptor, target=target, documents=docs,
            declaration_text=declaration_text, observer="alice", public_key=key,
            signer=lambda _observer, _digest: "signature",
            fact_signer=lambda _observer, _digest: "signature",
            arrival_signer=lambda _observer, _digest: "signature",
        )
    assert raised.value.head == minted_head
    assert raised.value.commit is None
    assert Path(raised.value.intent_path).exists()


def test_publication_failure_reports_known_commit_and_keeps_intent(tmp_path: Path) -> None:
    def fail(stage: str) -> None:
        if stage == "after-publication":
            raise OSError("declaration cache fsync failed")

    with pytest.raises(InitializationCommittedIncomplete) as raised:
        _initialize(tmp_path, failure_hook=fail)
    error = raised.value
    assert error.phase == "published"
    assert error.captured_head is not None
    assert error.captured_head.ordinal == 1
    assert error.commit is not None
    assert Path(error.intent_path).exists()


def test_existing_declaration_is_never_overwritten(tmp_path: Path) -> None:
    target, location, public, signer, fact_signer, descriptor, documents, _text = _inputs(tmp_path)
    target.write_text("operator edit\n")
    with pytest.raises(InitializationConflict, match="vertex file already exists"):
        initialize_arrival(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, documents=documents, declaration_text="new",
            observer="alice", public_key=public, signer=signer,
            fact_signer=fact_signer, arrival_signer=signer,
        )
    assert target.read_text() == "operator edit\n"
    assert not location.exists()
