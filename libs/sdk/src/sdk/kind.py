"""Headless declaration mutation operations over Loops vertices."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from engine.arrival_registry import BackendRegistry
from engine.ceremony import (
    apply_declaration_update,
    plan_declaration_update,
    recover_declaration_update,
)
from engine.credentials import CredentialProvider
from lang.ast import FoldCollect, FoldDecl, LoopDef
from lang.vertex_mutation import (
    add_vertex_kind,
    edit_vertex_kind,
    remove_vertex_kind,
    remove_vertex_observer,
    upsert_vertex_observer,
)

from .emit import CustodyCredentialProvider, _refuse_legacy_mapped_credentials
from .target import resolve_target
from .types import (
    CeremonyFailed,
    DeclarationPlanResult,
    KindMutationResult,
    SdkValueError,
    StoreDescriptorInfo,
    TargetUnsupported,
)

__all__ = [
    "add_kind",
    "edit_kind",
    "remove_kind",
    "grant_observer",
    "revoke_observer",
    "plan_kind_mutation",
    "recover_ceremony",
]


def _default_loop_def() -> LoopDef:
    """Least presumptive default: items collect 100."""
    return LoopDef(folds=(FoldDecl("items", FoldCollect(100)),))


def _arrival_descriptor_for(vertex_path: Path):
    from .target import _arrival_descriptor

    return _arrival_descriptor(vertex_path)


def _legacy_result(result: KindMutationResult):
    from .declare import DeclarationEditResult

    return DeclarationEditResult(
        status=result.status,
        reason=result.reason,
        mode=result.mode,
        vertex_path=result.vertex_path,
        target_path=result.vertex_path,
        read_path="legacy",
        generation_before=result.generation_before,
        generation_after=result.generation_after,
        changes=result.changes,
        file_written=result.file_written,
    )


def _arrival_semantic_preview(
    vertex_path: Path,
    proposed_text: str,
    *,
    registry: Any | None,
) -> DeclarationPlanResult:
    """Preview a splice only after confirming the cache matches CURRENT."""
    from engine.arrival_boundary_continuity import (
        BoundaryContinuityConflict,
        analyze_boundary_continuity,
        collect_verified_parameter_rows,
    )
    from engine.arrival_contract import TickRequest
    from engine.arrival_declarations import DeclarationPreparationRefused
    from engine.declaration import validate_arrival_runtime_identity
    from lang import diff_documents, parse_vertex, validate_vertex, vertex_to_documents

    from .declare import DeclarationPreviewResult
    from .errors import normalize_exception
    from .read import _arrival_declaration, _open_arrival_read

    resolved = _arrival_descriptor_for(vertex_path)
    if resolved is None:
        raise TargetUnsupported(f"not an explicit Arrival target: {vertex_path}")
    _path, locator_ast, descriptor = resolved
    active = registry or BackendRegistry.with_builtin_backends()
    try:
        local_ast = parse_vertex(vertex_path.read_text(encoding="utf-8"), path=vertex_path)
        with _open_arrival_read(resolved, registry=active) as (_locator, _descriptor, opened):
            effective_ast, _status, _facts, _lineage = _arrival_declaration(
                locator_ast, vertex_path, opened
            )
            local_docs = [doc.as_json() for doc in vertex_to_documents(local_ast)]
            effective_docs = [doc.as_json() for doc in vertex_to_documents(effective_ast)]
            if local_docs != effective_docs:
                return DeclarationPreviewResult(
                    applicable=False,
                    reason="declaration cache differs from CURRENT Arrival history",
                    mode="arrival-semantic-preview",
                    vertex_path=str(vertex_path),
                    generation_before={"captured_head": opened.basis.captured_head},
                    changes=[],
                    store=StoreDescriptorInfo.from_descriptor(descriptor),
                    basis=asdict(opened.basis),
                    captured_head={
                        "lineage": opened.basis.captured_head.lineage,
                        "ordinal": opened.basis.captured_head.ordinal,
                        "record_hash": opened.basis.captured_head.record_hash,
                    },
                    lineage=opened.basis.lineage,
                )
            proposed_ast = parse_vertex(proposed_text, path=vertex_path)
            validate_vertex(proposed_ast)
            validate_arrival_runtime_identity(
                proposed_ast.name, proposed_ast.loops, refusal=DeclarationPreparationRefused
            )
            proposed_docs = [
                doc.as_json() for doc in vertex_to_documents(proposed_ast)
            ]
            changes = diff_documents(local_docs, proposed_docs)
            try:
                verified_params = collect_verified_parameter_rows(
                    opened.snapshot.declaration_anchor,
                    _facts,
                    target_documents=proposed_docs,
                    base_dir=vertex_path.parent,
                )
                analyze_boundary_continuity(
                    opened.snapshot.declaration_anchor,
                    _facts,
                    opened.snapshot.ticks(TickRequest(since=float("-inf"))),
                    target_documents=proposed_docs,
                    verified_params=verified_params,
                )
            except BoundaryContinuityConflict as conflict:
                refusal = DeclarationPreparationRefused(
                    f"boundary continuity refuses declaration preview: {conflict}",
                    coordinator_phase="prepare",
                    effects={
                        "custody": {
                            "attempt": "not-entered",
                            "state": "not-attempted",
                        }
                    },
                    captured_head=opened.basis.captured_head,
                )
                raise refusal from conflict
            return DeclarationPreviewResult(
                applicable=True,
                reason="semantic preview only; signed execution requires observer credentials",
                mode="arrival-semantic-preview",
                vertex_path=str(vertex_path),
                generation_before={"captured_head": opened.basis.captured_head},
                changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in changes],
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                basis=asdict(opened.basis),
                captured_head={
                    "lineage": opened.basis.captured_head.lineage,
                    "ordinal": opened.basis.captured_head.ordinal,
                    "record_hash": opened.basis.captured_head.record_hash,
                },
                lineage=opened.basis.lineage,
            )
    except Exception as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc


def plan_kind_mutation(
    target: Path | str,
    op: str,
    kind_name: str,
    definition: LoopDef | None = None,
    *,
    registry: BackendRegistry | None = None,
) -> DeclarationPlanResult:
    """Dry-run preview of a proposed kind declaration mutation.

    Parameters:
        target: Path to the .vertex file.
        op: Operation type ('add', 'edit', or 'remove').
        kind_name: The name of the kind to mutate.
        definition: LoopDef AST node (for add/edit).

    Returns:
        DeclarationPlanResult with proposed changes and applicability status.
    """
    vertex_path = Path(target).resolve()
    if _arrival_descriptor_for(vertex_path) is not None:
        from .declare import DeclarationPreviewResult

        loop_def = definition or _default_loop_def()
        current_text = vertex_path.read_text(encoding="utf-8")
        try:
            if op == "add":
                new_text = add_vertex_kind(current_text, kind_name, loop_def)
            elif op == "edit":
                new_text = edit_vertex_kind(current_text, kind_name, loop_def)
            elif op == "remove":
                new_text = remove_vertex_kind(current_text, kind_name)
            else:
                raise SdkValueError(
                    f"unsupported mutation op '{op}', expected 'add', 'edit', or 'remove'"
                )
        except SdkValueError:
            raise
        except ValueError as exc:
            return DeclarationPreviewResult(
                applicable=False, reason=str(exc), mode="refused",
                vertex_path=str(vertex_path), generation_before=None, changes=[],
            )
        return _arrival_semantic_preview(vertex_path, new_text, registry=registry)

    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(
            f"plan_kind_mutation requires a .vertex target, got {info.target_type}"
        )

    vertex_path = Path(target).resolve()
    current_text = vertex_path.read_text(encoding="utf-8")
    loop_def = definition or _default_loop_def()

    try:
        if op == "add":
            new_text = add_vertex_kind(current_text, kind_name, loop_def)
        elif op == "edit":
            new_text = edit_vertex_kind(current_text, kind_name, loop_def)
        elif op == "remove":
            new_text = remove_vertex_kind(current_text, kind_name)
        else:
            raise SdkValueError(
                f"unsupported mutation op '{op}', expected 'add', 'edit', or 'remove'"
            )
    except SdkValueError:
        raise
    except ValueError as exc:
        # lang refused the mutation (duplicate add, missing edit/remove target, ...).
        # A plan is a preview of applicability, so a describable refusal is a
        # non-applicable plan, not an exception — the apply paths raise CeremonyFailed.
        return DeclarationPlanResult(
            applicable=False,
            reason=str(exc),
            mode="refused",
            vertex_path=str(vertex_path),
            generation_before=None,
            changes=[],
        )

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    return DeclarationPlanResult(
        applicable=preview.applicable,
        reason=preview.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
    )


def add_kind(
    target: Path | str,
    kind_name: str,
    definition: LoopDef | None = None,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
    registry: BackendRegistry | None = None,
) -> KindMutationResult:
    """Add a new loop-kind definition to a vertex and orchestrate declaration persistence.

    Parameters:
        target: Path to the .vertex file.
        kind_name: The name of the kind to add.
        definition: LoopDef AST node (defaults to items 'collect' 100).
        observer: Authorship identity performing the declaration update.
        credentials: Key provider for signing the ceremony.

    Returns:
        KindMutationResult detailing the preview, apply status, and updated generation.
    """
    vertex_path = Path(target).resolve()
    arrival = _arrival_descriptor_for(vertex_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=vertex_path)
        info = resolve_target(target)
        if info.target_type != "vertex":
            raise TargetUnsupported(f"add_kind requires a .vertex target, got {info.target_type}")
    loop_def = definition or _default_loop_def()
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = add_vertex_kind(current_text, kind_name, loop_def)
    except Exception as exc:
        if arrival is not None:
            raise SdkValueError(f"could not generate Arrival kind mutation: {exc}") from exc
        raise CeremonyFailed(f"could not generate kind mutation: {exc}") from exc

    if arrival is not None:
        from .declare import _edit_arrival_declaration

        return _edit_arrival_declaration(
            vertex_path, new_text, observer=observer, credentials=cred_provider,
            registry=registry,
            source_cache_bytes=current_text.encode("utf-8"),
            require_cache_basis=True,
        )

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    from engine.declaration import declaration_generation

    gen_after = declaration_generation(vertex_path)

    return _legacy_result(KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    ))


def edit_kind(
    target: Path | str,
    kind_name: str,
    definition: LoopDef,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
    registry: BackendRegistry | None = None,
) -> KindMutationResult:
    """Edit an existing loop-kind definition in a vertex and orchestrate declaration persistence."""
    vertex_path = Path(target).resolve()
    arrival = _arrival_descriptor_for(vertex_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=vertex_path)
        info = resolve_target(target)
        if info.target_type != "vertex":
            raise TargetUnsupported(f"edit_kind requires a .vertex target, got {info.target_type}")
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = edit_vertex_kind(current_text, kind_name, definition)
    except Exception as exc:
        if arrival is not None:
            raise SdkValueError(f"could not generate Arrival kind mutation: {exc}") from exc
        raise CeremonyFailed(f"could not generate kind mutation: {exc}") from exc

    if arrival is not None:
        from .declare import _edit_arrival_declaration

        return _edit_arrival_declaration(
            vertex_path, new_text, observer=observer, credentials=cred_provider,
            registry=registry,
            source_cache_bytes=current_text.encode("utf-8"),
            require_cache_basis=True,
        )

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    from engine.declaration import declaration_generation

    gen_after = declaration_generation(vertex_path)

    return _legacy_result(KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    ))


def remove_kind(
    target: Path | str,
    kind_name: str,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
    registry: BackendRegistry | None = None,
) -> KindMutationResult:
    """Remove a loop-kind definition from a vertex and orchestrate declaration persistence."""
    vertex_path = Path(target).resolve()
    arrival = _arrival_descriptor_for(vertex_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=vertex_path)
        info = resolve_target(target)
        if info.target_type != "vertex":
            raise TargetUnsupported(
                f"remove_kind requires a .vertex target, got {info.target_type}"
            )
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = remove_vertex_kind(current_text, kind_name)
    except Exception as exc:
        if arrival is not None:
            raise SdkValueError(f"could not generate Arrival kind mutation: {exc}") from exc
        raise CeremonyFailed(f"could not generate kind mutation: {exc}") from exc

    if arrival is not None:
        from .declare import _edit_arrival_declaration

        return _edit_arrival_declaration(
            vertex_path, new_text, observer=observer, credentials=cred_provider,
            registry=registry,
            source_cache_bytes=current_text.encode("utf-8"),
            require_cache_basis=True,
        )

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    from engine.declaration import declaration_generation

    gen_after = declaration_generation(vertex_path)

    return _legacy_result(KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    ))


def grant_observer(
    target: Path | str,
    observer_name: str,
    *,
    grants: Sequence[str] | None = None,
    identity: str | None = None,
    key: str | None = None,
    observer: str,
    credentials: CredentialProvider | None = None,
    registry: BackendRegistry | None = None,
) -> KindMutationResult:
    """Add or update an observer in the vertex's admission block via ceremony.

    Parameters:
        target: Path to the .vertex file.
        observer_name: Name of the observer to declare/grant.
        grants: List of kind names this observer is allowed to emit.
        identity: Optional backing vertex identity store name.
        key: Optional base64 public key (if omitted, ensured via custody).
        observer: Authorship identity performing the declaration update.
        credentials: Key provider for signing the ceremony.

    Returns:
        KindMutationResult detailing the applied ceremony outcome.
    """
    vertex_path = Path(target).resolve()
    arrival = _arrival_descriptor_for(vertex_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=vertex_path)
        info = resolve_target(target)
        if info.target_type != "vertex":
            raise TargetUnsupported(
                f"grant_observer requires a .vertex target, got {info.target_type}"
            )
    cred_provider = credentials or CustodyCredentialProvider()

    if key is None:
        mapped = getattr(cred_provider, "mapped", False)
        if arrival is not None and not mapped:
            # A wrapper need not expose a provider-level marker. Classify its
            # actual write configuration before the legacy custody helper can
            # mint a key for this requested observer.
            from .declare import _arrival_credentials

            mapped = _arrival_credentials(vertex_path, cred_provider).mapped
        if mapped:
            raise SdkValueError(
                "mapped observer grants require an explicitly pre-created binding public key"
            )
        from custody import ensure_signing_key

        try:
            keypair = ensure_signing_key(vertex_path, observer=observer_name)
        except ValueError as exc:
            if arrival is not None:
                raise SdkValueError(f"could not prepare Arrival observer grant: {exc}") from exc
            raise CeremonyFailed(f"could not splice observer grant: {exc}") from exc
        pub_key = keypair.public_b64
    else:
        pub_key = key

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = upsert_vertex_observer(
            current_text,
            observer_name,
            identity=identity,
            key=pub_key,
            grants=tuple(grants) if grants else (),
        )
    except Exception as exc:
        if arrival is not None:
            raise SdkValueError(f"could not generate Arrival observer grant: {exc}") from exc
        raise CeremonyFailed(f"could not splice observer grant: {exc}") from exc

    if arrival is not None:
        from .declare import _edit_arrival_declaration

        return _edit_arrival_declaration(
            vertex_path, new_text, observer=observer, credentials=cred_provider,
            registry=registry,
            source_cache_bytes=current_text.encode("utf-8"),
            require_cache_basis=True,
        )

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    from engine.declaration import declaration_generation

    gen_after = declaration_generation(vertex_path)

    return _legacy_result(KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    ))


def revoke_observer(
    target: Path | str,
    observer_name: str,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
    registry: BackendRegistry | None = None,
) -> KindMutationResult:
    """Remove an observer from the vertex's declared admission block via ceremony."""
    vertex_path = Path(target).resolve()
    arrival = _arrival_descriptor_for(vertex_path)
    if arrival is None:
        _refuse_legacy_mapped_credentials(credentials, vertex=vertex_path)
        info = resolve_target(target)
        if info.target_type != "vertex":
            raise TargetUnsupported(
                f"revoke_observer requires a .vertex target, got {info.target_type}"
            )
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = remove_vertex_observer(current_text, observer_name)
    except ValueError as exc:
        if arrival is not None:
            raise SdkValueError(f"could not generate Arrival observer removal: {exc}") from exc
        raise CeremonyFailed(f"could not remove observer '{observer_name}': {exc}") from exc

    if arrival is not None:
        from .declare import _edit_arrival_declaration

        return _edit_arrival_declaration(
            vertex_path, new_text, observer=observer, credentials=cred_provider,
            registry=registry,
            source_cache_bytes=current_text.encode("utf-8"),
            require_cache_basis=True,
        )

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    from engine.declaration import declaration_generation

    gen_after = declaration_generation(vertex_path)

    return _legacy_result(KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    ))


def recover_ceremony(
    intent_path: Path | str,
    *,
    registry: BackendRegistry | None = None,
) -> dict[str, Any]:
    """Recover an interrupted legacy or explicit Arrival ceremony."""
    try:
        import json

        intent = Path(intent_path).resolve()
        data = json.loads(intent.read_text(encoding="utf-8"))
        if data.get("schema") == "loops.engine/arrival-declaration-intent/v1":
            from .declare import recover_declaration

            return recover_declaration(intent, registry=registry).as_dict()
    except (OSError, ValueError, KeyError):
        pass
    outcome = recover_declaration_update(intent_path)
    return {
        "classification": outcome.classification,
        "finished": outcome.finished,
        "reason": outcome.reason,
        "intent_path": str(outcome.intent_path),
    }
