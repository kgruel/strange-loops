"""Hypothesis RuleBasedStateMachine stateful test suite for SDK public operations.

Validates end-to-end invariants across fact emission, dry-run simulation, batch
operations, declaration updates (add/edit/remove kind, grant/revoke observer),
and query operations (summary, pagination, ID lookup, fold state, search, ticks).
"""

from __future__ import annotations

import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import hypothesis.errors
import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from lang.ast import FoldCollect, FoldDecl, LoopDef

from sdk import (
    AdmissionFailed,
    CeremonyFailed,
    DeclarationInspectionResult,
    DeclarationPlanResult,
    EmitPreviewResult,
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    ReadSummary,
    SdkError,
    SearchResult,
    SyncResult,
    TargetInfo,
    TimelineResult,
    add_kind,
    discover_targets,
    edit_kind,
    emit_batch,
    emit_fact,
    grant_observer,
    init_vertex,
    inspect_declaration,
    plan_kind_mutation,
    preview_emission,
    read_fact_by_id,
    read_facts,
    read_state,
    read_summary,
    read_ticks,
    read_timeline,
    remove_kind,
    resolve_target,
    revoke_observer,
    search_facts,
    sync_target,
)

T = TypeVar("T")

# -----------------------------------------------------------------------------
# Strategies
# -----------------------------------------------------------------------------
KNOWN_KINDS = ["item", "task", "note", "metric", "event"]
KNOWN_OBSERVERS = ["admin", "alice", "bob", "carol"]

st_kind_names = st.sampled_from(KNOWN_KINDS)
st_observer_names = st.sampled_from(KNOWN_OBSERVERS)
st_extra_observers = st.sampled_from(["alice", "bob", "carol"])

st_small_payloads = st.fixed_dictionaries(
    {
        "title": st.text(
            alphabet=st.characters(categories=["Ll", "Nd"]),
            min_size=1,
            max_size=12,
        ),
    },
    optional={
        "priority": st.integers(min_value=0, max_value=100),
        "tag": st.text(
            alphabet=st.characters(categories=["Ll"]),
            min_size=1,
            max_size=6,
        ),
    },
)

st_batch_items = st.lists(
    st.tuples(st_kind_names, st_small_payloads),
    min_size=1,
    max_size=4,
)


@dataclass(frozen=True)
class EmittedFactModel:
    """Plain-Python tracking model for an emitted fact."""

    id: str
    kind: str
    payload: dict[str, Any]
    observer: str
    ts: float


# -----------------------------------------------------------------------------
# Stateful State Machine
# -----------------------------------------------------------------------------
# Settings configuration:
# - max_examples=30, stateful_step_count=25: runs in tens of seconds during standard CI.
# - For deep fuzzing / overnight regression runs, crank to:
#   max_examples=200, stateful_step_count=100.
@settings(
    max_examples=30,
    stateful_step_count=25,
    deadline=None,
)
class SdkStateMachine(RuleBasedStateMachine):
    """Hypothesis RuleBasedStateMachine modeling the SDK's public operation surface."""

    def __init__(self) -> None:
        super().__init__()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.vertex_path = self.tmp_path / "stateful.vertex"

        # Scaffold standalone SQLite vertex target
        init_res = self.call_sdk(
            init_vertex,
            self.vertex_path,
            name="stateful",
            store_type="sqlite",
            observer="admin",
        )
        assert init_res.file_written is True

        # Plain Python model state
        self.facts: list[EmittedFactModel] = []
        self.facts_by_id: dict[str, EmittedFactModel] = {}
        self.declared_kinds: set[str] = {"item"}
        self.removed_kinds: set[str] = set()
        self.declared_observers: set[str] = {"admin"}
        self._seq: int = 0

    def teardown(self) -> None:
        self.temp_dir.cleanup()
        super().teardown()

    def call_sdk(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Wrap every SDK operation call to enforce invariant (8): only SdkError may be raised."""
        try:
            return fn(*args, **kwargs)
        except SdkError:
            raise
        except hypothesis.errors.HypothesisException:
            raise
        except Exception as exc:
            raise AssertionError(
                f"SDK operation {getattr(fn, '__name__', str(fn))} raised non-SdkError exception "
                f"of type {type(exc).__name__}: {exc}"
            ) from exc

    def _next_ts(self) -> float:
        self._seq += 1
        return 1700000000.0 + self._seq * 10.0

    # =========================================================================
    # Mutation Rules: Emission (weighted)
    # =========================================================================

    @rule(
        kind=st_kind_names,
        payload=st_small_payloads,
        observer=st_observer_names,
        admit_undeclared=st.booleans(),
    )
    def emit_fact_rule(
        self,
        kind: str,
        payload: dict[str, Any],
        observer: str,
        admit_undeclared: bool,
    ) -> None:
        """Emit single fact into vertex and update model on success."""
        ts = self._next_ts()
        if observer not in self.declared_observers:
            with pytest.raises(AdmissionFailed):
                self.call_sdk(
                    emit_fact,
                    self.vertex_path,
                    kind,
                    payload,
                    observer=observer,
                    ts=ts,
                    admit_undeclared=admit_undeclared,
                )
            return

        receipt = self.call_sdk(
            emit_fact,
            self.vertex_path,
            kind,
            payload,
            observer=observer,
            ts=ts,
            admit_undeclared=admit_undeclared,
        )

        assert isinstance(receipt, EmitReceipt)
        assert receipt.stored is True
        assert receipt.id != ""
        assert receipt.observer == observer
        assert receipt.predicted_state_change is False

        if kind in self.declared_kinds:
            assert kind in receipt.affected_sections
        else:
            assert receipt.affected_sections == []
            assert receipt.delta_count == 0

        model_fact = EmittedFactModel(
            id=receipt.id,
            kind=kind,
            payload=payload,
            observer=observer,
            ts=ts,
        )
        self.facts.append(model_fact)
        self.facts_by_id[receipt.id] = model_fact

    @rule(
        kind=st_kind_names,
        payload=st_small_payloads,
        observer=st_observer_names,
        admit_undeclared=st.booleans(),
    )
    def emit_fact_dry_run_rule(
        self,
        kind: str,
        payload: dict[str, Any],
        observer: str,
        admit_undeclared: bool,
    ) -> None:
        """Dry-run emit_fact performs preflight checks and must NEVER mutate the store."""
        summary_before = self.call_sdk(read_summary, self.vertex_path)
        state_before = self.call_sdk(read_state, self.vertex_path)

        if observer not in self.declared_observers:
            with pytest.raises(AdmissionFailed):
                self.call_sdk(
                    emit_fact,
                    self.vertex_path,
                    kind,
                    payload,
                    observer=observer,
                    admit_undeclared=admit_undeclared,
                    dry_run=True,
                )
        else:
            receipt = self.call_sdk(
                emit_fact,
                self.vertex_path,
                kind,
                payload,
                observer=observer,
                admit_undeclared=admit_undeclared,
                dry_run=True,
            )
            # Invariant (4): dry-run receipts have stored=False, state_change=False
            assert isinstance(receipt, EmitReceipt)
            assert receipt.stored is False
            assert receipt.id == ""
            assert receipt.state_change is False
            assert receipt.delta_count == 0
            assert receipt.predicted_state_change is (kind in self.declared_kinds)
            if kind in self.declared_kinds:
                assert receipt.affected_sections == [kind]
            else:
                assert receipt.affected_sections == []

        # Invariant (3): reads before and after dry-run are identical
        summary_after = self.call_sdk(read_summary, self.vertex_path)
        state_after = self.call_sdk(read_state, self.vertex_path)
        assert summary_after == summary_before
        assert state_after == state_before

    @rule(
        kind=st_kind_names,
        payload=st_small_payloads,
        observer=st_observer_names,
        admit_undeclared=st.booleans(),
    )
    def preview_emission_rule(
        self,
        kind: str,
        payload: dict[str, Any],
        observer: str,
        admit_undeclared: bool,
    ) -> None:
        """preview_emission evaluates admission and foldability without store mutation."""
        summary_before = self.call_sdk(read_summary, self.vertex_path)
        state_before = self.call_sdk(read_state, self.vertex_path)

        preview = self.call_sdk(
            preview_emission,
            self.vertex_path,
            kind,
            payload,
            observer=observer,
            admit_undeclared=admit_undeclared,
        )

        assert isinstance(preview, EmitPreviewResult)
        is_admitted = observer in self.declared_observers
        assert preview.admitted is is_admitted
        assert preview.would_store is is_admitted
        assert preview.would_fold is (is_admitted and (kind in self.declared_kinds))

        # Invariant (3): reads after match reads before
        summary_after = self.call_sdk(read_summary, self.vertex_path)
        state_after = self.call_sdk(read_state, self.vertex_path)
        assert summary_after == summary_before
        assert state_after == state_before

    @rule(
        batch_items=st_batch_items,
        observer=st_observer_names,
        admit_undeclared=st.booleans(),
    )
    def emit_batch_rule(
        self,
        batch_items: list[tuple[str, dict[str, Any]]],
        observer: str,
        admit_undeclared: bool,
    ) -> None:
        """emit_batch commits a batch of facts under one handle session."""
        if observer not in self.declared_observers:
            with pytest.raises(AdmissionFailed):
                self.call_sdk(
                    emit_batch,
                    self.vertex_path,
                    batch_items,
                    observer=observer,
                    admit_undeclared=admit_undeclared,
                )
            return

        receipts = self.call_sdk(
            emit_batch,
            self.vertex_path,
            batch_items,
            observer=observer,
            admit_undeclared=admit_undeclared,
        )

        assert len(receipts) == len(batch_items)
        for (kind, payload), r in zip(batch_items, receipts, strict=True):
            assert r.stored is True
            assert r.id != ""
            assert r.observer == observer
            assert r.predicted_state_change is False
            ts = self._next_ts()
            model_fact = EmittedFactModel(
                id=r.id,
                kind=kind,
                payload=payload,
                observer=observer,
                ts=ts,
            )
            self.facts.append(model_fact)
            self.facts_by_id[r.id] = model_fact

    # =========================================================================
    # Mutation Rules: Declaration & Ceremonies
    # =========================================================================

    @rule(kind=st_kind_names)
    def add_kind_rule(self, kind: str) -> None:
        """add_kind declares a new kind in the vertex declaration."""
        if kind in self.declared_kinds:
            with pytest.raises(CeremonyFailed):
                self.call_sdk(add_kind, self.vertex_path, kind, observer="admin")
            return

        res = self.call_sdk(add_kind, self.vertex_path, kind, observer="admin")
        assert res.status in ("applied", "noop")
        assert res.file_written is True

        self.declared_kinds.add(kind)
        self.removed_kinds.discard(kind)

    @rule(
        kind=st_kind_names,
        max_items=st.integers(min_value=10, max_value=200),
    )
    def edit_kind_rule(self, kind: str, max_items: int) -> None:
        """edit_kind modifies an existing kind definition."""
        new_def = LoopDef(folds=(FoldDecl("items", FoldCollect(max_items)),))
        if kind not in self.declared_kinds:
            with pytest.raises(CeremonyFailed):
                self.call_sdk(
                    edit_kind,
                    self.vertex_path,
                    kind,
                    definition=new_def,
                    observer="admin",
                )
            return

        res = self.call_sdk(
            edit_kind,
            self.vertex_path,
            kind,
            definition=new_def,
            observer="admin",
        )
        assert res.status in ("applied", "noop")

    @rule(kind=st_kind_names)
    def remove_kind_rule(self, kind: str) -> None:
        """remove_kind removes kind from declaration while preserving emitted facts."""
        # A vertex declaration requires >= 1 loops; removing the sole kind raises CeremonyFailed
        if kind not in self.declared_kinds or len(self.declared_kinds) <= 1:
            with pytest.raises(CeremonyFailed):
                self.call_sdk(remove_kind, self.vertex_path, kind, observer="admin")
            return

        res = self.call_sdk(remove_kind, self.vertex_path, kind, observer="admin")
        assert res.status in ("applied", "noop")

        self.declared_kinds.remove(kind)
        self.removed_kinds.add(kind)

    @rule(
        op=st.sampled_from(["add", "edit", "remove"]),
        kind=st_kind_names,
    )
    def plan_kind_mutation_rule(self, op: str, kind: str) -> None:
        """plan_kind_mutation simulates ceremony planning without disk mutation."""
        # Only simulate valid candidate mutations
        if op == "add" and kind in self.declared_kinds:
            return
        if op == "edit" and kind not in self.declared_kinds:
            return
        if op == "remove" and (kind not in self.declared_kinds or len(self.declared_kinds) <= 1):
            return

        summary_before = self.call_sdk(read_summary, self.vertex_path)
        state_before = self.call_sdk(read_state, self.vertex_path)

        plan = self.call_sdk(plan_kind_mutation, self.vertex_path, op, kind)
        assert isinstance(plan, DeclarationPlanResult)

        summary_after = self.call_sdk(read_summary, self.vertex_path)
        state_after = self.call_sdk(read_state, self.vertex_path)
        assert summary_after == summary_before
        assert state_after == state_before

    @rule(observer_name=st_extra_observers)
    def grant_observer_rule(self, observer_name: str) -> None:
        """grant_observer adds observer identity to declared admission block."""
        res = self.call_sdk(
            grant_observer,
            self.vertex_path,
            observer_name,
            observer="admin",
        )
        assert res.status in ("applied", "noop")
        self.declared_observers.add(observer_name)

    @rule(observer_name=st_extra_observers)
    def revoke_observer_rule(self, observer_name: str) -> None:
        """revoke_observer removes observer identity from declared admission block."""
        if observer_name not in self.declared_observers:
            with pytest.raises(CeremonyFailed):
                self.call_sdk(
                    revoke_observer,
                    self.vertex_path,
                    observer_name,
                    observer="admin",
                )
            return

        res = self.call_sdk(
            revoke_observer,
            self.vertex_path,
            observer_name,
            observer="admin",
        )
        assert res.status in ("applied", "noop")
        self.declared_observers.discard(observer_name)

    # =========================================================================
    # Read Rules (Check rather than mutate)
    # =========================================================================

    @rule()
    def check_read_summary(self) -> None:
        """Verify read_summary matches model inventory."""
        summary = self.call_sdk(read_summary, self.vertex_path)
        assert isinstance(summary, ReadSummary)
        assert summary.target_type == "vertex"
        assert summary.fact_total == len(self.facts)

        kind_counts: dict[str, int] = defaultdict(int)
        for f in self.facts:
            kind_counts[f.kind] += 1

        for k, count in kind_counts.items():
            assert k in summary.kinds
            assert summary.kinds[k]["count"] == count

        expected_unfolded = set(kind_counts.keys()) - self.declared_kinds
        assert set(summary.unfolded_kinds) == expected_unfolded

    @rule(limit=st.sampled_from([1, 2, 3, 5, 10]))
    def check_read_facts_pagination(self, limit: int) -> None:
        """Verify read_facts cursoring partitions all facts without duplicates or gaps."""
        if not self.facts:
            page = self.call_sdk(read_facts, self.vertex_path, limit=limit)
            assert isinstance(page, FactPageResult)
            assert page.items == []
            return

        # Newest order
        collected_newest_ids: list[str] = []
        cursor: str | None = None
        while True:
            page = self.call_sdk(
                read_facts,
                self.vertex_path,
                limit=limit,
                before=cursor,
                order="newest",
            )
            assert isinstance(page, FactPageResult)
            collected_newest_ids.extend(it["id"] for it in page.items)
            if not page.truncated or page.next_cursor is None:
                break
            cursor = page.next_cursor

        assert len(collected_newest_ids) == len(self.facts)
        assert len(set(collected_newest_ids)) == len(self.facts)
        assert set(collected_newest_ids) == set(self.facts_by_id.keys())

        # Oldest order
        collected_oldest_ids: list[str] = []
        cursor = None
        while True:
            page = self.call_sdk(
                read_facts,
                self.vertex_path,
                limit=limit,
                after=cursor,
                order="oldest",
            )
            assert isinstance(page, FactPageResult)
            collected_oldest_ids.extend(it["id"] for it in page.items)
            if not page.truncated or page.next_cursor is None:
                break
            cursor = page.next_cursor

        assert len(collected_oldest_ids) == len(self.facts)
        assert set(collected_oldest_ids) == set(self.facts_by_id.keys())
        assert collected_oldest_ids == list(reversed(collected_newest_ids))

    @rule(kind=st_kind_names)
    def check_read_facts_filtered(self, kind: str) -> None:
        """Verify read_facts kind filter returns exact model facts."""
        page = self.call_sdk(read_facts, self.vertex_path, limit=100, kind=kind)
        expected_ids = {f.id for f in self.facts if f.kind == kind}
        actual_ids = {it["id"] for it in page.items}
        assert actual_ids == expected_ids

    @rule()
    def check_read_fact_by_id(self) -> None:
        """Verify every model fact is retrievable by ID and nonexistent ID returns None."""
        for mf in self.facts:
            f = self.call_sdk(read_fact_by_id, self.vertex_path, mf.id)
            assert f is not None
            assert f["id"] == mf.id
            assert f["kind"] == mf.kind
            assert f["observer"] == mf.observer

        none_res = self.call_sdk(read_fact_by_id, self.vertex_path, "00000000000000000000000000")
        assert none_res is None

    @rule()
    def check_read_state(self) -> None:
        """Verify reconstructed fold state matches declared kinds and fold counts."""
        state = self.call_sdk(read_state, self.vertex_path)
        assert isinstance(state, FoldStateResult)
        assert state.vertex_name == "stateful"

        if state.sections:
            for k in self.declared_kinds:
                assert k in state.sections
                emitted_count = sum(1 for f in self.facts if f.kind == k)
                assert len(state.sections[k]["items"]) == min(100, emitted_count)

            for k in self.removed_kinds:
                assert k not in state.sections

            for k in state.sections:
                assert k in self.declared_kinds

    @rule()
    def check_read_ticks(self) -> None:
        """Verify read_ticks returns valid chronological tick structures."""
        ticks = self.call_sdk(read_ticks, self.vertex_path)
        assert isinstance(ticks, list)
        for t in ticks:
            assert isinstance(t, dict)
            assert "id" in t
            assert "name" in t

    @rule()
    def check_search_facts(self) -> None:
        """Verify search_facts returns structured SearchResult."""
        res = self.call_sdk(search_facts, self.vertex_path, "test")
        assert isinstance(res, SearchResult)
        assert res.query == "test"
        assert isinstance(res.matches, list)

    @rule()
    def check_inspect_declaration(self) -> None:
        """Verify inspect_declaration agrees with model declared kinds and observers."""
        info = self.call_sdk(inspect_declaration, self.vertex_path)
        assert isinstance(info, DeclarationInspectionResult)
        assert info.name == "stateful"
        assert info.syntax_valid is True
        assert set(info.declared_kinds) == self.declared_kinds
        assert set(info.declared_observers) == self.declared_observers

    @rule()
    def check_timeline_and_sync(self) -> None:
        """Verify read_timeline and sync_target execution consistency."""
        timeline = self.call_sdk(read_timeline, self.vertex_path, limit=100)
        assert isinstance(timeline, TimelineResult)
        assert timeline.total_events >= len(self.facts)

        sync_res = self.call_sdk(sync_target, self.vertex_path)
        assert isinstance(sync_res, SyncResult)
        assert sync_res.agreement is True

        target_info = self.call_sdk(resolve_target, self.vertex_path)
        assert isinstance(target_info, TargetInfo)
        assert target_info.target_type == "vertex"

        discovered = self.call_sdk(discover_targets, self.tmp_path)
        assert any(isinstance(t, TargetInfo) for t in discovered)

    # =========================================================================
    # Invariants (@invariant)
    # =========================================================================

    @invariant()
    def invariant_fact_count_agreement(self) -> None:
        """(1) Fact-count agreement between model and read_summary/read_facts totals."""
        summary = self.call_sdk(read_summary, self.vertex_path)
        assert summary.fact_total == len(self.facts)
        assert sum(k["count"] for k in summary.kinds.values()) == len(self.facts)

    @invariant()
    def invariant_all_facts_retrievable_by_id(self) -> None:
        """(2) Every emitted receipt id is subsequently readable via read_fact_by_id."""
        for mf in self.facts:
            stored = self.call_sdk(read_fact_by_id, self.vertex_path, mf.id)
            assert stored is not None
            assert stored["id"] == mf.id
            assert stored["kind"] == mf.kind
            assert stored["observer"] == mf.observer

    @invariant()
    def invariant_dry_run_semantics_and_non_mutation(self) -> None:
        """(3) & (4) Dry-run operations never mutate store and satisfy dry-run receipt semantics."""
        summary_before = self.call_sdk(read_summary, self.vertex_path)
        state_before = self.call_sdk(read_state, self.vertex_path)

        receipt = self.call_sdk(
            emit_fact,
            self.vertex_path,
            "item",
            {"check": "dry_run"},
            observer="admin",
            dry_run=True,
        )
        assert receipt.stored is False
        assert receipt.id == ""
        assert receipt.state_change is False
        assert receipt.delta_count == 0
        assert receipt.predicted_state_change is ("item" in self.declared_kinds)

        preview = self.call_sdk(
            preview_emission,
            self.vertex_path,
            "item",
            {"check": "preview"},
            observer="admin",
        )
        assert preview.admitted is True
        assert preview.would_store is True
        assert preview.would_fold is ("item" in self.declared_kinds)

        plan = self.call_sdk(plan_kind_mutation, self.vertex_path, "add", "temp_invar_kind")
        assert isinstance(plan, DeclarationPlanResult)

        summary_after = self.call_sdk(read_summary, self.vertex_path)
        state_after = self.call_sdk(read_state, self.vertex_path)
        assert summary_after == summary_before
        assert state_after == state_before

    @invariant()
    def invariant_pagination_consistency(self) -> None:
        """(5) read_facts pagination: walking all pages yields each fact exactly once."""
        if not self.facts:
            page = self.call_sdk(read_facts, self.vertex_path, limit=3)
            assert page.items == []
            return

        newest_ids: list[str] = []
        cursor: str | None = None
        while True:
            page = self.call_sdk(
                read_facts,
                self.vertex_path,
                limit=3,
                before=cursor,
                order="newest",
            )
            newest_ids.extend(it["id"] for it in page.items)
            if not page.truncated or page.next_cursor is None:
                break
            cursor = page.next_cursor

        assert len(newest_ids) == len(self.facts)
        assert len(set(newest_ids)) == len(self.facts)
        assert set(newest_ids) == set(self.facts_by_id.keys())

        oldest_ids: list[str] = []
        cursor = None
        while True:
            page = self.call_sdk(
                read_facts,
                self.vertex_path,
                limit=3,
                after=cursor,
                order="oldest",
            )
            oldest_ids.extend(it["id"] for it in page.items)
            if not page.truncated or page.next_cursor is None:
                break
            cursor = page.next_cursor

        assert len(oldest_ids) == len(self.facts)
        assert len(set(oldest_ids)) == len(self.facts)
        assert oldest_ids == list(reversed(newest_ids))

    @invariant()
    def invariant_removed_kinds_append_only(self) -> None:
        """(6) After remove_kind, declared_kinds drops kind but emitted facts remain readable."""
        info = self.call_sdk(inspect_declaration, self.vertex_path)
        for k in self.removed_kinds:
            assert k not in info.declared_kinds
            expected_facts_for_k = [f for f in self.facts if f.kind == k]
            page = self.call_sdk(read_facts, self.vertex_path, kind=k, limit=100)
            assert len(page.items) == len(expected_facts_for_k)

    @invariant()
    def invariant_observer_declaration_sync(self) -> None:
        """(7) grant_observer then inspect_declaration shows observer; revoke then it does not."""
        info = self.call_sdk(inspect_declaration, self.vertex_path)
        assert set(info.declared_observers) == self.declared_observers


# Register the state machine with a standard TestCase so pytest discovers and executes it
TestSdkStateMachine = SdkStateMachine.TestCase


# -----------------------------------------------------------------------------
# Boundary Regression Tests
# -----------------------------------------------------------------------------
def test_plan_kind_mutation_refused_mutation_returns_inapplicable_plan(
    sample_vertex: Path,
) -> None:
    """A lang-refused mutation is a non-applicable plan, never a raw ValueError."""
    # 'note' is already declared in sample_vertex, so 'add' is a refused mutation.
    plan = plan_kind_mutation(sample_vertex, "add", "note")
    assert plan.applicable is False
    assert plan.mode == "refused"
    assert plan.reason != ""
    assert plan.changes == []
