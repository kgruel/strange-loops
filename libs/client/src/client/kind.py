"""Headless declaration mutation operations over Loops vertices."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.ceremony import apply_declaration_update, plan_declaration_update, recover_declaration_update
from engine.handle import CredentialProvider
from lang.ast import FoldCollect, FoldDecl, LoopDef
from lang.vertex_mutation import add_vertex_kind, edit_vertex_kind, remove_vertex_kind

from .emit import CustodyCredentialProvider
from .target import resolve_target
from .types import CeremonyFailed, KindMutationResult, TargetUnsupported

__all__ = [
    "add_kind",
    "edit_kind",
    "remove_kind",
    "recover_ceremony",
]


def _default_loop_def() -> LoopDef:
    """Least presumptive default: items collect 100."""
    return LoopDef(folds=(FoldDecl("items", FoldCollect(100)),))


def add_kind(
    target: Path | str,
    kind_name: str,
    definition: LoopDef | None = None,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
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
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"add_kind requires a .vertex target, got {info.target_type}")

    vertex_path = Path(target).resolve()
    loop_def = definition or _default_loop_def()
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = add_vertex_kind(current_text, kind_name, loop_def)
    except Exception as exc:
        raise CeremonyFailed(f"could not generate kind mutation: {exc}") from exc

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    # Re-read generation after successful apply
    from engine.declaration import declaration_generation
    gen_after = declaration_generation(vertex_path)

    return KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    )


def edit_kind(
    target: Path | str,
    kind_name: str,
    definition: LoopDef,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
) -> KindMutationResult:
    """Edit an existing loop-kind definition in a vertex and orchestrate declaration persistence."""
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"edit_kind requires a .vertex target, got {info.target_type}")

    vertex_path = Path(target).resolve()
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = edit_vertex_kind(current_text, kind_name, definition)
    except Exception as exc:
        raise CeremonyFailed(f"could not generate kind mutation: {exc}") from exc

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    from engine.declaration import declaration_generation
    gen_after = declaration_generation(vertex_path)

    return KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    )


def remove_kind(
    target: Path | str,
    kind_name: str,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
) -> KindMutationResult:
    """Remove a loop-kind definition from a vertex and orchestrate declaration persistence."""
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"remove_kind requires a .vertex target, got {info.target_type}")

    vertex_path = Path(target).resolve()
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = remove_vertex_kind(current_text, kind_name)
    except Exception as exc:
        raise CeremonyFailed(f"could not generate kind mutation: {exc}") from exc

    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    if not preview.applicable:
        raise CeremonyFailed(f"declaration update not applicable: {preview.reason}")

    result = apply_declaration_update(preview, observer=observer, credentials=cred_provider)
    if result.status not in ("applied", "noop"):
        raise CeremonyFailed(f"declaration update failed ({result.status}): {result.reason}")

    from engine.declaration import declaration_generation
    gen_after = declaration_generation(vertex_path)

    return KindMutationResult(
        status=result.status,
        reason=result.reason,
        mode=preview.mode,
        vertex_path=str(vertex_path),
        generation_before=preview.generation,
        generation_after=gen_after,
        changes=[c.as_dict() if hasattr(c, "as_dict") else str(c) for c in preview.changes],
        file_written=result.file_written,
    )


def recover_ceremony(intent_path: Path | str) -> dict[str, Any]:
    """Recover an interrupted declaration update ceremony from its .intent file."""
    outcome = recover_declaration_update(intent_path)
    return {
        "classification": outcome.classification,
        "finished": outcome.finished,
        "reason": outcome.reason,
        "intent_path": str(outcome.intent_path),
    }
