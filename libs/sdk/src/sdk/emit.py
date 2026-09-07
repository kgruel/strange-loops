"""Headless fact and batch emission operations over Loops vertices."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atoms import Fact
from custody.binding import MappedCredentialProvider as _MappedCredentialProvider
from custody.signing import arrival_signer_for, fact_signer_for, tick_signer_for
from engine.admission import AdmissionError, UndeclaredKind, grant_for_observer
from engine.arrival_registry import BackendRegistry
from engine.credentials import CredentialProvider, WriteCredentials
from engine.declaration import load_declaration_status
from engine.handle import ReceiveCommittedError, open_vertex
from lang.ast import FoldBy

from .target import (
    _arrival_descriptor,
    _refuse_arrival_aggregate_members,
    resolve_target,
)
from .types import (
    AdmissionFailed,
    BatchEmitResult,
    CommittedEmissionError,
    EmissionFailed,
    EmitPreviewResult,
    EmitReceipt,
    InvalidEmissionRequest,
    LegacyBatchPartialFailure,
    SdkError,
    SdkValueError,
    StoreDescriptorInfo,
    TargetUnsupported,
)

__all__ = [
    "emit_fact",
    "emit_batch",
    "preview_emission",
    "CustodyCredentialProvider",
    "MappedCredentialProvider",
]


def _tick_fields(tick: Any, change: Any) -> tuple[str | None, str | None]:
    """Resolve (tick_mark, tick_id) for a receipt whose write fired a boundary.

    The in-memory engine ``Tick`` carries no id — the store assigns one on the
    tick row, surfaced as ``TickEvent.tick_id`` in the post-write ``ChangeBatch``.
    Reading ``tick.id`` off the Tick object was an AttributeError on every
    boundary-firing emission.
    """
    if tick is None:
        return None, None
    tick_id: str | None = None
    if change is not None and change.ticks:
        matching = [ev for ev in change.ticks if ev.name == tick.name]
        if matching:
            tick_id = matching[-1].tick_id
    return tick.name, tick_id


def _fold_preview(
    declaration: Any, kind: str, payload: Mapping[str, Any]
) -> tuple[bool, str | None, bool, Any | None]:
    """Describe the existing SDK fold fields from one effective declaration."""
    kind_declared = kind in declaration.loops
    fold_key_field: str | None = None
    fold_key_present = True
    fold_key_value: Any | None = None
    if kind_declared:
        for fold in declaration.loops[kind].folds:
            if isinstance(fold.op, FoldBy):
                fold_key_field = fold.op.key_field
                fold_key_present = fold_key_field in payload
                fold_key_value = payload.get(fold_key_field)
                break
    return kind_declared, fold_key_field, fold_key_present, fold_key_value


def _preparation_refusal_reason(refusal: Any) -> str:
    """Preserve the established strict-kind message from snapshot evidence."""
    effective = refusal.effective_declaration
    fact = refusal.fact
    if isinstance(refusal.cause, UndeclaredKind):
        return f"vertex {effective.name!r} declares strict — kind {fact.kind!r} is not declared"
    return str(refusal.cause)


class CustodyCredentialProvider:
    """Bridge custody's disk keypair management to engine's CredentialProvider interface."""

    def __init__(self, key_dir: Path | None = None) -> None:
        if key_dir is not None:
            raise SdkValueError(
                "CustodyCredentialProvider key_dir overrides are not supported"
            )

    def for_write(self, vertex: Path) -> WriteCredentials:
        """Construct operation-fresh WriteCredentials using custody key resolution."""
        return WriteCredentials(
            tick_signer=tick_signer_for(vertex),
            fact_signer=fact_signer_for(vertex),
            arrival_signer=arrival_signer_for(vertex),
        )


class MappedCredentialProvider(_MappedCredentialProvider):
    """SDK export for explicit namespace-scoped, persistent custody bindings."""

    def __init__(
        self,
        root: Path | str,
        *,
        namespace: str,
        receipt_observer: str | None = None,
    ) -> None:
        try:
            super().__init__(root, namespace=namespace, receipt_observer=receipt_observer)
        except ValueError as exc:
            raise SdkValueError(str(exc)) from exc


def _mapped_credentials(
    value: CredentialProvider | WriteCredentials | None, *, vertex: Path | None = None
) -> bool:
    """Mapped credentials cannot silently route through legacy store writers."""
    if value is None:
        return False
    if bool(getattr(value, "mapped", False)):
        return True
    if isinstance(value, WriteCredentials):
        return value.mapped
    provider = getattr(value, "for_write", None)
    if vertex is None or not callable(provider):
        return False
    produced = provider(vertex)
    if not isinstance(produced, WriteCredentials):
        raise SdkValueError("credential provider did not return WriteCredentials")
    return produced.mapped


def _refuse_legacy_mapped_credentials(
    value: CredentialProvider | WriteCredentials | None, *, vertex: Path
) -> None:
    if _mapped_credentials(value, vertex=vertex):
        raise TargetUnsupported(
            "mapped credentials require an explicit Arrival descriptor target"
        )


def preview_emission(
    target: Path | str,
    kind_or_fact: str | Fact,
    payload: dict[str, Any] | None = None,
    *,
    observer: str | None = None,
    origin: str = "",
    ts: float | None = None,
    id_override: str | None = None,
    admit_undeclared: bool = False,
    credentials: CredentialProvider | None = None,
    registry: BackendRegistry | None = None,
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
    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=target_path)

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

    if arrival is not None:
        from engine.runtime_write import (
            OrdinaryWritePreparationRefused,
            prepare_ordinary_write,
        )

        _path, locator, descriptor = arrival
        registry = registry or BackendRegistry.with_builtin_backends()
        cred_provider = credentials or CustodyCredentialProvider()
        prepared_fact = (
            fact
            if isinstance(kind_or_fact, Fact)
            else Fact(
                kind=actual_kind,
                ts=actual_ts,
                payload=actual_payload,
                observer=actual_observer,
                origin=actual_origin,
            )
        )
        refusal: OrdinaryWritePreparationRefused | None = None
        try:
            plan = prepare_ordinary_write(
                registry,
                descriptor,
                locator,
                prepared_fact,
                credentials=cred_provider.for_write(target_path),
                fact_id=id_override,
                admit_undeclared=admit_undeclared,
            )
            effective = plan.effective_declaration
            captured_head = plan.captured_head
        except OrdinaryWritePreparationRefused as exc:
            refusal = exc
            effective = exc.effective_declaration
            captured_head = exc.captured_head
            plan = None
        except SdkError:
            raise
        except Exception as exc:
            from .errors import normalize_exception

            normalized = normalize_exception(exc)
            if normalized is not exc:
                raise normalized from exc
            raise EmissionFailed(f"emission preview failed: {exc}") from exc
        if effective is None:
            raise EmissionFailed("Arrival preparation returned no effective declaration")
        kind_declared, fold_key_field, fold_key_present, fold_key_value = _fold_preview(
            effective, actual_kind, actual_payload
        )
        return EmitPreviewResult(
            read_path="arrival",
            store=StoreDescriptorInfo.from_descriptor(descriptor),
            captured_head=captured_head,
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
            admitted=refusal is None,
            reason=(None if refusal is None else _preparation_refusal_reason(refusal)),
            strict=bool(effective.strict),
            would_store=plan is not None and not plan.already_present,
            would_fold=(refusal is None and kind_declared and fold_key_present),
        )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(
            f"preview_emission requires a .vertex target, got {info.target_type}"
        )

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
    registry: BackendRegistry | None = None,
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
    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=target_path)

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
            id_override=id_override,
            admit_undeclared=admit_undeclared,
            credentials=credentials,
            registry=registry,
        )
        if not preview.admitted:
            raise AdmissionFailed(
                preview.reason or "admission failed",
                observer=preview.observer,
                kind=preview.kind,
            )
        return EmitReceipt(
            write_path=preview.read_path,
            store=preview.store,
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
            captured_head=preview.captured_head,
            witnessed=None,
            projection="not-requested" if arrival is not None else None,
        )

    if arrival is not None:
        from engine.arrival_maintenance import sync_projection
        from engine.runtime_write import (
            OrdinaryWritePlan,
            OrdinaryWritePreparationRefused,
            execute_ordinary_write,
            prepare_ordinary_write,
        )

        _path, locator, descriptor = arrival
        registry = registry or BackendRegistry.with_builtin_backends()
        cred_provider = credentials or CustodyCredentialProvider()
        plan: OrdinaryWritePlan | None = None
        try:
            plan = prepare_ordinary_write(
                registry,
                descriptor,
                locator,
                fact,
                credentials=cred_provider.for_write(target_path),
                fact_id=id_override,
                admit_undeclared=admit_undeclared,
            )
            outcome = execute_ordinary_write(
                registry,
                descriptor,
                plan,
                after_commit=lambda head: sync_projection(registry, descriptor, through=head),
            )
        except OrdinaryWritePreparationRefused as exc:
            cause = exc.cause
            raise AdmissionFailed(
                _preparation_refusal_reason(exc),
                observer=getattr(cause, "observer", actual_observer),
                kind=getattr(cause, "kind", fact.kind),
                vertex=getattr(cause, "vertex", exc.effective_declaration.name),
            ) from exc
        except SdkError:
            raise
        except Exception as exc:
            from .errors import normalize_exception

            context = (
                None
                if plan is None
                else {
                    "captured_head": plan.captured_head,
                    "fact_id": plan.fact_id,
                    "tick_id": plan.tick_id,
                }
            )
            normalized = normalize_exception(exc, context=context)
            if normalized is not exc:
                raise normalized from exc
            raise EmissionFailed(f"fact emission failed: {exc}") from exc

        assert plan is not None
        fact_draft = next((draft for draft in plan.drafts if draft.kind == "fact"), None)
        tick_draft = next((draft for draft in plan.drafts if draft.kind == "tick"), None)
        return EmitReceipt(
            write_path="arrival",
            store=StoreDescriptorInfo.from_descriptor(descriptor),
            id=outcome.fact_id,
            stored=not plan.already_present,
            signed=(None if fact_draft is None else fact_draft.body.get("signature") is not None),
            observer=actual_observer,
            tick_mark=(None if tick_draft is None else str(tick_draft.body["name"])),
            tick_id=outcome.tick_id,
            state_change=None,
            affected_sections=[],
            delta_count=None,
            predicted_state_change=False,
            captured_head=plan.captured_head,
            commit=outcome.commit,
            witnessed=None if plan.already_present else True,
            projection=outcome.projection.value,
        )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"emit_fact requires a .vertex target, got {info.target_type}")

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
        tick_mark, tick_id = _tick_fields(receipt.tick, result.change)

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
    registry: BackendRegistry | None = None,
) -> BatchEmitResult:
    """Emit multiple facts and return explicit batch atomicity evidence.

    Parameters:
        target: Path to the target .vertex file.
        facts: List of Fact atoms, (kind, payload) tuples, or fact dict mappings.
        observer: Default observer identity for items omitting one.
        origin: Default provenance origin for items omitting one.
        credentials: Key provider for signing emissions.
        admit_undeclared: Explicit default for items without their own mapping flag.

    Returns:
        One uniform result containing ordered item receipts and any shared commit.
    """
    prepared_items: list[tuple[Fact, str | None, bool]] = []
    for item in facts:
        item_id_override = None
        item_admit_undeclared = admit_undeclared
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
            try:
                p = dict(item.get("payload", {}))
            except (TypeError, ValueError) as exc:
                raise InvalidEmissionRequest(
                    "batch item 'payload' must be convertible to a dictionary"
                ) from exc
            item_obs = (
                str(item["observer"]) if "observer" in item and item["observer"] else observer
            )
            if not item_obs:
                raise InvalidEmissionRequest("observer is required for dict fact")
            item_origin = str(item.get("origin", origin))
            try:
                item_ts = (
                    float(item["ts"])
                    if "ts" in item and item["ts"] is not None
                    else datetime.now(UTC).timestamp()
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise InvalidEmissionRequest(
                    "batch item 'ts' must be convertible to a timestamp"
                ) from exc
            if "id" in item and item["id"]:
                item_id_override = str(item["id"])
            if "admit_undeclared" in item:
                explicit_admit = item["admit_undeclared"]
                if not isinstance(explicit_admit, bool):
                    raise InvalidEmissionRequest("batch item 'admit_undeclared' must be a boolean")
                item_admit_undeclared = explicit_admit
            f = Fact(
                kind=k,
                ts=item_ts,
                payload=p,
                observer=item_obs,
                origin=item_origin,
            )
        else:
            raise InvalidEmissionRequest(f"unsupported batch fact item shape: {item}")
        prepared_items.append((f, item_id_override, item_admit_undeclared))

    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=target_path)
    if arrival is not None:
        from engine.arrival_contract import NotAuthority, Profile
        from engine.arrival_maintenance import sync_projection
        from engine.runtime_write import (
            BatchFactInput,
            BatchWritePlan,
            execute_batch_write,
            prepare_batch_write,
        )

        _path, locator, descriptor = arrival
        if descriptor.role is not Profile.AUTHORITY:
            from .errors import normalize_exception

            refused = normalize_exception(
                NotAuthority("batch writes require an Authority descriptor role")
            )
            raise refused
        store = StoreDescriptorInfo.from_descriptor(descriptor)
        if not prepared_items:
            return BatchEmitResult(
                write_path="arrival",
                store=store,
                atomic=True,
                atomicity="empty-noop",
                witnessed=None,
                projection="not-requested",
            )
        registry = registry or BackendRegistry.with_builtin_backends()
        cred_provider = credentials or CustodyCredentialProvider()
        plan: BatchWritePlan | None = None
        try:
            plan = prepare_batch_write(
                registry,
                descriptor,
                locator,
                tuple(
                    BatchFactInput(
                        fact,
                        fact_id=item_id,
                        admit_undeclared=item_admit,
                    )
                    for fact, item_id, item_admit in prepared_items
                ),
                credentials=cred_provider.for_write(target_path),
            )
            outcome = execute_batch_write(
                registry,
                descriptor,
                plan,
                after_commit=lambda head: sync_projection(registry, descriptor, through=head),
            )
        except SdkError:
            raise
        except Exception as exc:
            from .errors import normalize_exception

            context = None
            if plan is not None:
                context = {
                    "captured_head": plan.captured_head,
                    "fact_ids": tuple(item.fact_id for item in plan.items),
                    "tick_ids": tuple(
                        item.tick_id for item in plan.items if item.tick_id is not None
                    ),
                    "items": plan.items,
                }
            normalized = normalize_exception(exc, context=context)
            if normalized is not exc:
                raise normalized from exc
            raise EmissionFailed(f"batch emission failed: {exc}") from exc

        assert plan is not None
        signed_by_id: dict[str, bool] = {}
        for draft in plan.drafts:
            if draft.kind == "fact":
                signed_by_id[str(draft.body["id"])] = draft.body.get("signature") is not None
            elif draft.kind == "batch":
                for row in draft.body["rows"]:
                    signed_by_id[str(row["id"])] = row.get("signature") is not None
        item_receipts = [
            EmitReceipt(
                write_path="arrival",
                store=store,
                id=item_result.fact_id,
                stored=not item_result.already_present,
                signed=signed_by_id.get(item_result.fact_id),
                observer=prepared[0].observer,
                tick_mark=item_result.tick_name,
                tick_id=item_result.tick_id,
                state_change=None,
                affected_sections=[],
                delta_count=None,
                predicted_state_change=False,
                captured_head=plan.captured_head,
                commit=None,
                witnessed=None if item_result.already_present else True,
                projection=(
                    "not-requested" if item_result.already_present else outcome.projection.value
                ),
            )
            for prepared, item_result in zip(prepared_items, outcome.items, strict=True)
        ]
        return BatchEmitResult(
            write_path="arrival",
            store=store,
            items=item_receipts,
            atomic=True,
            atomicity=("idempotent-noop" if outcome.commit is None else "single-append"),
            captured_head=plan.captured_head,
            commit=outcome.commit,
            witnessed=None if outcome.commit is None else True,
            projection=outcome.projection.value,
        )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"emit_batch requires a .vertex target, got {info.target_type}")

    if not prepared_items:
        return BatchEmitResult(
            write_path="legacy",
            atomic=True,
            atomicity="empty-noop",
        )

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
        for index, (f, item_id_override, item_admit) in enumerate(prepared_items):
            try:
                result = handle.receive_as(
                    f,
                    id_override=item_id_override,
                    admit_undeclared=item_admit,
                )
                r = result.receipt
                signed = r.attestation.signed if r.attestation is not None else None
                tick_mark, tick_id = _tick_fields(r.tick, result.change)

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
            except AdmissionError as exc:
                failure: BaseException = AdmissionFailed(
                    str(exc),
                    observer=getattr(exc, "observer", observer),
                    kind=getattr(exc, "kind", None),
                    vertex=getattr(exc, "vertex", None),
                )
            except ReceiveCommittedError as exc:
                failure = CommittedEmissionError(str(exc), fact_id=exc.fact_id)
            except SdkValueError as exc:
                failure = exc
            except Exception as exc:
                failure = EmissionFailed(f"batch emission failed: {exc}")
            else:
                continue

            committed_fact_id = (
                failure.fact_id if isinstance(failure, CommittedEmissionError) else None
            )
            if receipts or committed_fact_id is not None:
                raise LegacyBatchPartialFailure(
                    "legacy sequential batch stopped after an observable prefix; "
                    "inspect retained item receipts before retrying",
                    failed_index=index,
                    items=receipts,
                    cause=failure,
                    committed_fact_id=committed_fact_id,
                ) from failure
            raise failure
        return BatchEmitResult(
            write_path="legacy",
            items=receipts,
            atomic=False,
            atomicity="legacy-sequential",
        )
    finally:
        handle.close()
