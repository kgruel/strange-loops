"""Architecture boundary tests — enforce dependency rules across the monorepo.

AST-based: parses source files for import statements, no runtime imports needed.
TYPE_CHECKING-aware: imports guarded by `if TYPE_CHECKING:` are excluded from
runtime rules (engine → atoms uses this pattern).

Run: uv run pytest tests/test_architecture.py -v
"""

from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

def _lib_names() -> tuple[str, ...]:
    """Every package directory under libs/, derived from the filesystem.

    Not a hand-written tuple on purpose: a hand-maintained mirror of libs/ is
    a silent pass for every lib added after it was written (docs/RATCHETS.md —
    "never hand-enumerate a mirrored structure"). Derived, a new lib enters
    Rule 4's DAG check and Rule 11's layer check the moment it exists.
    """
    libs = REPO_ROOT / "libs"
    return tuple(
        sorted(
            d.name
            for d in libs.iterdir()
            if d.is_dir() and not d.name.startswith(("_", "."))
        )
    )


LIBS = _lib_names()


def _app_names(apps: Path | None = None) -> tuple[str, ...]:
    """Top-level IMPORT names under ``apps/*/src/`` — derived, same reason as
    :func:`_lib_names`: the hand-written ``APPS`` tuple this replaces was a
    silent pass for every app added after it was written (the fifth sighting of
    the hand-enumerated-mirror shape this repo has paid for; S1's Rule 12
    derives its own roots and flagged this one on the way past). Import name,
    not directory name — ``apps/tasks`` ships ``strange_loops``.

    Every immediate ``src`` entry counts, because every one of them is
    importable once that ``src`` is on the path:

    * package directories **with or without** ``__init__.py`` — the earlier
      ``__init__.py`` requirement quietly dropped PEP 420 namespace packages
      out of ``APPS`` entirely, which took them out of Rule 3's reach too
      (sol HIGH r1: ``apps/evasion/src/nsapp/feature.py`` imported from a lib
      and the rule stayed green);
    * bare ``*.py`` modules — a single-module app is importable by its stem.

    Exclusions are by *shape*, and only where the shape makes the name
    unimportable as a top level: dot-prefixed entries (not identifiers),
    ``__dunder__`` entries (``__pycache__``, ``__init__``, ``__main__`` —
    machinery, not top-level import names), and ``*.egg-info`` build residue.

    A SINGLE leading underscore is NOT an exclusion. sol HIGH r2 §5 showed the
    r1 docstring's claim — "not names a lib could legally import" — was simply
    false: ``_nsapp`` is a legal identifier, ``import _nsapp.feature`` works,
    and the exclusion took it out of ``APPS`` and therefore out of Rule 3's
    reach. Privacy convention is not an import barrier.

    Case sensitivity is a known, unclosed edge: matching against imports is
    exact-case, so a package named ``Camel`` will not match ``import camel``.
    That resolves on case-insensitive filesystems and fails on case-sensitive
    ones, making it a platform-dependent packaging hazard rather than a
    portable evasion. Noted, not coded around — a case-folding matcher would
    create false positives on legitimately distinct names.
    """
    base = REPO_ROOT / "apps" if apps is None else apps
    if not base.is_dir():
        return ()
    names: set[str] = set()
    for app_dir in base.iterdir():
        src = app_dir / "src"
        if not src.is_dir():
            continue
        for entry in src.iterdir():
            name = entry.stem if entry.is_file() else entry.name
            if entry.name.startswith(".") or name.startswith("__"):
                continue
            if entry.is_dir() and not entry.name.endswith(".egg-info"):
                names.add(entry.name)
            elif entry.is_file() and entry.suffix == ".py":
                names.add(name)
    return tuple(sorted(names))


APPS = _app_names()


# ---------------------------------------------------------------------------
# AST import collector
# ---------------------------------------------------------------------------


class _ImportCollector(ast.NodeVisitor):
    """Collect imported module names, distinguishing TYPE_CHECKING scope.

    Tracks two separate lists per scope:
    - modules: the base module path (for _imports_module checks)
    - symbols: (module, name) pairs (for _imports_symbol checks)

    Skips relative imports (node.level > 0) since those are intra-package.
    """

    def __init__(self) -> None:
        self.runtime_modules: list[tuple[str, int]] = []  # (module, lineno)
        self.runtime_symbols: list[tuple[str, str, int]] = []  # (module, name, lineno)
        self._in_type_checking = False

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        is_tc = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if is_tc:
            prev = self._in_type_checking
            self._in_type_checking = True
            self.generic_visit(node)
            self._in_type_checking = prev
        else:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if self._in_type_checking:
            return
        for alias in node.names:
            self.runtime_modules.append((alias.name, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None or node.level > 0:
            return  # skip relative imports — intra-package, not cross-lib
        if self._in_type_checking:
            return
        self.runtime_modules.append((node.module, node.lineno))
        for alias in node.names:
            self.runtime_symbols.append((node.module, alias.name, node.lineno))


def _collect_imports(path: Path) -> _ImportCollector:
    """Parse a Python file and return its import collector."""
    collector = _ImportCollector()
    collector.visit(ast.parse(path.read_text(), filename=str(path)))
    return collector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src_py_files(root: Path) -> list[Path]:
    """All .py files under root/src/, skipping __pycache__."""
    src = root / "src"
    if not src.exists():
        return []
    return [p for p in src.rglob("*.py") if "__pycache__" not in p.parts]


def _rel(path: Path) -> str:
    """Path relative to repo root, forward slashes."""
    return str(path.relative_to(REPO_ROOT))


def _imports_module(modules: list[tuple[str, int]], module: str) -> list[int]:
    """Line numbers where any module import starts with the given prefix."""
    return [lineno for name, lineno in modules if name == module or name.startswith(module + ".")]


def _imports_symbol(symbols: list[tuple[str, str, int]], name: str) -> list[int]:
    """Line numbers where a specific symbol name was imported (e.g. 'StoreReader')."""
    return [lineno for _mod, sym, lineno in symbols if sym == name]


# ---------------------------------------------------------------------------
# Exception validation
# ---------------------------------------------------------------------------


def _check_exceptions(exceptions: set[str]) -> None:
    """Assert every exception path still exists — stale exceptions must be cleaned up."""
    for exc in exceptions:
        assert (REPO_ROOT / exc).exists(), f"Stale exception: {exc} no longer exists"


# ---------------------------------------------------------------------------
# Rule 1: Apps don't import StoreReader
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Rule 2: Apps don't access raw database connections
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Rule 3: Libs don't import from apps
# ---------------------------------------------------------------------------


def test_libs_do_not_import_apps():
    """Dependency flows libs -> apps, never apps -> libs."""
    violations = []
    for lib_dir in (REPO_ROOT / "libs").iterdir():
        if not lib_dir.is_dir():
            continue
        for py_file in _src_py_files(lib_dir):
            collector = _collect_imports(py_file)
            for app in APPS:
                lines = _imports_module(collector.runtime_modules, app)
                for lineno in lines:
                    violations.append(f"  {_rel(py_file)}:{lineno} imports {app}")

    assert APPS, (
        "APPS derived empty — Rule 3 would pass vacuously against any lib. "
        "Fix _app_names() before trusting the green."
    )
    assert not violations, (
        "Libs must not import from apps:\n" + "\n".join(violations)
    )


def _synthetic_apps_tree(tmp_path: Path, entries: dict[str, str]) -> Path:
    """Write throwaway ``apps/`` content and return the ``apps`` directory."""
    apps = tmp_path / "apps"
    for rel, body in entries.items():
        target = apps / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    return apps


def test_app_names_include_namespace_packages(tmp_path: Path):
    """sol HIGH r1: a PEP 420 namespace package was invisible to ``APPS``.

    ``apps/evasion/src/nsapp/feature.py`` with no ``nsapp/__init__.py`` is
    importable the moment that ``src`` is on the path, but the old
    ``(pkg / "__init__.py").is_file()`` filter dropped it from ``APPS`` — and
    an app absent from ``APPS`` is an app Rule 3 cannot see, so a lib importing
    it passed green. Missing ``__init__.py`` must cost visibility to nobody.
    """
    apps = _synthetic_apps_tree(
        tmp_path, {"evasion/src/nsapp/feature.py": "VALUE = 1\n"}
    )
    assert "nsapp" in _app_names(apps)


def test_app_names_include_underscore_packages(tmp_path: Path):
    """sol HIGH r2 §5: a single leading underscore is a legal identifier.

    ``apps/x/src/_nsapp/feature.py`` is importable as ``_nsapp.feature`` the
    moment that ``src`` is on the path. The r1 filter dropped it on a privacy
    convention that has no force at import time, taking the app out of Rule 3.
    ``__dunder__`` entries stay excluded — those really are machinery.
    """
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "x/src/_nsapp/feature.py": "VALUE = 1\n",
            "x/src/_solo.py": "VALUE = 1\n",
            "x/src/__pycache__/junk.py": "",
        },
    )
    assert _app_names(apps) == ("_nsapp", "_solo")


# Top-level directories under an app that are allowed to contain Python.
# `src` is the import root both derivations read; `tests` is never imported by
# libs and is not walked as a source root.
_APP_PYTHON_ROOTS = {"src", "tests"}

# Shrink-only allowlist of ADDITIONAL top-level dirs that hold Python today.
# Each is a real directory that is not an import root and not a test tree, so
# it needs to be named rather than silently tolerated by a broad rule.
_APP_PYTHON_ROOT_EXCEPTIONS: dict[str, str] = {
    "apps/tasks/scripts": (
        "standalone dev helper scripts (gen_cli_docs.py and lib/) — run "
        "directly, never imported as a package, so absent from APPS by design"
    ),
}


def _misplaced_app_python(apps: Path) -> list[str]:
    """Python under an app that is outside every sanctioned top-level directory.

    Containment, not existence. The predecessor only asked whether a directory
    NAMED ``src`` was present, which sol's HIGH r3 §6 defeated with the most
    ordinary partially-migrated state there is::

        apps/mixed/src/README.md        # src exists...
        apps/mixed/flatpkg/__init__.py  # ...but the Python is beside it
        apps/mixed/flatpkg/main.py

    ``_app_names`` returned ``()`` and the layout rule returned ``[]`` — the
    package sat outside both APPS and ``_source_roots``, exempt from Rule 3 and
    Rule 12, and the rule that existed to catch exactly that said nothing. An
    empty or docs-only ``src`` beside misplaced Python is not smuggling; it is
    what a half-finished migration looks like.
    """
    offenders: list[str] = []
    for app_dir in sorted(apps.iterdir()) if apps.is_dir() else []:
        if not app_dir.is_dir() or app_dir.name.startswith("."):
            continue
        for py in sorted(app_dir.rglob("*.py")):
            rel = py.relative_to(app_dir)
            parts = rel.parts
            # Excluded by shape, the same way _app_names excludes them: cache
            # dirs and dot/underscore-prefixed trees are not package layout.
            if any(p.startswith((".", "__")) for p in parts[:-1]):
                continue
            top = parts[0] if len(parts) > 1 else ""
            if top in _APP_PYTHON_ROOTS:
                continue
            if f"apps/{app_dir.name}/{top}" in _APP_PYTHON_ROOT_EXCEPTIONS:
                continue
            offenders.append(f"{app_dir.name}/{rel.as_posix()}")
    return offenders


def test_every_app_ships_python_under_a_sanctioned_root():
    """The ``src/`` layout is a RULE, and it is about CONTAINMENT.

    ``_app_names`` and Rule 12's ``_source_roots`` both derive from
    ``apps/*/src``. Python that lives anywhere else under an app is invisible
    to both: its packages never enter ``APPS``, so Rule 3 cannot see a lib
    importing them, and its sources are never walked for ``render=``/``piped``.

    r2 made the convention loud by requiring a ``src`` directory to EXIST;
    r3 showed that proves nothing about where the Python actually is. This
    asserts the property the derivations rely on — every ``.py`` under an app
    sits beneath a sanctioned top-level directory — so a half-migrated tree
    fails by naming the stray files rather than passing on the presence of an
    empty ``src``.
    """
    offenders = _misplaced_app_python(REPO_ROOT / "apps")
    assert not offenders, (
        f"app Python outside {sorted(_APP_PYTHON_ROOTS)} plus "
        f"{sorted(_APP_PYTHON_ROOT_EXCEPTIONS)}: {offenders}. Both APPS "
        "(Rule 3) and _source_roots (Rule 12) derive from apps/*/src — Python "
        "outside it is exempt from both by accident. Move it under src/, or "
        "add a reasoned exception if it is genuinely not an import root."
    )


def test_app_python_root_exceptions_are_real_and_reasoned():
    """The exception list is shrink-only in the same mechanical sense as the
    renderer allowlist: every entry must be a directory that still exists and
    must carry prose saying why it is not an import root."""
    for path, reason in _APP_PYTHON_ROOT_EXCEPTIONS.items():
        assert (REPO_ROOT / path).is_dir(), f"stale exception: {path}"
        assert reason and reason.strip(), f"{path} has no reason"


def test_src_layout_rule_catches_python_beside_an_existing_src(tmp_path: Path):
    """sol HIGH r3 §6, his fixture exactly: a ``src`` that exists but holds no
    Python, with a flat package beside it. The r2 existence check accepted this
    and the package stayed outside both derivations."""
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "mixed/src/README.md": "docs only\n",
            "mixed/flatpkg/__init__.py": "\n",
            "mixed/flatpkg/main.py": "VALUE = 1\n",
        },
    )
    assert _app_names(apps) == ()  # still invisible to the derivation
    assert _misplaced_app_python(apps) == [
        "mixed/flatpkg/__init__.py",
        "mixed/flatpkg/main.py",
    ]


def test_src_layout_rule_catches_a_flat_app(tmp_path: Path):
    """sol's r2 flat-layout construction, still caught: ``apps/x/nsapp/`` with
    no ``src`` at all."""
    apps = _synthetic_apps_tree(tmp_path, {"x/nsapp/__init__.py": "\n"})
    assert _app_names(apps) == ()
    assert _misplaced_app_python(apps) == ["x/nsapp/__init__.py"]


def test_src_layout_rule_catches_python_at_the_app_root(tmp_path: Path):
    """A bare module at the app root has no containing directory at all —
    the degenerate case the `len(parts) > 1` guard has to get right."""
    apps = _synthetic_apps_tree(tmp_path, {"x/setup_helper.py": "\n"})
    assert _misplaced_app_python(apps) == ["x/setup_helper.py"]


def test_src_layout_rule_accepts_the_sanctioned_roots(tmp_path: Path):
    """The floor. src/ and tests/ pass, and so do cache and dot-prefixed trees
    excluded by shape — otherwise the rule would fire on every checkout."""
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "x/src/pkg/__init__.py": "\n",
            "x/tests/test_pkg.py": "\n",
            "x/src/pkg/__pycache__/pkg.cpython-313.py": "\n",
            "x/.venv/lib/site.py": "\n",
        },
    )
    assert _misplaced_app_python(apps) == []


def test_src_layout_rule_ignores_apps_without_python(tmp_path: Path):
    """A docs-only or asset-only directory under apps/ is not an app skipping
    the layout, and must not be reported as one."""
    apps = _synthetic_apps_tree(tmp_path, {"notes/README.md": "hi\n"})
    assert _misplaced_app_python(apps) == []


def test_app_names_include_single_module_apps(tmp_path: Path):
    """The same hole one shape over: an app shipping a bare module, not a
    package. ``import solo`` works; the old derivation never listed it."""
    apps = _synthetic_apps_tree(tmp_path, {"tiny/src/solo.py": "VALUE = 1\n"})
    assert "solo" in _app_names(apps)


def test_app_names_exclude_build_residue(tmp_path: Path):
    """Over-approximation still has to stop at things no lib could import:
    ``*.egg-info`` build residue and dot/underscore entries."""
    apps = _synthetic_apps_tree(
        tmp_path,
        {
            "evasion/src/nsapp/feature.py": "VALUE = 1\n",
            "evasion/src/nsapp.egg-info/PKG-INFO": "Name: nsapp\n",
            "evasion/src/.hidden/x.py": "",
            "evasion/src/__pycache__/x.py": "",
        },
    )
    assert _app_names(apps) == ("nsapp",)


def test_rule3_catches_a_lib_importing_a_namespace_package_app(tmp_path: Path):
    """The evasion end to end: with ``nsapp`` restored to ``APPS``, the import
    predicate Rule 3 applies to every lib source file now fires on sol's
    ``libs/atoms/src/atoms/ratchet_evasion.py`` (``import nsapp.feature``)."""
    apps = _synthetic_apps_tree(
        tmp_path, {"evasion/src/nsapp/feature.py": "VALUE = 1\n"}
    )
    offender = tmp_path / "libs" / "atoms" / "src" / "atoms" / "ratchet_evasion.py"
    offender.parent.mkdir(parents=True, exist_ok=True)
    offender.write_text("import nsapp.feature\n")

    names = _app_names(apps)
    collector = _collect_imports(offender)
    hits = [
        (app, lineno)
        for app in names
        for lineno in _imports_module(collector.runtime_modules, app)
    ]
    assert hits == [("nsapp", 1)]


# ---------------------------------------------------------------------------
# Rule 4: Lib dependency DAG
# ---------------------------------------------------------------------------

# Allowed runtime imports between libs.
# Everything not listed here is forbidden.
_LIB_ALLOWED_RUNTIME: dict[str, set[str]] = {
    "atoms": set(),
    "lang": set(),
    "sign": set(),  # loops-agnostic utility — shared with vouch/pile/comms
    "store": {
        "engine",  # rebirth.py reuses tick_row_hash — chain hashing stays
                   # single-sourced; duplicating it would fork the format
    },
    "engine": {
        "lang",   # program.py, compiler.py — lang provides AST types
        "atoms",  # function-local lazy imports in compiler.py, vertex.py, program.py
    },
    "custody": {
        "sign",    # Ed25519 primitives
        "engine",  # load_declaration — store-canonical observer-key registry
    },
}


def test_lib_dependency_dag():
    """Enforce the lib dependency DAG.

    Allowed runtime: engine -> lang, engine -> atoms (function-local).
    All other cross-lib runtime imports are forbidden.
    Relative imports (intra-package) are excluded by the collector.
    """
    violations = []
    for lib_name in LIBS:
        lib_dir = REPO_ROOT / "libs" / lib_name
        if not lib_dir.is_dir():
            continue
        allowed = _LIB_ALLOWED_RUNTIME.get(lib_name, set())
        for py_file in _src_py_files(lib_dir):
            collector = _collect_imports(py_file)
            for other_lib in LIBS:
                if other_lib == lib_name:
                    continue
                if other_lib in allowed:
                    continue
                lines = _imports_module(collector.runtime_modules, other_lib)
                for lineno in lines:
                    violations.append(
                        f"  {_rel(py_file)}:{lineno} — {lib_name} imports {other_lib} at runtime"
                    )

    assert not violations, (
        "Lib dependency DAG violation (see _LIB_ALLOWED_RUNTIME):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# AST dataclass collector
# ---------------------------------------------------------------------------


class _DataclassCollector(ast.NodeVisitor):
    """Find @dataclass classes and check for frozen=True."""

    def __init__(self) -> None:
        self.unfrozen: list[tuple[str, int]] = []  # (class_name, lineno)

    def _is_dataclass(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name) and node.id == "dataclass":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "dataclass":
            return True
        if isinstance(node, ast.Call):
            return self._is_dataclass(node.func)
        return False

    def _has_frozen(self, node: ast.expr) -> bool:
        if not isinstance(node, ast.Call):
            return False  # bare @dataclass — no frozen
        for kw in node.keywords:
            if (
                kw.arg == "frozen"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                return True
        return False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            if self._is_dataclass(dec) and not self._has_frozen(dec):
                self.unfrozen.append((node.name, node.lineno))
        self.generic_visit(node)


def _collect_unfrozen_dataclasses(path: Path) -> list[tuple[str, int]]:
    """Return (class_name, lineno) for dataclasses missing frozen=True."""
    collector = _DataclassCollector()
    collector.visit(ast.parse(path.read_text(), filename=str(path)))
    return collector.unfrozen


# ---------------------------------------------------------------------------
# Rule 5: Lib dataclasses must be frozen
# ---------------------------------------------------------------------------


def test_lib_dataclasses_frozen():
    """Lib dataclasses must use @dataclass(frozen=True).

    Convention: "Immutable by default — frozen dataclasses, pure functions."
    Mutable state belongs in local variables and closures, not data types.
    """
    EXCEPTIONS: set[tuple[str, str]] = {
        # Legitimately mutable — accumulator/collector patterns
        ("libs/lang/src/lang/validator.py", "ValidationContext"),  # error accumulator
        ("libs/engine/src/engine/loop.py", "Loop"),  # _period_start timing state
        # TODO: freeze — these are config/output holders, not accumulators
        ("libs/atoms/src/atoms/source.py", "Source"),
        ("libs/engine/src/engine/compiler.py", "CompiledVertex"),
        ("libs/engine/src/engine/stream.py", "Tap"),
        ("libs/lang/src/lang/validator.py", "Shape"),
        ("libs/lang/src/lang/errors.py", "Location"),
        # Accumulated while the ratchet was red (found 2026-07-16):
        ("libs/engine/src/engine/executor.py", "SyncResult"),  # output holder — freezable
        ("libs/engine/src/engine/executor.py", "Executor"),  # runtime coordinator
    }
    # Validate exception paths still exist
    for rel_path, _cls in EXCEPTIONS:
        assert (REPO_ROOT / rel_path).exists(), f"Stale exception: {rel_path}"

    violations = []
    for lib_dir in (REPO_ROOT / "libs").iterdir():
        if not lib_dir.is_dir():
            continue
        for py_file in _src_py_files(lib_dir):
            rel = _rel(py_file)
            for cls_name, lineno in _collect_unfrozen_dataclasses(py_file):
                if (rel, cls_name) in EXCEPTIONS:
                    continue
                violations.append(f"  {rel}:{lineno} class {cls_name}")

    assert not violations, (
        "Lib dataclasses must use @dataclass(frozen=True):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 6: atoms has zero external runtime dependencies
# ---------------------------------------------------------------------------

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
        for module, lineno in collector.runtime_modules:
            top_level = module.split(".")[0]
            # Allow intra-package imports (atoms.*)
            if top_level == "atoms":
                continue
            if top_level not in _STDLIB_MODULES:
                violations.append(f"  {_rel(py_file)}:{lineno} imports {module}")

    assert not violations, (
        "atoms must only import stdlib — no external dependencies:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 7: sqlite3 confined to engine and store
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Rule 8: signing domain constants live in libs/custody only
# ---------------------------------------------------------------------------

_DOMAIN_LITERALS = ("loops-tick-v1", "loops-fact-v1")
_DOMAIN_HOME = "libs/custody/src/custody/signing.py"


def test_domain_constants_confined_to_custody():
    """The domain-separation literals appear in exactly one source file.

    ``loops-tick-v1``/``loops-fact-v1`` are the store's at-rest signing
    format (design/architecture/custody-lib-extraction). This pin is
    string-level, not import-level, on purpose: re-hardcoding the literal
    instead of importing TICK_DOMAIN/FACT_DOMAIN would pass any import
    ratchet while silently forking the format. Import the constants.
    """
    assert (REPO_ROOT / _DOMAIN_HOME).exists(), f"custody moved? {_DOMAIN_HOME}"

    violations = []
    for root_name in ("libs", "apps"):
        for pkg_dir in (REPO_ROOT / root_name).iterdir():
            if not pkg_dir.is_dir():
                continue
            for py_file in _src_py_files(pkg_dir):
                rel = _rel(py_file)
                if rel == _DOMAIN_HOME:
                    continue
                text = py_file.read_text()
                for literal in _DOMAIN_LITERALS:
                    if literal in text:
                        violations.append(f"  {rel} contains {literal!r}")

    assert not violations, (
        f"Signing domain literals belong to {_DOMAIN_HOME} only — "
        "import TICK_DOMAIN/FACT_DOMAIN from custody instead:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 9: every resolve_local_vertex caller handles the ambiguity refusal
# ---------------------------------------------------------------------------

#: Call sites licensed to break a multi-vertex tie ARBITRARILY — i.e. to pass
#: ``allow_ambiguous=True`` to ``_find_local_vertex``. SHRINK-ONLY: each entry
#: is a place the CLI may act on a vertex the user never named, which is the
#: defect friction:find-local-vertex-alphabetical-pick recorded. Keyed
#: ``module::function`` with the reason it is harmless there.
_AMBIGUITY_OPT_OUT = {
    # Completion is best-effort and must never raise mid-keystroke; it offers
    # candidates, it never writes.
    "apps/loops/src/loops/cli/completers.py::_vertex_path_on_line",
    # Topology enumeration collects EVERY candidate anyway — the first-match
    # pick carries no weight here.
    "apps/loops/src/loops/commands/resolve.py::_candidate_topology_vertices",
    "apps/loops/src/loops/commands/resolve.py::_topology_roots_for_emit",
}

#: The resolution primitives that refuse on ambiguity by default.
_AMBIGUITY_PRIMITIVES = {"_find_local_vertex", "resolve_local_vertex"}


class _OptOutCallCollector(ast.NodeVisitor):
    """Every call to an ambiguity primitive, with its enclosing function and
    whether it passed ``allow_ambiguous=True``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []  # (func, callee, opted_out)
        self._scope: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = (
            func.id if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute)
            else None
        )
        if name in _AMBIGUITY_PRIMITIVES:
            # ANY allow_ambiguous value that is not a literal False counts as
            # an opt-out to be declared — a literal True, a variable, an
            # expression, `1`. The rule must never be MORE permissive than the
            # runtime: it used to recognize only literal True, so
            # `allow_ambiguous=1` slipped past the ratchet while still opting
            # out at runtime (sol round 3). The runtime now honors literal True
            # only, and anything the rule cannot evaluate is flagged rather
            # than assumed safe.
            opted_out = any(
                kw.arg == "allow_ambiguous"
                and not (
                    isinstance(kw.value, ast.Constant) and kw.value.value is False
                )
                for kw in node.keywords
            )
            scope = self._scope[-1] if self._scope else "<module>"
            self.calls.append((scope, name, opted_out))
        self.generic_visit(node)


def test_ambiguous_vertex_opt_outs_are_enumerated():
    """Resolving an unnamed vertex must refuse on ambiguity, or be listed.

    The refusal lives in ``_find_local_vertex`` itself, so the DEFAULT is safe
    and there is no ungated primitive to reach for — the first version gated
    callers by hand and left the primitive importable, which is a bypass one
    import away, and its string-grep check passed a module that had one gated
    call and one ungated one (sol P1-b round 2).

    What remains checkable is the deliberate escape: ``allow_ambiguous=True``.
    It is explicit at the call site precisely so this rule can count it, and
    every occurrence must be named in ``_AMBIGUITY_OPT_OUT`` with its reason.
    A plain call needs no entry — it refuses on its own.

    The rule and the runtime are deliberately clamped to each other: the
    runtime honors the LITERAL ``True`` only, and this rule flags any value
    that is not a literal ``False``. Anything the rule cannot evaluate — a
    variable, an expression, ``1`` — is treated as an undeclared opt-out rather
    than assumed safe, so the two can never disagree about what an opt-out is
    (sol round 3, where ``allow_ambiguous=1`` opted out at runtime while being
    recorded here as safe).
    """
    for entry in sorted(_AMBIGUITY_OPT_OUT):
        rel, _, func = entry.partition("::")
        path = REPO_ROOT / rel
        assert path.exists(), f"Stale exception: {rel} no longer exists"
        tree = ast.parse(path.read_text(), filename=str(path))
        assert any(
            isinstance(n, ast.FunctionDef) and n.name == func
            for n in ast.walk(tree)
        ), f"Stale exception: {rel} has no function {func}"

    violations = []
    for py_file in _src_py_files(REPO_ROOT / "apps" / "loops"):
        collector = _OptOutCallCollector()
        collector.visit(ast.parse(py_file.read_text(), filename=str(py_file)))
        for scope, callee, opted_out in collector.calls:
            if not opted_out:
                continue  # default path — the primitive refuses
            key = f"{_rel(py_file)}::{scope}"
            if key not in _AMBIGUITY_OPT_OUT:
                violations.append(
                    f"  {key} calls {callee} with a non-False allow_ambiguous"
                )

    assert not violations, (
        "Breaking a multi-vertex tie arbitrarily must be declared "
        "(see _AMBIGUITY_OPT_OUT) — an unlisted opt-out lets the CLI act on a "
        "vertex the user never named:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 10: disclosure renderers do no store I/O
# ---------------------------------------------------------------------------

#: The disclosure render paths this rule guards. ``entry`` is the renderer;
#: ``licensed`` names the functions in that path that ARE allowed to touch the
#: store — the evidence gatherers. SHRINK-ONLY: every addition to ``licensed``
#: is one more place a disclosure anchor can be resolved away from the rows it
#: describes, which is the defect this rule exists to prevent.
#:
#: Scope note (sol round 2): the walk covers EVERY function reachable from the
#: entry point, not just the entry point itself — moving a store read one call
#: deeper was a working evasion of the first version. What the rule cannot
#: check is the licensed gatherer's own correctness: that its reads are pinned
#: to the position it discloses is pinned by behavior instead, in
#: ``test_review.TestReviewEvidenceBinding`` (cursor == rendered rows under a
#: concurrent write). Structure guards the shape; those tests guard the
#: content.
_DISCLOSURE_RENDER_PATHS = {
    "apps/loops/src/loops/cli/views/fold.py": {
        "entry": "_run_review",
        "licensed": {"_gather_review_evidence"},
    },
}

#: Store-I/O anchors a renderer must not call directly. Each one resolves state
#: from the store on its own connection; calling any of them from a renderer
#: reintroduces fetch-then-disclose — the pattern that has now shipped three
#: times (observation:practice/fetch-then-disclose-recurrence): S6's cut
#: provenance, S4's review head, and S4's declaration fingerprint. Ordering the
#: calls was the fix twice and held neither time; the invariant that does hold
#: is "the renderer cannot reach the store at all".
_STORE_IO_ANCHORS = {
    "fetch_fold",
    "declaration_generation",
    "fact_signatures",
    "resolve_review_head",
    "resolve_review_head_position",
    "resolve_cut",
    "resolve_cut_summary",
    "fetch_graph",
    "vertex_fold",
    "vertex_facts",
}


def _alias_bindings(nodes) -> dict[str, set[str]]:
    """Local name → the set of symbols it has been bound to by imports.

    A SET, not a single name: two bindings of one alias must both count, since
    the rule's job is to never MISS an anchor. Over-approximating what a name
    might resolve to can only produce more matches, never fewer — the safe
    direction for a guard.
    """
    bindings: dict[str, set[str]] = {}

    def record(local: str, origin: str) -> None:
        bindings.setdefault(local, set()).add(origin)

    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                record(a.asname or a.name, a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    # `import engine.vertex_reader as vr` — the tail is what
                    # attribute calls off it resolve against.
                    record(a.asname, a.name.rsplit(".", 1)[-1])
    return bindings


def _module_level_aliases(tree: ast.Module) -> dict[str, set[str]]:
    """Imports at module scope — the base every function inherits.

    Walks top-level statements and their non-function nested blocks (``if
    TYPE_CHECKING:`` and the like) but never descends into a function or class
    body: those are separate scopes and are overlaid per-function below.
    """
    collected: list[ast.stmt] = []

    def walk(body) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            collected.append(node)
            # Generic: recurse into EVERY statement-list field, including the
            # bodies of wrapper nodes (ExceptHandler in Try.handlers,
            # match_case in Match.cases). Enumerating field names by hand is
            # how `import ... as dg` inside an `except:` escaped this walk
            # (sol, round 3) — the fix is to stop enumerating.
            for _field, value in ast.iter_fields(node):
                if not isinstance(value, list):
                    continue
                stmts = [n for n in value if isinstance(n, ast.stmt)]
                if stmts:
                    walk(stmts)
                for wrapper in value:
                    if isinstance(wrapper, (ast.ExceptHandler, ast.match_case)):
                        walk(wrapper.body)

    walk(tree.body)
    return _alias_bindings(collected)


def _function_aliases(
    fnode: ast.FunctionDef, base: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Aliases visible INSIDE one function: module base + its own imports.

    Scoping this per-function is the point (sol round 3). A single module-wide
    last-import-wins dict let an unrelated function's local
    ``from harmless import noop as dg`` overwrite the renderer's
    ``dg -> declaration_generation`` binding, and the violation vanished. A
    function's local imports must not reach outside it.

    Imports inside NESTED functions are folded in deliberately: the call
    collector walks nested bodies, so their aliases have to be visible here or
    a call inside a closure would resolve against nothing.
    """
    local = _alias_bindings(list(ast.walk(fnode)))
    merged = {k: set(v) for k, v in base.items()}
    for name, origins in local.items():
        merged.setdefault(name, set()).update(origins)
    return merged


class _CallNameCollector(ast.NodeVisitor):
    """Call names in a function body, resolved through the aliases in scope.

    Collects ``f()`` and ``m.f()``. Each name is recorded as written AND as
    every symbol it has been bound to, so renaming at the import site cannot
    hide an anchor.
    """

    def __init__(self, aliases: dict[str, set[str]] | None = None) -> None:
        self.names: set[str] = set()
        self._aliases = aliases or {}

    def _record(self, name: str) -> None:
        self.names.add(name)
        self.names.update(self._aliases.get(name, ()))

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            self._record(func.id)
        elif isinstance(func, ast.Attribute):
            self._record(func.attr)
        self.generic_visit(node)


def _reachable_functions(
    entry: str, by_name: dict[str, ast.FunctionDef], licensed: set[str],
    base_aliases: dict[str, set[str]],
) -> list[str]:
    """Same-module functions reachable from ``entry``, licensed ones excluded.

    Traversal stops AT a licensed function (it is allowed store I/O, and so is
    whatever it calls to do that job); every other function on the path is
    walked, so a read cannot be hidden one call deeper.
    """
    seen: set[str] = set()
    order: list[str] = []
    stack = [entry]
    while stack:
        name = stack.pop()
        if name in seen or name in licensed or name not in by_name:
            continue
        seen.add(name)
        order.append(name)
        collector = _CallNameCollector(
            _function_aliases(by_name[name], base_aliases)
        )
        collector.visit(by_name[name])
        stack.extend(n for n in collector.names if n in by_name)
    return order


def test_disclosure_renderers_do_no_store_io():
    """A renderer describes evidence; it must not go re-read the store.

    The recurring defect (sol P1-a, and twice before it) is a disclosure whose
    anchors are resolved on a different connection — and therefore at a
    different moment — than the rows it renders: a cursor newer than the
    content, a fingerprint from one generation beside a head from another.
    Ordering the two calls narrows that window without closing it, so this
    ratchet pins the shape instead: everything on the render path consumes the
    evidence the licensed gatherer produced, and can reach nothing else.

    Two evasions of the first version are closed here: an aliased import
    (``declaration_generation as dg``) and moving the read one call deeper than
    the entry point. Names resolve through the module's import aliases, and the
    walk covers every reachable function rather than just the entry.
    """
    for rel, spec in _DISCLOSURE_RENDER_PATHS.items():
        path = REPO_ROOT / rel
        assert path.exists(), f"Stale exception: {rel} no longer exists"
        tree = ast.parse(path.read_text(), filename=str(path))
        by_name = {
            n.name: n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
        }
        base_aliases = _module_level_aliases(tree)

        entry = spec["entry"]
        licensed = set(spec["licensed"])
        assert entry in by_name, f"{rel}: no function named {entry}"
        for name in licensed:
            assert name in by_name, (
                f"{rel}: licensed gatherer {name} is missing — a stale "
                "allowlist entry silently widens this rule"
            )

        violations = []
        for name in _reachable_functions(entry, by_name, licensed, base_aliases):
            collector = _CallNameCollector(
                _function_aliases(by_name[name], base_aliases)
            )
            collector.visit(by_name[name])
            for leaked in sorted(collector.names & _STORE_IO_ANCHORS):
                violations.append(f"  {rel}:{name} calls {leaked}")

        assert not violations, (
            "Disclosure render paths must not reach the store — resolving an "
            "anchor at render time is the fetch-then-disclose defect "
            f"(Rule 10). Licensed gatherers for this path: "
            f"{', '.join(sorted(licensed))}.\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Rule 11: record-layer libs never import surfacing-layer libs
# ---------------------------------------------------------------------------

#: The instrument family each lib belongs to. Prose counterpart: the
#: "Layers — the instrument families" table in ARCHITECTURE.md, which carries
#: the Weaver-level reasoning and the membership rationale. This dict and that
#: table are the two halves of one declaration — a lib added to one belongs in
#: the other.
_LIB_LAYER: dict[str, str] = {
    "atoms": "record",
    "lang": "record",
    "engine": "record",
    "store": "record",
    "sign": "surfacing",
    "custody": "surfacing",
}

#: The chartered layer names. ``view`` (painted, external) and ``relevance``
#: (deliberately empty) have no lib members today; they are accepted values so
#: this mapping can say what ARCHITECTURE.md says, and so a misspelled layer
#: cannot quietly exempt a lib from the direction rule below.
_LAYERS = frozenset({"record", "view", "surfacing", "relevance"})


def test_every_lib_declares_a_layer():
    """Every lib under libs/ carries a layer assignment.

    This is what makes a hand-maintained mapping safe: ``_LIB_LAYER`` mirrors
    the filesystem, so the omission has to be loud or the mirror rots (see
    docs/RATCHETS.md). ``LIBS`` is derived from libs/, so a new directory
    fails here before it can slip past Rule 11's direction check by simply
    not being mentioned.
    """
    missing = [name for name in LIBS if name not in _LIB_LAYER]
    assert not missing, (
        "Lib without a layer assignment: "
        + ", ".join(missing)
        + " — assign a layer in _LIB_LAYER (tests/test_architecture.py) AND "
        "add the lib to the Layers table in ARCHITECTURE.md. A lib with no "
        "declared layer is exempt from Rule 11 by accident."
    )

    stale = sorted(set(_LIB_LAYER) - set(LIBS))
    assert not stale, (
        "Stale _LIB_LAYER entry: " + ", ".join(stale) + " no longer exists "
        "under libs/ — drop it here and from ARCHITECTURE.md's Layers table"
    )

    bad = {name: layer for name, layer in _LIB_LAYER.items() if layer not in _LAYERS}
    assert not bad, (
        "Unknown layer name(s): "
        + ", ".join(f"{name}={layer!r}" for name, layer in sorted(bad.items()))
        + f" — must be one of {', '.join(sorted(_LAYERS))}"
    )


def test_record_layer_does_not_import_surfacing():
    """Record-layer libs must not import surfacing-layer libs at runtime.

    The record layer answers Weaver's Level A — what happened, with accuracy
    claims that hold because meaning is out of scope there. The surfacing layer
    is Level C: conduct and authority — host orchestration, coordination,
    attestation. Those claims are relational (conducted-well-or-not), not
    correctness claims. Level A stays semantically and structurally pure of
    Level C, so a record-layer accuracy claim can never depend on an authority
    judgment. The reverse direction is fine and expected: surfacing composes
    over the record (custody -> engine), governed per-lib by Rule 4.

    Rule 4 already forbids each specific edge this rule would catch today.
    Rule 11 is the coarser overlay stated at the layer, so it survives future
    edits to Rule 4's per-lib allowlist: widening ``_LIB_ALLOWED_RUNTIME`` for
    a record lib is a one-line change that reads locally reasonable, and this
    rule is what makes the layer inversion in it fail out loud.

    TYPE_CHECKING-only imports are exempt, matching Rule 4 exactly — the
    collector records runtime imports only, and an annotation-only reference
    creates no runtime dependency to invert.
    """
    surfacing = {name for name, layer in _LIB_LAYER.items() if layer == "surfacing"}

    violations = []
    for lib_name in LIBS:
        if _LIB_LAYER.get(lib_name) != "record":
            continue
        lib_dir = REPO_ROOT / "libs" / lib_name
        for py_file in _src_py_files(lib_dir):
            collector = _collect_imports(py_file)
            for other_lib in sorted(surfacing):
                for lineno in _imports_module(collector.runtime_modules, other_lib):
                    violations.append(
                        f"  {_rel(py_file)}:{lineno} — record lib {lib_name} "
                        f"imports surfacing lib {other_lib} at runtime"
                    )

    assert not violations, (
        "Layer inversion: the record layer (Weaver Level A — accuracy) must "
        "not depend on the surfacing layer (Level C — conduct/authority). "
        "See ARCHITECTURE.md's Layers table and _LIB_LAYER:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 12: the render register IS the offered width
# ---------------------------------------------------------------------------

# painted's ``run_cli`` offers exactly one width-computation seam
# (``_offered_width``): geometry when stdout is a real viewport, ``None`` when
# it is not (a pipe, a file redirect). Every call site on the ``renderer=``
# contract — ``(data, fidelity, width) -> Block`` — gets that for free: painted
# computes ``width``, the app never touches ``ctx``, and a viewportless channel
# is *structurally incapable* of receiving a concrete width.
#
# The deprecated ``render=`` contract (``(ctx, data) -> Block``) has no such
# guarantee: the callback reads ``ctx.width``/``ctx.is_tty`` itself, and
# historically got it wrong (e8643a66 fixed store/store-stats renderers that
# passed ``ctx.width`` unconditionally, clipping the agent channel to an
# inherited ``COLUMNS``). The project store recorded that as "caller
# discipline, not an invariant".
#
# 0.10.0 S1 made it an invariant in two moves, and this rule is the enumerable
# half of both:
#
#   1. **No ``render=`` anywhere.** Migrating apps/tasks' seven sites onto
#      ``renderer=`` (design:rendering/tui-shell-integration, session-3
#      amendment 1) closed the last deprecated call sites in the repo. This
#      walks every app and lib source tree — not just apps/loops, which was
#      all the apps/loops-local predecessor of this rule could see — so a new
#      app cannot reintroduce the shape in a corner no ratchet reaches.
#
#   2. **No second channel.** The ``piped=`` kwarg register-split lenses used
#      to accept was deleted in the same slice; a lens now derives "am I
#      piped" from ``width is None``. That deletion is the *construction* half
#      (docs/RATCHETS.md): a render claiming the piped register while holding
#      a concrete width is no longer a state any call can express. This rule
#      detects only its residue — a ``piped`` parameter growing back onto a
#      lens entry point, which would re-open the disagreement.
#
# Both enumerations are derived, never hand-listed (docs/RATCHETS.md — "never
# hand-enumerate a mirrored structure"): source roots come from ``apps/*/src``
# and ``libs/*/src`` on disk, and lens entry points from the ``lenses/``
# packages plus whatever callables are actually bound at ``renderer=``.
#
# Known boundary, accepted: like every rule in this file the walk is AST-shaped,
# not data-flow. ``getattr(painted, "run_cli")(...)`` and a runner reached
# through a container/return value are not resolved. What IS resolved, after
# sol's HIGH r1 round (three of static analysis's classic defect classes, all
# from docs/RATCHETS.md's table, arriving on schedule):
#
#   * **aliasing** — ``runner = run_cli; runner(..., render=...)`` bypassed the
#     walk entirely. Plain assignment aliases now propagate to a fixed point,
#     deliberately WITHOUT reassignment invalidation: a name once bound to
#     ``run_cli`` stays suspect forever in that module. Over-approximating is
#     the rule (extra matches fail loudly, missed ones fail silently).
#   * **scoping** — ``_functions_by_name`` kept one def per spelling, so the
#     six sibling nested ``renderer`` closures in apps/tasks' CLI all collapsed
#     onto whichever def overwrote the map. Bindings now resolve through a real
#     lexical scope chain, nearest enclosing scope first.
#   * **granularity** — a ``renderer=`` name imported from another repository
#     module was skipped outright. Imports (absolute and relative) now resolve
#     across the derived source roots, and an unresolved REPOSITORY-LOCAL
#     binding fails closed rather than passing silently. Only a name that
#     provably leaves the repository (painted, stdlib) is out of scope, and it
#     is counted separately so the skip cannot go quiet.


def _source_roots() -> list[Path]:
    """Every app and lib ``src/`` tree, derived from the filesystem.

    Same reasoning as ``_lib_names()``: a hand-written list of roots is a
    silent pass for every app added after it was written.
    """
    roots: list[Path] = []
    for parent in ("apps", "libs"):
        base = REPO_ROOT / parent
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.name.startswith((".", "_")) and (d / "src").is_dir():
                roots.append(d / "src")
    return roots


def _all_source_files() -> list[Path]:
    return [
        p
        for root in _source_roots()
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _assign_target_names(target: ast.expr) -> list[str]:
    """Every plain ``Name`` bound by an assignment target, tuples included."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _assign_target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for e in target.elts for n in _assign_target_names(e)]
    return []  # Attribute/Subscript targets are not local names


def _binds_callable(value: ast.expr, aliases: set[str], imported_name: str) -> bool:
    """Does this RHS hand a *reference* to the runner (not its result) on?

    ``Call`` is deliberately absent: ``rc = run_cli(argv)`` binds an exit code,
    not the runner. Everything that can carry the reference through — tuple
    unpacking, a conditional, a ``or`` fallback — is followed, because
    over-approximating here costs a loud failure and under-approximating costs
    a silent pass.
    """
    if isinstance(value, ast.Name):
        return value.id in aliases
    if isinstance(value, ast.Attribute):
        return value.attr == imported_name
    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        return any(_binds_callable(e, aliases, imported_name) for e in value.elts)
    if isinstance(value, ast.IfExp):
        return _binds_callable(value.body, aliases, imported_name) or _binds_callable(
            value.orelse, aliases, imported_name
        )
    if isinstance(value, ast.BoolOp):
        return any(_binds_callable(v, aliases, imported_name) for v in value.values)
    return False


def _local_aliases_for(tree: ast.AST, imported_name: str) -> set[str]:
    """Local names that reach ``imported_name`` — imports AND assignments.

    ``from painted import run_cli as rc`` was always recognised. What was not,
    until sol's HIGH r1 constructed it, is one ordinary assignment::

        from painted import run_cli
        def deprecated_site(argv):
            runner = run_cli                     # <- invisible to the old walk
            return runner(argv, render=lambda ctx, data: None)

    Plain ``Name``/``Attribute``-valued assignments (and walrus binds) now
    propagate to a fixed point, so ``a = run_cli; b = a; b(...)`` is caught too.

    NO reassignment invalidation, on purpose: a name once bound to the runner
    stays suspect for the whole module. A later ``runner = something_else``
    would make an evasion out of a scope trick otherwise, and this rule's
    stated posture (docs/RATCHETS.md) is that false-loud beats silent-pass.

    Always includes the bare name (unaliased import, or no matching import at
    all — module-attribute calls like ``painted.run_cli(...)`` are matched
    separately on ``Attribute.attr``, which is alias-proof).
    """
    aliases = {imported_name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == imported_name:
                    aliases.add(alias.asname or alias.name)

    binds: list[tuple[list[str], ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [n for t in node.targets for n in _assign_target_names(t)]
            binds.append((names, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            binds.append((_assign_target_names(node.target), node.value))
        elif isinstance(node, ast.NamedExpr):
            binds.append((_assign_target_names(node.target), node.value))

    changed = True
    while changed:  # fixed point — chained aliases (a = run_cli; b = a)
        changed = False
        for names, value in binds:
            if not _binds_callable(value, aliases, imported_name):
                continue
            for name in names:
                if name not in aliases:
                    aliases.add(name)
                    changed = True
    return aliases


def _run_cli_calls(tree: ast.AST, aliases: set[str]) -> list[ast.Call]:
    """Every ``run_cli(...)`` call in the tree, aliased forms included."""
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Name) and fn.id in aliases) or (
            isinstance(fn, ast.Attribute) and fn.attr == "run_cli"
        ):
            out.append(node)
    return out


def _mentions_callable(node: ast.AST, aliases: set[str], imported_name: str) -> bool:
    """Does this expression subtree REACH the runner in any way at all?

    Deliberately wider than :func:`_binds_callable` — this is the detector for
    the forms the walk does not model, so it has to see them before it can
    classify them. Includes the reflective spelling
    ``getattr(painted, "run_cli")``, which mentions the runner only as a string.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in aliases:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == imported_name:
            return True
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "getattr"
            and len(sub.args) >= 2
            and isinstance(sub.args[1], ast.Constant)
            and sub.args[1].value == imported_name
        ):
            return True
    return False


def _classify_boundary(value: ast.expr) -> str:
    """Name the indirection class an out-of-scope runner binding uses."""
    if isinstance(value, ast.Call):
        fn = value.func
        if isinstance(fn, ast.Name) and fn.id == "getattr":
            return "reflective (getattr)"
        return "higher-order call (decorator/partial/factory)"
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return "container (dict)"
    if isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return "container (comprehension)"
    if isinstance(value, ast.Subscript):
        return "container (subscript)"
    return f"unmodelled {type(value).__name__} expression"


# Arbiter convergence ruling (090 precedent), applied at 0.10.0 r3: unbounded
# indirection is NOT chased. Containers, getattr, functools.partial and
# decorator wrappers can carry a callable arbitrarily far from its definition,
# and a walk that tried to follow them would be a whole-program dataflow
# analysis wearing a test's name. They are CLASSIFIED BOUNDARIES.
#
# What changed in r3 is that a boundary is no longer an unobserved `continue`.
# sol's refined doctrine: in-scope cannot-resolve fails loudly; out-of-scope
# must be explicitly classified and COUNTABLE. So every binding that reaches
# run_cli through an unmodelled form is enumerated, named by its indirection
# class, and pinned to a baseline below — the population cannot grow without
# someone seeing it, even though the rule declines to follow any member of it.
_RUNNER_BOUNDARY_BASELINE = 0


def _boundary_runner_bindings(
    tree: ast.Module, rel: str, aliases: set[str], imported_name: str
) -> list[str]:
    """Bindings that REACH the runner through a form the walk does not model.

    Not violations — classified out-of-scope observations. The census exists so
    that "we don't follow this" is a counted, reviewable position rather than a
    silent skip (sol HIGH r2 doctrine).
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            value = node.value
        else:
            continue
        if value is None:
            continue

        # Assigning the runner INTO a container slot or attribute
        # (`runners["go"] = run_cli`) is the ordinary incremental-registry
        # spelling, and it fell through both halves of the machinery: the RHS
        # is a plain reference so the census skipped it as "modelled", while
        # `_assign_target_names` binds nothing from a Subscript/Attribute
        # target so no alias was ever created and no call site was walked.
        # Neither modelled NOR counted — which reported population zero and
        # defeated the countability claim outright (sol HIGH r3 §3).
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
        )
        slot = next(
            (t for t in targets if isinstance(t, (ast.Subscript, ast.Attribute))),
            None,
        )
        if slot is not None and _binds_callable(value, aliases, imported_name):
            where = (
                "container (subscript assignment)"
                if isinstance(slot, ast.Subscript)
                else "container (attribute assignment)"
            )
            out.append(
                f"  {rel}:{node.lineno} — {imported_name} is stored into a "
                f"{where}; classified out of scope, not walked"
            )
            continue

        if _binds_callable(value, aliases, imported_name):
            continue  # modelled: a plain reference to a plain name, already an alias
        if not _mentions_callable(value, aliases, imported_name):
            continue
        if isinstance(value, ast.Call) and _binds_callable(
            value.func, aliases, imported_name
        ):
            # `code = run_cli(...)` — a direct invocation, fully modelled. Its
            # ARGUMENTS could still hand the runner onward, so only skip when
            # they do not.
            passed_on = [*value.args, *(kw.value for kw in value.keywords)]
            if not any(
                _mentions_callable(a, aliases, imported_name) for a in passed_on
            ):
                continue
        out.append(
            f"  {rel}:{node.lineno} — {imported_name} reaches a binding via "
            f"{_classify_boundary(value)}; classified out of scope, not walked"
        )
    return out


_SCOPE_NODES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    # Comprehensions carry their own scope in Python 3, and their `for`
    # targets bind in it. Omitting them let sol's
    # `[run_cli(..., renderer=renderer) for renderer in [bad]]` resolve to a
    # clean outer def (HIGH r2 §3).
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _lexical_bindings(tree: ast.Module) -> tuple[dict, dict, dict, dict]:
    """``(defs, shadows, imports, enclosing_scopes)`` — all keyed per scope.

    A ``def`` statement binds its name in the ENCLOSING scope, which is what
    makes ``apps/tasks``' six sibling nested ``renderer`` closures resolve to
    six different definitions rather than collapsing onto one (HIGH r1).

    But indexing ONLY ``def`` bindings is not a Python binding model, and sol's
    HIGH r2 §3 walked straight through the gap: a clean outer
    ``def renderer(...)`` masked a NEARER runtime binding of the same name, so
    the resolver reported the callable Python would not call. Every one of
    these returned ``resolved=1, violations=0``::

        renderer = bad                  # assignment
        def f(renderer=bad): ...        # parameter
        renderer, other = bad, None     # tuple unpack
        renderer = {"bad": bad}["bad"]  # subscript
        renderer = getattr(Box, "bad")  # reflective
        renderer = functools.partial(bad)
        renderer = decorate(bad)
        [... for renderer in [bad]]     # comprehension target
        class C: renderer = bad         # class body

    So SHADOWS are indexed too — every non-``def`` binding construct that can
    put a different object under the name: assignment (plain, annotated,
    augmented, walrus), function/lambda parameters, ``for``/``with``/``except``
    targets, comprehension targets, class statements, and ``global``/
    ``nonlocal`` declarations (which we cannot follow, so they count as
    shadows). A shadow nearer than the def makes the binding UNRESOLVABLE,
    which routes it to the loud fail-closed path rather than to a wrong answer.

    IMPORTS are the third category, and the one sol's HIGH r3 §2 found missing.
    A function-local ``from evapp.views import bad as renderer`` is an ordinary
    local binding — the normal "module ships a default renderer, one command
    imports a specialised one under the same name" shape — and because the
    scope model indexed no import bindings at all, the resolver walked straight
    past it to the clean outer def and reported ``resolved=1, violations=0``:
    the r2 false-green class, recreated by a spelling the r2 fix did not cover.

    Imports are indexed SEPARATELY from shadows rather than lumped in with
    them, because unlike an assignment they are followable — the machinery to
    resolve an imported name across source roots already exists
    (:func:`_resolve_callable`, absolute + relative, up to ``_MAX_IMPORT_HOPS``
    re-exports). So a local import RESOLVES, catching the imported function's
    ``piped`` directly, and only falls to the loud fail-closed path when
    resolution genuinely fails on a repository-local module.

    ``import x.y as renderer`` (plain ``Import``) is a shadow, not a resolvable
    import: it binds a MODULE object, which is not a renderer and not something
    this walk can inspect as one.
    """
    defs: dict[int, dict[str, list]] = {id(tree): {}}
    shadows: dict[int, dict[str, list[int]]] = {id(tree): {}}
    imports: dict[int, dict[str, list]] = {id(tree): {}}
    stacks: dict[int, tuple] = {id(tree): (tree,)}

    def shadow(scope: ast.AST, name: str, lineno: int) -> None:
        shadows.setdefault(id(scope), {}).setdefault(name, []).append(lineno)

    def visit(node: ast.AST, stack: tuple) -> None:
        stacks[id(node)] = stack
        here = stack[-1]

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(id(here), {}).setdefault(node.name, []).append(node)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue  # a star import can bind anything; nothing to follow
                imports.setdefault(id(here), {}).setdefault(
                    alias.asname or alias.name, []
                ).append((node, alias))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # Binds a module object, not a callable this walk can inspect.
                shadow(here, alias.asname or alias.name.split(".")[0], node.lineno)
        elif isinstance(node, ast.ClassDef):
            # A class statement binds a name that is not a function def.
            shadow(here, node.name, node.lineno)
        elif isinstance(node, ast.arg):
            # Parameters are children of the arguments node, so `here` is
            # already the function/lambda whose own scope they bind in.
            shadow(here, node.arg, node.lineno)
        elif isinstance(node, ast.comprehension):
            for name in _assign_target_names(node.target):
                shadow(here, name, getattr(node.target, "lineno", 0))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            shadow(here, node.name, node.lineno)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                shadow(here, name, node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            for target in targets:
                for name in _assign_target_names(target):
                    shadow(here, name, node.lineno)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for name in _assign_target_names(node.target):
                shadow(here, name, node.lineno)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            for name in _assign_target_names(node.optional_vars):
                shadow(here, name, getattr(node.optional_vars, "lineno", 0))

        if isinstance(node, _SCOPE_NODES):
            defs.setdefault(id(node), {})
            shadows.setdefault(id(node), {})
            imports.setdefault(id(node), {})
            stack = (*stack, node)
        for child in ast.iter_child_nodes(node):
            visit(child, stack)

    for child in ast.iter_child_nodes(tree):
        visit(child, (tree,))
    return defs, shadows, imports, stacks


def _resolve_lexically(
    name: str, node: ast.AST, defs: dict, shadows: dict, imports: dict, stacks: dict
) -> tuple[list, list, str | None]:
    """``(defs, import bindings to follow, reason it is unresolvable)``.

    The nearest enclosing scope that binds the name AT ALL decides the answer —
    that is what lexical scoping means, and looking past it was the r2 defect
    (assignments and parameters) and again the r3 defect (local imports).

    Three outcomes from that scope:

    * a non-``def`` binding (or a mix) — UNRESOLVABLE, the loud path. Some
      object other than the visible def may be under the name at runtime, and
      guessing is exactly what produced the false green;
    * ``from X import name`` — FOLLOWABLE, handed back for the caller to
      resolve across source roots;
    * ``def``s only — returned, ALL of them rather than the textually-last, so
      a ``piped``-taking def cannot hide behind a later clean redefinition.

    A scope holding both a def and an import of the same name is ambiguous
    without flow analysis, so it takes the unresolvable path too.
    """
    for scope in reversed(stacks.get(id(node), ())):
        found = defs.get(id(scope), {}).get(name)
        shadowed = shadows.get(id(scope), {}).get(name)
        imported = imports.get(id(scope), {}).get(name)
        if shadowed:
            where = ", ".join(f"line {n}" for n in sorted(set(shadowed)))
            kind = "also rebound" if (found or imported) else "bound by a non-def statement"
            return [], [], (
                f"'{name}' is {kind} in its nearest binding scope ({where}) — "
                "the def a reader sees may not be the object Python calls"
            )
        if imported and found:
            return [], [], (
                f"'{name}' is both defined and imported in its nearest binding "
                f"scope (line {imported[0][0].lineno}) — which one runs depends "
                "on order this walk does not model"
            )
        if imported:
            return [], list(imported), None
        if found:
            return list(found), [], None
    return [], [], None


def _absolute_module(node: ast.ImportFrom, origin: Path, roots: list[Path]) -> str | None:
    """Dotted module name for an ``ImportFrom``, resolving relative forms.

    Relative imports are the common spelling inside these packages, so a walk
    that only understood ``level == 0`` would leave most in-repo renderer
    imports unresolved — and unresolved now fails closed.
    """
    if node.level == 0:
        return node.module
    root = next((r for r in roots if r in origin.parents), None)
    if root is None:
        return None
    package = list(origin.relative_to(root).parts[:-1])
    up = node.level - 1
    if up > len(package):
        return None
    base = package[: len(package) - up]
    return ".".join([*base, *([node.module] if node.module else [])]) or None


def _module_file(dotted: str, roots: list[Path]) -> Path | None:
    """Source file for a dotted module, if it lives in a repository source root."""
    parts = dotted.split(".")
    for root in roots:
        module = root.joinpath(*parts[:-1], parts[-1] + ".py")
        if module.is_file():
            return module
        package = root.joinpath(*parts, "__init__.py")
        if package.is_file():
            return package
    return None


_MAX_IMPORT_HOPS = 4


def _resolve_callable(
    name: str,
    node: ast.AST | None,
    tree: ast.Module,
    origin: Path,
    roots: list[Path],
    hops: int = 0,
) -> tuple[list, str | None]:
    """``(function defs ``name`` can reach, reason it could not be resolved)``.

    ``node`` scopes the lookup lexically; ``None`` means module scope only
    (the re-export hop). ``from X import name`` is followed into other
    repository source files, up to ``_MAX_IMPORT_HOPS`` re-exports.

    A ``None`` reason with no candidates means the name provably LEAVES the
    repository (painted, stdlib) — not inspectable, and counted separately by
    the caller so the skip stays visible. Any other unresolved case returns a
    reason and the caller fails closed on it.
    """
    defs, shadows, imports, stacks = _lexical_bindings(tree)
    if node is not None:
        found, followable, reason = _resolve_lexically(
            name, node, defs, shadows, imports, stacks
        )
        if reason is not None:
            return [], reason  # nearer non-def binding, or ambiguous — fail closed
    else:
        # Re-export hop: module scope only. A module-level rebinding of the
        # same name is still a shadow, and still fails closed.
        if shadows.get(id(tree), {}).get(name):
            return [], (
                f"'{name}' is rebound at module scope in {origin.name} — "
                "the re-exported def may not be what the name reaches"
            )
        found = list(defs.get(id(tree), {}).get(name, ()))
        followable = list(imports.get(id(tree), {}).get(name, ()))
    if found:
        return found, None
    if not followable:
        return [], f"'{name}' is neither a def, a lambda, nor an import in this module"
    if hops >= _MAX_IMPORT_HOPS:
        return [], f"re-export chain for '{name}' exceeded {_MAX_IMPORT_HOPS} hops"

    # Follow the import binding that the SCOPE model chose. The predecessor
    # scanned `ast.walk(tree)` for any matching ImportFrom anywhere in the
    # module, which both ignored scope and could not see a local import as the
    # binding it is (sol HIGH r3 §2).
    imp, alias = followable[0]
    dotted = _absolute_module(imp, origin, roots)
    target = _module_file(dotted, roots) if dotted else None
    if target is None:
        return [], None  # leaves the repository — not ours to inspect
    sub = ast.parse(target.read_text(), filename=str(target))
    return _resolve_callable(alias.name, None, sub, target, roots, hops + 1)


def _param_names(fn) -> set[str]:
    """Every parameter name a function declares, in any position."""
    a = fn.args
    names = {p.arg for p in [*a.posonlyargs, *a.args, *a.kwonlyargs]}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


# Shrink-only. Empty — every current run_cli() call site uses renderer= with no
# **kwargs unpacking, and no lens entry point declares `piped`. A new entry owes
# the justification e8643a6 records: painted's offered-width guarantee does not
# cover the site, and the callback re-derives ctx.width/ctx.is_tty by hand.
_RENDER_CONTRACT_EXCEPTIONS: set[str] = set()

# Shrink-only, and mechanically so (sol HIGH r2 §3 found the r1 version was a
# shrink-only *claim* with nothing enforcing it: `_check_exceptions` only
# verified the paths existed, any source file could be added with no reason and
# no cardinality bound, and one entry suppressed EVERY renderer finding in that
# file — including a resolved renderer explicitly declaring `piped`).
#
# Three mechanics now back the claim:
#   * path -> REASON, and the reason is required to be non-empty prose;
#   * the baseline below pins the cardinality, so growth is a deliberate,
#     reviewable edit to a number rather than a quiet append;
#   * suppression is scoped to UNRESOLVABLE bindings only. A `piped`-taking
#     renderer that RESOLVED is never suppressible by any entry — that is the
#     invariant itself, not a limit of the walk.
#
# An entry says only: "this file binds renderer= to something the walk cannot
# resolve, and that is intentional."
_RENDERER_BINDING_EXCEPTIONS: dict[str, str] = {}

# Shrink-only baseline. Raising this is the reviewable act.
_RENDERER_BINDING_EXCEPTIONS_BASELINE = 0


def _render_contract_violations(tree: ast.Module, rel: str) -> tuple[list[str], int]:
    """``(violations, run_cli call sites seen)`` for one parsed module."""
    violations: list[str] = []
    seen = 0
    aliases = _local_aliases_for(tree, "run_cli")
    for call in _run_cli_calls(tree, aliases):
        seen += 1
        names = {kw.arg for kw in call.keywords if kw.arg is not None}
        if "render" in names:
            violations.append(
                f"  {rel}:{call.lineno} — run_cli(render=...) is the "
                "deprecated (ctx, data) contract; use "
                "renderer=(data, fidelity, width) so painted's "
                "offered-width guarantee applies"
            )
        elif any(kw.arg is None for kw in call.keywords):
            violations.append(
                f"  {rel}:{call.lineno} — run_cli(**...) unpacks keywords; "
                "cannot statically verify render= isn't among them — "
                "allowlist if intentional"
            )
    return violations, seen


def _lens_entry_piped_violations(tree: ast.Module, rel: str) -> list[str]:
    """Public module-level functions in a ``lenses/`` module taking ``piped``."""
    violations: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue  # private helper — receives the derived bool
        if "piped" in _param_names(node):
            violations.append(
                f"  {rel}:{node.lineno} — lens entry point "
                f"{node.name}() declares a 'piped' parameter; derive "
                "it from `width is None` instead"
            )
    return violations


class _RendererScan(NamedTuple):
    """One module's renderer= census.

    ``piped`` and ``unresolvable`` are separate lists on purpose: the allowlist
    may suppress ONLY the second. sol HIGH r2 §3 noted that a single combined
    list let one allowlist entry silence a resolved renderer that explicitly
    declares ``piped`` — a far broader exemption than the comment claimed.
    """

    piped: list[str]          # resolved to a def that takes `piped` — never suppressible
    unresolvable: list[str]   # repo-local and unresolvable — suppressible, with a reason
    resolved: int
    external: int


def _renderer_binding_violations(
    tree: ast.Module, origin: Path, rel: str, roots: list[Path]
) -> _RendererScan:
    """Resolve every ``renderer=`` keyword on a ``run_cli`` call.

    Lexically first (nearest BINDING scope, so sibling nested closures stay
    distinct and a nearer non-def binding fails closed), then through
    repository-local imports. An unresolved REPOSITORY-LOCAL binding is itself
    a violation: the rule fails closed, because "skipped what it could not
    resolve" was one of sol's HIGH r1 evasions, not an acceptable boundary.
    """
    piped: list[str] = []
    unresolvable: list[str] = []
    resolved = external = 0
    aliases = _local_aliases_for(tree, "run_cli")
    for call in _run_cli_calls(tree, aliases):
        for kw in call.keywords:
            if kw.arg != "renderer":
                continue
            value = kw.value
            if isinstance(value, ast.Lambda):
                targets, reason = [value], None
            elif isinstance(value, ast.Name):
                targets, reason = _resolve_callable(
                    value.id, value, tree, origin, roots
                )
            else:
                targets, reason = [], f"a {type(value).__name__} expression"

            if targets:
                resolved += 1
                for target in targets:
                    if "piped" not in _param_names(target):
                        continue
                    name = getattr(target, "name", "<lambda>")
                    piped.append(
                        f"  {rel}:{target.lineno} — renderer {name}() "
                        "declares a 'piped' parameter; the register is the "
                        "offered width painted already passes "
                        f"(bound at {rel}:{value.lineno})"
                    )
            elif reason is None:
                external += 1  # painted/stdlib — outside every source root
            else:
                unresolvable.append(
                    f"  {rel}:{value.lineno} — renderer= binding could not be "
                    f"resolved ({reason}); Rule 12 fails closed on "
                    "repository-local bindings rather than skipping them — "
                    "bind a def in this module, import one from a repository "
                    "module, or allowlist the file with a reason"
                )
    return _RendererScan(piped, unresolvable, resolved, external)


def test_run_cli_sites_use_renderer_not_render():
    """No ``run_cli(`` call in any app or lib passes the deprecated
    ``render=`` (ctx, data), and none unpacks ``**kwargs`` into the call
    (the keys cannot be verified statically, so it must be allowlisted)."""
    _check_exceptions(_RENDER_CONTRACT_EXCEPTIONS)

    violations = []
    boundary = []
    seen_calls = 0
    for py_file in _all_source_files():
        rel = _rel(py_file)
        if rel in _RENDER_CONTRACT_EXCEPTIONS:
            continue
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        found, seen = _render_contract_violations(tree, rel)
        violations.extend(found)
        seen_calls += seen
        aliases = _local_aliases_for(tree, "run_cli")
        boundary.extend(_boundary_runner_bindings(tree, rel, aliases, "run_cli"))

    assert seen_calls, (
        "Rule 12 found no run_cli call sites at all — the walk went vacuous "
        "(painted renamed, or the source roots moved). Fix the walk; a green "
        f"ratchet that inspects nothing is worse than no ratchet. "
        f"({len(boundary)} classified out-of-scope bindings seen.)"
    )
    # The classified-boundary census. Out-of-scope indirection is not chased
    # (arbiter convergence ruling), but it is COUNTED — a boundary that grows
    # silently is indistinguishable from a rule that stopped working.
    assert len(boundary) <= _RUNNER_BOUNDARY_BASELINE, (
        f"{len(boundary)} run_cli bindings now reach the runner through "
        f"indirection the walk does not model (baseline "
        f"{_RUNNER_BOUNDARY_BASELINE}). These are NOT automatically "
        "violations — container/getattr/partial/decorator forms are a "
        "classified boundary — but the population may not grow unobserved. "
        "Review each, then raise the baseline deliberately:\n"
        + "\n".join(boundary)
    )
    assert not violations, (
        "run_cli() must bind renderer=, never the deprecated render= "
        "(see the Rule 12 preamble — this is the piped ⇒ width=None net):\n"
        + "\n".join(violations)
    )


def test_no_lens_entry_point_takes_a_piped_argument():
    """No lens entry point accepts a ``piped`` parameter.

    The presentation register is read off the offered width (``width is None``
    IS the pipe). A ``piped`` parameter is a *second* channel that can
    disagree with the first — exactly the state 0.10.0 S1 made unconstructible
    by deleting the kwarg. Private helpers may still take a derived ``piped``
    bool: they receive the answer, they are not a place to contradict it.

    Two derived enumerations, deliberately over-approximating (extra matches
    fail loudly, missed ones fail silently — so err wide):

    * every PUBLIC function defined in a ``lenses/`` package under any app or
      lib source tree;
    * every callable bound at a ``renderer=`` keyword, resolved through the
      lexical scope chain and then through repository-local imports — with
      unresolved repository-local bindings failing closed.
    """
    _check_exceptions(set(_RENDERER_BINDING_EXCEPTIONS))
    assert len(_RENDERER_BINDING_EXCEPTIONS) <= _RENDERER_BINDING_EXCEPTIONS_BASELINE, (
        f"_RENDERER_BINDING_EXCEPTIONS has {len(_RENDERER_BINDING_EXCEPTIONS)} "
        f"entries, baseline {_RENDERER_BINDING_EXCEPTIONS_BASELINE}. The "
        "allowlist is shrink-only: raising the baseline is the reviewable act, "
        "appending is not."
    )
    for path, reason in _RENDERER_BINDING_EXCEPTIONS.items():
        assert reason and reason.strip(), (
            f"_RENDERER_BINDING_EXCEPTIONS[{path!r}] has no reason. An opt-out "
            "from a fail-closed rule states why the binding cannot be resolved."
        )

    roots = _source_roots()
    violations = []
    seen_lens_modules = 0
    seen_renderer_bindings = 0
    left_repository = 0

    for py_file in _all_source_files():
        rel = _rel(py_file)
        tree = ast.parse(py_file.read_text(), filename=str(py_file))

        if "lenses" in py_file.parts:
            seen_lens_modules += 1
            violations.extend(_lens_entry_piped_violations(tree, rel))

        scan = _renderer_binding_violations(tree, py_file, rel, roots)
        seen_renderer_bindings += scan.resolved
        left_repository += scan.external
        # A resolved renderer that declares `piped` IS the invariant — no
        # allowlist entry may suppress it (sol HIGH r2 §3). Only the
        # cannot-resolve findings are suppressible.
        violations.extend(scan.piped)
        if rel not in _RENDERER_BINDING_EXCEPTIONS:
            violations.extend(scan.unresolvable)

    assert seen_lens_modules, (
        "Rule 12 found no lenses/ modules — the walk went vacuous (packages "
        "renamed or relocated). Fix the walk before trusting the green."
    )
    assert seen_renderer_bindings, (
        "Rule 12 resolved no renderer= bindings — the walk went vacuous "
        f"({left_repository} left the repository unexamined). Fix the walk "
        "before trusting the green."
    )
    assert not violations, (
        "The presentation register is the offered width, not a second "
        "argument (see the Rule 12 preamble):\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 12 — the ratchet's own regression suite (sol HIGH r1 evasions)
#
# Every case below is an evasion that PASSED the pre-r1 walk. They run against
# synthetic trees rather than the repository, which is the point: a ratchet
# verified only against the repository as it happens to look today is a
# regression test wearing a ratchet's name (docs/RATCHETS.md).
# ---------------------------------------------------------------------------


def _synthetic_app(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a throwaway ``apps/<x>/src`` tree and return its src root."""
    root = tmp_path / "apps" / "evasion" / "src"
    for rel, body in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body).lstrip())
    return root


def test_rule12_catches_an_assignment_aliased_runner():
    """sol HIGH r1 evasion 1: ``runner = run_cli`` then ``runner(render=...)``.

    Verbatim from the review. The pre-r1 alias collector followed only
    ``from ... import run_cli as alias``, so this call site was invisible —
    and the repository's existing direct calls kept anti-vacuity satisfied,
    so nothing else noticed.
    """
    tree = ast.parse(
        textwrap.dedent(
            """
            from painted import run_cli

            def deprecated_site(argv):
                runner = run_cli
                return runner(argv, fetch=lambda: {},
                              render=lambda ctx, data: None)
            """
        )
    )
    assert "runner" in _local_aliases_for(tree, "run_cli")
    violations, seen = _render_contract_violations(tree, "evasion.py")
    assert seen == 1, "the aliased call site was not walked at all"
    assert violations and "render=" in violations[0]


def test_rule12_follows_a_chain_of_assignment_aliases():
    """The same evasion one hop deeper — the alias set is a fixed point, and
    ``painted.run_cli`` on the right-hand side seeds it just as an import does."""
    tree = ast.parse(
        textwrap.dedent(
            """
            import painted

            _runner = painted.run_cli
            go = _runner

            def site(argv):
                return go(argv, fetch=lambda: {}, render=lambda ctx, d: None)
            """
        )
    )
    assert {"_runner", "go"} <= _local_aliases_for(tree, "run_cli")
    violations, seen = _render_contract_violations(tree, "evasion.py")
    assert seen == 1 and violations


def test_rule12_does_not_alias_a_run_cli_return_value():
    """Over-approximation has a floor: ``code = run_cli(...)`` binds an exit
    status, not the runner, so calling ``code`` later is not a run_cli site."""
    tree = ast.parse(
        textwrap.dedent(
            """
            from painted import run_cli

            def site(argv):
                code = run_cli(argv, fetch=lambda: {},
                               renderer=lambda d, f, w: None)
                return code
            """
        )
    )
    assert "code" not in _local_aliases_for(tree, "run_cli")


def test_rule12_resolves_the_nearest_nested_renderer(tmp_path: Path):
    """sol HIGH r1 evasion 2: sibling nested ``renderer`` closures.

    The shape of ``apps/tasks/src/strange_loops/cli.py``, which defines six of
    them. The pre-r1 ``_functions_by_name`` kept one def per spelling, so both
    bindings below resolved to ``cmd_two``'s clean definition and the ``piped``
    on ``cmd_one``'s went unseen.
    """
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/cli.py": """
                from painted import run_cli

                def cmd_one(argv):
                    def renderer(data, fidelity, width, *, piped=False):
                        return None
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)

                def cmd_two(argv):
                    def renderer(data, fidelity, width):
                        return None
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    violations = [*scan.piped, *scan.unresolvable]
    resolved, external = scan.resolved, scan.external
    assert (resolved, external) == (2, 0)
    assert len(violations) == 1, violations
    assert "piped" in violations[0]


def test_rule12_inspects_a_renderer_imported_from_a_repository_module(
    tmp_path: Path,
):
    """sol HIGH r1 evasion 3: ``renderer=`` imported from a non-``lenses/``
    repository module. The pre-r1 walk skipped any binding it could not find
    in the same module (``if target is None: continue``)."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/__init__.py": "",
            "evapp/views/__init__.py": "",
            "evapp/views/cards.py": """
                def card_view(data, fidelity, width, *, piped=False):
                    return None
            """,
            "evapp/cli.py": """
                from painted import run_cli
                from evapp.views.cards import card_view

                def main(argv):
                    return run_cli(argv, fetch=lambda: {}, renderer=card_view)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    violations = [*scan.piped, *scan.unresolvable]
    resolved, external = scan.resolved, scan.external
    assert (resolved, external) == (1, 0)
    assert violations and "card_view" in violations[0]


def test_rule12_resolves_relative_and_re_exported_renderer_imports(
    tmp_path: Path,
):
    """The spelling this repo actually uses: a relative import through a
    package that re-exports the def. Both hops must resolve, or the previous
    test is evaded by writing ``from . import`` instead."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/__init__.py": "",
            "evapp/views/__init__.py": "from .cards import card_view\n",
            "evapp/views/cards.py": """
                def card_view(data, fidelity, width, *, piped=False):
                    return None
            """,
            "evapp/cli.py": """
                from painted import run_cli
                from .views import card_view

                def main(argv):
                    return run_cli(argv, fetch=lambda: {}, renderer=card_view)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    violations = [*scan.piped, *scan.unresolvable]
    resolved, external = scan.resolved, scan.external
    assert (resolved, external) == (1, 0)
    assert violations and "card_view" in violations[0]


def test_rule12_fails_closed_on_an_unresolvable_repository_binding(
    tmp_path: Path,
):
    """"Could not resolve" must be loud. A renderer built at runtime is not
    something the walk can inspect, so it is a violation until someone
    allowlists the file — the opposite of the pre-r1 silent ``continue``."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/cli.py": """
                from painted import run_cli
                from functools import partial

                renderer = partial(print)

                def main(argv):
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    violations = [*scan.piped, *scan.unresolvable]
    resolved, external = scan.resolved, scan.external
    assert (resolved, external) == (0, 0)
    assert violations and "fails closed" in violations[0]


def test_rule12_counts_but_does_not_flag_renderers_outside_the_repository(
    tmp_path: Path,
):
    """A renderer imported from painted cannot be inspected, and that is not a
    violation — but it is counted apart from the resolved ones, so a walk that
    resolves nothing and skips everything still trips anti-vacuity."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/cli.py": """
                from painted import run_cli, default_view

                def main(argv):
                    return run_cli(argv, fetch=lambda: {}, renderer=default_view)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    violations = [*scan.piped, *scan.unresolvable]
    resolved, external = scan.resolved, scan.external
    assert (violations, resolved, external) == ([], 0, 1)


# ---------------------------------------------------------------------------
# Rule 12 — sol HIGH r2 evasions
# ---------------------------------------------------------------------------

# Sol's §3 table, verbatim in shape: in each case a clean outer
# `def renderer(...)` decoy exists, and a NEARER non-def binding puts `bad`
# (which takes `piped`) under the same name. All of these returned
# `resolved=1, violations=0` against the r1 scope model — the resolver named a
# callable Python would not call.
_SHADOW_EVASIONS = {
    "assignment": """
        def by_assignment(argv):
            renderer = bad
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "parameter": """
        def by_parameter(argv, renderer=bad):
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "tuple_unpack": """
        def by_tuple(argv):
            renderer, other = bad, None
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "dict_subscript": """
        def by_dict(argv):
            renderer = {"bad": bad}["bad"]
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "getattr": """
        def by_getattr(argv):
            renderer = getattr(Box, "bad")
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "partial": """
        def by_partial(argv):
            renderer = functools.partial(bad)
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "decorator": """
        def by_decorator(argv):
            renderer = decorate(bad)
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "for_loop": """
        def by_for(argv):
            for renderer in [bad]:
                return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "with_target": """
        def by_with(argv):
            with opened() as renderer:
                return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
    "comprehension": """
        def by_comprehension(argv):
            return [
                run_cli(argv, fetch=lambda: {}, renderer=renderer)
                for renderer in [bad]
            ]
    """,
    "class_body": """
        class C:
            renderer = bad
            result = run_cli([], fetch=lambda: {}, renderer=renderer)
    """,
    "global_decl": """
        def by_global(argv):
            global renderer
            return run_cli(argv, fetch=lambda: {}, renderer=renderer)
    """,
}


def _shadow_module(tmp_path: Path, body: str) -> tuple[ast.Module, Path, Path]:
    """A module with a clean outer ``renderer`` decoy plus one evasion body."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/cli.py": textwrap.dedent(
                """
                from painted import run_cli

                def renderer(data, fidelity, width):
                    return None

                def bad(data, fidelity, width, *, piped=False):
                    return None
                """
            ).lstrip()
            + textwrap.dedent(body),
        },
    )
    cli = root / "evapp" / "cli.py"
    return ast.parse(cli.read_text()), cli, root


def test_rule12_fails_closed_when_a_local_binding_shadows_the_renderer(
    tmp_path: Path,
):
    """sol HIGH r2 §3: the r1 scope model indexed only ``def`` bindings.

    A clean outer definition therefore masked a nearer runtime binding of the
    same name, and the walk confidently reported the wrong callable — worse
    than skipping, because it looked like a resolution. Every shape below must
    now land on the loud fail-closed path instead.

    Note this is deliberately NOT an attempt to follow the shadow to its real
    target (that would be whole-program dataflow, which the arbiter ruling
    declines). It is the honest answer: the name's nearest binding is not a
    def, so what Python calls here is unknown, and unknown fails closed.
    """
    for label, body in _SHADOW_EVASIONS.items():
        tree, cli, root = _shadow_module(tmp_path / label, body)
        scan = _renderer_binding_violations(tree, cli, "evapp/cli.py", [root])
        assert scan.resolved == 0, (
            f"[{label}] resolved a def while a nearer non-def binding shadows "
            "it — this is the r2 evasion, not a resolution"
        )
        assert scan.piped == []
        assert len(scan.unresolvable) == 1, f"[{label}] {scan}"
        assert "fails closed" in scan.unresolvable[0], f"[{label}] {scan}"


def test_rule12_still_resolves_an_unshadowed_nested_renderer(tmp_path: Path):
    """The floor for the test above: fail-closed must not swallow everything.

    The repository's real shape — a nested ``def renderer`` with no competing
    binding of that name in the same scope — must still RESOLVE, or the
    shadowing fix would have silently converted the whole ratchet into a
    uniform "cannot resolve" and the piped check would inspect nothing.
    """
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/cli.py": """
                from painted import run_cli

                def cmd(argv):
                    def renderer(data, fidelity, width, *, piped=False):
                        return None
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    assert (scan.resolved, scan.unresolvable) == (1, [])
    assert scan.piped and "piped" in scan.piped[0]


def test_rule12_classifies_out_of_scope_runner_bindings():
    """sol HIGH r2 doctrine: out-of-scope must be classified and countable.

    The arbiter ruling declines to CHASE container/reflective/higher-order
    aliases — following them is whole-program dataflow. What it does not
    permit is an unobserved ``continue``. Each form below is recognised and
    named, so the census in ``test_run_cli_sites_use_renderer_not_render``
    fails when the population grows.
    """
    tree = ast.parse(
        textwrap.dedent(
            """
            import functools

            import painted
            from painted import run_cli

            registry = {"go": run_cli}
            reflective = getattr(painted, "run_cli")
            wrapped = decorate(run_cli)
            partialed = functools.partial(run_cli)
            """
        )
    )
    aliases = _local_aliases_for(tree, "run_cli")
    classified = _boundary_runner_bindings(tree, "evasion.py", aliases, "run_cli")
    assert len(classified) == 4, classified
    joined = "\n".join(classified)
    assert "container (dict)" in joined
    assert "reflective (getattr)" in joined
    assert joined.count("higher-order call") == 2
    # And none of them silently became an alias — that is the honest half:
    # the walk does not claim to follow these.
    assert {"registry", "reflective", "wrapped", "partialed"} & aliases == set()


def test_rule12_boundary_census_ignores_a_direct_run_cli_invocation():
    """The census must not cry wolf on ordinary calls. ``code = run_cli(...)``
    mentions the runner but hands nothing onward, so it is neither an alias nor
    a boundary. A call that DOES pass the runner into something else is."""
    tree = ast.parse(
        textwrap.dedent(
            """
            from painted import run_cli

            def site(argv):
                code = run_cli(argv, fetch=lambda: {},
                               renderer=lambda d, f, w: None)
                return code
            """
        )
    )
    aliases = _local_aliases_for(tree, "run_cli")
    assert _boundary_runner_bindings(tree, "e.py", aliases, "run_cli") == []

    leaky = ast.parse(
        textwrap.dedent(
            """
            from painted import run_cli

            handed_on = register(run_cli)
            """
        )
    )
    aliases = _local_aliases_for(leaky, "run_cli")
    assert len(_boundary_runner_bindings(leaky, "e.py", aliases, "run_cli")) == 1


def test_rule12_allowlist_cannot_suppress_a_resolved_piped_renderer(
    tmp_path: Path,
):
    """sol HIGH r2 §3: one allowlist entry used to silence EVERY renderer
    finding in a file, including a resolved def that declares ``piped`` — the
    invariant itself. Suppression is now scoped to the unresolvable list, so an
    entry cannot reach the finding it was never meant to cover."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/cli.py": """
                from painted import run_cli
                from functools import partial

                built = partial(print)

                def cmd(argv):
                    def renderer(data, fidelity, width, *, piped=False):
                        return None
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)

                def other(argv):
                    return run_cli(argv, fetch=lambda: {}, renderer=built)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    # Both findings are present, but they live in different buckets.
    assert len(scan.piped) == 1 and "piped" in scan.piped[0]
    assert len(scan.unresolvable) == 1 and "fails closed" in scan.unresolvable[0]
    # An allowlist entry for this file suppresses only the second.
    assert scan.piped, (
        "the piped finding must survive any allowlist entry — it is the "
        "invariant, not a limitation of the walk"
    )


def test_rule12_allowlist_entries_are_bounded_and_carry_reasons():
    """The shrink-only claim, made mechanical. Empty today; the point is that
    growing it is an edit to a pinned number plus a required justification,
    not a quiet append."""
    assert len(_RENDERER_BINDING_EXCEPTIONS) <= _RENDERER_BINDING_EXCEPTIONS_BASELINE
    assert all(r and r.strip() for r in _RENDERER_BINDING_EXCEPTIONS.values())
    assert isinstance(_RENDERER_BINDING_EXCEPTIONS, dict), (
        "a set cannot carry reasons — the allowlist is path -> why"
    )


# ---------------------------------------------------------------------------
# Rule 12 — sol HIGH r3 evasions
# ---------------------------------------------------------------------------


def test_rule12_resolves_a_function_local_import_binding(tmp_path: Path):
    """sol HIGH r3 §2, his shape exactly.

    A function-local import is an ordinary local binding — the everyday
    "module ships a default renderer, one command imports a specialised one
    under the same name" override. The r2 scope model indexed assignments,
    parameters and comprehension targets as shadows but no import bindings at
    all, so the resolver looked past the real binding to the clean outer def
    and returned ``resolved=1, violations=0``.

    Imports are followable, so the answer here is a RESOLUTION rather than a
    fail-closed: the walk reaches ``bad`` across the source root and sees its
    ``piped`` directly.
    """
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/__init__.py": "",
            "evapp/views/__init__.py": "",
            "evapp/views/cards.py": """
                def bad(data, fidelity, width, *, piped=False):
                    return None
            """,
            "evapp/cli.py": """
                from painted import run_cli

                def renderer(data, fidelity, width):
                    return None

                def site(argv):
                    from evapp.views.cards import bad as renderer
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    assert scan.resolved == 1 and scan.external == 0
    assert len(scan.piped) == 1, scan
    assert "bad()" in scan.piped[0], scan.piped


def test_rule12_local_import_shadow_does_not_leak_to_a_sibling_scope(
    tmp_path: Path,
):
    """The other half of scoping the import: a local import in ONE function
    must not become the binding for a call site in another. The predecessor's
    ``ast.walk`` scan for a matching ImportFrom was module-wide and would."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/__init__.py": "",
            "evapp/views.py": """
                def bad(data, fidelity, width, *, piped=False):
                    return None
            """,
            "evapp/cli.py": """
                from painted import run_cli

                def renderer(data, fidelity, width):
                    return None

                def elsewhere(argv):
                    from evapp.views import bad as renderer
                    return renderer

                def site(argv):
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    # site() sees the module-level def, which is clean.
    assert (scan.resolved, scan.piped, scan.unresolvable) == (1, [], [])


def test_rule12_fails_closed_on_a_local_module_import_binding(tmp_path: Path):
    """``import x as renderer`` binds a MODULE, not a callable. There is
    nothing to inspect, so it takes the loud path rather than resolving past
    the outer def."""
    root = _synthetic_app(
        tmp_path,
        {
            "evapp/cli.py": """
                from painted import run_cli

                def renderer(data, fidelity, width):
                    return None

                def site(argv):
                    import evapp.views as renderer
                    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
            """,
        },
    )
    cli = root / "evapp" / "cli.py"
    scan = _renderer_binding_violations(
        ast.parse(cli.read_text()), cli, "evapp/cli.py", [root]
    )
    assert scan.resolved == 0
    assert len(scan.unresolvable) == 1 and "fails closed" in scan.unresolvable[0]


def test_rule12_counts_a_subscript_registry_assignment(tmp_path: Path):
    """sol HIGH r3 §3, his shape exactly::

        runners = {}
        runners["go"] = run_cli
        runners["go"](..., render=...)

    Neither modelled nor counted: the RHS is a plain reference so the census
    skipped it as already-an-alias, while a Subscript target binds no name, so
    no alias existed and no call site was walked. The census reported
    population ZERO, which is worse than reporting a boundary — it defeated the
    countability claim r3 had just added.
    """
    tree = ast.parse(
        textwrap.dedent(
            """
            from painted import run_cli

            runners = {}
            runners["go"] = run_cli

            def site(argv):
                return runners["go"](argv, fetch=lambda: {},
                                     render=lambda ctx, d: None)
            """
        )
    )
    aliases = _local_aliases_for(tree, "run_cli")
    classified = _boundary_runner_bindings(tree, "evasion.py", aliases, "run_cli")
    assert len(classified) == 1, classified
    assert "container (subscript assignment)" in classified[0]
    # Still honestly out of scope: the call through the subscript is not
    # walked, and the census is what makes that position visible.
    assert _run_cli_calls(tree, aliases) == []


def test_rule12_counts_an_attribute_registry_assignment():
    """The sibling spelling — ``registry.go = run_cli`` — has the same shape
    and the same hole, so it is counted the same way."""
    tree = ast.parse(
        textwrap.dedent(
            """
            from painted import run_cli

            class Registry:
                pass

            registry = Registry()
            registry.go = run_cli
            """
        )
    )
    aliases = _local_aliases_for(tree, "run_cli")
    classified = _boundary_runner_bindings(tree, "evasion.py", aliases, "run_cli")
    assert len(classified) == 1, classified
    assert "container (attribute assignment)" in classified[0]


def test_rule12_subscript_census_ignores_unrelated_assignments():
    """The floor: storing something that is NOT the runner into a container is
    ordinary code and must not enter the census."""
    tree = ast.parse(
        textwrap.dedent(
            """
            from painted import run_cli

            config = {}
            config["width"] = 80
            config["name"] = "loops"
            """
        )
    )
    aliases = _local_aliases_for(tree, "run_cli")
    assert _boundary_runner_bindings(tree, "e.py", aliases, "run_cli") == []
