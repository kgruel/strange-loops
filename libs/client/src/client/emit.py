"""Headless fact emission operations over Loops vertices."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atoms import Fact
from custody.signing import fact_signer_for, tick_signer_for
from engine.admission import AdmissionError
from engine.handle import CredentialProvider, ReceiveCommittedError, VertexHandle, WriteCredentials, open_vertex

from .target import resolve_target
from .types import AdmissionFailed, CommittedEmissionError, EmissionFailed, EmitReceipt, TargetUnsupported

__all__ = ["emit_fact", "CustodyCredentialProvider"]


class CustodyCredentialProvider:
    """Default CredentialProvider fetching operation-fresh keys from custody."""

    def for_write(self, vertex: Path) -> WriteCredentials:
        return WriteCredentials(
            tick_signer=tick_signer_for(vertex),
            fact_signer=fact_signer_for(vertex),
        )


def emit_fact(
    target: Path | str,
    kind: str,
    payload: dict[str, Any],
    *,
    observer: str,
    origin: str = "",
    ts: float | None = None,
    credentials: CredentialProvider | None = None,
    admit_undeclared: bool = False,
) -> EmitReceipt:
    """Emit a validated, signed fact to a vertex store under declared admission policy.

    Parameters:
        target: Path to the target .vertex file.
        kind: The fact kind name.
        payload: The JSON-serializable fact payload dictionary.
        observer: Authorship identity name.
        origin: Optional origin string.
        ts: Event timestamp (defaults to current UTC timestamp).
        credentials: Key provider (defaults to CustodyCredentialProvider).
        admit_undeclared: If True, bypasses strict declared-kind rejection.

    Returns:
        EmitReceipt containing the persisted fact ID, storage status, and attestation.
    """
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"emit_fact requires a .vertex target, got {info.target_type}")

    target_path = Path(target).resolve()
    if ts is None:
        ts = datetime.now(UTC).timestamp()

    fact = Fact.of(kind, observer, origin=origin, ts=ts, **payload)
    cred_provider = credentials or CustodyCredentialProvider()

    try:
        handle = open_vertex(target_path, credentials=cred_provider)
    except Exception as exc:
        raise EmissionFailed(f"could not open vertex {target_path}: {exc}") from exc

    try:
        result = handle.receive_as(fact, admit_undeclared=admit_undeclared)
        receipt = result.receipt

        # Extract attestation
        signed = receipt.attestation.signed if receipt.attestation is not None else None
        tick_id = receipt.tick.id if receipt.tick is not None else None
        tick_mark = receipt.tick.name if receipt.tick is not None else None
        state_change = result.change is not None and len(result.change.receipts) > 0

        return EmitReceipt(
            id=receipt.fact_id or "",
            stored=receipt.stored,
            signed=signed,
            observer=observer,
            tick_mark=tick_mark,
            tick_id=tick_id,
            state_change=state_change,
        )
    except AdmissionError as exc:
        raise AdmissionFailed(str(exc)) from exc
    except ReceiveCommittedError as exc:
        raise CommittedEmissionError(str(exc), fact_id=exc.fact_id) from exc
    except Exception as exc:
        raise EmissionFailed(f"fact emission failed: {exc}") from exc
    finally:
        handle.close()
