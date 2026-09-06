"""Explicit, attested maintenance of Arrival query projections.

Reads never import this module.  The public coordinator first earns the normal
registry/head-attestation result, then obtains a private adapter maintenance
handle and asks it to advance derived state through one verified full head.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .arrival_contract import (
    Full,
    Head,
    HeadMismatch,
    NotAuthority,
    NotSupported,
    Profile,
    ProjectionAbsent,
    ProjectionRequirement,
    QuerySnapshot,
    Watermark,
)
from .arrival_head_seam import AttestedLedger, Compared, Indeterminate, PreGenesis

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .arrival_contract import ArrivalQuery, StoreDescriptor
    from .arrival_registry import BackendRegistry

__all__ = [
    "MaintenanceAdvance",
    "MaintenanceCapabilities",
    "MaintenanceOpener",
    "ProjectionMaintenance",
    "ProjectionSyncError",
    "ProjectionSyncResult",
    "sync_projection",
]


@dataclass(frozen=True)
class MaintenanceCapabilities:
    """The derived-state operations an adapter maintenance handle supports."""

    catch_up: bool
    rebuild: bool = False


@dataclass(frozen=True)
class MaintenanceAdvance:
    """Adapter-local watermarks observed under its maintenance lock."""

    before: Watermark | None
    after: Watermark
    changed: bool


@runtime_checkable
class ProjectionMaintenance(Protocol):
    """A narrow derived-state authority, separate from query and custody."""

    def capabilities(self) -> MaintenanceCapabilities: ...

    def catch_up(self, through: Head) -> MaintenanceAdvance:
        """Advance through ``through`` transactionally, never past it."""
        ...

    def close(self) -> None: ...


MaintenanceOpener = Callable[["StoreDescriptor"], ProjectionMaintenance]


@dataclass(frozen=True)
class ProjectionSyncResult:
    """The attested head and derived prefix established by one explicit sync."""

    captured_head: Head
    target: Head
    projected_before: Head | None
    projected_after: Head
    view_generation: str | None
    changed: bool
    rebuilt: bool = False


class ProjectionSyncError(Exception):
    """Maintenance failed after derived mutation may have been attempted.

    ``observed_after`` is custody-completed evidence read after the failure.
    ``None`` means that the coordinator could not establish a resulting
    projection prefix; it does not claim that no derived write occurred.
    """

    def __init__(
        self,
        message: str,
        *,
        target: Head,
        projected_before: Head | None,
        observed_after: Head | None,
        cause: BaseException,
    ) -> None:
        super().__init__(message)
        self.target = target
        self.projected_before = projected_before
        self.observed_after = observed_after
        self.cause = cause


def _close_quietly(handle: object) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _captured_head(ledger: AttestedLedger) -> Head:
    comparison = ledger.opened.comparison
    if isinstance(comparison, PreGenesis):
        if comparison.ledger_refusal is not None:
            raise comparison.ledger_refusal
        raise NotSupported("a pre-genesis ledger has no projection target")
    if isinstance(comparison, Indeterminate):
        raise comparison.refusal
    if not isinstance(comparison, Compared):
        raise TypeError(f"unsupported head comparison {comparison!r}")
    return comparison.presented


def _resolve_head(ledger: AttestedLedger, watermark: Watermark | None) -> Head | None:
    if watermark is None:
        return None
    return ledger.head_at(watermark)


def _snapshot_state(
    query: ArrivalQuery, ledger: AttestedLedger, *, bound: Head
) -> tuple[Head | None, str | None]:
    snapshot: QuerySnapshot | None = None
    try:
        try:
            snapshot = query.open_snapshot(
                captured_head=bound,
                requirement=ProjectionRequirement.ALLOW_BEHIND,
            )
        except ProjectionAbsent:
            return None, None
        return _resolve_head(ledger, snapshot.represented), snapshot.view_generation
    finally:
        if snapshot is not None:
            _close_quietly(snapshot)


def _verify_target(ledger: AttestedLedger, captured: Head, target: Head) -> Head:
    if target.lineage != captured.lineage:
        raise NotAuthority(
            f"maintenance target names lineage {target.lineage}, but the "
            f"attested ledger presents {captured.lineage}"
        )
    if target.ordinal > captured.ordinal:
        raise HeadMismatch(
            f"maintenance target ordinal {target.ordinal} exceeds the attested "
            f"captured ordinal {captured.ordinal}"
        )
    resolved = ledger.head_at(Watermark(target.lineage, target.ordinal))
    if resolved != target:
        raise HeadMismatch("maintenance target no longer resolves to its recorded hash")
    verified = ledger.verify(Full(through=resolved))
    if verified != resolved:
        raise HeadMismatch("full verification returned a head other than its target")
    return verified


def sync_projection(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    *,
    through: Head | None = None,
    rebuild: bool = False,
) -> ProjectionSyncResult:
    """Advance one projection after normal registry attestation.

    Catch-up is the only supported operation.  Existing inconsistent state is
    refused; this coordinator has no path that discards rows or identity
    markers.  A projection already at or beyond the target is validated and
    reported at its actual prefix without moving backward.
    """
    if descriptor.role not in (Profile.AUTHORITY, Profile.REPLICA):
        raise NotAuthority(
            "projection maintenance requires an explicit Authority or Replica role"
        )

    ledger, query = registry.open(descriptor)
    maintenance: ProjectionMaintenance | None = None
    try:
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("BackendRegistry.open must return an AttestedLedger")
        captured = _captured_head(ledger)
        target = _verify_target(
            ledger, captured, captured if through is None else through
        )

        maintenance = registry._maintenance_for(descriptor)
        capabilities = maintenance.capabilities()
        if rebuild or not capabilities.catch_up:
            raise NotSupported(
                "projection rebuild is not supported"
                if rebuild
                else f"backend {descriptor.backend!r} does not support projection catch-up"
            )
        if capabilities.rebuild:
            raise TypeError(
                "first-stage maintenance providers must advertise rebuild=False"
            )

        projected_before, before_generation = _snapshot_state(
            query, ledger, bound=captured
        )
        if (
            projected_before is not None
            and projected_before.lineage == target.lineage
            and projected_before.ordinal >= target.ordinal
        ):
            generation = (
                None
                if projected_before.ordinal > captured.ordinal
                else before_generation
            )
            return ProjectionSyncResult(
                captured_head=captured,
                target=target,
                projected_before=projected_before,
                projected_after=projected_before,
                view_generation=generation,
                changed=False,
            )

        try:
            advance = maintenance.catch_up(target)
            projected_after = _resolve_head(ledger, advance.after)
            if projected_after is None:  # the adapter contract requires one
                raise TypeError("maintenance returned no resulting watermark")
            if projected_after.lineage != target.lineage:
                raise NotAuthority("maintenance returned a foreign projection lineage")
            if projected_after.ordinal < target.ordinal:
                raise HeadMismatch("maintenance returned a prefix behind its target")
            if projected_after.ordinal == target.ordinal and projected_after != target:
                raise HeadMismatch(
                    "maintenance returned a same-height head different from its target"
                )
            projected_before = _resolve_head(ledger, advance.before)
            observed_after, generation = _snapshot_state(
                query, ledger, bound=projected_after
            )
            if (
                observed_after is None
                or observed_after.lineage != projected_after.lineage
                or observed_after.ordinal < projected_after.ordinal
            ):
                raise HeadMismatch(
                    "query projection does not reach the prefix maintenance returned"
                )
            if observed_after != projected_after:
                # Another serialized maintainer advanced after this handle
                # committed. The first snapshot's generation is bounded at
                # our returned prefix, so it cannot identify the newer view.
                # Report the attested actual prefix and leave generation
                # unknown rather than mislabel it or report success as loss.
                projected_after = observed_after
                generation = None
            return ProjectionSyncResult(
                captured_head=captured,
                target=target,
                projected_before=projected_before,
                projected_after=projected_after,
                view_generation=generation,
                changed=advance.changed,
            )
        except Exception as cause:
            observed_after = None
            with suppress(Exception):
                observed_after, _ = _snapshot_state(query, ledger, bound=captured)
            raise ProjectionSyncError(
                f"projection maintenance through ordinal {target.ordinal} failed; "
                "inspect observed_after before retrying",
                target=target,
                projected_before=projected_before,
                observed_after=observed_after,
                cause=cause,
            ) from cause
    finally:
        if maintenance is not None:
            _close_quietly(maintenance)
        _close_quietly(query)
        _close_quietly(ledger)
