"""Descriptor-first, read-only Arrival consumer opening.

This module owns the composition that neither a query adapter nor an SDK
renderer may spell independently: registry opening and head attestation happen
before a query snapshot, custody completes the projection watermark, and the
caller receives no append-capable ledger.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from .arrival_contract import (
    Continuation,
    FactPage,
    FactRequest,
    Head,
    HeadMismatch,
    InvalidContinuation,
    NotAuthority,
    ProjectionAbsent,
    ProjectionRequirement,
    QuerySnapshot,
    ReadBasis,
    Watermark,
)
from .arrival_head_seam import (
    AttestedLedger,
    Compared,
    Indeterminate,
    OpenReport,
    PreGenesis,
    complete_projection_custody,
)
from .declaration import validate_arrival_declaration_anchor

if TYPE_CHECKING:  # pragma: no cover - imports only for annotations
    from .arrival_contract import StoreDescriptor
    from .arrival_registry import BackendRegistry

__all__ = ["OpenedRead", "open_read"]


def _close_quietly(handle: object) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


class OpenedRead:
    """A closeable query snapshot plus its custody-completed read basis.

    ``_query`` and ``_ledger`` are deliberately private. The former may own
    adapter resources and the latter can append; exposing either would make a
    read opener an authority escape hatch.
    """

    def __init__(
        self,
        snapshot: QuerySnapshot,
        basis: ReadBasis,
        report: OpenReport,
        _query: object,
        _ledger: object,
    ) -> None:
        self.snapshot = snapshot
        self.basis = basis
        self.report = report
        self._query = _query
        self._ledger = _ledger
        self._closed = False

    def continuation(
        self, request: FactRequest, page: FactPage
    ) -> Continuation | None:
        """Bind ``page.cursor`` to the exact facts request that produced it."""
        if page.cursor is None:
            return None
        if self.basis.projected_through is None:
            raise ProjectionAbsent("an unrepresented projection cannot continue")
        if self.basis.view_generation is None:
            raise InvalidContinuation(
                "this query adapter cannot prove a stable derived view for resume"
            )
        return Continuation(
            captured_head=self.basis.captured_head,
            projected_through=self.basis.projected_through,
            request=request,
            cursor=page.cursor,
            view_generation=self.basis.view_generation,
        )

    def close(self) -> None:
        """Close snapshot, query handle, then custody handle without leaking."""
        if self._closed:
            return
        self._closed = True
        _close_quietly(self.snapshot)
        _close_quietly(self._query)
        _close_quietly(self._ledger)

    def __enter__(self) -> OpenedRead:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _head_at(ledger: AttestedLedger, head: Head, *, label: str) -> Head:
    resolved = ledger.head_at(Watermark(lineage=head.lineage, ordinal=head.ordinal))
    if resolved != head:
        raise InvalidContinuation(
            f"{label} head no longer resolves to its recorded hash"
        )
    return resolved


def open_read(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    *,
    requirement: ProjectionRequirement = ProjectionRequirement.CURRENT,
    continuation: Continuation | None = None,
) -> OpenedRead:
    """Open one descriptor-first, attested, bounded read without writer access."""
    if descriptor.role is None:
        raise NotAuthority(
            "the supported SDK read path requires an explicit descriptor role"
        )
    ledger, query = registry.open(descriptor)
    snapshot: QuerySnapshot | None = None
    try:
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("BackendRegistry.open must return an AttestedLedger")
        report = ledger.opened
        comparison = report.comparison
        if isinstance(comparison, PreGenesis):
            if comparison.ledger_refusal is not None:
                raise comparison.ledger_refusal
            raise ProjectionAbsent("a pre-genesis ledger has no captured read head")
        if isinstance(comparison, Indeterminate):
            raise comparison.refusal
        if not isinstance(comparison, Compared):  # defensive against future report arms
            raise TypeError(f"unsupported head comparison {comparison!r}")

        if continuation is None:
            captured = comparison.presented
            represented_from_token = None
        else:
            if continuation.view_generation is None:
                raise InvalidContinuation(
                    "continuations require a derived-view generation"
                )
            captured = _head_at(ledger, continuation.captured_head, label="continuation captured")
            represented_from_token = _head_at(
                ledger, continuation.projected_through, label="continuation represented"
            )
            if represented_from_token.ordinal > captured.ordinal:
                raise InvalidContinuation(
                    "continuation represented prefix exceeds its captured head"
                )

        snapshot = query.open_snapshot(
            captured_head=captured,
            requirement=requirement,
            continuation=continuation,
        )
        watermark = snapshot.represented
        validate_arrival_declaration_anchor(snapshot.declaration_anchor, captured)
        if watermark is None:
            if represented_from_token is not None:
                raise InvalidContinuation(
                    "projection disappeared since this continuation was issued"
                )
            basis = ReadBasis(
                lineage=captured.lineage,
                captured_head=captured,
                projected_through=None,
                view_generation=snapshot.view_generation,
            )
        elif watermark.lineage != captured.lineage:
            raise NotAuthority(
                f"query snapshot represents {watermark.lineage}, not {captured.lineage}"
            )
        else:
            # The query transaction can observe a projection written after the
            # seam captured H, including while resuming a prior page. Every
            # reported watermark still needs custody membership validation.
            observed = complete_projection_custody(
                ledger,
                captured=captured,
                represented=watermark,
                lineage_refusal=NotAuthority,
                conflict_refusal=HeadMismatch,
            )
            if (
                continuation is not None
                and snapshot.view_generation != continuation.view_generation
            ):
                raise InvalidContinuation(
                    "projection view changed since this continuation was issued"
                )
            if represented_from_token is not None:
                if watermark.ordinal < represented_from_token.ordinal:
                    raise InvalidContinuation(
                        "projection no longer reaches the continuation prefix"
                    )
                basis = ReadBasis(
                    lineage=captured.lineage,
                    captured_head=captured,
                    projected_through=represented_from_token,
                    view_generation=snapshot.view_generation,
                )
            elif watermark.ordinal > captured.ordinal:
                basis = ReadBasis(
                    lineage=captured.lineage,
                    captured_head=captured,
                    projected_through=captured,
                    view_generation=snapshot.view_generation,
                )
            else:
                basis = ReadBasis(
                    lineage=captured.lineage,
                    captured_head=captured,
                    projected_through=observed,
                    view_generation=snapshot.view_generation,
                )
        return OpenedRead(
            snapshot=snapshot, basis=basis, report=report, _query=query, _ledger=ledger
        )
    except BaseException:
        if snapshot is not None:
            _close_quietly(snapshot)
        _close_quietly(query)
        _close_quietly(ledger)
        raise
