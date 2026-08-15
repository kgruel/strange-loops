"""Headless fact and batch emission operations over Loops vertices."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atoms import Fact
from custody.signing import fact_signer_for, tick_signer_for
from engine.admission import AdmissionError, grant_for_observer
from engine.declaration import load_declaration_status
from engine.handle import CredentialProvider, ReceiveCommittedError, WriteCredentials, open_vertex
from lang.ast import FoldBy

from .target import resolve_target
from .types import (
    AdmissionFailed,
    CommittedEmissionError,
    EmissionFailed,
    EmitPreviewResult,
    EmitReceipt,
    InvalidEmissionRequest,
    SdkValueError,
    TargetUnsupported,
)

__all__ = [
    "emit_fact",
    "emit_batch",
    "preview_emission",
    "CustodyCredentialProvider",
]


class CustodyCredentialProvider:
    """Bridge custody's disk keypair management to engine's CredentialProvider interface."""

    def __init__(self, key_dir: Path | None = None) -> None:
        self._key_dir = key_dir

    def for_write(self, vertex: Path) -> WriteCredentials:
        """Construct operation-fresh WriteCredentials using custody key resolution."""
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
    """Preflight simulation of an emission request against declared admission and fold policies.

    Parameters:
        target: Path to the .vertex file.
        kind_or_fact: Kind name string or complete `Fact` atom.
        payload: Payload dictionary (required if `kind_or_fact` is a string).
        observer: Identity emitting the observation.
        origin: Provenance identifier string.
        ts: Timestamp (defaults to current UTC time).
        admit_undeclared: Whether to simulate emission bypassing strict kind admission.

    Returns:
        EmitPreviewResult detailing admission, predicted storage, and fold requirements.
    """
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(
            f"preview_emission requires a .vertex target, got {info.target_type}"
        )

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

    vertex_name = getattr(ast, "name", target_path.stem)
    try:
        grant_for_observer(ast, actual_observer)
    except AdmissionError as exc:
        return EmitPreviewResult(
            target=str(target_path),
            kind=actual_kind,
            observer=actual_observer,
            origin=actual_origin,
            ts=actual_ts,
            admitted=False,
            reason=str(exc),
            would_store=False,
            would_fold=False,
            fold_key_field=None,
            fold_key_value=None,
        )

    kind_declared = actual_kind in ast.loops
    strict = bool(getattr(ast, "strict", False))

    if strict and not kind_declared and not admit_undeclared:
        return EmitPreviewResult(
            target=str(target_path),
            kind=actual_kind,
            observer=actual_observer,
            origin=actual_origin,
            ts=actual_ts,
            payload=actual_payload,
            kind_declared=kind_declared,
            fold_key_field=None,
            fold_key_present=True,
            fold_key_value=None,
            admitted=False,
            reason=f"vertex {vertex_name!r} declares strict — kind {actual_kind!r} is not declared",
            strict=strict,
            would_store=False,
            would_fold=False,
        )

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
        reason=None,
        strict=strict,
        would_store=True,
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
    """Emit a single fact into a Loops vertex under declared admission rules.

    Parameters:
        target: Path to the target .vertex file.
        kind_or_fact: Kind name string or complete `Fact` atom.
        payload: Fact payload dictionary (required if `kind_or_fact` is a string).
        observer: Authorship identity emitting the fact.
        origin: Provenance identifier string.
        ts: Explicit timestamp (defaults to current UTC time).
        id_override: Optional deterministic fact ULID.
        credentials: Key provider for signing the fact.
        admit_undeclared: If True, bypasses strict declared-kind admission refusal.
        dry_run: If True, simulates emission without writing to storage.

    Returns:
        EmitReceipt containing stored fact ID, attestation, tick mark, and state delta count.
    """
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
        if payload is None:
            raise InvalidEmissionRequest(
                "payload dictionary is required when emitting by kind name"
            )

        actual_observer = observer
        actual_ts = ts if ts is not None else datetime.now(UTC).timestamp()
        fact = Fact(
            kind=kind_or_fact,
            ts=actual_ts,
            payload=payload,
            observer=actual_observer,
            origin=origin,
        )

    if dry_run:
        preview = preview_emission(
            target,
            kind_or_fact=fact,
            observer=actual_observer,
            origin=origin,
            ts=ts,
            admit_undeclared=admit_undeclared,
        )
        if not preview.admitted:
            raise AdmissionFailed(
                preview.reason or "admission failed",
                observer=preview.observer,
                kind=preview.kind,
            )
        return EmitReceipt(
            id="",
            stored=False,
            signed=None,
            observer=actual_observer,
            tick_mark=None,
            tick_id=None,
            state_change=False,
            affected_sections=[preview.kind] if preview.would_fold else [],
            delta_count=0,
            predicted_state_change=preview.would_fold,
        )

    cred_provider = credentials or CustodyCredentialProvider()
    try:
        handle = open_vertex(
            target_path,
            credentials=cred_provider,
        )
    except Exception as exc:
        raise EmissionFailed(f"could not open vertex {target_path}: {exc}") from exc

    try:
        result = handle.receive_as(
            fact,
            id_override=id_override,
            admit_undeclared=admit_undeclared,
        )
        receipt = result.receipt

        signed = receipt.attestation.signed if receipt.attestation is not None else None
        tick_id = receipt.tick.id if receipt.tick is not None else None
        tick_mark = receipt.tick.name if receipt.tick is not None else None

        delta_count = 0
        affected_sections: list[str] = []
        if result.change is not None:
            delta_count = len(result.change.rows)
            sections = {r.address.kind for r in result.change.rows if r.address.kind}
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
            predicted_state_change=False,
        )
    except AdmissionError as exc:
        obs = getattr(exc, "observer", actual_observer)
        k = getattr(exc, "kind", getattr(fact, "kind", None))
        v = getattr(exc, "vertex", None)
        raise AdmissionFailed(str(exc), observer=obs, kind=k, vertex=v) from exc
    except ReceiveCommittedError as exc:
        raise CommittedEmissionError(str(exc), fact_id=exc.fact_id) from exc
    except SdkValueError:
        raise
    except Exception as exc:
        raise EmissionFailed(f"fact emission failed: {exc}") from exc
    finally:
        handle.close()


def emit_batch(
    target: Path | str,
    facts: list[
        Fact | tuple[str, dict[str, Any]] | tuple[str, dict[str, Any], float] | dict[str, Any]
    ],
    *,
    observer: str | None = None,
    origin: str = "",
    credentials: CredentialProvider | None = None,
    admit_undeclared: bool = False,
) -> list[EmitReceipt]:
    """Emit multiple facts into a Loops vertex atomically.

    Parameters:
        target: Path to the target .vertex file.
        facts: List of Fact atoms, (kind, payload) tuples, or fact dict mappings.
        observer: Default observer identity for items omitting one.
        origin: Default provenance origin for items omitting one.
        credentials: Key provider for signing emissions.
        admit_undeclared: If True, bypasses strict declared-kind admission refusal.

    Returns:
        List of EmitReceipt instances corresponding to each emitted fact.
    """
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"emit_batch requires a .vertex target, got {info.target_type}")

    if not facts:
        return []

    target_path = Path(target).resolve()

    prepared_items: list[tuple[Fact, str | None]] = []
    for item in facts:
        item_id_override = None
        if isinstance(item, Fact):
            f = item
        elif isinstance(item, tuple):
            if not observer:
                raise InvalidEmissionRequest(
                    "observer is required when passing (kind, payload) tuples"
                )
            if len(item) == 2:
                k, p = item
                f = Fact(
                    kind=k,
                    ts=datetime.now(UTC).timestamp(),
                    payload=p,
                    observer=observer,
                    origin=origin,
                )
            elif len(item) == 3:
                k, p, item_ts = item
                f = Fact(
                    kind=k,
                    ts=item_ts,
                    payload=p,
                    observer=observer,
                    origin=origin,
                )
            else:
                raise InvalidEmissionRequest(f"unsupported batch fact item shape: {item}")
        elif isinstance(item, Mapping):
            k = item.get("kind")
            if not k:
                raise InvalidEmissionRequest(f"batch item dict missing 'kind': {item}")
            p = dict(item.get("payload", {}))
            item_obs = (
                str(item["observer"]) if "observer" in item and item["observer"] else observer
            )
            if not item_obs:
                raise InvalidEmissionRequest("observer is required for dict fact")
            item_origin = str(item.get("origin", origin))
            item_ts = (
                float(item["ts"])
                if "ts" in item and item["ts"] is not None
                else datetime.now(UTC).timestamp()
            )
            if "id" in item and item["id"]:
                item_id_override = str(item["id"])
            f = Fact(
                kind=k,
                ts=item_ts,
                payload=p,
                observer=item_obs,
                origin=item_origin,
            )
        else:
            raise InvalidEmissionRequest(f"unsupported batch fact item shape: {item}")
        prepared_items.append((f, item_id_override))

    cred_provider = credentials or CustodyCredentialProvider()
    try:
        handle = open_vertex(
            target_path,
            credentials=cred_provider,
        )
    except Exception as exc:
        raise EmissionFailed(f"could not open vertex {target_path}: {exc}") from exc

    receipts: list[EmitReceipt] = []
    try:
        for f, item_id_override in prepared_items:
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
                    observer=f.observer,
                    tick_mark=tick_mark,
                    tick_id=tick_id,
                    state_change=state_change,
                    affected_sections=affected_sections,
                    delta_count=delta_count,
                    predicted_state_change=False,
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
    except SdkValueError:
        raise
    except Exception as exc:
        raise EmissionFailed(f"batch emission failed: {exc}") from exc
    finally:
        handle.close()
