"""Rule 7: sqlite3 confined to engine and store."""

from __future__ import annotations

from ._helpers import (
    REPO_ROOT,
    _collect_imports,
    _imports_module,
    _rel,
    _src_py_files,
)

_SQLITE_ALLOWED_LIBS = {"engine", "store"}


def test_sqlite3_confined_to_engine_store():
    """Only engine and store may import sqlite3.

    atoms, lang, and painted have no business touching the database.
    Database access flows through engine's vertex interface.
    """
    violations = []
    for lib_dir in (REPO_ROOT / "libs").iterdir():
        if not lib_dir.is_dir():
            continue
        lib_name = lib_dir.name
        if lib_name in _SQLITE_ALLOWED_LIBS:
            continue
        for py_file in _src_py_files(lib_dir):
            collector = _collect_imports(py_file)
            lines = _imports_module(collector.runtime_modules, "sqlite3")
            for lineno in lines:
                violations.append(f"  {_rel(py_file)}:{lineno} — {lib_name} imports sqlite3")

    assert not violations, (
        "Only engine and store may import sqlite3:\n"
        + "\n".join(violations)
    )
