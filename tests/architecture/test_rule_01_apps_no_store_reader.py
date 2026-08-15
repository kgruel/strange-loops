"""Rule 1: Apps don't import StoreReader."""

from __future__ import annotations

from ._helpers import (
    REPO_ROOT,
    _check_exceptions,
    _collect_imports,
    _imports_symbol,
    _rel,
    _src_py_files,
)


def test_apps_do_not_import_store_reader():
    """Apps must use vertex_read/vertex_facts, not StoreReader directly.

    The vertex is the sole read interface. StoreReader is an internal
    implementation detail of libs/engine/vertex_reader.py.
    """
    EXCEPTIONS = {
        # store inspector meta-tool — needs raw store access for introspection
        "apps/loops/src/loops/commands/store.py",
        # Accumulated while the ratchet was red (found 2026-07-16, custody
        # move) — read-path internals reaching below vertex_read/vertex_facts.
        # Shrink-only: reroute through the vertex read interface, don't add.
        "apps/loops/src/loops/commands/resolve.py",
        "apps/loops/src/loops/commands/ls.py",
        "apps/loops/src/loops/commands/vertices.py",
    }
    _check_exceptions(EXCEPTIONS)

    violations = []
    for app_dir in (REPO_ROOT / "apps").iterdir():
        if not app_dir.is_dir():
            continue
        for py_file in _src_py_files(app_dir):
            rel = _rel(py_file)
            if rel in EXCEPTIONS:
                continue
            collector = _collect_imports(py_file)
            lines = _imports_symbol(collector.runtime_symbols, "StoreReader")
            for lineno in lines:
                violations.append(f"  {rel}:{lineno}")

    assert not violations, (
        "Apps must not import StoreReader — use vertex_read/vertex_facts instead:\n"
        + "\n".join(violations)
    )
