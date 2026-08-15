"""Rule 6: atoms has zero external runtime dependencies."""

from __future__ import annotations

import sys

from ._helpers import (
    REPO_ROOT,
    _collect_imports,
    _rel,
    _src_py_files,
)

_STDLIB_MODULES = frozenset(sys.stdlib_module_names)


def test_atoms_stdlib_only():
    """atoms must only import stdlib modules at runtime.

    atoms is the foundational data layer — zero external dependencies
    keeps it portable and fast to import.
    """
    violations = []
    atoms_dir = REPO_ROOT / "libs" / "atoms"
    for py_file in _src_py_files(atoms_dir):
        collector = _collect_imports(py_file)
        # Sole exception: atoms.testing ships shared Hypothesis strategies for
        # downstream libs' test suites (numpy.testing pattern). It may import
        # hypothesis and nothing else non-stdlib; the atoms runtime API never
        # imports atoms.testing.
        in_testing = "atoms/testing/" in _rel(py_file)
        for module, lineno in collector.runtime_modules:
            top_level = module.split(".")[0]
            # Allow intra-package imports (atoms.*)
            if top_level == "atoms":
                continue
            if in_testing and top_level == "hypothesis":
                continue
            if top_level not in _STDLIB_MODULES:
                violations.append(f"  {_rel(py_file)}:{lineno} imports {module}")

    assert not violations, (
        "atoms must only import stdlib — no external dependencies:\n"
        + "\n".join(violations)
    )
