"""Architecture boundary tests — enforce dependency rules across the monorepo.

AST-based: parses source files for import statements, no runtime imports needed.
TYPE_CHECKING-aware: imports guarded by `if TYPE_CHECKING:` are excluded from
runtime rules (engine → atoms uses this pattern).

Run: uv run pytest tests/test_architecture.py -v
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LIBS = ("atoms", "engine", "lang", "painted", "store")
APPS = ("loops", "hlab", "strange_loops")


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
        # TODO: migrate to vertex_facts
        "apps/loops/src/loops/pop_store.py",
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
    """Apps must not import sqlite3 directly."""
    violations = []
    for app_dir in (REPO_ROOT / "apps").iterdir():
        if not app_dir.is_dir():
            continue
        for py_file in _src_py_files(app_dir):
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

    assert not violations, (
        "Libs must not import from apps:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 4: Lib dependency DAG
# ---------------------------------------------------------------------------

# Allowed runtime imports between libs.
# Everything not listed here is forbidden.
_LIB_ALLOWED_RUNTIME: dict[str, set[str]] = {
    "atoms": set(),
    "lang": set(),
    "painted": set(),
    "store": set(),
    "engine": {
        "lang",   # program.py, compiler.py — lang provides AST types
        "atoms",  # function-local lazy imports in compiler.py, vertex.py, program.py
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
        ("libs/painted/src/painted/_timer.py", "FrameRecord"),  # timing accumulator
        # TODO: freeze — these are config/output holders, not accumulators
        ("libs/atoms/src/atoms/source.py", "Source"),
        ("libs/engine/src/engine/compiler.py", "CompiledVertex"),
        ("libs/engine/src/engine/stream.py", "Tap"),
        ("libs/lang/src/lang/validator.py", "Shape"),
        ("libs/lang/src/lang/errors.py", "Location"),
        ("libs/painted/src/painted/buffer.py", "CellWrite"),
        ("libs/painted/src/painted/fidelity.py", "CliRunner"),
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
