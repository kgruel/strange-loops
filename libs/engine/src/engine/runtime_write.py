"""Detached planning and one-CAS execution for an ordinary Arrival write.

This is deliberately narrower than the legacy runtime writer: one ordinary
fact, and at most the one boundary tick it causes.  It owns no SQLite handle.
The caller supplies a detached, already snapshot-rebuilt vertex; this module
turns its admission/fold result into Arrival drafts and performs one witnessed
append.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ulid import ULID

from .admission import fact_commitment_hash
from .arrival import content_commitment
from .arrival_body import body_of_batch, body_of_fact_row, body_of_tick_row
from .arrival_contract import (
    AtomicLimitExceeded,
    ContractRefusal,
    FactRequest,
    Head,
    NotAuthority,
    ProjectionBehind,
    RecordDraft,
    SearchPage,
    SearchRequest,
    SummaryRequest,
    TickRequest,
    Watermark,
)
from .arrival_contract import Fact as SnapshotFact
from .arrival_contract import Tick as SnapshotTick
from .arrival_head_seam import (
    AttestedLedger,
    Compared,
    Indeterminate,
    NotWitnessed,
    PreGenesis,
    complete_projection_custody,
)
from .credentials import WriteCredentials
from .row_commitment import fact_row_hash, tick_commitment_hash, tick_row_hash

if TYPE_CHECKING:  # pragma: no cover - typing only
    from atoms import Fact
    from lang.ast import VertexFile

    from .arrival_contract import QuerySnapshot, ReadBasis, StoreDescriptor
    from .arrival_registry import BackendRegistry
    from .compiler import FoldOverride
    from .peer import Grant
    from .vertex import Vertex

__all__ = [
    "CommittedWrite",
    "BatchFactInput",
    "BatchItemResult",
    "BatchPostCommitProjectionFailed",
    "BatchWritePlan",
    "BatchWriteCommitUnknown",
    "BatchWritePreparationRefused",
    "BoundaryContinuityRefused",
    "CommittedBatchWrite",
    "OrdinaryWritePlan",
    "OrdinaryWritePreparationRefused",
    "PostCommitProjectionFailed",
    "ProjectionOutcome",
    "RuntimeWriteRefused",
    "RuntimeCapture",
    "WriteCommitUnknown",
    "execute_ordinary_write",
    "execute_batch_write",
    "hydrate_arrival_candidate",
    "capture_runtime",
    "plan_batch_from_capture",
    "prepare_ordinary_write",
    "prepare_batch_write",
]


class RuntimeWriteRefused(Exception):
    """The runtime writer cannot establish a safe pre-append plan."""


class BoundaryContinuityRefused(RuntimeWriteRefused):
    """Current replay would consume an unlicensed historical boundary edge."""

    def __init__(
        self,
        *,
        issue: Any,
        basis: ReadBasis,
        effective_declaration: VertexFile,
        cause: Exception,
    ) -> None:
        super().__init__(str(cause))
        self.issue = issue
        self.basis = basis
        self.captured_head = basis.captured_head
        self.effective_declaration = effective_declaration
        self.tick_id = issue.tick_id
        self.ordinal = issue.tick_ordinal
        self.fact_id = issue.declaration_fact_id
        self.vertex = issue.vertex_name
        self.coordinator_phase = "prepare"
        self.effects = {
            "custody": {"attempt": "not-entered", "state": "not-attempted"}
        }
        self.cause = cause


class OrdinaryWritePreparationRefused(RuntimeWriteRefused):
    """A supported pre-append refusal with same-snapshot preview evidence.

    SDK preview may report an admission or strict-kind refusal, but must not
    reopen a locator declaration to explain it.  This exception retains the
    declaration reconstructed from the bounded snapshot and the physical
    custodian already verified from the ledger; no custody write occurred.
    """

    def __init__(
        self,
        *,
        effective_declaration: VertexFile,
        admission_grant: Grant | None,
        custodian: str,
        basis: ReadBasis,
        fact: Fact,
        cause: Exception,
    ) -> None:
        super().__init__(str(cause))
        self.effective_declaration = effective_declaration
        self.admission_grant = admission_grant
        self.custodian = custodian
        self.basis = basis
        self.captured_head = basis.captured_head
        self.fact = fact
        self.cause = cause


class BatchWritePreparationRefused(RuntimeWriteRefused):
    """One batch item refused while the whole operation was still a plan.

    The input coordinate and same-snapshot declaration evidence let an SDK
    explain the refusal without reopening a locator or implying that an
    earlier item committed. No custody append has been attempted.
    """

    def __init__(
        self,
        *,
        input_index: int,
        item: BatchFactInput,
        effective_declaration: VertexFile,
        custodian: str,
        basis: ReadBasis,
        cause: Exception,
        admission_refused: bool,
    ) -> None:
        super().__init__(str(cause))
        self.item_index = input_index
        self.item = item
        self.effective_declaration = effective_declaration
        self.custodian = custodian
        self.basis = basis
        self.captured_head = basis.captured_head
        self.cause = cause
        self.admission_refused = admission_refused


class _AdmissionPlanRefused(RuntimeWriteRefused):
    """The detached admission gate rejected a fact without a typed error."""


class WriteCommitUnknown(Exception):
    """Append raised without proving that it left custody unchanged.

    The stable planned identities let callers reconcile this operation without
    treating an adapter failure as permission to append the fact again.
    """

    outcome = "unknown"

    def __init__(self, plan: OrdinaryWritePlan, cause: Exception) -> None:
        super().__init__(
            "ordinary append outcome is unknown; reconcile by captured head "
            "and planned record identities"
        )
        self.captured_head = plan.captured_head
        self.fact_id = plan.fact_id
        self.tick_id = plan.tick_id
        self.drafts = plan.drafts
        self.cause = cause


class BatchWriteCommitUnknown(Exception):
    """A batch append raised without proving that custody stayed unchanged."""

    outcome = "unknown"

    def __init__(self, plan: BatchWritePlan, cause: Exception) -> None:
        super().__init__(
            "batch append outcome is unknown; reconcile by captured head "
            "and every planned record identity"
        )
        self.captured_head = plan.captured_head
        self.items = plan.items
        self.fact_ids = tuple(item.fact_id for item in plan.items)
        self.tick_ids = plan.pending_tick_ids + tuple(
            item.tick_id for item in plan.items if item.tick_id is not None
        )
        self.tick_runs = plan.pending_tick_runs + tuple(
            item.tick_run for item in plan.items if item.tick_id is not None
        )
        self.drafts = plan.drafts
        self.cause = cause


def _close_quietly(handle: object) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


class ProjectionOutcome(Enum):
    """What happened to derived state after a durable append."""

    NOT_REQUESTED = "not-requested"
    SYNCED = "synced"
    PENDING = "pending"
    FAILED = "failed"


@dataclass(frozen=True)
class OrdinaryWritePlan:
    """A fully prepared ordinary fact and optional local boundary tick."""

    captured_head: Head
    fact_id: str
    tick_id: str | None
    drafts: tuple[RecordDraft, ...]
    already_present: bool = False
    # These values are provenance for the supported preparation seam.  They
    # are not append inputs: execution uses only the immutable drafts and H.
    effective_declaration: VertexFile | None = field(default=None, repr=False, compare=False)
    admission_grant: Grant | None = field(default=None, repr=False, compare=False)
    custodian: str | None = None
    admit_undeclared: bool = False
    tick_run: str | None = field(default=None, repr=False, compare=False)


class PostCommitProjectionFailed(Exception):
    """Custody committed, but requested projection publication failed."""

    def __init__(self, commit: Any, plan: OrdinaryWritePlan, cause: Exception) -> None:
        super().__init__(
            "ordinary append committed but projection publication failed; "
            "reconcile from the durable commit"
        )
        self.commit = commit
        self.captured_head = plan.captured_head
        self.fact_id = getattr(plan, "fact_id", None)
        self.tick_id = getattr(plan, "tick_id", None)
        self.items = getattr(plan, "items", None)
        self.drafts = plan.drafts
        self.cause = cause
        self.projection = ProjectionOutcome.FAILED


class BatchPostCommitProjectionFailed(PostCommitProjectionFailed):
    """A batch committed, but its requested projection publication failed."""

    def __init__(self, commit: Any, plan: BatchWritePlan, cause: Exception) -> None:
        Exception.__init__(
            self,
            "batch append committed but projection publication failed; "
            "reconcile from the durable commit",
        )
        self.commit = commit
        self.captured_head = plan.captured_head
        self.items = plan.items
        self.fact_ids = tuple(item.fact_id for item in plan.items)
        self.tick_ids = plan.pending_tick_ids + tuple(
            item.tick_id for item in plan.items if item.tick_id is not None
        )
        self.tick_runs = plan.pending_tick_runs + tuple(
            item.tick_run for item in plan.items if item.tick_id is not None
        )
        self.drafts = plan.drafts
        self.cause = cause
        self.projection = ProjectionOutcome.FAILED


@dataclass(frozen=True)
class CommittedWrite:
    """A durable append and its honest projection status."""

    commit: Any | None
    fact_id: str
    tick_id: str | None
    projection: ProjectionOutcome


@dataclass(frozen=True)
class BatchFactInput:
    """One ordered ordinary input to the supported atomic batch writer."""

    fact: Fact
    fact_id: str | None = None
    admit_undeclared: bool = False


@dataclass(frozen=True)
class BatchItemResult:
    """Stable per-input identity, including a no-op retry."""

    fact_id: str
    tick_id: str | None
    tick_name: str | None
    already_present: bool
    tick_run: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class BatchWritePlan:
    """All batch evidence prepared before the one custody append."""

    captured_head: Head
    items: tuple[BatchItemResult, ...]
    drafts: tuple[RecordDraft, ...]
    effective_declaration: VertexFile | None = field(default=None, repr=False, compare=False)
    custodian: str | None = None
    pending_tick_ids: tuple[str, ...] = ()
    pending_tick_names: tuple[str, ...] = ()
    pending_tick_runs: tuple[str | None, ...] = field(
        default=(), repr=False, compare=False
    )


@dataclass(frozen=True)
class CommittedBatchWrite:
    """One custody result shared by every prepared batch item."""

    commit: Any | None
    items: tuple[BatchItemResult, ...]
    projection: ProjectionOutcome
    pending_tick_ids: tuple[str, ...] = ()
    pending_tick_names: tuple[str, ...] = ()
    pending_tick_runs: tuple[str | None, ...] = field(
        default=(), repr=False, compare=False
    )


@dataclass(frozen=True)
class RuntimeCapture:
    """Closed-handle evidence and construction recipe for exact-H planning.

    Mutable runtime objects stay private and are copied before every planning
    operation. Public declaration, document, fact, tick, and source accessors
    likewise return copies, so caller mutation cannot alter a later plan.
    """

    basis: ReadBasis
    custodian: str
    max_atomic_records: int | None
    evaluated_at: float
    _effective_declaration: VertexFile = field(repr=False, compare=False)
    _locator: VertexFile = field(repr=False, compare=False)
    _declaration_anchor: Any = field(repr=False, compare=False)
    _declaration_documents: tuple[dict[str, Any], ...] = field(repr=False, compare=False)
    _facts: tuple[SnapshotFact, ...] = field(repr=False, compare=False)
    _ticks: tuple[SnapshotTick, ...] = field(repr=False, compare=False)
    _candidate_template: Vertex = field(repr=False, compare=False)
    _post_boundary_candidate_template: Vertex | None = field(
        default=None, repr=False, compare=False
    )
    _sources: tuple[Any, ...] = field(default=(), repr=False, compare=False)
    _pending_boundaries: tuple[Any, ...] = field(default=(), repr=False, compare=False)

    @property
    def effective_declaration(self) -> VertexFile:
        from .declaration import effective_declaration_from_documents

        return effective_declaration_from_documents(
            self._declaration_documents,
            self._locator,
            verify_pins=False,
        )

    @property
    def declaration_documents(self) -> tuple[dict[str, Any], ...]:
        return copy.deepcopy(self._declaration_documents)

    @property
    def facts(self) -> tuple[SnapshotFact, ...]:
        return copy.deepcopy(self._facts)

    @property
    def ticks(self) -> tuple[SnapshotTick, ...]:
        return copy.deepcopy(self._ticks)

    @property
    def sources(self) -> tuple[Any, ...]:
        return copy.deepcopy(self._sources)

    @property
    def pending_boundaries(self) -> tuple[Any, ...]:
        return copy.deepcopy(self._pending_boundaries)

    def _locator_copy(self) -> VertexFile:
        return _capture_locator_ingress(self._locator)

    def _candidate_copy(self, *, after_pending_boundaries: bool = False) -> Vertex:
        template = (
            self._post_boundary_candidate_template
            if after_pending_boundaries and self._post_boundary_candidate_template is not None
            else self._candidate_template
        )
        return template.detached_copy()


def _capture_locator_ingress(locator: VertexFile) -> VertexFile:
    """Detach the residence and ingress values capture may use after return."""
    from lang.ast import InlineSource, SourcesBlock, VertexFile

    def frozen_ast(cls: type, **fields: object) -> Any:
        # lang.ast deliberately implements its own frozen slots rather than
        # dataclasses. Constructing through object.__new__ is the narrow copy
        # primitive that neither invokes its custom setter nor shares a caller
        # object; all supplied values below are immutable scalars/tuples.
        instance = object.__new__(cls)
        for name, value in fields.items():
            object.__setattr__(instance, name, value)
        return instance

    blocks = tuple(
        frozen_ast(
            SourcesBlock,
            mode=block.mode,
            sources=tuple(
                frozen_ast(
                    InlineSource,
                    command=source.command,
                    kind=source.kind,
                    observer=source.observer,
                    every=source.every,
                    on=source.on,
                    format=source.format,
                    timeout=source.timeout,
                    origin=source.origin,
                    env=tuple(source.env),
                    parse=tuple(source.parse),
                    path=source.path,
                )
                for source in block.sources
            ),
        )
        for block in (locator.sources_blocks or ())
    )
    return frozen_ast(
        VertexFile,
        name=locator.name,
        loops={},
        store=locator.store,
        store_backend=locator.store_backend,
        store_location=locator.store_location,
        sources_blocks=blocks or None,
        path=locator.path,
    )


def _json_default(value: object) -> object:
    from types import MappingProxyType

    if isinstance(value, MappingProxyType):
        return dict(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _payload_text(payload: object) -> str:
    """Match the live SQLite writer's fresh-row payload encoding."""
    return json.dumps(payload, default=_json_default)


class _BatchSnapshot:
    """One in-memory extension of a captured snapshot during planning only."""

    def __init__(
        self,
        base: QuerySnapshot | RuntimeCapture,
        facts: tuple[SnapshotFact, ...],
        ticks: tuple[SnapshotTick, ...],
    ) -> None:
        if isinstance(base, RuntimeCapture):
            projected = base.basis.projected_through
            self.represented = (
                None
                if projected is None
                else Watermark(lineage=projected.lineage, ordinal=projected.ordinal)
            )
            self.view_generation = base.basis.view_generation
            self.declaration_anchor = base._declaration_anchor
        else:
            self.represented = base.represented
            self.view_generation = base.view_generation
            self.declaration_anchor = base.declaration_anchor
        self._facts = facts
        self._ticks = ticks

    def facts(self, request: FactRequest):
        from .arrival_contract import FactPage

        rows = self._facts
        if request.fact_id is not None:
            rows = tuple(row for row in rows if row.id == request.fact_id)
        return FactPage(rows, None, False, request.order)

    def ticks(self, request: TickRequest) -> tuple[SnapshotTick, ...]:
        return self._ticks

    def summary(self, request: SummaryRequest) -> Any:
        raise RuntimeWriteRefused(
            "summary reads are unavailable on a pending batch planning snapshot"
        )

    def search(self, request: SearchRequest) -> SearchPage:
        raise RuntimeWriteRefused("search is unavailable on a pending batch planning snapshot")

    def close(self) -> None:
        # The outer preparation scope owns the real snapshot. A synthetic
        # extension is an immutable view over tuples and holds no resource.
        return None


def _fact_from_draft(draft: RecordDraft, ordinal: int, seq: int) -> SnapshotFact:
    body = draft.body
    return SnapshotFact(
        id=body["id"],
        kind=body["kind"],
        ts=body["ts"],
        observer=body["observer"],
        origin=body["origin"],
        payload=json.loads(body["payload"]),
        arrival_ordinal=ordinal,
        arrival_seq=seq,
        payload_text=body["payload"],
        signature=body.get("signature"),
    )


def _tick_from_draft(draft: RecordDraft, ordinal: int, seq: int) -> SnapshotTick:
    body = draft.body
    return SnapshotTick(
        id=body["id"],
        name=body["name"],
        ts=body["ts"],
        since=body["since"],
        origin=body["origin"],
        payload=json.loads(body["payload"]),
        arrival_ordinal=ordinal,
        arrival_seq=seq,
        payload_text=body["payload"],
        prev_hash=body["prev_hash"],
        window_start=body["window_start"],
        fact_cursor=body["fact_cursor"],
        window_hash=body["window_hash"],
        signature=body.get("signature"),
    )


def _window_hash(
    facts: tuple[SnapshotFact, ...],
    *,
    start: str,
    appended: tuple[object, ...] | None = None,
) -> str:
    """The live tick window hash over exact snapshot rows plus this fact."""
    import hashlib

    digest = hashlib.sha256()
    if appended is not None and start == appended[0]:
        return digest.hexdigest()
    start_at = -1
    if start:
        for index, fact in enumerate(facts):
            if fact.id == start:
                start_at = index
                break
        else:
            raise RuntimeWriteRefused(f"tick window start {start!r} is absent from the snapshot")
    for fact in facts[start_at + 1 :]:
        if fact.payload_text is None:
            raise RuntimeWriteRefused("snapshot omitted exact fact payload text")
        digest.update(
            fact_row_hash(
                (
                    fact.id,
                    fact.kind,
                    fact.ts,
                    fact.observer,
                    fact.origin,
                    fact.payload_text,
                    fact.signature,
                )
            ).encode()
        )
    if appended is not None:
        digest.update(fact_row_hash(appended).encode())
    return digest.hexdigest()


def _current_tick_context(
    ticks: tuple[SnapshotTick, ...], *, current_fact_id: str
) -> tuple[str | None, str]:
    """Return the predecessor identity and next tick's window start."""
    if not ticks:
        return None, ""
    previous = max(ticks, key=lambda tick: (tick.arrival_ordinal, tick.arrival_seq))
    if previous.payload_text is None:
        raise RuntimeWriteRefused("snapshot omitted exact tick payload text")
    previous_hash = tick_row_hash(
        (
            previous.id,
            previous.name,
            previous.ts,
            previous.since,
            previous.origin,
            previous.payload_text,
            previous.prev_hash,
            previous.window_start,
            previous.fact_cursor,
            previous.window_hash,
            previous.signature,
        )
    )
    if previous.window_hash is None:
        # The live store starts a new chain epoch at its current fact edge,
        # which is this just-planned fact; its first window is empty.
        return previous_hash, current_fact_id
    if previous.fact_cursor is None:
        raise RuntimeWriteRefused("chained tick has no fact cursor")
    return previous_hash, previous.fact_cursor


def _existing_fact_plan(
    snapshot: QuerySnapshot,
    basis: ReadBasis,
    fact: Fact,
    credentials: WriteCredentials,
    fact_id: str | None,
) -> OrdinaryWritePlan | None:
    """Recognize an exact retry before any new-fact admission decision."""
    if fact_id is None:
        return None
    chosen_id = fact_id
    payload_text = _payload_text(fact.payload)
    inner_signature = (
        credentials.fact_signer(
            fact.observer,
            fact_commitment_hash(fact.kind, fact.ts, fact.observer, fact.origin, payload_text),
        )
        if credentials.fact_signer is not None
        else None
    )
    existing = next(
        (
            row
            for row in snapshot.facts(
                FactRequest(limit=None, include_internal=True, order="oldest")
            ).items
            if row.id == chosen_id
        ),
        None,
    )
    if existing is None:
        return None
    if existing.payload_text is None:
        raise RuntimeWriteRefused("snapshot omitted exact fact payload text")
    if (
        existing.kind,
        existing.ts,
        existing.observer,
        existing.origin,
        existing.payload_text,
        existing.signature,
    ) != (fact.kind, fact.ts, fact.observer, fact.origin, payload_text, inner_signature):
        raise RuntimeWriteRefused(f"fact id {chosen_id!r} already exists with different content")
    return OrdinaryWritePlan(
        captured_head=basis.captured_head,
        fact_id=chosen_id,
        tick_id=None,
        drafts=(),
        already_present=True,
    )


def _ensure_current_basis(snapshot: QuerySnapshot, basis: ReadBasis) -> None:
    if basis.projected_through != basis.captured_head:
        raise ProjectionBehind("ordinary writes require a current projection snapshot")
    if snapshot.represented is None:
        raise RuntimeWriteRefused("ordinary writes require a represented projection")
    if snapshot.represented.lineage != basis.captured_head.lineage:
        raise NotAuthority("snapshot lineage differs from the captured ledger head")


def _current_write_basis(
    ledger: AttestedLedger, snapshot: QuerySnapshot, captured: Head
) -> ReadBasis:
    """Complete a CURRENT query watermark without mistaking an advance for lag."""
    from .arrival_contract import ReadBasis

    watermark = snapshot.represented
    if watermark is None:
        raise RuntimeWriteRefused("ordinary emission requires a projection watermark")
    projected = complete_projection_custody(
        ledger,
        captured=captured,
        represented=watermark,
        lineage_refusal=NotAuthority,
        conflict_refusal=RuntimeWriteRefused,
    )
    if projected.ordinal < captured.ordinal:
        raise ProjectionBehind("CURRENT snapshot did not reach the captured head")
    return ReadBasis(
        lineage=captured.lineage,
        captured_head=captured,
        projected_through=projected,
        view_generation=snapshot.view_generation,
    )


def _build_effective_arrival_candidate(
    snapshot: QuerySnapshot,
    basis: ReadBasis,
    locator: VertexFile,
    *,
    fold_overrides: dict[str, FoldOverride] | None = None,
) -> tuple[
    Vertex,
    VertexFile,
    tuple[dict[str, Any], ...],
    tuple[Any, ...],
    tuple[SnapshotFact, ...],
    tuple[SnapshotTick, ...],
]:
    """Build a fresh, storeless candidate from this exact bounded snapshot.

    The locator contributes only ingress/residence fields. Effective documents,
    facts, and ticks come from the one CURRENT query snapshot, so no mutable
    caller vertex or legacy store can decide the next boundary.
    """
    _ensure_current_basis(snapshot, basis)
    facts = snapshot.facts(FactRequest(limit=None, include_internal=True, order="oldest")).items
    from .declaration import (
        Unhistorized,
        effective_declaration_from_documents,
        resolve_declaration_documents_from_snapshot,
        validate_arrival_declaration_anchor,
        validate_arrival_runtime_identity,
    )

    validate_arrival_declaration_anchor(snapshot.declaration_anchor, basis.captured_head)
    documents = resolve_declaration_documents_from_snapshot(snapshot.declaration_anchor, facts)
    if documents is None or isinstance(documents, Unhistorized):
        raise RuntimeWriteRefused("ordinary emission requires historized effective declarations")
    effective = effective_declaration_from_documents(documents, locator)
    if effective.vertices or effective.discover or effective.combine is not None:
        raise RuntimeWriteRefused("multi-store child execution is not in stage 3A")
    validate_arrival_runtime_identity(
        effective.name,
        effective.loops,
        refusal=RuntimeWriteRefused,
    )
    from .compiler import (
        CompiledVertex,
        compile_parse_pipelines,
        compile_sources,
        compile_sources_block,
        map_boundary,
        map_vertex_file,
        materialize_vertex,
    )

    base_dir = locator.path.parent if locator.path is not None else Path.cwd()
    sources, template_specs = compile_sources(effective, base_dir)
    for block in effective.sources_blocks or ():
        sources.append(compile_sources_block(block, effective.name))
    specs = map_vertex_file(effective)
    specs.update(template_specs)
    validate_arrival_runtime_identity(
        effective.name,
        specs,
        refusal=RuntimeWriteRefused,
    )
    if sources:
        from .executor import validate_dependency_graph

        validate_dependency_graph(sources)
    runtime_ticks = tuple(snapshot.ticks(TickRequest()))
    continuity_ticks = tuple(snapshot.ticks(TickRequest(since=float("-inf"))))
    from .arrival_boundary_continuity import (
        BoundaryContinuityConflict,
        analyze_boundary_continuity,
        collect_verified_parameter_rows,
    )

    verified_params = collect_verified_parameter_rows(
        snapshot.declaration_anchor,
        facts,
        target_documents=documents,
        base_dir=base_dir,
    )
    try:
        analyze_boundary_continuity(
            snapshot.declaration_anchor,
            facts,
            continuity_ticks,
            target_documents=documents,
            verified_params=verified_params,
            compiled_loop_names=set(specs) | {"cite"},
        )
    except BoundaryContinuityConflict as exc:
        raise BoundaryContinuityRefused(
            issue=exc.issue,
            basis=basis,
            effective_declaration=effective,
            cause=exc,
        ) from exc
    compiled = CompiledVertex(
        name=effective.name,
        specs=specs,
        children={},
        routes=effective.routes,
        store=effective.store,
        path=effective.path,
        boundary=tuple(map_boundary(boundary) for boundary in effective.boundary),
        parse_pipelines=compile_parse_pipelines(effective),
        strict=effective.strict,
        sources=sources or None,
        template_specs=template_specs or None,
    )
    candidate = materialize_vertex(compiled, fold_overrides=fold_overrides, attach_store=False)
    candidate.hydrate_snapshot(facts, runtime_ticks)
    return (
        candidate,
        effective,
        tuple(copy.deepcopy(documents)),
        tuple(copy.deepcopy(sources)),
        tuple(copy.deepcopy(facts)),
        tuple(copy.deepcopy(runtime_ticks)),
    )


def _hydrate_effective_arrival_candidate(
    snapshot: QuerySnapshot,
    basis: ReadBasis,
    locator: VertexFile,
    *,
    fold_overrides: dict[str, FoldOverride] | None = None,
) -> tuple[Vertex, VertexFile]:
    candidate, effective, _documents, _sources, _facts, _ticks = (
        _build_effective_arrival_candidate(
            snapshot, basis, locator, fold_overrides=fold_overrides
        )
    )
    return candidate, effective


def hydrate_arrival_candidate(
    snapshot: QuerySnapshot,
    basis: ReadBasis,
    locator: VertexFile,
    *,
    fold_overrides: dict[str, FoldOverride] | None = None,
) -> Vertex:
    """Build the supported storeless candidate from this bounded snapshot."""
    candidate, _effective = _hydrate_effective_arrival_candidate(
        snapshot, basis, locator, fold_overrides=fold_overrides
    )
    return candidate


def plan_ordinary_write(
    snapshot: QuerySnapshot,
    basis: ReadBasis,
    vertex: Vertex,
    fact: Fact,
    *,
    grant: Grant | None,
    credentials: WriteCredentials,
    custodian: str,
    fact_id: str | None = None,
    admit_undeclared: bool = False,
    _mutate_candidate: bool = False,
) -> OrdinaryWritePlan:
    """Internal, caller-responsible planner for one local fact and tick.

    ``vertex`` must be a detached reconstruction of this exact snapshot.
    Supported consumers use :func:`prepare_ordinary_write`, which creates it
    through :func:`hydrate_arrival_candidate`; this lower-level seam exists
    for focused engine composition and must not be offered as a coherent
    writer from a stale caller-owned vertex.
    """
    _ensure_current_basis(snapshot, basis)
    if getattr(vertex, "_store", None) is not None:
        raise RuntimeWriteRefused("ordinary planning requires a detached vertex")
    if getattr(vertex, "_has_children", False):
        raise RuntimeWriteRefused("multi-store child execution is not in stage 3A")
    from .declaration import validate_arrival_runtime_identity

    validate_arrival_runtime_identity(
        vertex.name,
        vertex.kinds,
        refusal=RuntimeWriteRefused,
    )
    anchor = snapshot.declaration_anchor
    if anchor.own_lineage is None or anchor.genesis is None:
        raise RuntimeWriteRefused("ordinary emission requires a declaration anchor")
    from .declaration import validate_arrival_declaration_anchor

    validate_arrival_declaration_anchor(anchor, basis.captured_head)

    existing_plan = _existing_fact_plan(snapshot, basis, fact, credentials, fact_id)
    if existing_plan is not None:
        return existing_plan
    facts = snapshot.facts(FactRequest(limit=None, include_internal=True, order="oldest")).items
    # The neutral request is receipt-ordered, but keep this safety boundary at
    # the chain calculation: window membership is coordinates, never a
    # backend's event-time or identifier presentation order.
    facts = tuple(sorted(facts, key=lambda row: (row.arrival_ordinal, row.arrival_seq)))
    ticks = snapshot.ticks(TickRequest())
    chosen_id = fact_id if fact_id is not None else str(ULID())
    payload_text = _payload_text(fact.payload)
    inner_signature = (
        credentials.fact_signer(
            fact.observer,
            fact_commitment_hash(fact.kind, fact.ts, fact.observer, fact.origin, payload_text),
        )
        if credentials.fact_signer is not None
        else None
    )
    fact_row = (
        chosen_id,
        fact.kind,
        fact.ts,
        fact.observer,
        fact.origin,
        payload_text,
        inner_signature,
    )
    candidate = vertex if _mutate_candidate else vertex.detached_copy()
    receipt = candidate.plan_receive_receipt(
        fact,
        grant,
        id_override=chosen_id,
        admit_undeclared=admit_undeclared,
    )
    if not receipt.stored:
        raise _AdmissionPlanRefused("admission rejected the fact before append")
    fact_body = body_of_fact_row(fact_row)
    outer_signature = (
        credentials.arrival_signer(
            fact.observer,
            content_commitment("fact", fact.ts, fact.observer, fact.origin, fact_body),
        )
        if credentials.arrival_signer is not None
        else None
    )
    drafts = [
        RecordDraft(
            kind="fact",
            authored_at=fact.ts,
            observer=fact.observer,
            origin=fact.origin,
            body=fact_body,
            signature=outer_signature,
        )
    ]
    tick_id: str | None = None
    if receipt.tick is not None:
        previous_hash, window_start = _current_tick_context(ticks, current_fact_id=chosen_id)
        tick = receipt.tick
        tick_id = str(ULID())
        if any(existing.id == tick_id for existing in ticks):
            raise RuntimeWriteRefused(f"generated tick id {tick_id!r} already exists")
        tick_payload_text = _payload_text(tick.payload)
        tick_row = (
            tick_id,
            tick.name,
            tick.ts.timestamp(),
            None if tick.since is None else tick.since.timestamp(),
            tick.origin,
            tick_payload_text,
            previous_hash,
            window_start,
            chosen_id,
            _window_hash(facts, start=window_start, appended=fact_row),
        )
        tick_signature = (
            credentials.tick_signer(tick_commitment_hash(tick_row))
            if credentials.tick_signer is not None
            else None
        )
        if tick_signature is None and any(
            existing.signature is not None and existing.window_hash is not None
            for existing in ticks
        ):
            raise RuntimeWriteRefused("refusing an unsigned tick in the signed tick era")
        tick_body = body_of_tick_row((*tick_row, tick_signature))
        drafts.append(
            RecordDraft(
                kind="tick",
                authored_at=tick.ts.timestamp(),
                observer=custodian,
                origin=tick.origin,
                body=tick_body,
                signature=None,
            )
        )
    return OrdinaryWritePlan(
        captured_head=basis.captured_head,
        fact_id=chosen_id,
        tick_id=tick_id,
        drafts=tuple(drafts),
        tick_run=None if receipt.tick is None else receipt.tick.run,
    )


def _custodian_from_verified_genesis(ledger: AttestedLedger) -> str:
    """Return the physical lineage's tick custodian from its verified record 0."""
    genesis = ledger.read(0)
    if genesis.get("k") != "genesis":
        raise RuntimeWriteRefused("ledger record 0 is not a physical genesis")
    observer = genesis.get("observer")
    if not isinstance(observer, str) or not observer:
        raise RuntimeWriteRefused("physical genesis has no custodian observer")
    return observer


def capture_runtime(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    locator: VertexFile,
    *,
    fold_overrides: dict[str, FoldOverride] | None = None,
    source_mode: bool = False,
    evaluated_at: float | None = None,
) -> RuntimeCapture:
    """Capture one immutable, closed-handle Authority/CURRENT runtime view."""
    from .arrival_contract import Profile, ProjectionRequirement

    if descriptor.role is not Profile.AUTHORITY:
        raise NotAuthority("runtime capture requires an Authority descriptor role")
    ledger, query = registry.open(descriptor)
    snapshot = None
    try:
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("BackendRegistry.open must return an AttestedLedger")
        comparison = ledger.opened.comparison
        if not isinstance(comparison, Compared):
            if isinstance(comparison, PreGenesis) and comparison.ledger_refusal is not None:
                raise comparison.ledger_refusal
            if isinstance(comparison, Indeterminate):
                raise comparison.refusal
            raise RuntimeWriteRefused("runtime capture requires a minted compared ledger")
        captured = comparison.presented
        snapshot = query.open_snapshot(
            captured_head=captured, requirement=ProjectionRequirement.CURRENT
        )
        basis = _current_write_basis(ledger, snapshot, captured)
        candidate, effective, documents, sources, facts, ticks = (
            _build_effective_arrival_candidate(
                snapshot, basis, locator, fold_overrides=fold_overrides
            )
        )
        at = time.time() if evaluated_at is None else evaluated_at
        post_boundary_candidate = candidate.detached_copy() if source_mode else None
        pending = (
            post_boundary_candidate.plan_pending_boundaries(facts, ticks, evaluated_at=at)
            if post_boundary_candidate is not None
            else ()
        )
        captured_locator = _capture_locator_ingress(locator)
        return RuntimeCapture(
            basis=basis,
            custodian=_custodian_from_verified_genesis(ledger),
            max_atomic_records=ledger.capabilities().max_atomic_records,
            evaluated_at=at,
            _effective_declaration=effective,
            _locator=captured_locator,
            _declaration_anchor=copy.deepcopy(snapshot.declaration_anchor),
            _declaration_documents=copy.deepcopy(documents),
            _facts=copy.deepcopy(facts),
            _ticks=copy.deepcopy(ticks),
            _candidate_template=candidate.detached_copy(),
            _post_boundary_candidate_template=(
                None
                if post_boundary_candidate is None
                else post_boundary_candidate.detached_copy()
            ),
            _sources=copy.deepcopy(sources),
            _pending_boundaries=copy.deepcopy(tuple(pending)),
        )
    finally:
        if snapshot is not None:
            _close_quietly(snapshot)
        _close_quietly(query)
        _close_quietly(ledger)


def prepare_ordinary_write(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    locator: VertexFile,
    fact: Fact,
    *,
    credentials: WriteCredentials,
    fact_id: str | None = None,
    fold_overrides: dict[str, FoldOverride] | None = None,
    admit_undeclared: bool = False,
) -> OrdinaryWritePlan:
    """Capture a CURRENT basis and prepare one retryable ordinary write.

    The writer opens its own registry handles because a read consumer never
    receives append capability.  It closes those handles before returning the
    detached plan; execution later compares the same complete head under the
    ledger fence and refuses any intervening append.
    """
    capture = capture_runtime(registry, descriptor, locator, fold_overrides=fold_overrides)
    basis = capture.basis
    effective = capture.effective_declaration
    candidate = capture._candidate_copy()
    snapshot = _BatchSnapshot(capture, capture._facts, capture._ticks)
    duplicate = _existing_fact_plan(snapshot, basis, fact, credentials, fact_id)
    if duplicate is not None:
        return replace(
            duplicate,
            effective_declaration=effective,
            custodian=capture.custodian,
            admit_undeclared=admit_undeclared,
        )
    grant = None
    try:
        from .admission import AdmissionError, grant_for_observer

        grant = grant_for_observer(effective, fact.observer)
        plan = plan_ordinary_write(
            snapshot,
            basis,
            candidate,
            fact,
            grant=grant,
            credentials=credentials,
            custodian=capture.custodian,
            fact_id=fact_id,
            admit_undeclared=admit_undeclared,
        )
    except (AdmissionError, _AdmissionPlanRefused) as exc:
        raise OrdinaryWritePreparationRefused(
            effective_declaration=effective,
            admission_grant=grant,
            custodian=capture.custodian,
            basis=basis,
            fact=fact,
            cause=exc,
        ) from exc
    return replace(
        plan,
        effective_declaration=effective,
        admission_grant=grant,
        custodian=capture.custodian,
        admit_undeclared=admit_undeclared,
    )


def execute_ordinary_write(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    plan: OrdinaryWritePlan,
    *,
    after_commit: Callable[[Head], object] | None = None,
) -> CommittedWrite:
    """Append a previously prepared plan once against its exact full head.

    Projection publication is deliberately not attempted in 3A.  A successful
    result says only that custody committed; maintenance is an explicit later
    operation.  ``after_commit`` is the optional injected maintenance seam:
    it receives the durable ``Commit.after`` and cannot change the append
    outcome.  ``NotWitnessed`` already carries the durable commit and is
    intentionally propagated rather than relabeled as a refusal.
    """
    from .arrival_contract import Profile

    if descriptor.role is not Profile.AUTHORITY:
        raise NotAuthority("ordinary writes require an Authority descriptor role")
    ledger, query = registry.open(descriptor)
    try:
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("BackendRegistry.open must return an AttestedLedger")
        comparison = ledger.opened.comparison
        if isinstance(comparison, PreGenesis):
            if comparison.ledger_refusal is not None:
                raise comparison.ledger_refusal
            raise RuntimeWriteRefused("ordinary emission requires a minted ledger")
        if isinstance(comparison, Indeterminate):
            raise comparison.refusal
        if not isinstance(comparison, Compared):
            raise TypeError(f"unsupported head comparison {comparison!r}")
        if plan.already_present:
            return CommittedWrite(
                commit=None,
                fact_id=plan.fact_id,
                tick_id=None,
                projection=ProjectionOutcome.NOT_REQUESTED,
            )
        if comparison.presented != plan.captured_head:
            raise RuntimeWriteRefused("captured head changed before append")
        try:
            commit = ledger.append(plan.captured_head, plan.drafts)
        except NotWitnessed:
            raise
        except ContractRefusal:
            raise
        except Exception as exc:
            raise WriteCommitUnknown(plan, exc) from exc
        if after_commit is not None:
            try:
                after_commit(commit.after)
            except Exception as exc:
                raise PostCommitProjectionFailed(commit, plan, exc) from exc
            projection = ProjectionOutcome.SYNCED
        else:
            projection = ProjectionOutcome.NOT_REQUESTED
        return CommittedWrite(
            commit=commit,
            fact_id=plan.fact_id,
            tick_id=plan.tick_id,
            projection=projection,
        )
    finally:
        _close_quietly(query)
        _close_quietly(ledger)


def _pack_batch_drafts(
    drafts: Sequence[RecordDraft], credentials: WriteCredentials
) -> tuple[RecordDraft, ...]:
    """Turn adjacent ordinary fact drafts into wire-valid same-author batches."""
    packed: list[RecordDraft] = []
    held: list[RecordDraft] = []

    def flush() -> None:
        if not held:
            return
        if len(held) == 1:
            packed.append(held[0])
        else:
            first = held[0]
            rows = [
                (
                    row.body["id"],
                    row.body["kind"],
                    row.body["ts"],
                    row.body["observer"],
                    row.body["origin"],
                    row.body["payload"],
                    row.body.get("signature"),
                )
                for row in held
            ]
            body = body_of_batch(rows)
            signature = (
                credentials.arrival_signer(
                    first.observer,
                    content_commitment(
                        "batch", first.authored_at, first.observer, first.origin, body
                    ),
                )
                if credentials.arrival_signer is not None
                else None
            )
            packed.append(
                RecordDraft(
                    kind="batch",
                    authored_at=first.authored_at,
                    observer=first.observer,
                    origin=first.origin,
                    body=body,
                    signature=signature,
                )
            )
        held.clear()

    for draft in drafts:
        if draft.kind == "fact" and (not held or held[0].observer == draft.observer):
            held.append(draft)
            continue
        flush()
        if draft.kind == "fact":
            held.append(draft)
        else:
            packed.append(draft)
    flush()
    return tuple(packed)


def _pending_tick_draft(
    tick: Any,
    facts: tuple[SnapshotFact, ...],
    ticks: tuple[SnapshotTick, ...],
    *,
    credentials: WriteCredentials,
    custodian: str,
) -> RecordDraft:
    """Encode one captured pending boundary without re-evaluating it."""
    if not facts:
        raise RuntimeWriteRefused("a pending boundary requires captured fact evidence")
    current_fact = max(facts, key=lambda row: (row.arrival_ordinal, row.arrival_seq))
    previous_hash, window_start = _current_tick_context(ticks, current_fact_id=current_fact.id)
    tick_id = str(ULID())
    payload_text = _payload_text(tick.payload)
    row = (
        tick_id,
        tick.name,
        tick.ts.timestamp(),
        None if tick.since is None else tick.since.timestamp(),
        tick.origin,
        payload_text,
        previous_hash,
        window_start,
        current_fact.id,
        _window_hash(facts, start=window_start),
    )
    signature = (
        credentials.tick_signer(tick_commitment_hash(row))
        if credentials.tick_signer is not None
        else None
    )
    if signature is None and any(
        existing.signature is not None and existing.window_hash is not None for existing in ticks
    ):
        raise RuntimeWriteRefused("refusing an unsigned tick in the signed tick era")
    return RecordDraft(
        kind="tick",
        authored_at=tick.ts.timestamp(),
        observer=custodian,
        origin=tick.origin,
        body=body_of_tick_row((*row, signature)),
        signature=None,
    )


def plan_batch_from_capture(
    capture: RuntimeCapture,
    items: Sequence[BatchFactInput],
    *,
    credentials: WriteCredentials,
    include_pending_boundaries: bool = False,
) -> BatchWritePlan:
    """Plan one batch from frozen evidence without reopening the registry."""
    from .admission import AdmissionError, grant_for_observer

    pending = capture._pending_boundaries if include_pending_boundaries else ()
    if not items and not pending:
        raise RuntimeWriteRefused("batch requires at least one fact or pending boundary")
    basis = capture.basis
    effective = capture._effective_declaration
    candidate = capture._candidate_copy(after_pending_boundaries=include_pending_boundaries)
    from .declaration import validate_arrival_runtime_identity

    validate_arrival_runtime_identity(
        candidate.name,
        candidate.kinds,
        refusal=RuntimeWriteRefused,
    )
    facts = copy.deepcopy(capture._facts)
    ticks = copy.deepcopy(capture._ticks)
    logical: list[RecordDraft] = []
    pending_ids: list[str] = []
    pending_names: list[str] = []
    pending_runs: list[str | None] = []
    for sequence, tick in enumerate(copy.deepcopy(pending)):
        draft = _pending_tick_draft(
            tick,
            facts,
            ticks,
            credentials=credentials,
            custodian=capture.custodian,
        )
        logical.append(draft)
        pending_ids.append(str(draft.body["id"]))
        pending_names.append(str(draft.body["name"]))
        pending_runs.append(tick.run)
        ticks = (
            *ticks,
            _tick_from_draft(draft, basis.captured_head.ordinal + 1, sequence),
        )

    results: list[BatchItemResult] = []
    for index, item in enumerate(items):
        synthetic = _BatchSnapshot(capture, facts, ticks)
        try:
            plan = _existing_fact_plan(synthetic, basis, item.fact, credentials, item.fact_id)
            if plan is None:
                grant = grant_for_observer(effective, item.fact.observer)
                plan = plan_ordinary_write(
                    synthetic,
                    basis,
                    candidate,
                    item.fact,
                    grant=grant,
                    credentials=credentials,
                    custodian=capture.custodian,
                    fact_id=item.fact_id,
                    admit_undeclared=item.admit_undeclared,
                    _mutate_candidate=True,
                )
        except (AdmissionError, _AdmissionPlanRefused) as exc:
            raise BatchWritePreparationRefused(
                input_index=index,
                item=item,
                effective_declaration=capture.effective_declaration,
                custodian=capture.custodian,
                basis=basis,
                cause=exc,
                admission_refused=True,
            ) from exc
        except RuntimeWriteRefused as exc:
            raise BatchWritePreparationRefused(
                input_index=index,
                item=item,
                effective_declaration=capture.effective_declaration,
                custodian=capture.custodian,
                basis=basis,
                cause=exc,
                admission_refused=False,
            ) from exc
        tick_draft = next((draft for draft in plan.drafts if draft.kind == "tick"), None)
        results.append(
            BatchItemResult(
                fact_id=plan.fact_id,
                tick_id=plan.tick_id,
                tick_name=None if tick_draft is None else tick_draft.body["name"],
                already_present=plan.already_present,
                tick_run=plan.tick_run,
            )
        )
        if plan.already_present:
            continue
        ordinal = basis.captured_head.ordinal + 1 + len(logical)
        for sequence, draft in enumerate(plan.drafts):
            if draft.kind == "fact":
                facts = (*facts, _fact_from_draft(draft, ordinal, sequence))
            elif draft.kind == "tick":
                ticks = (*ticks, _tick_from_draft(draft, ordinal, sequence))
        logical.extend(plan.drafts)

    packed = _pack_batch_drafts(logical, credentials)
    if capture.max_atomic_records is not None and len(packed) > capture.max_atomic_records:
        raise AtomicLimitExceeded(
            f"{len(packed)} packed records exceeds this backend's configured "
            f"atomic limit of {capture.max_atomic_records}; the batch was refused before append"
        )
    return BatchWritePlan(
        captured_head=basis.captured_head,
        items=tuple(results),
        drafts=packed,
        effective_declaration=capture.effective_declaration,
        custodian=capture.custodian,
        pending_tick_ids=tuple(pending_ids),
        pending_tick_names=tuple(pending_names),
        pending_tick_runs=tuple(pending_runs),
    )


def prepare_batch_write(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    locator: VertexFile,
    items: Sequence[BatchFactInput],
    *,
    credentials: WriteCredentials,
    fold_overrides: dict[str, FoldOverride] | None = None,
) -> BatchWritePlan:
    """Capture once, then prepare every item against that exact evidence."""
    if not items:
        raise RuntimeWriteRefused("batch requires at least one fact")
    capture = capture_runtime(registry, descriptor, locator, fold_overrides=fold_overrides)
    return plan_batch_from_capture(capture, items, credentials=credentials)


def execute_batch_write(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    plan: BatchWritePlan,
    *,
    after_commit: Callable[[Head], object] | None = None,
) -> CommittedBatchWrite:
    """Append a prepared batch exactly once; no item is retried separately."""
    from .arrival_contract import Profile

    if descriptor.role is not Profile.AUTHORITY:
        raise NotAuthority("batch writes require an Authority descriptor role")
    if not plan.drafts:
        return CommittedBatchWrite(
            None,
            plan.items,
            ProjectionOutcome.NOT_REQUESTED,
            plan.pending_tick_ids,
            plan.pending_tick_names,
            plan.pending_tick_runs,
        )
    ledger, query = registry.open(descriptor)
    try:
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("BackendRegistry.open must return an AttestedLedger")
        comparison = ledger.opened.comparison
        if isinstance(comparison, PreGenesis):
            if comparison.ledger_refusal is not None:
                raise comparison.ledger_refusal
            raise RuntimeWriteRefused("batch emission requires a minted ledger")
        if isinstance(comparison, Indeterminate):
            raise comparison.refusal
        if not isinstance(comparison, Compared):
            raise TypeError(f"unsupported head comparison {comparison!r}")
        if comparison.presented != plan.captured_head:
            raise RuntimeWriteRefused("captured head changed before batch append")
        try:
            commit = ledger.append(plan.captured_head, plan.drafts)
        except NotWitnessed:
            raise
        except ContractRefusal:
            raise
        except Exception as exc:
            raise BatchWriteCommitUnknown(plan, exc) from exc
        if after_commit is not None:
            try:
                after_commit(commit.after)
            except Exception as exc:
                raise BatchPostCommitProjectionFailed(commit, plan, exc) from exc
        projection = ProjectionOutcome.SYNCED if after_commit else ProjectionOutcome.NOT_REQUESTED
        return CommittedBatchWrite(
            commit,
            plan.items,
            projection,
            plan.pending_tick_ids,
            plan.pending_tick_names,
            plan.pending_tick_runs,
        )
    finally:
        _close_quietly(query)
        _close_quietly(ledger)
