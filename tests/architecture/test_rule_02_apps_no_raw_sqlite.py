"""Rule 2: Apps don't access raw database connections."""

from __future__ import annotations

from ._helpers import (
    REPO_ROOT,
    _collect_imports,
    _imports_module,
    _rel,
    _src_py_files,
)


def test_apps_no_raw_sqlite():
    """Apps must use the SDK, not import sqlite3 directly."""

    violations = []
    scanned = 0
    for app_dir in (REPO_ROOT / "apps").iterdir():
        if not app_dir.is_dir():
            continue
        for py_file in _src_py_files(app_dir):
            scanned += 1
            collector = _collect_imports(py_file)
            lines = _imports_module(collector.runtime_modules, "sqlite3")
            for lineno in lines:
                violations.append(f"  {_rel(py_file)}:{lineno}")

    assert scanned, "Rule 2 found no app source files"
    assert not violations, "Apps must not import sqlite3 — use the SDK:\n" + "\n".join(
        violations
    )
