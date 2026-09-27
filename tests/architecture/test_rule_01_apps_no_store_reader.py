"""Rule 1: Apps don't import StoreReader."""

from __future__ import annotations

from ._helpers import (
    REPO_ROOT,
    _collect_imports,
    _imports_symbol,
    _rel,
    _src_py_files,
)


def test_apps_do_not_import_store_reader():
    """Apps must use SDK reads, not StoreReader directly.

    The vertex is the sole read interface. StoreReader is an internal
    implementation detail of libs/engine/vertex_reader.py.
    """
    violations = []
    scanned = 0
    for app_dir in (REPO_ROOT / "apps").iterdir():
        if not app_dir.is_dir():
            continue
        for py_file in _src_py_files(app_dir):
            scanned += 1
            rel = _rel(py_file)
            collector = _collect_imports(py_file)
            lines = _imports_symbol(collector.runtime_symbols, "StoreReader")
            for lineno in lines:
                violations.append(f"  {rel}:{lineno}")

    assert scanned, "Rule 1 found no app source files"
    assert not violations, (
        "Apps must not import StoreReader — use SDK reads instead:\n"
        + "\n".join(violations)
    )
