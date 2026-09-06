"""Explicit exact-prefix restoration, with no reusable custody handle.

The proposed receiver head passes pure witness comparison before mutation.
The actual receiver is compared again after full-head CAS, then witnessed.
No reset, new genesis, projection repair, or partial chunking occurs.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .arrival import GENESIS_KIND, KEY_INTRODUCTION_KIND
from .arrival_body import ROW_KINDS, rows_of_body
from .arrival_contract import (
    AtomicLimitExceeded,
    Commit,
    ContractRefusal,
    FactRequest,
    Full,
    Head,
    HeadMismatch,
    Open,
    ProjectionRequirement,
    StoreDescriptor,
    TickRequest,
    VerifyScope,
    Watermark,
)
from .arrival_head_attestation import record_binding
from .arrival_head_seam import AttestedLedger, Compared, Indeterminate, _HeadObservation
from .arrival_transfer import _captured, _close, _require_role, _verify_prefix
from .declaration import validate_arrival_declaration_anchor

if TYPE_CHECKING:
    from .arrival_registry import BackendRegistry


@dataclass(frozen=True)
class RestoreForwardResult:
    captured_head: Head
    before: Head
    after: Head
    commit: Commit | None


class RestoreForwardUnknown(Exception):
    """Replication was entered but no authoritative receipt returned."""

    def __init__(self, before: Head, target: Head, cause: BaseException) -> None:
        super().__init__(f"restore-forward outcome is unknown: {cause}")
        self.before = before
        self.target = target
        self.cause = cause


class RestoreForwardIncomplete(Exception):
    """Exact records committed; later comparison or witnessing failed."""

    def __init__(self, commit: Commit, cause: BaseException) -> None:
        super().__init__(f"restore-forward committed but completion failed: {cause}")
        self.commit = commit
        self.before = commit.before
        self.after = commit.after
        self.cause = cause


class _BoundedProof:
    """Only the evidence operations used by the pure head comparison."""

    def __init__(self, source: AttestedLedger, head: Head) -> None:
        self._source = source
        self._head = head

    def verify(self, scope: VerifyScope) -> Head:
        if isinstance(scope, Open):
            return self._head
        _verify_prefix(self._source, self._head, scope.through)
        return scope.through

    def head_at(self, watermark: Watermark) -> Head:
        if watermark.lineage != self._head.lineage or watermark.ordinal > self._head.ordinal:
            raise HeadMismatch("restoration proof does not cover this watermark")
        return self._source.head_at(watermark)


def _ledger_rows(ledger: AttestedLedger, through: Head) -> list[tuple[object, ...]]:
    """Expand one verified custody prefix into its exact projected row stream."""
    rows: list[tuple[object, ...]] = []
    for record in ledger.scan(through=through):
        record_kind = record["k"]
        if record_kind in (GENESIS_KIND, KEY_INTRODUCTION_KIND):
            continue
        if record_kind not in ROW_KINDS:
            raise HeadMismatch(
                f"record {record['ord']} has unsupported projection kind {record_kind!r}"
            )
        for sequence, (row_kind, row) in enumerate(rows_of_body(record_kind, record["body"])):
            rows.append((int(record["ord"]), sequence, row_kind, *row))
    return rows


def _snapshot_rows(snapshot: object) -> list[tuple[object, ...]]:
    """Read retained wire evidence without rebuilding payload text from JSON."""
    facts = snapshot.facts(
        FactRequest(limit=None, include_internal=True, order="oldest")
    ).items
    ticks = snapshot.ticks(TickRequest(since=-float("inf"), until=float("inf")))
    rows: list[tuple[object, ...]] = []
    for fact in facts:
        if fact.payload_text is None:
            raise HeadMismatch(
                "projection omitted exact fact payload text required for restore audit"
            )
        rows.append(
            (
                fact.arrival_ordinal,
                fact.arrival_seq,
                "fact",
                fact.id,
                fact.kind,
                fact.ts,
                fact.observer,
                fact.origin,
                fact.payload_text,
                fact.signature,
            )
        )
    for tick in ticks:
        if tick.payload_text is None:
            raise HeadMismatch(
                "projection omitted exact tick payload text required for restore audit"
            )
        rows.append(
            (
                tick.arrival_ordinal,
                tick.arrival_seq,
                "tick",
                tick.id,
                tick.name,
                tick.ts,
                tick.since,
                tick.origin,
                tick.payload_text,
                tick.prev_hash,
                tick.window_start,
                tick.fact_cursor,
                tick.window_hash,
                tick.signature,
            )
        )
    return sorted(rows, key=lambda row: (row[0], row[1], row[2]))


def _audit_declaration_anchor(
    snapshot: object, expected: list[tuple[object, ...]], head: Head
) -> None:
    """Require a claimed own declaration identity to be projected exactly."""
    anchor = snapshot.declaration_anchor
    validate_arrival_declaration_anchor(anchor, head)
    expected_genesis = [
        row
        for row in expected
        if row[2] == "fact" and row[3] == head.lineage and row[4] == "_decl.genesis"
    ]
    if not expected_genesis:
        if anchor.own_lineage is not None or anchor.genesis is not None:
            raise HeadMismatch(
                "projection claims a declaration identity absent from its audited prefix"
            )
        return
    if len(expected_genesis) != 1 or anchor.own_lineage != head.lineage:
        raise HeadMismatch("projection does not name the audited declaration genesis")
    genesis = anchor.genesis
    if genesis is None or genesis.payload_text is None:
        raise HeadMismatch("projection omitted audited declaration genesis evidence")
    actual = (
        genesis.arrival_ordinal,
        genesis.arrival_seq,
        "fact",
        genesis.id,
        genesis.kind,
        genesis.ts,
        genesis.observer,
        genesis.origin,
        genesis.payload_text,
        genesis.signature,
    )
    if actual != expected_genesis[0]:
        raise HeadMismatch("projection declaration anchor differs from audited genesis row")


def _audit_projection(ledger: AttestedLedger, query: object, through: Head) -> None:
    """Refuse a represented projection whose bounded rows differ from custody.

    Watermarks contain a lineage and ordinal but no record hash.  An explicit
    restore therefore pays this full, read-only comparison: it catches a
    projection from a distinct branch at the same coordinate without adding a
    checkpoint field to the neutral query contract.  An absent projection has
    no derived evidence to contradict custody and remains absent; this never
    builds or repairs it.
    """
    snapshot = query.open_snapshot(
        captured_head=through,
        requirement=ProjectionRequirement.ALLOW_BEHIND,
    )
    try:
        watermark = snapshot.represented
        if watermark is None:
            return
        observed = ledger.head_at(watermark)
        # A snapshot clamps rows to H when its watermark advanced concurrently;
        # when it lags, its own represented prefix is the only row set it claims.
        audited = through if observed.ordinal > through.ordinal else observed
        expected = _ledger_rows(ledger, audited)
        _audit_declaration_anchor(snapshot, expected, audited)
        actual = _snapshot_rows(snapshot)
        if actual != expected:
            raise HeadMismatch(
                "projection rows do not exactly match the verified custody prefix "
                f"through ordinal {audited.ordinal}"
            )
    finally:
        _close(snapshot)


def _restore_forward(
    registry: BackendRegistry,
    source: StoreDescriptor,
    receiver: StoreDescriptor,
    *,
    through: Head | None = None,
) -> RestoreForwardResult:
    """Registry-owned procedure: restore an existing verified exact prefix."""
    _require_role(source)
    _require_role(receiver)
    source_ledger, source_query = registry.open(source)
    target_ledger = target_query = None
    try:
        if not isinstance(source_ledger, AttestedLedger):
            raise TypeError("restoration source must be independently attested")
        captured = _captured(source_ledger)
        selected = captured if through is None else through
        _verify_prefix(source_ledger, captured, selected)
        target_ledger, target_query, binding = registry._open_components(receiver)
        before = target_ledger.verify(Open())
        if target_ledger.verify(Full(through=before)) != before:
            raise HeadMismatch("receiver full verification did not establish its head")
        if before.lineage != selected.lineage or before.ordinal > selected.ordinal:
            raise HeadMismatch("receiver is not an older prefix of the selected source")
        if source_ledger.head_at(Watermark(before.lineage, before.ordinal)) != before:
            raise HeadMismatch("receiver and source do not share the exact receiver head")

        # Derived evidence belongs to the receiver's actual prefix. Comparing
        # it only with the proposed head can hide tail loss: a fork's ahead
        # projection would become apparently current after a different suffix
        # fills the same ordinals. Refuse before mutation, preserving that
        # evidence for explicit projection recovery.
        _HeadObservation(
            target_ledger,
            location=receiver.location,
            query=target_query,
            binding=binding,
        )._projection(before)
        _audit_projection(target_ledger, target_query, before)

        count = selected.ordinal - before.ordinal
        limit = target_ledger.capabilities().max_atomic_records
        if limit is not None and count > limit:
            raise AtomicLimitExceeded(
                f"restoration requires {count} atomic records; receiver limit is {limit}"
            )
        records = tuple(
            deepcopy(dict(record))
            for record in source_ledger.scan(after=before.ordinal, through=selected)
        )
        if len(records) != count:
            raise HeadMismatch("source scan did not supply the complete restoration suffix")
        # Pure proof: binding, witness floor, reset fences and projection evidence.
        observation = _HeadObservation(
            _BoundedProof(source_ledger, selected),
            location=receiver.location,
            query=target_query,
            binding=binding,
        )
        report, _earned = observation._observe()
        if isinstance(report.comparison, Indeterminate):
            raise report.comparison.refusal
        if not isinstance(report.comparison, Compared):
            raise HeadMismatch("restoration proof established no comparable head")

        commit = None
        if records:
            try:
                commit = target_ledger.replicate(before, records)
            except ContractRefusal:
                raise
            except Exception as exc:
                raise RestoreForwardUnknown(before, selected, exc) from exc
        try:
            if commit is not None and (commit.before != before or commit.after != selected):
                raise HeadMismatch("backend receipt differs from the proven restoration")
            # First receiver acceptance; recheck changes while replication ran.
            actual = AttestedLedger(
                target_ledger,
                location=receiver.location,
                query=target_query,
                binding=binding,
            )
            if _captured(actual) != selected:
                raise HeadMismatch("receiver changed before restoration completion")
            _audit_projection(actual, target_query, selected)
            if commit is not None:
                actual._witness(commit)
            record_binding(binding.key, selected.lineage, time.time())
        except Exception as exc:
            if commit is None:
                raise
            raise RestoreForwardIncomplete(commit, exc) from exc
        return RestoreForwardResult(captured, before, selected, commit)
    finally:
        _close(target_query)
        _close(target_ledger)
        _close(source_query)
        _close(source_ledger)
