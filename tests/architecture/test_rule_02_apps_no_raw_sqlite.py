"""Rule 2: Apps don't access raw database connections."""

from __future__ import annotations

from ._helpers import (
    REPO_ROOT,
    _check_exceptions,
    _collect_imports,
    _imports_module,
    _rel,
    _src_py_files,
)


def test_apps_no_raw_sqlite():
    """Apps must not import sqlite3 directly.

    EXCEPTIONS is a shrink-only allowlist of low-level store probes that
    predate an engine surface for them (era probe, lock-aware declaration
    probe, genesis/marker probe). New entries need the same justification:
    engine has no interface for the question being asked. TODO: dissolve
    when engine grows a probe surface (friction:sqlite-probes-in-apps).
    """
    EXCEPTIONS = {
        # store inspector meta-tool + genesis/marker probe for absorb
        "apps/loops/src/loops/commands/store.py",
        # lock-aware store-canonical declaration probe (SPEC §9.5)
        "apps/loops/src/loops/commands/resolve.py",
        # signed-era probe — era-is-a-floor guard reads the signature column
        "apps/loops/src/loops/cli/views/seal.py",
    }
    _check_exceptions(EXCEPTIONS)

    violations = []
    for app_dir in (REPO_ROOT / "apps").iterdir():
        if not app_dir.is_dir():
            continue
        for py_file in _src_py_files(app_dir):
            if _rel(py_file) in EXCEPTIONS:
                continue
            collector = _collect_imports(py_file)
            lines = _imports_module(collector.runtime_modules, "sqlite3")
            for lineno in lines:
                violations.append(f"  {_rel(py_file)}:{lineno}")

    assert not violations, (
        "Apps must not import sqlite3 — use engine's vertex read interface:\n"
        + "\n".join(violations)
    )
