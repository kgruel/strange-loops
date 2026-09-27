"""Rule 15: Apps access substrate libraries only through the SDK."""

from __future__ import annotations

from ._helpers import (
    LIBS,
    REPO_ROOT,
    _collect_imports,
    _imports_module,
    _rel,
    _src_py_files,
)


def test_apps_import_substrate_only_through_sdk():
    """No direct substrate imports, including the offline migration sidecar.

    Presentation libraries are outside this internal-lib rule. All legacy
    frontend exceptions retired with apps/loops; there is no bypass list.
    """
    forbidden_libs = set(LIBS) - {"sdk"}
    violations = []
    scanned = 0
    for app_dir in (REPO_ROOT / "apps").iterdir():
        if not app_dir.is_dir():
            continue
        for py_file in _src_py_files(app_dir):
            scanned += 1
            collector = _collect_imports(py_file)
            for lib in sorted(forbidden_libs):
                for lineno in _imports_module(collector.runtime_modules, lib):
                    violations.append(
                        f"  {_rel(py_file)}:{lineno} — imports substrate lib {lib!r} directly"
                    )

    assert scanned, "Rule 15 found no app source files"
    assert not violations, (
        "Apps must compose substrate libraries through the SDK:\n"
        + "\n".join(violations)
    )
