"""Declaration inspection and vertex scaffolding operations."""

from __future__ import annotations

from pathlib import Path

from engine.declaration import load_declaration_status
from engine.probe import probe_target
from lang.loader import parse_vertex_file

from .types import (
    DeclarationInspectionResult,
    InitVertexResult,
    SdkValueError,
    TargetError,
    TargetNotFound,
)

__all__ = ["init_vertex", "inspect_declaration"]


def init_vertex(
    target: Path | str,
    *,
    name: str | None = None,
    store_type: str = "sqlite",
    store_path: str | Path | None = None,
    is_root: bool = False,
    observer: str | None = None,
    strict: bool = False,
    overwrite: bool = False,
) -> InitVertexResult:
    """Scaffold a new Loops .vertex declaration file.

    Parameters:
        target: Target .vertex file path to create.
        name: Name of the vertex (defaults to target file stem).
        store_type: Backing store format ('sqlite' or 'jsonl').
        store_path: Custom store path (defaults to .loops/data/<name>.db or .jsonl).
        is_root: If True, scaffolds an aggregate root discovery vertex.
        observer: Initial observer identity to register.
        strict: If True, declares 'strict true'.
        overwrite: If True, overwrites existing file.

    Returns:
        InitVertexResult detailing the created vertex file and storage paths.
    """
    vertex_path = Path(target).resolve()
    if vertex_path.exists() and not overwrite:
        raise TargetError(f"vertex file already exists: {vertex_path}")

    v_name = name or vertex_path.stem

    if is_root:
        content = (
            f'name "{v_name}"\n'
            "// Root vertex — discovers all .vertex files under this directory\n"
            'discover "./**/*.vertex"\n'
        )
        resolved_store = None
    else:
        ext = ".jsonl" if store_type.lower() == "jsonl" else ".db"
        default_store = f".loops/data/{v_name}{ext}"
        resolved_store = str(store_path) if store_path is not None else default_store

        lines = [f'name "{v_name}"', f'store "{resolved_store}"']
        if strict:
            lines.append("strict true")
        lines.append("")

        if observer:
            # Ensure keypair exists for initial observer
            from custody import ensure_signing_key

            keypair = ensure_signing_key(vertex_path, observer=observer)
            lines.append("observers {")
            lines.append(f"  {observer} {{")
            lines.append(f'    key "{keypair.public_b64}"')
            lines.append("  }")
            lines.append("}")
            lines.append("")

        lines.append("loops {")
        lines.append("  item {")
        lines.append("    fold {")
        lines.append('      items "collect" 100')
        lines.append("    }")
        lines.append("  }")
        lines.append("}")
        lines.append("")
        content = "\n".join(lines)

    # Ensure parent directory exists
    vertex_path.parent.mkdir(parents=True, exist_ok=True)
    vertex_path.write_text(content, encoding="utf-8")

    return InitVertexResult(
        target_path=str(vertex_path),
        name=v_name,
        store_path=resolved_store,
        store_type=store_type,
        is_root=is_root,
        file_written=True,
    )


def inspect_declaration(target: Path | str) -> DeclarationInspectionResult:
    """Deeply inspect and validate a .vertex declaration without side effects.

    Parameters:
        target: Path to the .vertex file.

    Returns:
        DeclarationInspectionResult containing AST metadata, admission rules, and syntax health.
    """
    path = Path(target).resolve()
    if not path.exists():
        raise TargetNotFound(f"target path does not exist: {path}")

    probe = probe_target(path)
    if probe.target_type != "vertex":
        raise SdkValueError(
            f"inspect_declaration requires a .vertex target, got {probe.target_type}"
        )

    errors: list[str] = []
    syntax_valid = True
    file_ast = None
    try:
        file_ast = parse_vertex_file(path)
    except Exception as exc:
        syntax_valid = False
        errors.append(str(exc))

    decl_status = None
    if syntax_valid:
        try:
            decl_ast, decl_status = load_declaration_status(path)
        except Exception as exc:
            errors.append(str(exc))

    v_name = getattr(file_ast, "name", path.stem) if file_ast else path.stem
    store_mode = probe.canonical_mode
    store_path = str(probe.canonical_path) if probe.canonical_path else None

    declared_kinds: list[str] = []
    declared_observers: list[str] = []
    cadence_ticks: list[str] = []
    strict = False
    is_aggregate = False

    if file_ast is not None:
        if hasattr(file_ast, "loops") and file_ast.loops:
            declared_kinds = sorted(file_ast.loops.keys())
        if hasattr(file_ast, "observers") and file_ast.observers:
            declared_observers = sorted([o.name for o in file_ast.observers])
        if hasattr(file_ast, "cadence") and file_ast.cadence:
            cadence_ticks = sorted([t.name for t in file_ast.cadence])
        strict = getattr(file_ast, "strict", False)
        is_aggregate = (
            getattr(file_ast, "combine", None) is not None
            or getattr(file_ast, "discover", None) is not None
        )

    return DeclarationInspectionResult(
        target_path=str(path),
        name=v_name,
        status=decl_status or "uninitialized",
        store_mode=store_mode,
        store_path=store_path,
        declared_kinds=declared_kinds,
        declared_observers=declared_observers,
        cadence_ticks=cadence_ticks,
        strict=strict,
        is_aggregate=is_aggregate,
        syntax_valid=syntax_valid,
        errors=errors,
    )
