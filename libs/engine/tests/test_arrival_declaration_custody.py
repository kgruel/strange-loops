"""Declaration preparation completes projection evidence through custody."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from lang.document import vertex_to_documents
from lang.loader import parse_vertex

from engine.arrival_contract import (
    DeclarationAnchor,
    Fact,
    FactPage,
    Head,
    Profile,
    ProjectionBehind,
    StoreDescriptor,
    Watermark,
)
from engine.arrival_declarations import (
    DeclarationPreparationRefused,
    prepare_declaration_edit,
)
from engine.arrival_head_attestation import Outcome
from engine.arrival_head_seam import Compared


class _Snapshot:
    def __init__(self, represented: Watermark, genesis: Fact):
        self.represented = represented
        self.view_generation = "view"
        self.declaration_anchor = DeclarationAnchor(genesis.id, genesis)
        self._genesis = genesis
        self.closed = False

    def facts(self, request):
        return FactPage((self._genesis,), None, False, request.order)

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
        payload_text="{}",
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


@pytest.mark.parametrize("args", [(), ("message",), ("message", "detail")])
def test_preparation_refusal_preserves_inherited_exception_arguments(args) -> None:
    refusal = DeclarationPreparationRefused(*args)
    assert refusal.args == args
    assert refusal.coordinator_phase is None
    assert refusal.effects is None
    assert not hasattr(refusal, "captured_head")
    assert not hasattr(refusal, "projected_head")
