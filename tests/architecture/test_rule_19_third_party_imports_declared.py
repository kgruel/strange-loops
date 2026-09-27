"""Rule 19: Third-party and workspace-member imports must be declared in pyproject.toml.

Why: Rule 4 checks only the DAG of inter-lib imports in production src/, but does
not verify that imported modules are actually declared as dependencies in the
importing package's pyproject.toml. During Slice 4, this imports-not-declared gap
was encountered four times:
1. ckdl imported in libs/migrate/src without being declared via lang's query
2. migrate imported in apps/loops without being declared in apps/loops/pyproject.toml
3. custody imported in libs/migrate/tests without being in migrate's dev group
4. sign imported in libs/migrate/tests without being in migrate's dev group

This rule enforces the invariant:
- For every package under libs/ and apps/, every top-level module imported at runtime
  in src/ (excluding stdlib and the package's own root) must appear in that package's
  declared dependencies (pyproject.toml `[project].dependencies`).
- For every package that declares a `dev` dependency group, every top-level module
  imported at runtime in tests/ (excluding stdlib, own root, and test framework builtins)
  must appear in `dependencies` or `[dependency-groups].dev`.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from ._helpers import (
    REPO_ROOT,
    _collect_imports,
    _rel,
    _src_py_files,
)

_STDLIB_MODULES = frozenset(sys.stdlib_module_names)

# Map known distribution names to their top-level import module names.
_DIST_TO_MODULES: dict[str, set[str]] = {
    "python_ulid": {"ulid"},
    "python-ulid": {"ulid"},
    "pyjwt": {"jwt"},
    "pyyaml_ft": {"yaml"},
    "pyyaml-ft": {"yaml"},
    "pyyaml": {"yaml"},
    "typing_extensions": {"typing_extensions"},
    "typing-extensions": {"typing_extensions"},
    "rfc8785": {"rfc8785"},
    "pytest_cov": {"pytest_cov"},
    "pytest-cov": {"pytest_cov"},
    "pytest_asyncio": {"pytest_asyncio"},
    "pytest-asyncio": {"pytest_asyncio"},
    "linkify_it_py": {"linkify_it"},
    "markdown_it_py": {"markdown_it"},
    "mdit_py_plugins": {"mdit_py_plugins"},
}

# Enumerable, shrink-only allowlist for legitimate structural exceptions.
# Every entry must document why it is necessary.
_ALLOWLIST: set[tuple[str, str]] = {
    # atoms.testing ships shared Hypothesis strategies for downstream libs' test suites
    # (numpy.testing pattern, same exception as Rule 6); hypothesis is declared in atoms's
    # dev group rather than production dependencies.
    ("libs/atoms/src/atoms/testing/strategies.py", "hypothesis"),
    # lang.testing ships shared Hypothesis strategies for downstream libs' test suites;
    # hypothesis is declared in lang's dev group rather than production dependencies.
    ("libs/lang/src/lang/testing/strategies.py", "hypothesis"),
}


def _normalize_dep(dep_str: str) -> set[str]:
    """Extract top-level module names from a dependency requirement string."""
    m = re.match(r"^([a-zA-Z0-9_\-\.]+)", dep_str)
    if not m:
        return {dep_str}
    raw = m.group(1).lower()
    if raw in _DIST_TO_MODULES:
        return _DIST_TO_MODULES[raw]
    norm = raw.replace("-", "_")
    if norm in _DIST_TO_MODULES:
        return _DIST_TO_MODULES[norm]
    return {norm}


def _get_package_declared_modules(pkg_dir: Path, include_dev: bool = False) -> set[str]:
    """Extract all declared module names from a package's pyproject.toml."""
    pyproject = pkg_dir / "pyproject.toml"
    if not pyproject.exists():
        return set()
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    deps = data.get("project", {}).get("dependencies", [])
    declared: set[str] = set()
    for d in deps:
        declared.update(_normalize_dep(d))
    if include_dev:
        dev_deps = data.get("dependency-groups", {}).get("dev", [])
        for d in dev_deps:
            declared.update(_normalize_dep(d))
    return declared


def _test_py_files(pkg_dir: Path) -> list[Path]:
    """All .py files under pkg_dir/tests/, skipping __pycache__."""
    tests_dir = pkg_dir / "tests"
    if not tests_dir.is_dir():
        return []
    return [p for p in tests_dir.rglob("*.py") if "__pycache__" not in p.parts]


def _package_dirs(repo: Path) -> list[Path]:
    """Discover package directories, not import names or a particular app."""
    return [
        package
        for parent in ("libs", "apps")
        for package in sorted((repo / parent).iterdir())
        if package.is_dir() and not package.name.startswith(".")
    ]


def test_package_discovery_includes_new_apps(tmp_path: Path):
    expected = [tmp_path / "libs" / "core", tmp_path / "apps" / "fresh-client"]
    for package in expected:
        package.mkdir(parents=True)
    (tmp_path / "apps" / ".cache").mkdir()
    (tmp_path / "apps" / "README.md").write_text("not a package")
    assert _package_dirs(tmp_path) == expected


def test_third_party_and_interpackage_imports_declared():
    """Every imported module must appear in pyproject.toml declared dependencies."""
    packages = _package_dirs(REPO_ROOT)
    violations: list[str] = []
    scanned = 0

    for pkg_dir in packages:
        if not pkg_dir.is_dir():
            continue
        pkg_name = pkg_dir.name

        # Determine own root module names in src/
        src_dir = pkg_dir / "src"
        own_modules: set[str] = set()
        if src_dir.is_dir():
            for item in src_dir.iterdir():
                if not item.name.startswith((".", "_")):
                    own_modules.add(item.stem if item.is_file() else item.name)

        src_declared = _get_package_declared_modules(pkg_dir, include_dev=False)
        test_declared = _get_package_declared_modules(pkg_dir, include_dev=True)
        test_declared.add("pytest")
        test_declared.add("_pytest")

        # 1. Check production src/ against [project].dependencies
        for py_file in _src_py_files(pkg_dir):
            scanned += 1
            rel = _rel(py_file)
            collector = _collect_imports(py_file)
            for mod, lineno in collector.runtime_modules:
                top = mod.split(".")[0]
                if top in _STDLIB_MODULES or top in own_modules:
                    continue
                if (rel, top) in _ALLOWLIST:
                    continue
                if top not in src_declared:
                    violations.append(
                        f"  {rel}:{lineno} — {pkg_name} imports {top!r} "
                        f"(undeclared in {pkg_name}/pyproject.toml dependencies)"
                    )

        # 2. Check tests/ against dependencies + dev group (if dev group declared)
        pyproject = pkg_dir / "pyproject.toml"
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            if data.get("dependency-groups", {}).get("dev"):
                for py_file in _test_py_files(pkg_dir):
                    rel = _rel(py_file)
                    collector = _collect_imports(py_file)
                    for mod, lineno in collector.runtime_modules:
                        top = mod.split(".")[0]
                        if (
                            top in _STDLIB_MODULES
                            or top in own_modules
                            or top in ("tests", "conftest", "test_read", "_fixtures")
                        ):
                            continue
                        if (rel, top) in _ALLOWLIST:
                            continue
                        if top not in test_declared:
                            violations.append(
                                f"  {rel}:{lineno} — {pkg_name} tests import {top!r} "
                                f"(undeclared in {pkg_name}/pyproject.toml dependencies or dev group)"
                            )

    assert scanned, "Rule 19 found no package source files"
    assert not violations, (
        "Rule 19: Undeclared import violation (imports ⊆ declared dependencies):\n"
        + "\n".join(violations)
    )


def test_rule_19_allowlist_is_minimal():
    """Assert every entry in _ALLOWLIST corresponds to an active undeclared import violation.

    The allowlist is shrink-only: an entry must be an actual import AND must still be
    undeclared in its package dependencies (or dev group for test files). If an import is
    properly declared in pyproject.toml, its allowlist entry is redundant and fails the test.
    """
    stale: list[str] = []
    for rel_path, module in sorted(_ALLOWLIST):
        target = REPO_ROOT / rel_path
        if not target.exists():
            stale.append(f"  {rel_path}: file no longer exists")
            continue
        collector = _collect_imports(target)
        imported_tops = {m.split(".")[0] for m, _ in collector.runtime_modules}
        if module not in imported_tops:
            stale.append(f"  {rel_path}: {module!r} is no longer imported")
            continue

        parts = Path(rel_path).parts
        if len(parts) >= 2 and parts[0] in ("libs", "apps"):
            pkg_dir = REPO_ROOT / parts[0] / parts[1]
            is_test = "tests" in parts
            declared = _get_package_declared_modules(pkg_dir, include_dev=is_test)
            if is_test:
                declared.add("pytest")
                declared.add("_pytest")
            if module in declared:
                stale.append(
                    f"  {rel_path}: {module!r} is declared in {pkg_dir.name}/pyproject.toml "
                    f"(allowlist entry is redundant and must be removed)"
                )

    assert not stale, (
        "Rule 19: Stale _ALLOWLIST entries — the import they excused is no longer a violation:\n"
        + "\n".join(stale)
    )
