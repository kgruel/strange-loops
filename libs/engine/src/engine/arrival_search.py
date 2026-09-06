"""Explicit exact-prefix search-index maintenance for Arrival adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
    ProjectionRequirement,
    SearchFieldSpec,
    Watermark,
)
from .arrival_head_seam import AttestedLedger, Compared, Indeterminate, PreGenesis

if TYPE_CHECKING:  # pragma: no cover
    from .arrival_contract import StoreDescriptor
    from .arrival_registry import BackendRegistry

__all__ = [
    "SearchCoverage",
    "SearchIndexBuild",
    "SearchIndexMaintenance",
    "SearchIndexSyncError",
    "SearchIndexSyncResult",
    "SearchMaintenanceOpener",
    "derive_search_spec",
    "sync_search_index",
]


@dataclass(frozen=True)
class SearchCoverage:
    through: Head
    fields_hash: str
    schema_version: str


@dataclass(frozen=True)
class SearchIndexBuild:
    before: SearchCoverage | None
    after: SearchCoverage
    changed: bool


@runtime_checkable
class SearchIndexMaintenance(Protocol):
    """Private adapter authority for one fully rebuilt exact-prefix corpus."""

    def coverage(self) -> SearchCoverage | None: ...

    def build(self, through: Head, spec: SearchFieldSpec) -> SearchIndexBuild: ...

    def close(self) -> None: ...


SearchMaintenanceOpener = Callable[["StoreDescriptor"], SearchIndexMaintenance]


@dataclass(frozen=True)
class SearchIndexSyncResult:
    captured_head: Head
    target: Head
    coverage_before: SearchCoverage | None
    coverage_after: SearchCoverage
    changed: bool


class SearchIndexSyncError(Exception):
    """A search build failed; ``observed_after`` may describe partial evidence."""

    def __init__(
        self,
        message: str,
        *,
        target: Head,
        coverage_before: SearchCoverage | None,
        observed_after: SearchCoverage | None,
        fields_hash: str,
        cause: BaseException,
        coordinator_phase: str | None = None,
        effects: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.target = target
        self.coverage_before = coverage_before
        self.observed_after = observed_after
        self.fields_hash = fields_hash
        self.cause = cause
        self.coordinator_phase = coordinator_phase
        self.effects = effects


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
        raise NotSupported("a pre-genesis ledger has no search target")
    if isinstance(comparison, Indeterminate):
        raise comparison.refusal
    if not isinstance(comparison, Compared):
        raise TypeError(f"unsupported head comparison {comparison!r}")
    return comparison.presented


def _target(ledger: AttestedLedger, captured: Head, target: Head) -> Head:
    if target.lineage != captured.lineage:
        raise NotAuthority("search target names a lineage other than the attested ledger")
    if target.ordinal > captured.ordinal:
        raise HeadMismatch("search target exceeds the attested captured head")
    resolved = ledger.head_at(Watermark(target.lineage, target.ordinal))
    if resolved != target:
        raise HeadMismatch("search target no longer resolves to its recorded hash")
    if ledger.verify(Full(through=resolved)) != resolved:
        raise HeadMismatch("full verification returned a different search target")
    return resolved


def derive_search_spec(effective_ast: object, ingress_dir) -> SearchFieldSpec:
    """Canonicalize fields from an already bounded, pin-checked declaration."""
    from .compiler import collect_search_fields
    from .search_fields import EXTRACTION_VERSION

    return SearchFieldSpec.from_fields(
        collect_search_fields(effective_ast, ingress_dir),
        normalization_version=EXTRACTION_VERSION,
    )


def sync_search_index(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    spec: SearchFieldSpec,
    *,
    through: Head | None = None,
) -> SearchIndexSyncResult:
    """Build one adapter FTS corpus through an attested exact head.

    The caller supplies a canonical field spec derived from its same-bounded
    declaration snapshot. This coordinator never parses a locator or opens a
    legacy declaration/store reader on the maintainer's behalf.
    """
    if descriptor.role not in (Profile.AUTHORITY, Profile.REPLICA):
        raise NotAuthority("search maintenance requires an Authority or Replica role")
    canonical = SearchFieldSpec.from_fields(
        spec.fields_by_kind, normalization_version=spec.normalization_version
    )
    if canonical != spec:
        raise ValueError("search field spec hash does not match its canonical fields")
    ledger = query = maintenance = snapshot = None
    before = None
    target: Head | None = None
    build_entered = False
    try:
        ledger, query = registry.open(descriptor)
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("BackendRegistry.open must return an AttestedLedger")
        captured = _captured_head(ledger)
        target = _target(ledger, captured, captured if through is None else through)
        # Require a projection snapshot now, but do not let it build/recover.
        snapshot = query.open_snapshot(
            captured_head=target, requirement=ProjectionRequirement.CURRENT
        )
        snapshot.close()
        snapshot = None
        maintenance = registry._search_maintenance_for(descriptor)
        before = maintenance.coverage()
        build_entered = True
        build = maintenance.build(target, spec)
        if build.after.through != target or build.after.fields_hash != spec.fields_hash:
            raise HeadMismatch("search maintainer returned coverage other than its target/spec")
        return SearchIndexSyncResult(
            captured_head=captured,
            target=target,
            coverage_before=build.before,
            coverage_after=build.after,
            changed=build.changed,
        )
    except Exception as cause:
        if target is None:
            raise
        observed_after = None
        if maintenance is not None:
            with suppress(Exception):
                observed_after = maintenance.coverage()
        raise SearchIndexSyncError(
            f"search maintenance through ordinal {target.ordinal} failed; "
            "inspect coverage evidence",
            target=target,
            coverage_before=before,
            observed_after=observed_after,
            fields_hash=spec.fields_hash,
            cause=cause,
            coordinator_phase="derived-sync",
            effects={
                "derived": {
                    "attempt": "entered" if build_entered else "not-entered",
                    "state": "unknown" if build_entered else "not-attempted",
                }
            },
        ) from cause
    finally:
        _close_quietly(snapshot)
        _close_quietly(maintenance)
        _close_quietly(query)
        _close_quietly(ledger)
