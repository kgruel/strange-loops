"""Descriptor-first vertex boundary sealing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atoms import Fact
from engine.arrival_registry import BackendRegistry
from engine.credentials import CredentialProvider

from .emit import _execute_arrival_fact
from .target import _arrival_descriptor, _refuse_arrival_aggregate_members
from .types import EmitReceipt, InvalidEmissionRequest, SdkValueError, TargetUnsupported

__all__ = ["SealReceipt", "seal_fact"]


@dataclass(frozen=True)
class SealReceipt:
    """Evidence for one descriptor-first boundary sealing attempt."""

    receipt: EmitReceipt
    boundary_match: dict[str, str]
    vertex_name: str
    sealed: bool
    schema: str = "loops.sdk/seal-receipt/v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "receipt": self.receipt.as_dict(),
            "boundary_match": dict(self.boundary_match),
            "vertex_name": self.vertex_name,
            "sealed": self.sealed,
        }


def seal_fact(
    target: Path | str,
    payload: Mapping[str, Any],
    *,
    observer: str,
    credentials: CredentialProvider,
    origin: str = "",
    ts: float | None = None,
    id_override: str | None = None,
    registry: BackendRegistry | None = None,
) -> SealReceipt:
    """Append a ``seal`` fact through a captured vertex-level BoundaryWhen.

    This operation has no legacy route: the captured Arrival declaration picks
    the first vertex boundary for ``seal`` and the engine plans and appends the
    fact under one full-head CAS. A committed fact can honestly return
    ``sealed=False`` when its declaration's boundary conditions did not fire.
    """
    if not isinstance(observer, str) or not observer:
        raise InvalidEmissionRequest("observer is required when sealing")
    if not isinstance(payload, Mapping):
        raise InvalidEmissionRequest("payload must be a mapping")
    if credentials is None or not callable(getattr(credentials, "for_write", None)):
        raise SdkValueError("seal_fact requires an explicit credential provider")

    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is None:
        _refuse_arrival_aggregate_members(target_path)
        raise TargetUnsupported("seal_fact requires an explicit Arrival descriptor target")

    actual_ts = ts if ts is not None else datetime.now(UTC).timestamp()
    fact = Fact(
        kind="seal",
        ts=actual_ts,
        payload=dict(payload),
        observer=observer,
        origin=origin,
    )
    _path, locator, descriptor = arrival
    receipt, plan = _execute_arrival_fact(
        target_path,
        locator,
        descriptor,
        fact,
        observer=observer,
        credentials=credentials,
        registry=registry,
        id_override=id_override,
        boundary=True,
    )
    # The shared execution path validated this evidence before append.
    vertex_name = plan.effective_declaration.name
    return SealReceipt(
        receipt=receipt,
        boundary_match=dict(plan.boundary_match),
        vertex_name=vertex_name,
        sealed=(receipt.tick_id is not None and receipt.tick_mark == vertex_name),
    )
