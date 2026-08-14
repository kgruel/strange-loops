"""Headless fact emission operations over Loops vertices."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atoms import Fact
from custody.signing import fact_signer_for, tick_signer_for
from engine import load_declaration_status
from engine.admission import AdmissionError, grant_for_observer
from engine.handle import CredentialProvider, ReceiveCommittedError, VertexHandle, WriteCredentials, open_vertex
from lang.ast import FoldBy

from .target import resolve_target
from .types import (
    AdmissionFailed,
    ClientValueError,
    CommittedEmissionError,
    EmissionFailed,
    EmitPreviewResult,
    EmitReceipt,
    InvalidEmissionRequest,
    TargetUnsupported,
)

__all__ = [
    "emit_fact",
    "emit_batch",
    "preview_emission",
    "CustodyCredentialProvider",
]


class CustodyCredentialProvider:
    """Default CredentialProvider fetching operation-fresh keys from custody."""

    def for_write(self, vertex: Path) -> WriteCredentials:
        return WriteCredentials(
            tick_signer=tick_signer_for(vertex),
            fact_signer=fact_signer_for(vertex),
        )


def preview_emission(
    target: Path | str,
    kind_or_fact: str | Fact,
    payload: dict[str, Any] | None = None,
    *,
    observer: str | None = None,
    origin: str = "",
    ts: float | None = None,
    admit_undeclared: bool = False,
) -> EmitPreviewResult:
    """Simulate fact emission against declared vertex policies without modifying disk.

    Parameters:
        target: Path to the target .vertex file.
        kind_or_fact: Either a fact kind string (with payload dict) or a Fact atom.
        payload: Optional fact payload dictionary.
        observer: Authorship identity name (required when passing kind string).
        origin: Optional origin string.
        ts: Event timestamp (defaults to current UTC timestamp).
        admit_undeclared: If True, simulates bypassing strict kind rejection.

    Returns:
        EmitPreviewResult containing admission, fold-key presence, and simulation details.
    """
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"preview_emission requires a .vertex target, got {info.target_type}")

    target_path = Path(target).resolve()

    if isinstance(kind_or_fact, Fact):
        fact = kind_or_fact
        actual_kind = fact.kind
        actual_observer = fact.observer
        actual_origin = fact.origin
        actual_ts = fact.ts
        actual_payload = dict(fact.payload) if fact.payload else {}
    else:
        if observer is None:
            raise InvalidEmissionRequest("observer is required when previewing by kind name")
        actual_kind = kind_or_fact
        actual_observer = observer
        actual_origin = origin
        actual_ts = ts if ts is not None else datetime.now(UTC).timestamp()
        actual_payload = payload if payload is not None else {}

    try:
        ast, _status = load_declaration_status(target_path)
    except Exception as exc:
        raise EmissionFailed(f"could not load vertex declaration {target_path}: {exc}") from exc

    # Evaluate observer admission policy
    vertex_name = getattr(ast, "name", target_path.stem)
    try:
        grant_for_observer(ast, actual_observer)
    except AdmissionError as exc:
        obs = getattr(exc, "observer", actual_observer)
        k = getattr(exc, "kind", actual_kind)
        v = getattr(exc, "vertex", vertex_name)
        raise AdmissionFailed(str(exc), observer=obs, kind=k, vertex=v) from exc

    kind_declared = actual_kind in ast.loops
    strict = bool(getattr(ast, "strict", False))

    if strict and not kind_declared and not admit_undeclared:
        raise AdmissionFailed(
            f"vertex {vertex_name!r} declares strict — kind {actual_kind!r} is not declared",
            observer=actual_observer,
            kind=actual_kind,
            vertex=vertex_name,
        )

    # Check fold key requirements
    fold_key_field: str | None = None
    fold_key_present = True
    fold_key_value: Any | None = None

    if kind_declared:
        loop_def = ast.loops[actual_kind]
        for f_decl in loop_def.folds:
            if isinstance(f_decl.op, FoldBy):
                fold_key_field = f_decl.op.key_field
                fold_key_present = fold_key_field in actual_payload
                fold_key_value = actual_payload.get(fold_key_field)
                break

    would_fold = kind_declared and fold_key_present
    would_store = True

    return EmitPreviewResult(
        target=str(target_path),
        kind=actual_kind,
        observer=actual_observer,
        origin=actual_origin,
        ts=actual_ts,
        payload=actual_payload,
        kind_declared=kind_declared,
        fold_key_field=fold_key_field,
        fold_key_present=fold_key_present,
        fold_key_value=fold_key_value,
        admitted=True,
        strict=strict,
        would_store=would_store,
        would_fold=would_fold,
    )


def emit_fact(
    target: Path | str,
    kind_or_fact: str | Fact,
    payload: dict[str, Any] | None = None,
    *,
    observer: str | None = None,
    origin: str = "",
    ts: float | None = None,
    id_override: str | None = None,
    credentials: CredentialProvider | None = None,
    admit_undeclared: bool = False,
    dry_run: bool = False,
) -> EmitReceipt:
    """Emit a validated, signed fact to a vertex store under declared admission policy.

    Parameters:
        target: Path to the target .vertex file.
        kind_or_fact: Either a fact kind string (with payload dict) or a pre-instantiated Fact atom.
        payload: The JSON-serializable fact payload dictionary (optional when passing a Fact).
        observer: Authorship identity name (required when passing kind string).
        origin: Optional origin string.
        ts: Event timestamp (defaults to current UTC timestamp).
        id_override: Optional deterministic fact ID.
        credentials: Key provider (defaults to CustodyCredentialProvider).
        admit_undeclared: If True, bypasses strict declared-kind rejection.
        dry_run: If True, simulates emission and returns an uncommitted receipt.

    Returns:
        EmitReceipt containing the persisted fact ID, storage status, attestation, and delta metadata.
    """
    if dry_run:
        preview = preview_emission(
            target,
            kind_or_fact=kind_or_fact,
            payload=payload,
            observer=observer,
            origin=origin,
            ts=ts,
            admit_undeclared=admit_undeclared,
        )
        return EmitReceipt(
            id=id_override or "",
            stored=False,
            signed=None,
            observer=preview.observer,
            tick_mark=None,
            tick_id=None,
            state_change=preview.would_fold,
            affected_sections=[preview.kind] if preview.would_fold else [],
            delta_count=1 if preview.would_fold else 0,
        )

    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"emit_fact requires a .vertex target, got {info.target_type}")

    target_path = Path(target).resolve()

    if isinstance(kind_or_fact, Fact):
        fact = kind_or_fact
        actual_observer = fact.observer
    else:
        if observer is None:
            raise InvalidEmissionRequest("observer is required when emitting by kind name")
        if ts is None:
            ts = datetime.now(UTC).timestamp()
        actual_payload = payload if payload is not None else {}
        fact = Fact.of(kind_or_fact, observer, origin=origin, ts=ts, **actual_payload)
        actual_observer = observer

    cred_provider = credentials or CustodyCredentialProvider()

    try:
        handle = open_vertex(target_path, credentials=cred_provider)
    except Exception as exc:
        raise EmissionFailed(f"could not open vertex {target_path}: {exc}") from exc

    try:
        result = handle.receive_as(
            fact,
            id_override=id_override,
            admit_undeclared=admit_undeclared,
        )
        receipt = result.receipt

        # Extract attestation
        signed = receipt.attestation.signed if receipt.attestation is not None else None
        tick_id = receipt.tick.id if receipt.tick is not None else None
        tick_mark = receipt.tick.name if receipt.tick is not None else None

        delta_count = 0
        affected_sections: list[str] = []
        if result.change is not None:
            delta_count = len(result.change.rows)
            sections = {r.address.kind for r in result.change.rows if r.address.kind}
            if not sections and fact.kind in getattr(handle, "_ast", {}).loops if hasattr(handle, "_ast") else False:
                sections = {fact.kind}
            affected_sections = sorted(sections)
            state_change = delta_count > 0 or len(result.change.receipts) > 0
        else:
            state_change = False

        return EmitReceipt(
            id=receipt.fact_id or "",
            stored=receipt.stored,
            signed=signed,
            observer=actual_observer,
            tick_mark=tick_mark,
            tick_id=tick_id,
            state_change=state_change,
            affected_sections=affected_sections,
            delta_count=delta_count,
        )
    except AdmissionError as exc:
        obs = getattr(exc, "observer", actual_observer)
        k = getattr(exc, "kind", getattr(fact, "kind", None))
        v = getattr(exc, "vertex", None)
        raise AdmissionFailed(str(exc), observer=obs, kind=k, vertex=v) from exc
    except ReceiveCommittedError as exc:
        raise CommittedEmissionError(str(exc), fact_id=exc.fact_id) from exc
    except ClientValueError:
        raise
    except Exception as exc:
        raise EmissionFailed(f"fact emission failed: {exc}") from exc
    finally:
        handle.close()


def emit_batch(
    target: Path | str,
    facts: Sequence[Fact | tuple[str, dict[str, Any]] | dict[str, Any]],
    *,
    observer: str | None = None,
    origin: str = "",
    credentials: CredentialProvider | None = None,
    admit_undeclared: bool = False,
) -> list[EmitReceipt]:
    """Emit a sequence of facts under a single vertex handle session.

    Parameters:
        target: Path to the target .vertex file.
        facts: Sequence of Fact objects, (kind, payload) tuples, or dicts.
        observer: Default observer identity if not specified on individual facts.
        origin: Default origin if not specified on individual facts.
        credentials: Key provider (defaults to CustodyCredentialProvider).
        admit_undeclared: If True, bypasses strict declared-kind rejection.

    Returns:
        List of EmitReceipts corresponding to each committed fact.
    """
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"emit_batch requires a .vertex target, got {info.target_type}")

    target_path = Path(target).resolve()
    cred_provider = credentials or CustodyCredentialProvider()

    try:
        handle = open_vertex(target_path, credentials=cred_provider)
    except Exception as exc:
        raise EmissionFailed(f"could not open vertex {target_path}: {exc}") from exc

    receipts: list[EmitReceipt] = []

    try:
        for item in facts:
            item_id_override: str | None = None
            if isinstance(item, Fact):
                f = item
                actual_obs = f.observer
            elif isinstance(item, tuple) and len(item) == 2:
                k, p = item
                if observer is None:
                    raise InvalidEmissionRequest("observer is required when passing (kind, payload) tuples in emit_batch")
                f = Fact.of(k, observer, origin=origin, **p)
                actual_obs = observer
            elif isinstance(item, dict):
                k = item["kind"]
                p = item.get("payload", {})
                actual_obs = item.get("observer", observer)
                if actual_obs is None:
                    raise InvalidEmissionRequest("observer is required for dict fact in emit_batch")
                item_origin = item.get("origin", origin)
                item_ts = item.get("ts") or datetime.now(UTC).timestamp()
                item_id_override = item.get("id") or item.get("id_override")
                f = Fact.of(k, actual_obs, origin=item_origin, ts=item_ts, **p)
            else:
                raise InvalidEmissionRequest(f"unsupported batch fact item shape: {type(item)}")

            result = handle.receive_as(
                f,
                id_override=item_id_override,
                admit_undeclared=admit_undeclared,
            )
            r = result.receipt

            signed = r.attestation.signed if r.attestation is not None else None
            tick_id = r.tick.id if r.tick is not None else None
            tick_mark = r.tick.name if r.tick is not None else None

            delta_count = 0
            affected_sections: list[str] = []
            if result.change is not None:
                delta_count = len(result.change.rows)
                sections = {row.address.kind for row in result.change.rows if row.address.kind}
                affected_sections = sorted(sections)
                state_change = delta_count > 0 or len(result.change.receipts) > 0
            else:
                state_change = False

            receipts.append(
                EmitReceipt(
                    id=r.fact_id or "",
                    stored=r.stored,
                    signed=signed,
                    observer=actual_obs,
                    tick_mark=tick_mark,
                    tick_id=tick_id,
                    state_change=state_change,
                    affected_sections=affected_sections,
                    delta_count=delta_count,
                )
            )
        return receipts
    except AdmissionError as exc:
        obs = getattr(exc, "observer", observer)
        k = getattr(exc, "kind", None)
        v = getattr(exc, "vertex", None)
        raise AdmissionFailed(str(exc), observer=obs, kind=k, vertex=v) from exc
    except ReceiveCommittedError as exc:
        raise CommittedEmissionError(str(exc), fact_id=exc.fact_id) from exc
    except ClientValueError:
        raise
    except Exception as exc:
        raise EmissionFailed(f"batch emission failed: {exc}") from exc
    finally:
        handle.close()
