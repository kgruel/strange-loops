"""Declaration preparation completes projection evidence through custody."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from lang.document import vertex_to_documents
from lang.loader import parse_vertex

from engine.arrival_boundary_continuity import BoundaryContinuityConflict
from engine.arrival_contract import (
    DeclarationAnchor,
    Fact,
    FactPage,
    Head,
    Profile,
    ProjectionBehind,
    StoreDescriptor,
    Tick,
    Watermark,
)
from engine.arrival_declarations import (
    DeclarationPreparationRefused,
    prepare_declaration_edit,
)
from engine.arrival_head_attestation import Outcome
from engine.arrival_head_seam import Compared
from engine.credentials import (
    CredentialBindingEvidence,
    CredentialPurpose,
    CredentialRequest,
    ResolvedCredential,
    SigningDomain,
    WriteCredentials,
)


class _Snapshot:
    def __init__(self, represented: Watermark, genesis: Fact):
        self.represented = represented
        self.view_generation = "view"
        self.declaration_anchor = DeclarationAnchor(genesis.id, genesis)
        self._genesis = genesis
        self._facts = [genesis]
        self._ticks = []
        self.closed = False

    def facts(self, request):
        return FactPage(tuple(self._facts), None, False, request.order)

    def ticks(self, _request):
        return tuple(self._ticks)

    def close(self):
        self.closed = True


def _declaration_fixture(tmp_path, *, case: str, changed: bool):
    captured = Head("lineage", 3, "captured")
    advanced = Head(captured.lineage, captured.ordinal + 1, "advanced")
    target = tmp_path / "x.vertex"
    current = (
        'name "x"\n'
        'store "ledger.arrival" backend="file" lineage="lineage" '
        'role="authority"\n'
        "loops {\n"
        "  item {\n"
        '    fold { items "collect" 100 }\n'
        "  }\n"
        "}\n"
    )
    target.write_text(current)
    documents = [
        document.as_json()
        for document in vertex_to_documents(parse_vertex(current, path=target))
    ]
    genesis = Fact(
        id=captured.lineage,
        kind="_decl.genesis",
        ts=0.0,
        observer="alice",
        origin="",
        payload={"protocol": 1, "documents": documents},
        arrival_ordinal=0,
        arrival_seq=0,
        payload_text=json.dumps({"protocol": 1, "documents": documents}),
    )
    represented = Watermark(
        "foreign" if case == "foreign" else captured.lineage,
        (
            advanced.ordinal
            if case in {"advance", "missing"}
            else captured.ordinal - 1 if case == "behind" else captured.ordinal
        ),
    )
    snapshot = _Snapshot(represented, genesis)
    activity: list[str] = []

    class MissingPrefix(Exception):
        pass

    class Ledger:
        opened = SimpleNamespace(
            comparison=Compared(Outcome.UNCHANGED, captured, None)
        )

        def head_at(self, watermark):
            activity.append("head_at")
            if case == "foreign":
                raise AssertionError("foreign watermark reached custody lookup")
            if case == "missing":
                raise MissingPrefix("prefix absent")
            if case == "substitution":
                return Head(captured.lineage, captured.ordinal, "replacement")
            if case == "wrong-coordinate":
                return Head(captured.lineage, captured.ordinal - 1, "wrong")
            if case == "behind":
                return Head(captured.lineage, captured.ordinal - 1, "behind")
            return advanced

        def scan(self, **kwargs):
            activity.append("scan")
            return ()

        def read(self, coordinate):
            current_genesis = snapshot._genesis
            assert coordinate == current_genesis.arrival_ordinal
            return {
                "k": "fact", "lin": captured.lineage, "ord": coordinate,
                "observer": current_genesis.observer, "origin": current_genesis.origin,
                "body": {
                    "id": current_genesis.id, "kind": current_genesis.kind,
                    "ts": current_genesis.ts,
                    "observer": current_genesis.observer,
                    "origin": current_genesis.origin,
                    "payload": current_genesis.payload_text,
                },
            }

        def capabilities(self):
            return SimpleNamespace(max_atomic_records=None)

        def close(self):
            activity.append("ledger-close")

    class Query:
        def open_snapshot(self, **kwargs):
            if case == "snapshot-behind":
                raise ProjectionBehind("projection is behind")
            return snapshot

        def close(self):
            activity.append("query-close")

    class Registry:
        def open(self, descriptor):
            return Ledger(), Query()

    descriptor = StoreDescriptor(
        "file",
        str((target.parent / "ledger.arrival").resolve()),
        lineage=captured.lineage,
        role=Profile.AUTHORITY,
    )
    proposed = current.replace("100", "101") if changed else current
    return (
        Registry(),
        descriptor,
        target,
        proposed,
        captured,
        snapshot,
        activity,
        MissingPrefix,
    )


def test_declaration_preparation_clamps_a_custody_proven_projection_advance(
    tmp_path,
):
    registry, descriptor, target, proposed, captured, snapshot, activity, _ = (
        _declaration_fixture(tmp_path, case="advance", changed=False)
    )

    plan = prepare_declaration_edit(
        registry,
        descriptor,
        target=target,
        proposed_text=proposed,
        observer="alice",
        credentials=None,
        fact_verify=lambda *_args: True,
        arrival_verify=lambda *_args: True,
    )

    assert plan.basis.captured_head == captured
    assert plan.basis.projected_through == captured
    assert activity == ["head_at", "scan", "query-close", "ledger-close"]
    assert snapshot.closed


@pytest.mark.parametrize(
    "case", ("foreign", "missing", "substitution", "wrong-coordinate")
)
def test_declaration_preparation_refuses_unvouched_projection_before_signing_or_scan(
    tmp_path, case
):
    registry, descriptor, target, proposed, _, snapshot, activity, missing = (
        _declaration_fixture(tmp_path, case=case, changed=True)
    )
    signing_attempted = False

    def signer(*_args):
        nonlocal signing_attempted
        signing_attempted = True
        raise AssertionError("invalid projection reached signing")

    with pytest.raises(DeclarationPreparationRefused) as raised:
        prepare_declaration_edit(
            registry,
            descriptor,
            target=target,
            proposed_text=proposed,
            observer="alice",
            credentials=SimpleNamespace(
                fact_signer=signer,
                arrival_signer=signer,
            ),
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )

    if case == "missing":
        assert isinstance(raised.value.__cause__, missing)
    assert signing_attempted is False
    assert "scan" not in activity
    assert activity[-2:] == ["query-close", "ledger-close"]
    assert snapshot.closed


def test_declaration_projection_behind_retains_prepare_and_custody_evidence(
    tmp_path,
):
    registry, descriptor, target, proposed, captured, snapshot, activity, _ = (
        _declaration_fixture(tmp_path, case="behind", changed=True)
    )

    with pytest.raises(DeclarationPreparationRefused) as raised:
        prepare_declaration_edit(
            registry,
            descriptor,
            target=target,
            proposed_text=proposed,
            observer="alice",
            credentials=None,
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )

    refusal = raised.value
    assert refusal.coordinator_phase == "prepare"
    assert refusal.effects == {
        "custody": {"attempt": "not-entered", "state": "not-attempted"}
    }
    assert refusal.captured_head == captured
    assert refusal.projected_head == Head(
        captured.lineage, captured.ordinal - 1, "behind"
    )
    assert isinstance(refusal.__cause__, ProjectionBehind)
    assert refusal.__cause__.captured_head == refusal.captured_head
    assert refusal.__cause__.projected_head == refusal.projected_head
    assert activity[-2:] == ["query-close", "ledger-close"]
    assert snapshot.closed


def test_snapshot_projection_behind_retains_actual_captured_head(tmp_path) -> None:
    registry, descriptor, target, proposed, captured, _, activity, _ = (
        _declaration_fixture(tmp_path, case="snapshot-behind", changed=True)
    )

    with pytest.raises(DeclarationPreparationRefused) as raised:
        prepare_declaration_edit(
            registry,
            descriptor,
            target=target,
            proposed_text=proposed,
            observer="alice",
            credentials=None,
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )

    refusal = raised.value
    assert refusal.captured_head == captured
    assert getattr(refusal, "projected_head", None) is None
    assert isinstance(refusal.__cause__, ProjectionBehind)
    assert activity[-2:] == ["query-close", "ledger-close"]


def test_proposed_declaration_refuses_vertex_loop_identity_before_open(
    tmp_path,
) -> None:
    registry, descriptor, target, proposed, _, _, activity, _ = (
        _declaration_fixture(tmp_path, case="advance", changed=True)
    )
    proposed = proposed.replace("  item {", "  x {")

    with pytest.raises(
        DeclarationPreparationRefused,
        match="reserves vertex name 'x' from the loop-name namespace",
    ) as raised:
        prepare_declaration_edit(
            registry,
            descriptor,
            target=target,
            proposed_text=proposed,
            observer="alice",
            credentials=None,
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )

    assert raised.value.coordinator_phase == "prepare"
    assert raised.value.effects == {
        "custody": {"attempt": "not-entered", "state": "not-attempted"}
    }
    assert activity == []


def test_proposed_declaration_can_repair_ambiguous_effective_history(
    tmp_path,
) -> None:
    registry, descriptor, target, proposed, _, snapshot, activity, _ = (
        _declaration_fixture(tmp_path, case="advance", changed=True)
    )
    ambiguous = target.read_text().replace("  item {", "  x {")
    snapshot._genesis.payload["documents"] = [
        document.as_json()
        for document in vertex_to_documents(parse_vertex(ambiguous, path=target))
    ]
    snapshot._genesis = replace(
        snapshot._genesis, payload_text=json.dumps(snapshot._genesis.payload)
    )
    snapshot.declaration_anchor = replace(
        snapshot.declaration_anchor, genesis=snapshot._genesis
    )
    snapshot._facts = [snapshot._genesis]

    with pytest.raises(
        DeclarationPreparationRefused,
        match="declaration edits require fact and Arrival signers",
    ):
        prepare_declaration_edit(
            registry,
            descriptor,
            target=target,
            proposed_text=proposed,
            observer="alice",
            credentials=None,
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )

    assert "scan" in activity


def test_declaration_preparation_uses_mapped_fact_and_arrival_bindings(
    tmp_path, monkeypatch
) -> None:
    from engine import arrival_declarations
    from engine.arrival import KeyRegistry

    registry, descriptor, target, proposed, captured, _, activity, _ = (
        _declaration_fixture(tmp_path, case="advance", changed=True)
    )
    monkeypatch.setattr(
        arrival_declarations,
        "key_registry_from_records",
        lambda _records, _verify: (
            KeyRegistry(captured.lineage, {"alice": (("public-key", 0),)}),
            (),
        ),
    )
    requests: list[CredentialRequest] = []

    def resolve(request: CredentialRequest) -> ResolvedCredential:
        requests.append(request)
        return ResolvedCredential(
            CredentialBindingEvidence(
                request, "key", "ed25519", "public-key", "test"
            ),
            lambda digest: f"{request.domain.value}:{digest}",
        )

    plan = prepare_declaration_edit(
        registry,
        descriptor,
        target=target,
        proposed_text=proposed,
        observer="alice",
        credentials=WriteCredentials(
            binding_namespace="space",
            binding_resolver=resolve,
            signature_verifier=lambda domain, _key, signature, digest: signature
            == f"{domain.value}:{digest}",
        ),
        fact_verify=lambda *_args: False,
        arrival_verify=lambda *_args: False,
    )

    assert plan.status == "planned"
    assert {(request.domain, request.purpose) for request in requests} == {
        (SigningDomain.FACT, CredentialPurpose.AUTHORSHIP),
        (SigningDomain.ARRIVAL, CredentialPurpose.AUTHORSHIP),
    }
    assert len(plan.credential_bindings) == 2
    assert activity[-2:] == ["query-close", "ledger-close"]


def test_declaration_preparation_refuses_ticked_reincarnation_before_scan(
    tmp_path,
) -> None:
    registry, descriptor, target, proposed, captured, snapshot, activity, _ = (
        _declaration_fixture(tmp_path, case="advance", changed=True)
    )
    item_document = next(
        document
        for document in snapshot._genesis.payload["documents"]
        if document["kind"] == "_decl.kind-defined"
        and document["subject"] == "item"
    )
    snapshot._ticks.append(
        Tick(
            id="old-item-edge",
            name="item",
            ts=-1.0,
            since=None,
            origin="x",
            payload={},
            arrival_ordinal=1,
            arrival_seq=0,
            payload_text="{}",
        )
    )
    snapshot._facts.extend(
        (
            Fact(
                id="retire-item",
                kind="_decl.kind-retired",
                ts=2.0,
                observer="alice",
                origin="",
                payload={"lineage": captured.lineage, "subject": "item"},
                arrival_ordinal=2,
                arrival_seq=0,
                payload_text="{}",
            ),
            Fact(
                id="redefine-item",
                kind="_decl.kind-defined",
                ts=3.0,
                observer="alice",
                origin="",
                payload={
                    "lineage": captured.lineage,
                    "subject": "item",
                    "payload": item_document["payload"],
                },
                arrival_ordinal=3,
                arrival_seq=0,
                payload_text="{}",
            ),
        )
    )

    with pytest.raises(DeclarationPreparationRefused) as raised:
        prepare_declaration_edit(
            registry,
            descriptor,
            target=target,
            proposed_text=proposed,
            observer="alice",
            credentials=None,
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )

    assert "boundary continuity refuses" in str(raised.value)
    assert isinstance(raised.value.__cause__, BoundaryContinuityConflict)
    assert raised.value.__cause__.tick_id == "old-item-edge"
    assert raised.value.__cause__.fact_id == "retire-item"
    assert raised.value.captured_head == captured
    assert activity == ["head_at", "query-close", "ledger-close"]
    assert snapshot.closed


@pytest.mark.parametrize("args", [(), ("message",), ("message", "detail")])
def test_preparation_refusal_preserves_inherited_exception_arguments(args) -> None:
    refusal = DeclarationPreparationRefused(*args)
    assert refusal.args == args
    assert refusal.coordinator_phase is None
    assert refusal.effects is None
    assert not hasattr(refusal, "captured_head")
    assert not hasattr(refusal, "projected_head")
