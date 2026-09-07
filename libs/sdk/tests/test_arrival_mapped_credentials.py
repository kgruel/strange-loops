"""Public SDK checks for explicitly mapped Arrival credentials.

These tests intentionally use the public custody provider and SDK operations.
They do not inspect the provider's private slot layout; the temporary root is
only a test-owned custody namespace.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from atoms import Fact, SourceError
from engine.credentials import CredentialPurpose, CredentialRequest, SigningDomain

from sdk import (
    CredentialBindingIncomplete,
    MappedCredentialProvider,
    SdkError,
    edit_declaration,
    emit_batch,
    emit_fact,
    grant_observer,
    init_vertex,
    preview_emission,
    run_sources,
)


@pytest.fixture(autouse=True)
def _isolated_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep custody, config, and legacy home state inside this test."""

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops"))


def _provider(tmp_path: Path, *, namespace: str = "tenant-a") -> MappedCredentialProvider:
    return MappedCredentialProvider(
        tmp_path / "mapped-custody", namespace=namespace, receipt_observer="alice"
    )


def _create(provider: MappedCredentialProvider, observer: str, token: str):
    return provider.create_binding(observer, token=token)


def _file_state(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _init_mapped(
    tmp_path: Path, provider: MappedCredentialProvider, *, observer: str = "alice"
) -> tuple[Path, object]:
    target = tmp_path / "declared-name.vertex"
    _create(provider, observer, f"create-{observer}")
    result = init_vertex(
        target,
        name="declared-name",
        store_type="arrival",
        observer=observer,
        location=str(tmp_path / "records.arrival"),
        credentials=provider,
    )
    return target, result


def test_mapped_provider_separates_domains_and_keeps_key_ref_stable(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    created = _create(provider, "alice", "create-alice")

    fact = provider.resolve(
        CredentialRequest(
            provider.namespace,
            "alice",
            SigningDomain.FACT,
            CredentialPurpose.AUTHORSHIP,
        )
    )
    arrival = provider.resolve(
        CredentialRequest(
            provider.namespace,
            "alice",
            SigningDomain.ARRIVAL,
            CredentialPurpose.AUTHORSHIP,
        )
    )
    tick = provider.resolve(
        CredentialRequest(
            provider.namespace,
            "alice",
            SigningDomain.TICK,
            CredentialPurpose.RECEIPT,
        )
    )

    assert fact is not None and arrival is not None and tick is not None
    assert fact.evidence.key_ref == created.key_ref
    assert arrival.evidence.key_ref == created.key_ref
    assert tick.evidence.key_ref == created.key_ref
    assert fact.evidence.public_key == created.public_key
    assert fact.evidence.request.domain is SigningDomain.FACT
    assert tick.evidence.request.observer == "alice"
    signature = fact.sign_digest("mapped-digest")
    assert provider.verify(
        SigningDomain.FACT, created.public_key, signature, "mapped-digest"
    )
    assert not provider.verify(
        SigningDomain.ARRIVAL, created.public_key, signature, "mapped-digest"
    )
    tick_signature = tick.sign_digest("tick-digest")
    assert provider.verify(
        SigningDomain.TICK, created.public_key, tick_signature, "tick-digest"
    )
    assert not provider.verify(
        SigningDomain.FACT, created.public_key, tick_signature, "tick-digest"
    )


def test_mapped_init_uses_observer_identity_after_vertex_relocation(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    target, result = _init_mapped(tmp_path, provider)
    assert result.lineage
    assert target.exists()
    binding = provider.resolve(
        CredentialRequest(
            provider.namespace,
            "alice",
            SigningDomain.FACT,
            CredentialPurpose.INITIALIZATION,
        )
    )
    assert binding is not None
    assert f'key "{binding.evidence.public_key}"' in target.read_text(encoding="utf-8")

    relocated = tmp_path / "moved" / "different-stem.vertex"
    relocated.parent.mkdir()
    target.rename(relocated)

    receipt = emit_fact(
        relocated,
        "item",
        {"value": 7},
        observer="alice",
        credentials=provider,
    )
    assert receipt.stored is True
    assert receipt.observer == "alice"


def test_mapped_source_tiers_use_bound_author_for_each_append(tmp_path: Path) -> None:
    class CountingProvider(MappedCredentialProvider):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.requests = []

        def resolve(self, request):
            self.requests.append(request)
            return super().resolve(request)

    provider = CountingProvider(
        tmp_path / "mapped-custody", namespace="tenant-a", receipt_observer="alice"
    )
    target, _ = _init_mapped(tmp_path, provider)
    for kind in ("item", "other"):
        cadence = 'on "_sync.item"\n' if kind == "other" else ""
        (tmp_path / f"{kind}.loop").write_text(
            f'kind "{kind}"\nobserver "alice"\nsource "collect-{kind}"\n{cadence}',
            encoding="utf-8",
        )
    original = target.read_text(encoding="utf-8")
    prefix = original.split("loops {", 1)[0]
    proposal = prefix + (
        'sources {\n'
        '  path "./item.loop"\n'
        '  path "./other.loop"\n'
        '}\n\n'
        'loops {\n'
        '  item {\n    fold { items "collect" 100 }\n  }\n'
        '  other {\n    fold { items "collect" 100 }\n  }\n'
        '}\n'
    )
    edited = edit_declaration(target, proposal, observer="alice", credentials=provider)
    assert edited.commit is not None
    requests_before_sources = len(provider.requests)

    async def collect(source):
        yield Fact(source.kind, 5.0, {"source": source.kind}, observer="alice")

    result = asyncio.run(
        run_sources(
            target,
            observer="alice",
            force=True,
            credentials=provider,
            collector_factory=collect,
            evaluated_at=4.0,
        )
    )
    assert result.status == "ok"
    assert len(result.tiers) == 2
    assert all(tier.commit is not None for tier in result.tiers)
    assert len(provider.requests) - requests_before_sources >= 2


def test_mapped_init_rejects_relabelled_binding_evidence_before_intent(
    tmp_path: Path,
) -> None:
    class RelabelledProvider(MappedCredentialProvider):
        def resolve(self, request):
            resolved = super().resolve(request)
            if resolved is None:
                return None
            evidence = replace(
                resolved.evidence,
                request=replace(resolved.evidence.request, observer="mallory"),
            )
            return replace(resolved, evidence=evidence)

    provider = RelabelledProvider(
        tmp_path / "mapped-custody", namespace="tenant-a", receipt_observer="alice"
    )
    _create(provider, "alice", "create-alice")
    before = _file_state(tmp_path)

    with pytest.raises(SdkError):
        init_vertex(
            tmp_path / "relabelled.vertex",
            name="relabelled",
            store_type="arrival",
            observer="alice",
            location=str(tmp_path / "records.arrival"),
            credentials=provider,
        )

    assert _file_state(tmp_path) == before
    assert not (tmp_path / "relabelled.vertex").exists()


def test_mapped_two_author_batch_preserves_inner_and_outer_domains(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    target, initialized = _init_mapped(tmp_path, provider)
    bob = _create(provider, "bob", "create-bob")
    grant_observer(
        target,
        "bob",
        observer="alice",
        credentials=provider,
        key=bob.public_key,
    )

    from engine.admission import fact_commitment_hash
    from engine.arrival import ArrivalLog, content_commitment

    result = emit_batch(
        target,
        [
            {"kind": "item", "payload": {"value": 1}, "observer": "alice", "ts": 3.0},
            {"kind": "item", "payload": {"value": 2}, "observer": "alice", "ts": 4.0},
            {"kind": "item", "payload": {"value": 3}, "observer": "bob", "ts": 5.0},
            {"kind": "item", "payload": {"value": 4}, "observer": "bob", "ts": 6.0},
        ],
        credentials=provider,
    )
    assert result.commit is not None
    assert initialized.store is not None
    records = list(ArrivalLog(initialized.store.location).walk())
    batches = [record for record in records if record["k"] == "batch"]
    assert [batch["observer"] for batch in batches[-2:]] == ["alice", "bob"]
    for batch in batches[-2:]:
        outer_observer = str(batch["observer"])
        outer = provider.resolve(
            CredentialRequest(
                provider.namespace,
                outer_observer,
                SigningDomain.ARRIVAL,
                CredentialPurpose.AUTHORSHIP,
            )
        )
        assert outer is not None
        outer_digest = content_commitment(
            batch["k"], batch["at"], batch["observer"], batch["origin"], batch["body"]
        )
        assert provider.verify(
            SigningDomain.ARRIVAL,
            outer.evidence.public_key,
            batch["sig"],
            outer_digest,
        )

        for row in batch["body"]["rows"]:
            inner = provider.resolve(
                CredentialRequest(
                    provider.namespace,
                    row["observer"],
                    SigningDomain.FACT,
                    CredentialPurpose.AUTHORSHIP,
                )
            )
            assert inner is not None
            inner_digest = fact_commitment_hash(
                row["kind"], row["ts"], row["observer"], row["origin"], row["payload"]
            )
            assert provider.verify(
                SigningDomain.FACT,
                inner.evidence.public_key,
                row["signature"],
                inner_digest,
            )


def test_mapped_tick_uses_receipt_observer_domain_and_unsigned_outer_envelope(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    target, initialized = _init_mapped(tmp_path, provider)
    proposal = target.read_text(encoding="utf-8").replace(
        'fold {\n      items "collect" 100\n    }',
        'fold {\n      items "collect" 100\n    }\n    boundary when="item"',
    )
    edited = edit_declaration(target, proposal, observer="alice", credentials=provider)
    assert edited.commit is not None

    receipt = emit_fact(
        target,
        "item",
        {"value": 11},
        observer="alice",
        credentials=provider,
        ts=3.0,
    )
    assert receipt.tick_id is not None
    assert initialized.store is not None

    from engine.arrival import ArrivalLog
    from engine.row_commitment import tick_commitment_hash

    tick_record = next(
        record
        for record in ArrivalLog(initialized.store.location).walk()
        if record["k"] == "tick" and record["body"]["id"] == receipt.tick_id
    )
    assert tick_record.get("sig") is None
    binding = provider.resolve(
        CredentialRequest(
            provider.namespace,
            "alice",
            SigningDomain.TICK,
            CredentialPurpose.RECEIPT,
        )
    )
    assert binding is not None
    tick_digest = tick_commitment_hash((
            tick_record["body"]["id"],
            tick_record["body"]["name"],
            tick_record["body"]["ts"],
            tick_record["body"]["since"],
            tick_record["body"]["origin"],
            tick_record["body"]["payload"],
            tick_record["body"]["prev_hash"],
            tick_record["body"]["window_start"],
            tick_record["body"]["fact_cursor"],
            tick_record["body"]["window_hash"],
        ))
    assert provider.verify(
        SigningDomain.TICK,
        binding.evidence.public_key,
        tick_record["body"]["signature"],
        tick_digest,
    )


def test_mapped_source_failure_after_collection_retains_uncommitted_evidence(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    target, initialized = _init_mapped(tmp_path, provider)
    (tmp_path / "item.loop").write_text(
        'kind "item"\nobserver "alice"\nsource "collect-item"\n',
        encoding="utf-8",
    )
    proposal = target.read_text(encoding="utf-8").replace(
        "loops {",
        'sources { path "./item.loop" }\n\nloops {',
        1,
    )
    edited = edit_declaration(target, proposal, observer="alice", credentials=provider)
    assert edited.commit is not None
    assert initialized.store is not None

    async def collect(source):
        yield Fact("item", 5.0, {"value": 12}, observer="alice")
        raise SourceError(source.command, returncode=9, stderr="collector failed")

    result = asyncio.run(
        run_sources(
            target,
            observer="alice",
            credentials=provider,
            collector_factory=collect,
            evaluated_at=4.0,
        )
    )
    assert result.status == "error"
    assert result.tiers[0].sources[0].facts[0].payload == {"value": 12}
    assert result.tiers[0].sources[0].stderr == "collector failed"
    assert result.tiers[0].commit is not None
    assert result.tiers[0].outcome == "committed"


def test_mapped_preview_has_no_persistence_effect(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    target, _ = _init_mapped(tmp_path, provider)
    before = sorted(path.relative_to(provider.root) for path in provider.root.rglob("*"))

    preview = preview_emission(
        target,
        "item",
        {"value": 8},
        observer="alice",
        credentials=provider,
    )
    assert preview.admitted is True

    after = sorted(path.relative_to(provider.root) for path in provider.root.rglob("*"))
    assert after == before


def test_wrong_mapped_public_key_refuses_before_append(tmp_path: Path) -> None:
    provider = _provider(tmp_path, namespace="tenant-a")
    target, initialized = _init_mapped(tmp_path, provider)
    other = _provider(tmp_path / "other", namespace="tenant-b")
    _create(other, "alice", "other-alice")
    assert initialized.store is not None
    store = Path(initialized.store.location)
    before = store.read_bytes()

    with pytest.raises(SdkError):
        emit_fact(
            target,
            "item",
            {"value": 10},
            observer="alice",
            credentials=other,
        )

    assert store.read_bytes() == before


def test_mapped_grant_requires_precreated_binding_and_explicit_public_key(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    target, _ = _init_mapped(tmp_path, provider)
    bob = _create(provider, "bob", "create-bob")
    before = sorted(path.relative_to(provider.root) for path in provider.root.rglob("*"))

    with pytest.raises(SdkError):
        grant_observer(
            target,
            "carol",
            observer="alice",
            credentials=provider,
            key=None,
        )
    assert sorted(path.relative_to(provider.root) for path in provider.root.rglob("*")) == before

    result = grant_observer(
        target,
        "bob",
        observer="alice",
        credentials=provider,
        key=bob.public_key,
    )
    assert result.status == "applied"

    receipt = emit_fact(
        target,
        "item",
        {"value": 9},
        observer="bob",
        credentials=provider,
    )
    assert receipt.stored is True


def test_mapped_provider_legacy_target_refuses_before_legacy_write(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    _create(provider, "alice", "create-alice")
    target = tmp_path / "legacy.vertex"
    init_vertex(target, store_type="sqlite")
    before = _file_state(tmp_path)

    with pytest.raises((SdkError, ValueError)):
        emit_fact(
            target,
            "note",
            {"value": 1},
            observer="alice",
            credentials=provider,
        )

    assert _file_state(tmp_path) == before


def test_mapped_binding_existing_ref_rejects_unknown_key_without_replacement(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    created = _create(provider, "alice", "create-alice")
    before = sorted(path.relative_to(provider.root) for path in provider.root.rglob("*"))

    with pytest.raises(CredentialBindingIncomplete) as raised:
        provider.bind_existing_ref(
            "bob",
            "missing-key-ref",
            created.public_key,
            token="bind-bob",
        )
    assert raised.value.operation == "bind-existing-ref"
    assert raised.value.source_type == "FileNotFoundError"

    after = sorted(path.relative_to(provider.root) for path in provider.root.rglob("*"))
    assert after == before
