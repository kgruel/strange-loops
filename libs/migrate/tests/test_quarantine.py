"""Quarantine ratchet guarding the freeze window against forbidden legacy imports.

This ratchet guards the freeze window until slice 5 deletes those modules, at which point
it dissolves (construction supersedes detection) — slice 5's residue sweep removes it.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "engine.jsonl_codec",
        "engine.jsonl_store",
        "store.rebirth",
        "store._conn",
    }
)


def _collect_imported_names(py_path: Path) -> list[tuple[int, str]]:
    """Parse a python file with ast and extract all imported module names."""
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                full = f"{mod}.{alias.name}" if mod else alias.name
                imports.append((node.lineno, full))
                if mod:
                    imports.append((node.lineno, mod))
    return imports


def test_quarantine_no_forbidden_legacy_imports() -> None:
    """Walk every module under libs/migrate/src and assert none imports forbidden modules."""
    src_dir = Path(__file__).resolve().parent.parent / "src"
    py_files = sorted(src_dir.rglob("*.py"))
    assert py_files, f"No python files found in {src_dir}"

    violations: list[str] = []
    for py_file in py_files:
        imported = _collect_imported_names(py_file)
        for lineno, name in imported:
            for forbidden in FORBIDDEN_MODULES:
                if name == forbidden or name.startswith(f"{forbidden}."):
                    rel = py_file.relative_to(src_dir)
                    violations.append(f"{rel}:{lineno} imports forbidden legacy module {forbidden!r} ({name})")

    assert not violations, (
        "Quarantine ratchet violation: forbidden legacy imports detected under libs/migrate/src:\n"
        + "\n".join(violations)
    )
