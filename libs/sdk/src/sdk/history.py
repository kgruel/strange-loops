"""Complete, descriptor-first fact history over one captured Arrival snapshot.

This module deliberately does not provide pagination or continuation tokens.  A
history result is an O(selected history) materialization of one current,
captured projection prefix.  It includes retained facts from before a fresh
execution epoch; epoch filtering belongs to state reconstruction, not history.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.arrival_contract import (
    FactRequest,
    NotSupported,
    ProjectionBehind,
    ReadBasis,
)
from engine.arrival_registry import BackendRegistry

from .read import _arrival_declaration, _fact_as_dict, _open_arrival_read
from .target import _arrival_descriptor
from .types import SdkValueError, StoreDescriptorInfo, TargetUnsupported

__all__ = ["FactHistoryResult", "read_all_facts"]


@dataclass(frozen=True)
class FactHistoryResult:
    """All selected facts from one complete, current Arrival projection prefix."""

    schema: str = "loops.sdk/facts-history/v1"
    read_path: str = "arrival"
    basis: ReadBasis | None = None
    store: StoreDescriptorInfo | None = None
    kind: str | None = None
    observer: str | None = None
    order: str = "newest"
    include_internal: bool = False
    items: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    item_count: int = 0
    complete: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-native copy without exposing adapter objects."""
        return {
            "schema": self.schema,
            "read_path": self.read_path,
            "basis": None if self.basis is None else asdict(self.basis),
            "store": None if self.store is None else asdict(self.store),
            "kind": self.kind,
            "observer": self.observer,
            "order": self.order,
            "include_internal": self.include_internal,
            "items": [deepcopy(item) for item in self.items],
            "item_count": self.item_count,
            "complete": self.complete,
        }


def _validate_request(
    *,
    kind: str | None,
    observer: str | None,
    order: str,
    include_internal: bool,
) -> None:
    """Reject invalid request values before opening an Arrival adapter."""
    if order not in ("newest", "oldest"):
        raise SdkValueError(f"invalid order {order!r}: expected 'newest' or 'oldest'")
    if kind is not None and not isinstance(kind, str):
        raise SdkValueError("kind must be a string or None")
    if observer is not None and not isinstance(observer, str):
        raise SdkValueError("observer must be a string or None")
    if not isinstance(include_internal, bool):
        raise SdkValueError("include_internal must be a bool")


def read_all_facts(
    target: Path | str,
    *,
    kind: str | None = None,
    observer: str | None = None,
    order: str = "newest",
    include_internal: bool = False,
    registry: BackendRegistry | None = None,
) -> FactHistoryResult:
    """Materialize selected facts from one current captured Arrival prefix.

    The result is O(selected history) memory: it intentionally has no page
    size, iterator, cursor, or continuation protocol.  It reads every selected
    row through one ``FactRequest(limit=None)`` on one CURRENT snapshot, so a
    result never combines pages or captures.  Retained history predating a
    fresh runtime epoch remains visible, just as it is in the store.

    Only an explicit, non-aggregate Arrival descriptor is accepted.  Legacy
    targets are refused rather than resolved or materialized through legacy
    readers.
    """
    _validate_request(
        kind=kind,
        observer=observer,
        order=order,
        include_internal=include_internal,
    )
    target_path = Path(target).resolve()
    resolved = _arrival_descriptor(target_path)
    if resolved is None:
        raise TargetUnsupported(
            f"complete fact history requires an explicit Arrival descriptor: {target_path}"
        )

    request = FactRequest(
        limit=None,
        kind=kind,
        observer=observer,
        order=order,
        include_internal=include_internal,
    )
    with _open_arrival_read(resolved, registry=registry) as (
        locator_ast,
        descriptor,
        opened,
    ):
        basis = opened.basis
        if basis.projected_through != basis.captured_head:
            raise ProjectionBehind(
                "complete fact history requires a projection through the captured head"
            )
        # Resolve the adopted declaration from complete evidence on this exact
        # snapshot; neither an aggregate nor a genesis-floor fallback is a
        # complete, adopted single-store history.
        _effective, status, _facts, _lineage = _arrival_declaration(
            locator_ast, target_path, opened
        )
        if status != "store":
            raise NotSupported("complete fact history requires an adopted declaration")
        page = opened.snapshot.facts(request)
        if page.truncated or page.cursor is not None:
            raise NotSupported(
                "the Arrival query adapter cannot provide complete fact history "
                "from one unbounded request"
            )
        if page.order != order:
            raise NotSupported(
                "the Arrival query adapter returned a fact order different from "
                "the requested complete history order"
            )
        store = StoreDescriptorInfo.from_descriptor(descriptor)
        facts = tuple(page.items)

    # Adapter resources have closed before response serialization begins.
    items = tuple(_fact_as_dict(fact) for fact in facts)
    return FactHistoryResult(
        basis=basis,
        store=store,
        kind=kind,
        observer=observer,
        order=order,
        include_internal=include_internal,
        items=items,
        item_count=len(items),
    )
