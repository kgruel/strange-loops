"""Headless declaration mutation operations over Loops vertices."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engine.ceremony import (
    apply_declaration_update,
    plan_declaration_update,
    recover_declaration_update,
)
from engine.handle import CredentialProvider
from lang.ast import FoldCollect, FoldDecl, LoopDef
from lang.population import kdl_insert_child, kdl_remove_child
from lang.vertex_mutation import add_vertex_kind, edit_vertex_kind, remove_vertex_kind

from .emit import CustodyCredentialProvider
from .target import resolve_target
from .types import (
    CeremonyFailed,
    DeclarationPlanResult,
    KindMutationResult,
    SdkValueError,
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


def _kdl_quote(val: str) -> str:
    """Return a safely quoted JSON/KDL string literal."""
    return json.dumps(val)


def plan_kind_mutation(
    target: Path | str,
    op: str,
    kind_name: str,
    definition: LoopDef | None = None,
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
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(
            f"plan_kind_mutation requires a .vertex target, got {info.target_type}"
        )

    vertex_path = Path(target).resolve()
    current_text = vertex_path.read_text(encoding="utf-8")
    loop_def = definition or _default_loop_def()

    if op == "add":
        new_text = add_vertex_kind(current_text, kind_name, loop_def)
    elif op == "edit":
        new_text = edit_vertex_kind(current_text, kind_name, loop_def)
    elif op == "remove":
        new_text = remove_vertex_kind(current_text, kind_name)
    else:
        raise SdkValueError(f"unsupported mutation op '{op}', expected 'add', 'edit', or 'remove'")

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


def grant_observer(
    target: Path | str,
    observer_name: str,
    *,
    grants: Sequence[str] | None = None,
    identity: str | None = None,
    key: str | None = None,
    observer: str,
    credentials: CredentialProvider | None = None,
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
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"grant_observer requires a .vertex target, got {info.target_type}")

    vertex_path = Path(target).resolve()
    cred_provider = credentials or CustodyCredentialProvider()

    if key is None:
        from custody import ensure_signing_key

        keypair = ensure_signing_key(vertex_path, observer=observer_name)
        pub_key = keypair.public_b64
    else:
        pub_key = key

    # Safely format observer node name
    node_name = _kdl_quote(observer_name) if not observer_name.isalnum() else observer_name

    obs_lines = [f"{node_name} {{"]
    if identity:
        obs_lines.append(f"  identity {_kdl_quote(identity)}")
    if pub_key:
        obs_lines.append(f"  key {_kdl_quote(pub_key)}")
    if grants:
        grants_str = " ".join(_kdl_quote(g) for g in grants)
        obs_lines.append("  grant {")
        obs_lines.append(f"    potential {grants_str}")
        obs_lines.append("  }")
    obs_lines.append("}")
    obs_kdl = "\n".join(obs_lines)

    import contextlib

    current_text = vertex_path.read_text(encoding="utf-8")
    if "observers {" not in current_text:
        current_text = current_text + "\nobservers {\n}\n"

    with contextlib.suppress(Exception):
        current_text = kdl_remove_child(current_text, ["observers"], observer_name)

    try:
        new_text = kdl_insert_child(current_text, ["observers"], obs_kdl)
    except Exception as exc:
        raise CeremonyFailed(f"could not splice observer grant: {exc}") from exc

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


def revoke_observer(
    target: Path | str,
    observer_name: str,
    *,
    observer: str,
    credentials: CredentialProvider | None = None,
) -> KindMutationResult:
    """Remove an observer from the vertex's declared admission block via ceremony."""
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(
            f"revoke_observer requires a .vertex target, got {info.target_type}"
        )

    vertex_path = Path(target).resolve()
    cred_provider = credentials or CustodyCredentialProvider()

    current_text = vertex_path.read_text(encoding="utf-8")
    try:
        new_text = kdl_remove_child(current_text, ["observers"], observer_name)
    except Exception as exc:
        raise CeremonyFailed(f"could not remove observer '{observer_name}': {exc}") from exc

    # If observers block is now empty, clean up the block
    new_text = re.sub(r"observers\s*\{\s*\}\n?", "", new_text)

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
