"""Stage 3A detached planning and one-CAS runtime writes."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from atoms import Fact as AtomFact
from lang.document import vertex_to_documents
from lang.loader import parse_vertex

from engine.admission import UndeclaredKind
from engine.arrival import ArrivalLog
from engine.arrival_contract import (
    DeclarationAnchor,
    Fact,
    FactPage,
    FactRequest,
    Head,
    NotAuthority,
    Profile,
    ReadBasis,
    RecordDraft,
    StoreDescriptor,
    Summary,
    SummaryRequest,
    Tick,
    TickRequest,
    Watermark,
)
from engine.arrival_file_backend import FileLedger
from engine.arrival_head_attestation import Outcome
from engine.arrival_head_seam import AttestedLedger, Compared
from engine.arrival_registry import BackendRegistry
from engine.handle import WriteCredentials
from engine.loop import Loop
from engine.peer import Grant
from engine.row_commitment import fact_row_hash
from engine.runtime_write import (
    BatchFactInput,
    OrdinaryWritePlan,
    OrdinaryWritePreparationRefused,
    PostCommitProjectionFailed,
    ProjectionOutcome,
    RuntimeWriteRefused,
    WriteCommitUnknown,
    _current_write_basis,
    _pack_batch_drafts,
    execute_ordinary_write,
    hydrate_arrival_candidate,
    plan_ordinary_write,
    prepare_batch_write,
    prepare_ordinary_write,
)
from engine.vertex import ReservedKindError, Vertex


class Snapshot:
    def __init__(self, head: Head, *, facts=(), ticks=(), documents=()):
        self.represented = Watermark(head.lineage, head.ordinal)
        self.view_generation = "test-view"
        self.declaration_anchor = DeclarationAnchor(
            own_lineage=head.lineage,
            genesis=Fact(
                id=head.lineage,
                kind="_decl.genesis",
                ts=0.0,
                observer="kyle",
                origin="",
                payload={"protocol": 1, "documents": list(documents)},
                arrival_ordinal=0,
                arrival_seq=0,
                payload_text="{}",
            ),
        )
        self._facts = tuple(facts)
        self._ticks = tuple(ticks)

    def facts(self, request: FactRequest) -> FactPage:
        assert request.limit is None
        return FactPage(self._facts, None, False, request.order)

    def ticks(self, request: TickRequest) -> tuple[Tick, ...]:
        return self._ticks

    def summary(self, request: SummaryRequest) -> Summary:
        return Summary(0, 0, 0, 0, {}, {})

    def search(self, request):
        raise NotImplementedError

    def close(self) -> None:
        return None


def _head() -> Head:
    return Head("lineage", 4, "head-hash")


def _vertex() -> Vertex:
    vertex = Vertex("kyle")
    vertex.register_loop(
        Loop(
            name="note",
            initial={"items": []},
            fold=lambda state, payload: {"items": [*state["items"], payload["value"]]},
            boundary_count=1,
            boundary_mode="every",
        )
    )
    return vertex


def test_plan_signs_fresh_fact_twice_and_keeps_fresh_tick_chain_evidence():
    head = _head()
    snapshot = Snapshot(head)
    credentials = WriteCredentials(
        fact_signer=lambda observer, digest: f"fact:{observer}:{digest}",
        arrival_signer=lambda observer, digest: f"arrival:{observer}:{digest}",
        tick_signer=lambda digest: f"tick:{digest}",
    )
    vertex = _vertex()
    plan = plan_ordinary_write(
        snapshot,
        ReadBasis(head.lineage, head, head, "test-view"),
        vertex,
        AtomFact("note", 42.0, {"value": "one"}, observer="kyle"),
        grant=None,
        credentials=credentials,
        custodian="kyle",
        fact_id="fact-1",
    )

    assert plan.fact_id == "fact-1"
    assert plan.tick_id is not None
    assert [draft.kind for draft in plan.drafts] == ["fact", "tick"]
    fact, tick = plan.drafts
    assert fact.body["signature"].startswith("fact:kyle:")
    assert fact.signature is not None and fact.signature.startswith("arrival:kyle:")
    assert tick.observer == "kyle"
    assert tick.signature is None
    assert tick.body["prev_hash"] is None
    assert tick.body["window_start"] == ""
    assert tick.body["fact_cursor"] == "fact-1"
    assert tick.body["window_hash"]
    assert tick.body["signature"].startswith("tick:")
    assert vertex.state("note") == {"items": []}


def test_fact_signer_never_substitutes_for_missing_arrival_signer():
    head = _head()
    plan = plan_ordinary_write(
        Snapshot(head),
        ReadBasis(head.lineage, head, head, "test-view"),
        _vertex(),
        AtomFact("note", 42.0, {"value": "one"}, observer="kyle"),
        grant=None,
        credentials=WriteCredentials(
            fact_signer=lambda observer, digest: f"fact:{observer}:{digest}"
        ),
        custodian="kyle",
        fact_id="fact-1",
    )

    assert plan.drafts[0].body["signature"].startswith("fact:kyle:")
    assert plan.drafts[0].signature is None


def test_plan_refuses_unsigned_fresh_tick_after_signed_tick_era():
    head = _head()
    existing = Tick(
        id="old-tick",
        name="note",
        ts=1.0,
        since=None,
        origin="kyle",
        payload={},
        arrival_ordinal=3,
        arrival_seq=0,
        payload_text="{}",
        prev_hash=None,
        window_start="",
        fact_cursor="",
        window_hash="hash",
        signature="signed",
    )
    with pytest.raises(RuntimeWriteRefused, match="signed tick era"):
        plan_ordinary_write(
            Snapshot(head, ticks=(existing,)),
            ReadBasis(head.lineage, head, head, "test-view"),
            _vertex(),
            AtomFact("note", 42.0, {"value": "one"}, observer="kyle"),
            grant=None,
            credentials=WriteCredentials(),
            custodian="kyle",
            fact_id="fact-1",
        )


def test_plan_starts_a_new_chain_epoch_after_a_prechain_tick():
    head = _head()
    prechain = Tick(
        id="old-tick",
        name="note",
        ts=1.0,
        since=None,
        origin="kyle",
        payload={},
        arrival_ordinal=3,
        arrival_seq=0,
        payload_text="{}",
        prev_hash=None,
        window_start=None,
        fact_cursor="old-fact",
        window_hash=None,
        signature=None,
    )
    plan = plan_ordinary_write(
        Snapshot(head, ticks=(prechain,)),
        ReadBasis(head.lineage, head, head, "test-view"),
        _vertex(),
        AtomFact("note", 42.0, {"value": "one"}, observer="kyle"),
        grant=None,
        credentials=WriteCredentials(tick_signer=lambda digest: f"tick:{digest}"),
        custodian="kyle",
        fact_id="fact-1",
    )
    tick = plan.drafts[1]
    assert tick.body["window_start"] == "fact-1"
    assert tick.body["window_hash"] == hashlib.sha256().hexdigest()


def test_detached_plan_refuses_reserved_declaration_kind_before_append():
    head = _head()
    with pytest.raises(ReservedKindError, match="reserved declaration namespace"):
        plan_ordinary_write(
            Snapshot(head),
            ReadBasis(head.lineage, head, head, "test-view"),
            _vertex(),
            AtomFact("_decl.vertex.defined", 42.0, {}, observer="kyle"),
            grant=None,
            credentials=WriteCredentials(),
            custodian="kyle",
            fact_id="fact-1",
        )


def test_plan_id_override_deduplicates_equal_fact_and_refuses_divergence():
    head = _head()
    existing = Fact(
        id="fact-1",
        kind="note",
        ts=42.0,
        observer="kyle",
        origin="",
        payload={"value": "one"},
        arrival_ordinal=4,
        arrival_seq=0,
        payload_text='{"value": "one"}',
        signature=None,
    )
    equal = plan_ordinary_write(
        Snapshot(head, facts=(existing,)),
        ReadBasis(head.lineage, head, head, "test-view"),
        _vertex(),
        AtomFact("note", 42.0, {"value": "one"}, observer="kyle"),
        # A retry remains idempotent even if its former grant is no longer
        # sufficient; it must not re-run admission or create another tick.
        grant=Grant(potential=frozenset()),
        credentials=WriteCredentials(),
        custodian="kyle",
        fact_id="fact-1",
    )
    assert equal.already_present
    assert not equal.drafts
    with pytest.raises(RuntimeWriteRefused, match="different content"):
        plan_ordinary_write(
            Snapshot(head, facts=(existing,)),
            ReadBasis(head.lineage, head, head, "test-view"),
            _vertex(),
            AtomFact("note", 42.0, {"value": "changed"}, observer="kyle"),
            grant=None,
            credentials=WriteCredentials(),
            custodian="kyle",
            fact_id="fact-1",
        )


def test_plan_hashes_the_tick_window_by_arrival_coordinate_not_input_order():
    head = _head()
    later = Fact(
        id="later",
        kind="note",
        ts=1.0,
        observer="kyle",
        origin="",
        payload={"value": "later"},
        arrival_ordinal=3,
        arrival_seq=0,
        payload_text='{"value": "later"}',
        signature=None,
    )
    earlier = Fact(
        id="earlier",
        kind="note",
        ts=99.0,
        observer="kyle",
        origin="",
        payload={"value": "earlier"},
        arrival_ordinal=1,
        arrival_seq=0,
        payload_text='{"value": "earlier"}',
        signature=None,
    )
    plan = plan_ordinary_write(
        Snapshot(head, facts=(later, earlier)),
        ReadBasis(head.lineage, head, head, "test-view"),
        _vertex(),
        AtomFact("note", 42.0, {"value": "new"}, observer="kyle"),
        grant=None,
        credentials=WriteCredentials(),
        custodian="kyle",
        fact_id="new",
    )
    fact_body, tick_body = (draft.body for draft in plan.drafts)
    expected = hashlib.sha256()
    for row in (earlier, later):
        expected.update(
            fact_row_hash(
                (
                    row.id,
                    row.kind,
                    row.ts,
                    row.observer,
                    row.origin,
                    row.payload_text,
                    row.signature,
                )
            ).encode()
        )
    expected.update(
        fact_row_hash(
            (
                fact_body["id"],
                fact_body["kind"],
                fact_body["ts"],
                fact_body["observer"],
                fact_body["origin"],
                fact_body["payload"],
                fact_body.get("signature"),
            )
        ).encode()
    )
    assert tick_body["window_hash"] == expected.hexdigest()


def test_hydrated_candidate_ignores_stale_runtime_state_and_uses_prior_tick_context():
    head = _head()
    effective = parse_vertex(
        'name "effective"\n'
        "loops {\n"
        "  note {\n"
        '    fold { total "sum" "amount" }\n'
        "    boundary every=2\n"
        "  }\n"
        "}\n"
    )
    locator = parse_vertex('name "locator"\nloops {\n  stale {\n    fold { count "inc" }\n  }\n}\n')
    documents = [document.as_json() for document in vertex_to_documents(effective)]
    prior = Tick(
        id="prior-tick",
        name="note",
        ts=2.0,
        since=1.0,
        origin="effective",
        payload={"total": 3},
        arrival_ordinal=3,
        arrival_seq=0,
        payload_text='{"total": 3}',
        prev_hash=None,
        window_start="",
        fact_cursor="second",
        window_hash="sealed",
        signature=None,
    )
    facts = (
        Fact("first", "note", 1.0, "kyle", "", {"amount": 1}, 1, 0, '{"amount": 1}'),
        Fact("second", "note", 2.0, "kyle", "", {"amount": 2}, 2, 0, '{"amount": 2}'),
        Fact("suffix", "note", 3.0, "kyle", "", {"amount": 3}, 4, 0, '{"amount": 3}'),
    )
    snapshot = Snapshot(head, facts=facts, ticks=(prior,), documents=documents)
    snapshot._facts = (snapshot.declaration_anchor.genesis, *facts)
    basis = ReadBasis(head.lineage, head, head, "test-view")

    candidate = hydrate_arrival_candidate(snapshot, basis, locator)

    assert candidate._store is None
    assert candidate.kinds == ["note", "cite"]
    assert candidate.state("note") == {"total": 3}
    plan = plan_ordinary_write(
        snapshot,
        basis,
        candidate,
        AtomFact("note", 4.0, {"amount": 4}, observer="kyle"),
        grant=None,
        credentials=WriteCredentials(),
        custodian="kyle",
        fact_id="fourth",
    )
    assert plan.tick_id is not None
    assert plan.drafts[1].body["payload"] == '{"total": 7}'
    assert plan.drafts[1].body["since"] == 3.0


@pytest.mark.parametrize(
    "boundary",
    ("", "boundary after=2", "boundary every=2", 'boundary when="close"'),
)
def test_hydration_refuses_effective_vertex_loop_identity_collision(boundary):
    head = _head()
    effective = parse_vertex(
        'name "same"\nloops {\n  same {\n    fold { count "inc" }\n'
        f"    {boundary}\n  }}\n}}\n"
    )
    locator = parse_vertex(
        'name "locator"\nloops { distinct { fold { count "inc" } } }\n'
    )
    documents = [document.as_json() for document in vertex_to_documents(effective)]
    snapshot = Snapshot(head, documents=documents)
    snapshot._facts = (snapshot.declaration_anchor.genesis,)

    with pytest.raises(
        RuntimeWriteRefused,
        match="reserves vertex name 'same' from the loop-name namespace",
    ):
        hydrate_arrival_candidate(
            snapshot,
            ReadBasis(head.lineage, head, head, "test-view"),
            locator,
        )


def test_hydration_refuses_implicit_cite_loop_identity() -> None:
    head = _head()
    effective = parse_vertex('name "cite"\nloops { note { fold { count "inc" } } }\n')
    documents = [document.as_json() for document in vertex_to_documents(effective)]
    snapshot = Snapshot(head, documents=documents)
    snapshot._facts = (snapshot.declaration_anchor.genesis,)

    with pytest.raises(RuntimeWriteRefused, match="vertex name 'cite'"):
        hydrate_arrival_candidate(
            snapshot,
            ReadBasis(head.lineage, head, head, "test-view"),
            parse_vertex(
                'name "locator"\nloops { distinct { fold { count "inc" } } }\n'
            ),
        )


def test_hydration_refuses_template_generated_loop_identity(tmp_path) -> None:
    head = _head()
    (tmp_path / "template.loop").write_text(
        'source #"echo ok"#\nkind "{{kind}}"\nobserver "kyle"\nformat "json"\n'
    )
    effective = parse_vertex(
        'name "generated"\n'
        'sources {\n  template "template.loop" {\n'
        '    with kind="generated"\n'
        '    loop { fold { count "inc" } }\n'
        "  }\n}\n",
        path=tmp_path / "effective.vertex",
    )
    documents = [document.as_json() for document in vertex_to_documents(effective)]
    snapshot = Snapshot(head, documents=documents)
    snapshot._facts = (snapshot.declaration_anchor.genesis,)

    with pytest.raises(RuntimeWriteRefused, match="vertex name 'generated'"):
        hydrate_arrival_candidate(
            snapshot,
            ReadBasis(head.lineage, head, head, "test-view"),
            parse_vertex(
                'name "locator"\nloops { distinct { fold { count "inc" } } }\n',
                path=tmp_path / "locator.vertex",
            ),
        )


@pytest.mark.parametrize("reset", (False, True))
def test_direct_planner_refuses_runtime_loop_identity_before_signing(reset) -> None:
    head = _head()
    candidate = Vertex("same")
    candidate.register_loop(
        Loop("same", {}, lambda state, _payload: state, reset=reset)
    )
    signing_attempted = False

    def signer(*_args):
        nonlocal signing_attempted
        signing_attempted = True
        return "signature"

    with pytest.raises(RuntimeWriteRefused, match="vertex name 'same'"):
        plan_ordinary_write(
            Snapshot(head),
            ReadBasis(head.lineage, head, head, "test-view"),
            candidate,
            AtomFact("note", 1.0, {}, observer="kyle"),
            grant=None,
            credentials=WriteCredentials(
                fact_signer=signer,
                arrival_signer=signer,
            ),
            custodian="kyle",
        )

    assert signing_attempted is False


def test_hydration_refuses_child_topology_before_any_authoritative_store_open(
    monkeypatch,
):
    head = _head()
    effective = parse_vertex(
        'name "aggregate"\nstore "authority.arrival"\nvertices "./child.vertex"\n'
    )
    locator = parse_vertex('name "locator"\nloops { note { fold { count "inc" } } }\n')
    documents = [document.as_json() for document in vertex_to_documents(effective)]
    snapshot = Snapshot(head, documents=documents)
    snapshot._facts = (snapshot.declaration_anchor.genesis,)
    opened: list[str] = []

    def forbidden_open(*args, **kwargs):
        opened.append("store")
        raise AssertionError("detached hydration opened an authoritative store")

    monkeypatch.setattr("engine.jsonl_store.open_canonical_store", forbidden_open)
    monkeypatch.setattr("engine.store.EventStore", forbidden_open)

    with pytest.raises(RuntimeWriteRefused, match="multi-store child execution"):
        hydrate_arrival_candidate(
            snapshot,
            ReadBasis(head.lineage, head, head, "test-view"),
            locator,
        )
    assert opened == []


def test_hydration_restores_vertex_tick_period_like_legacy_replay():
    vertex = _vertex()
    vertex.register_vertex_boundary("close")
    facts = (
        Fact("one", "note", 1.0, "kyle", "", {"value": "one"}, 1, 0, '{"value": "one"}'),
        Fact("two", "note", 3.0, "kyle", "", {"value": "two"}, 3, 0, '{"value": "two"}'),
    )
    boundary = Tick("close-tick", "kyle", 2.0, 1.0, "kyle", {}, 2, 0, "{}")

    vertex.hydrate_snapshot(facts, (boundary,))

    # Vertex boundaries snapshot all loops but source live/replay semantics do
    # not reset their fold state. The persisted tick timestamp is the period
    # context for the next vertex boundary.
    assert vertex.state("note") == {"items": ["one", "two"]}
    assert vertex._vertex_period_start is not None
    assert vertex._vertex_period_start.timestamp() == 2.0


def test_internal_planner_threads_explicit_admit_undeclared():
    head = _head()
    strict = Vertex("strict", strict=True)
    with pytest.raises(UndeclaredKind, match="not-declared"):
        plan_ordinary_write(
            Snapshot(head),
            ReadBasis(head.lineage, head, head, "test-view"),
            strict,
            AtomFact("not-declared", 1.0, {}, observer="kyle"),
            grant=None,
            credentials=WriteCredentials(),
            custodian="custodian",
            fact_id="strict-1",
        )
    planned = plan_ordinary_write(
        Snapshot(head),
        ReadBasis(head.lineage, head, head, "test-view"),
        strict,
        AtomFact("not-declared", 1.0, {}, observer="kyle"),
        grant=None,
        credentials=WriteCredentials(),
        custodian="custodian",
        fact_id="strict-1",
        admit_undeclared=True,
    )
    assert planned.fact_id == "strict-1"


def test_supported_prepare_uses_snapshot_policy_and_genesis_custodian(monkeypatch):
    head = _head()
    effective = parse_vertex(
        'name "effective"\n'
        'observers { kyle { grant { potential "current" } } }\n'
        'loops { current { fold { count "inc" } } }\n'
    )
    locator = parse_vertex(
        'name "locator"\n'
        'observers { kyle { grant { potential "stale" } } }\n'
        'loops { stale { fold { count "inc" } } }\n'
    )
    documents = [document.as_json() for document in vertex_to_documents(effective)]
    snapshot = Snapshot(head, documents=documents)
    snapshot._facts = (snapshot.declaration_anchor.genesis,)

    class FakeLedger:
        def __init__(self):
            self.opened = SimpleNamespace(comparison=Compared(Outcome.FIRST_CONTACT, head, None))

        def head_at(self, watermark):
            assert watermark == snapshot.represented
            return head

        def read(self, coordinate):
            assert coordinate == 0
            return {"k": "genesis", "observer": "physical-custodian"}

        def capabilities(self):
            return SimpleNamespace(max_atomic_records=None)

        def close(self):
            return None

    class FakeRegistry:
        def open(self, descriptor):
            return FakeLedger(), SimpleNamespace(
                open_snapshot=lambda **kwargs: snapshot,
                close=lambda: None,
            )

    monkeypatch.setattr("engine.runtime_write.AttestedLedger", FakeLedger)
    plan = prepare_ordinary_write(
        FakeRegistry(),
        StoreDescriptor("file", "ignored", role=Profile.AUTHORITY),
        locator,
        AtomFact("current", 1.0, {}, observer="kyle"),
        credentials=WriteCredentials(),
        fact_id="prepared",
    )

    assert plan.effective_declaration is not None
    assert plan.effective_declaration.name == "effective"
    assert plan.admission_grant is not None
    assert plan.admission_grant.potential == frozenset({"current"})
    assert plan.custodian == "physical-custodian"
    assert plan.drafts[0].observer == "kyle"


def test_supported_prepare_admission_refusal_retains_snapshot_preview_evidence(
    monkeypatch,
):
    head = _head()
    effective = parse_vertex(
        'name "effective"\n'
        'observers { kyle { grant { potential "current" } } }\n'
        'loops { current { fold { count "inc" } } }\n'
    )
    locator = parse_vertex('name "locator"\nloops { stale { fold { count "inc" } } }\n')
    snapshot = Snapshot(
        head,
        documents=[document.as_json() for document in vertex_to_documents(effective)],
    )
    snapshot._facts = (snapshot.declaration_anchor.genesis,)

    class FakeLedger:
        def __init__(self):
            self.opened = SimpleNamespace(comparison=Compared(Outcome.FIRST_CONTACT, head, None))

        def head_at(self, watermark):
            return head

        def read(self, coordinate):
            return {"k": "genesis", "observer": "physical-custodian"}

        def capabilities(self):
            return SimpleNamespace(max_atomic_records=None)

        def close(self):
            return None

    class FakeRegistry:
        def open(self, descriptor):
            return FakeLedger(), SimpleNamespace(
                open_snapshot=lambda **kwargs: snapshot,
                close=lambda: None,
            )

    monkeypatch.setattr("engine.runtime_write.AttestedLedger", FakeLedger)
    with pytest.raises(OrdinaryWritePreparationRefused) as raised:
        prepare_ordinary_write(
            FakeRegistry(),
            StoreDescriptor("file", "ignored", role=Profile.AUTHORITY),
            locator,
            AtomFact("current", 1.0, {}, observer="not-kyle"),
            credentials=WriteCredentials(),
        )
    refusal = raised.value
    assert refusal.effective_declaration.name == "effective"
    assert refusal.custodian == "physical-custodian"
    assert refusal.admission_grant is None
    assert refusal.fact.observer == "not-kyle"
    assert refusal.basis.captured_head == head
    assert refusal.captured_head == head


def test_supported_prepare_deduplicates_before_removed_observer_admission(monkeypatch):
    head = _head()
    effective = parse_vertex(
        'name "effective"\n'
        'observers { kyle { grant { potential "current" } } }\n'
        'loops { current { fold { count "inc" } } }\n'
    )
    locator = parse_vertex('name "locator"\nloops { stale { fold { count "inc" } } }\n')
    existing = Fact("retry", "current", 1.0, "removed", "", {}, 1, 0, "{}", None)
    snapshot = Snapshot(
        head,
        facts=(existing,),
        documents=[document.as_json() for document in vertex_to_documents(effective)],
    )
    snapshot._facts = (snapshot.declaration_anchor.genesis, existing)

    class FakeLedger:
        def __init__(self):
            self.opened = SimpleNamespace(comparison=Compared(Outcome.FIRST_CONTACT, head, None))

        def head_at(self, watermark):
            return head

        def read(self, coordinate):
            return {"k": "genesis", "observer": "physical-custodian"}

        def capabilities(self):
            return SimpleNamespace(max_atomic_records=None)

        def close(self):
            return None

    class FakeRegistry:
        def open(self, descriptor):
            return FakeLedger(), SimpleNamespace(
                open_snapshot=lambda **kwargs: snapshot,
                close=lambda: None,
            )

    monkeypatch.setattr("engine.runtime_write.AttestedLedger", FakeLedger)
    plan = prepare_ordinary_write(
        FakeRegistry(),
        StoreDescriptor("file", "ignored", role=Profile.AUTHORITY),
        locator,
        AtomFact("current", 1.0, {}, observer="removed"),
        credentials=WriteCredentials(),
        fact_id="retry",
    )
    assert plan.already_present
    assert plan.drafts == ()
    assert plan.effective_declaration.name == "effective"
    assert plan.custodian == "physical-custodian"


def test_current_write_basis_clamps_a_valid_projection_advance_to_captured_head():
    captured = _head()
    advanced = Head(captured.lineage, captured.ordinal + 1, "later-hash")
    snapshot = Snapshot(captured)
    snapshot.represented = Watermark(captured.lineage, advanced.ordinal)

    class Ledger:
        def head_at(self, watermark):
            assert watermark == snapshot.represented
            return advanced

    basis = _current_write_basis(Ledger(), snapshot, captured)
    assert basis.captured_head == captured
    assert basis.projected_through == captured


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("foreign", NotAuthority),
        ("missing", LookupError),
        ("substitution", RuntimeWriteRefused),
        ("wrong-coordinate", RuntimeWriteRefused),
    ),
)
def test_current_write_basis_refuses_unvouched_projection_prefixes(case, expected):
    captured = _head()
    represented = Watermark(
        "foreign" if case == "foreign" else captured.lineage,
        captured.ordinal + 1 if case == "missing" else captured.ordinal,
    )
    snapshot = Snapshot(captured)
    snapshot.represented = represented

    class Ledger:
        def head_at(self, watermark):
            if case == "foreign":
                raise AssertionError("foreign watermark reached custody lookup")
            if case == "missing":
                raise LookupError("prefix absent")
            if case == "wrong-coordinate":
                return Head(captured.lineage, captured.ordinal - 1, "wrong")
            return Head(captured.lineage, captured.ordinal, "replacement")

    with pytest.raises(expected):
        _current_write_basis(Ledger(), snapshot, captured)


def test_supported_prepare_refuses_projection_substitution_before_signing_or_append(
    monkeypatch,
):
    captured = _head()
    replacement = Head(captured.lineage, captured.ordinal, "replacement")
    snapshot = Snapshot(captured)
    activity: list[str] = []

    class Ledger:
        def __init__(self):
            self.opened = SimpleNamespace(
                comparison=Compared(Outcome.UNCHANGED, captured, None)
            )

        def head_at(self, watermark):
            activity.append("head_at")
            return replacement

        def append(self, *args, **kwargs):
            activity.append("append")
            raise AssertionError("invalid projection reached append")

        def close(self):
            activity.append("ledger-close")

    class Query:
        def open_snapshot(self, **kwargs):
            return snapshot

        def close(self):
            activity.append("query-close")

    class Registry:
        def open(self, descriptor):
            return Ledger(), Query()

    def signer(*_args):
        activity.append("sign")
        raise AssertionError("invalid projection reached signing")

    monkeypatch.setattr("engine.runtime_write.AttestedLedger", Ledger)
    with pytest.raises(RuntimeWriteRefused, match="disagrees"):
        prepare_ordinary_write(
            Registry(),
            StoreDescriptor("file", "unused", role=Profile.AUTHORITY),
            parse_vertex('name "x"\nloops { note { fold { count "inc" } } }\n'),
            AtomFact("note", 1.0, {}, observer="kyle"),
            credentials=WriteCredentials(
                fact_signer=signer,
                arrival_signer=signer,
                tick_signer=lambda _digest: signer(),
            ),
        )
    assert activity == ["head_at", "query-close", "ledger-close"]


def test_plan_refuses_a_generated_tick_id_already_present(monkeypatch):
    head = _head()
    previous = Tick(
        id="old-tick",
        name="note",
        ts=1.0,
        since=None,
        origin="kyle",
        payload={},
        arrival_ordinal=3,
        arrival_seq=0,
        payload_text="{}",
        prev_hash=None,
        window_start="",
        fact_cursor="",
        window_hash="hash",
        signature=None,
    )
    monkeypatch.setattr("engine.runtime_write.ULID", lambda: "old-tick")
    with pytest.raises(RuntimeWriteRefused, match="generated tick id"):
        plan_ordinary_write(
            Snapshot(head, ticks=(previous,)),
            ReadBasis(head.lineage, head, head, "test-view"),
            _vertex(),
            AtomFact("note", 42.0, {"value": "one"}, observer="kyle"),
            grant=None,
            credentials=WriteCredentials(),
            custodian="kyle",
            fact_id="fact-1",
        )


def test_execute_appends_one_prepared_plan_and_reports_unmaintained_projection(
    tmp_path, keys, signer
):
    log = ArrivalLog.mint(
        tmp_path / "runtime.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
    )
    head = FileLedger(log).head()
    plan = OrdinaryWritePlan(
        captured_head=head,
        fact_id="fact-1",
        tick_id=None,
        drafts=(
            RecordDraft(
                kind="fact",
                authored_at=2.0,
                observer="kyle",
                body={
                    "id": "fact-1",
                    "kind": "note",
                    "ts": 2.0,
                    "observer": "kyle",
                    "origin": "",
                    "payload": "{}",
                },
            ),
        ),
    )
    result = execute_ordinary_write(
        BackendRegistry.with_builtin_backends(),
        StoreDescriptor("file", str(log.path), role=Profile.AUTHORITY),
        plan,
    )
    assert result.commit.before == head
    assert result.commit.after.ordinal == head.ordinal + 1
    assert result.projection is ProjectionOutcome.NOT_REQUESTED


def test_execute_commits_a_planned_fact_and_boundary_tick_under_one_head_fence(
    tmp_path, keys, signer
):
    log = ArrivalLog.mint(
        tmp_path / "boundary.arrival", observer="kyle", signer=signer, key=keys.public
    )
    head = FileLedger(log).head()
    plan = plan_ordinary_write(
        Snapshot(head),
        ReadBasis(head.lineage, head, head, "test-view"),
        _vertex(),
        AtomFact("note", 2.0, {"value": "one"}, observer="kyle"),
        grant=None,
        credentials=WriteCredentials(),
        custodian="kyle",
        fact_id="fact-boundary",
    )
    assert [draft.kind for draft in plan.drafts] == ["fact", "tick"]
    result = execute_ordinary_write(
        BackendRegistry.with_builtin_backends(),
        StoreDescriptor("file", str(log.path), role=Profile.AUTHORITY),
        plan,
    )
    assert result.commit.before == head
    assert result.commit.after.ordinal == head.ordinal + 2
    assert [record["k"] for record in log.walk()] == ["genesis", "fact", "tick"]


def test_execute_surfaces_unknown_after_a_durable_adapter_append(
    tmp_path, keys, signer, monkeypatch
):
    log = ArrivalLog.mint(
        tmp_path / "unknown.arrival", observer="kyle", signer=signer, key=keys.public
    )
    head = FileLedger(log).head()
    plan = OrdinaryWritePlan(
        captured_head=head,
        fact_id="fact-unknown",
        tick_id=None,
        drafts=(
            RecordDraft(
                kind="fact",
                authored_at=2.0,
                observer="kyle",
                body={
                    "id": "fact-unknown",
                    "kind": "note",
                    "ts": 2.0,
                    "observer": "kyle",
                    "origin": "",
                    "payload": "{}",
                },
            ),
        ),
    )
    original = AttestedLedger.append
    calls = 0

    def append_then_raise(self, expected, drafts):
        nonlocal calls
        calls += 1
        original(self, expected, drafts)
        raise OSError("adapter lost its completion response")

    monkeypatch.setattr(AttestedLedger, "append", append_then_raise)
    with pytest.raises(WriteCommitUnknown) as raised:
        execute_ordinary_write(
            BackendRegistry.with_builtin_backends(),
            StoreDescriptor("file", str(log.path), role=Profile.AUTHORITY),
            plan,
        )
    unknown = raised.value
    assert calls == 1
    assert unknown.outcome == "unknown"
    assert unknown.captured_head == head
    assert unknown.fact_id == "fact-unknown"
    assert unknown.tick_id is None
    assert unknown.drafts == plan.drafts
    assert isinstance(unknown.cause, OSError)
    assert FileLedger(log).head().ordinal == head.ordinal + 1


def test_execute_noop_retry_remains_idempotent_after_an_unrelated_append(tmp_path, keys, signer):
    log = ArrivalLog.mint(
        tmp_path / "noop.arrival", observer="kyle", signer=signer, key=keys.public
    )
    captured = FileLedger(log).head()
    log.append(
        "fact",
        {
            "id": "already",
            "kind": "note",
            "ts": 1.0,
            "observer": "kyle",
            "origin": "",
            "payload": "{}",
        },
        observer="kyle",
    )
    plan = OrdinaryWritePlan(
        captured_head=captured,
        fact_id="already",
        tick_id=None,
        drafts=(),
        already_present=True,
    )
    result = execute_ordinary_write(
        BackendRegistry.with_builtin_backends(),
        StoreDescriptor("file", str(log.path), role=Profile.AUTHORITY),
        plan,
    )
    assert result.commit is None
    assert FileLedger(log).head().ordinal == captured.ordinal + 1


def test_execute_retains_commit_identity_when_postcommit_projection_fails(tmp_path, keys, signer):
    log = ArrivalLog.mint(
        tmp_path / "projection-failure.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
    )
    head = FileLedger(log).head()
    plan = OrdinaryWritePlan(
        head,
        "projection-fact",
        None,
        (
            RecordDraft(
                "fact",
                2.0,
                "kyle",
                body={
                    "id": "projection-fact",
                    "kind": "note",
                    "ts": 2.0,
                    "observer": "kyle",
                    "origin": "",
                    "payload": "{}",
                },
            ),
        ),
    )

    def fail_projection(committed_head):
        assert committed_head.ordinal == head.ordinal + 1
        raise RuntimeError("projection unavailable")

    with pytest.raises(PostCommitProjectionFailed) as raised:
        execute_ordinary_write(
            BackendRegistry.with_builtin_backends(),
            StoreDescriptor("file", str(log.path), role=Profile.AUTHORITY),
            plan,
            after_commit=fail_projection,
        )
    failure = raised.value
    assert failure.commit.after.ordinal == head.ordinal + 1
    assert failure.fact_id == "projection-fact"
    assert failure.projection is ProjectionOutcome.FAILED
    assert FileLedger(log).head() == failure.commit.after


def test_batch_packing_keeps_fact_tick_order_and_groups_only_adjacent_observer_facts():
    def fact(identifier, observer="kyle"):
        return RecordDraft(
            "fact",
            1.0,
            observer,
            body={
                "id": identifier,
                "kind": "note",
                "ts": 1.0,
                "observer": observer,
                "origin": "",
                "payload": "{}",
            },
        )

    tick = RecordDraft(
        "tick",
        2.0,
        "custodian",
        body={
            "id": "tick",
            "name": "note",
            "ts": 2.0,
            "since": None,
            "origin": "kyle",
            "payload": "{}",
            "prev_hash": None,
            "window_start": "",
            "fact_cursor": "two",
            "window_hash": "hash",
        },
    )
    packed = _pack_batch_drafts(
        (fact("one"), fact("two"), tick, fact("three"), fact("four", "other")),
        WriteCredentials(),
    )

    assert [draft.kind for draft in packed] == ["batch", "tick", "fact", "fact"]
    assert [row["id"] for row in packed[0].body["rows"]] == ["one", "two"]


def test_supported_batch_prepares_two_facts_as_one_wire_batch(monkeypatch):
    head = _head()
    effective = parse_vertex('name "effective"\nloops { note { fold { count "inc" } } }\n')
    locator = parse_vertex('name "locator"\nloops { stale { fold { count "inc" } } }\n')
    snapshot = Snapshot(
        head,
        documents=[document.as_json() for document in vertex_to_documents(effective)],
    )
    snapshot._facts = (snapshot.declaration_anchor.genesis,)

    class FakeLedger:
        def __init__(self):
            self.opened = SimpleNamespace(comparison=Compared(Outcome.FIRST_CONTACT, head, None))

        def head_at(self, watermark):
            return head

        def read(self, coordinate):
            return {"k": "genesis", "observer": "custodian"}

        def capabilities(self):
            return SimpleNamespace(max_atomic_records=None)

        def close(self):
            return None

    class FakeRegistry:
        def open(self, descriptor):
            return FakeLedger(), SimpleNamespace(
                open_snapshot=lambda **kwargs: snapshot,
                close=lambda: None,
            )

    monkeypatch.setattr("engine.runtime_write.AttestedLedger", FakeLedger)
    plan = prepare_batch_write(
        FakeRegistry(),
        StoreDescriptor("file", "ignored", role=Profile.AUTHORITY),
        locator,
        (
            BatchFactInput(AtomFact("note", 1.0, {"n": 1}, observer="kyle"), "one"),
            BatchFactInput(AtomFact("note", 2.0, {"n": 2}, observer="kyle"), "two"),
        ),
        credentials=WriteCredentials(),
    )
    assert [item.fact_id for item in plan.items] == ["one", "two"]
    assert [draft.kind for draft in plan.drafts] == ["batch"]
    assert [row["id"] for row in plan.drafts[0].body["rows"]] == ["one", "two"]
