"""Rule 15: Apps may import only sdk + painted."""

from __future__ import annotations

from ._helpers import (
    LIBS,
    REPO_ROOT,
    _check_exceptions,
    _collect_imports,
    _imports_module,
    _rel,
    _src_py_files,
)


def test_apps_import_only_sdk_and_painted():
    """Apps must only import from sdk and painted among the internal lib universe.

    The substrate libraries (atoms, lang, engine, store, sign, custody) must
    be composed through the sdk layer. Direct imports of substrate libraries
    by presentation applications are forbidden.

    EXCEPTIONS is a shrink-only allowlist of legacy CLI v1 modules in
    apps/loops that predate libs/sdk. As CLI v2 replaces CLI v1, this list
    shrinks to empty.
    """
    EXCEPTIONS = {
        "apps/loops/src/loops/cli/dispatch.py",
        "apps/loops/src/loops/cli/lens.py",
        "apps/loops/src/loops/cli/views/fold.py",
        "apps/loops/src/loops/cli/views/seal.py",
        "apps/loops/src/loops/cli/witness_address.py",
        "apps/loops/src/loops/commands/add.py",
        "apps/loops/src/loops/commands/devtools.py",
        "apps/loops/src/loops/commands/emit.py",
        "apps/loops/src/loops/commands/fetch.py",
        "apps/loops/src/loops/commands/identity.py",
        "apps/loops/src/loops/commands/init.py",
        "apps/loops/src/loops/commands/ls.py",
        "apps/loops/src/loops/commands/orient.py",
        "apps/loops/src/loops/commands/resolve.py",
        "apps/loops/src/loops/commands/rm.py",
        "apps/loops/src/loops/commands/store.py",
        "apps/loops/src/loops/commands/stream.py",
        "apps/loops/src/loops/commands/sync.py",
        "apps/loops/src/loops/commands/vertices.py",
        "apps/loops/src/loops/lenses/_helpers.py",
        "apps/loops/src/loops/lenses/declarations.py",
        "apps/loops/src/loops/lenses/fold.py",
        "apps/loops/src/loops/lenses/vertices.py",
        "apps/loops/src/loops/provenance.py",
        "apps/loops/src/loops/surface.py",
        "apps/loops/src/loops/tui/autoresearch_app.py",
    }
    _check_exceptions(EXCEPTIONS)

    forbidden_libs = set(LIBS) - {"sdk"}

    violations = []
    for app_dir in (REPO_ROOT / "apps").iterdir():
        if not app_dir.is_dir():
            continue
        for py_file in _src_py_files(app_dir):
            rel = _rel(py_file)
            if rel in EXCEPTIONS:
                continue
            collector = _collect_imports(py_file)
            for lib in sorted(forbidden_libs):
                for lineno in _imports_module(collector.runtime_modules, lib):
                    violations.append(
                        f"  {rel}:{lineno} — imports substrate lib {lib!r} directly; "
                        "apps must import only sdk + painted"
                    )

    assert not violations, (
        "Apps must import only sdk + painted (no direct substrate lib imports):\n"
        + "\n".join(violations)
    )
