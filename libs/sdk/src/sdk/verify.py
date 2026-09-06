"""Custody-prefix verification for explicit Arrival descriptors."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from engine.arrival_contract import Full, Head, HeadMismatch, NotAuthority, Watermark
from engine.arrival_head_seam import AttestedLedger, Compared, Indeterminate, PreGenesis
from engine.arrival_registry import BackendRegistry

from .errors import normalize_exception
from .target import _arrival_descriptor
from .types import StoreDescriptorInfo, VerifyResult

__all__ = ["verify_target"]


def _close_quietly(handle: object) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _verified_prefix(ledger: AttestedLedger, captured: Head, target: Head) -> Head:
    """Verify one target already bounded by the comparison established at open."""
    if target.lineage != captured.lineage:
        raise NotAuthority(
            f"verification target names lineage {target.lineage}, but the "
            f"attested ledger presents {captured.lineage}"
        )
    if target.ordinal > captured.ordinal:
        raise HeadMismatch(
            f"verification target ordinal {target.ordinal} exceeds the attested "
            f"captured ordinal {captured.ordinal}"
        )
    resolved = ledger.head_at(Watermark(target.lineage, target.ordinal))
    if resolved != target:
        raise HeadMismatch("verification target no longer resolves to its recorded hash")
    verified = ledger.verify(Full(through=resolved))
    if verified != resolved:
        raise HeadMismatch("full verification returned a different head")
    return verified


def verify_target(
    target: Path | str,
    *,
    through: Head | None = None,
    registry: BackendRegistry | None = None,
) -> VerifyResult:
    """Fully verify one attested Arrival prefix without reading its projection.

    ``Full`` establishes grammar, dense ordinals, one lineage, and the record
    hash chain through the returned head. It does not verify record signatures,
    authorship, key trust, or projection agreement.
    """
    ledger: object | None = None
    query: object | None = None
    try:
        resolved = _arrival_descriptor(target)
        if resolved is None:
            from .types import TargetUnsupported

            raise TargetUnsupported("verify_target requires an explicit Arrival descriptor")
        _path, _ast, descriptor = resolved
        ledger, query = (registry or BackendRegistry.with_builtin_backends()).open(descriptor)
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("BackendRegistry.open must return an AttestedLedger")
        comparison = ledger.opened.comparison
        if isinstance(comparison, PreGenesis):
            if comparison.ledger_refusal is not None:
                raise comparison.ledger_refusal
            raise HeadMismatch("a pre-genesis ledger has no full verification head")
        if isinstance(comparison, Indeterminate):
            raise comparison.refusal
        if not isinstance(comparison, Compared):
            raise TypeError(f"unsupported head comparison {comparison!r}")
        captured = comparison.presented
        verified = _verified_prefix(ledger, captured, captured if through is None else through)
        return VerifyResult(
            store=StoreDescriptorInfo.from_descriptor(descriptor),
            captured_head=captured,
            verified_through=verified,
        )
    except BaseException as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc
    finally:
        _close_quietly(query)
        _close_quietly(ledger)
