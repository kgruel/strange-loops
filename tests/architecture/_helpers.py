"""Shared infrastructure for architecture boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]


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
# Ambiguity opt-out collector
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Call name collector
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Renderer scan record
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Production file inspection helpers
# ---------------------------------------------------------------------------

_PRODUCTION_DIRS = ("libs", "apps")


def _has_python(directory: Path) -> bool:
    """Whether a directory holds any Python outside ``__pycache__``.

    Short-circuits on the first hit — this walks trees like ``docs/`` and
    ``experiments/`` that are large and mostly not Python.
    """
    for py in directory.rglob("*.py"):
        if "__pycache__" not in py.parts:
            return True
    return False


def _production_src_files(repo: Path | None = None) -> list[Path]:
    """Every shipped source file — ``libs/*/src`` plus ``apps/*/src``."""
    root = REPO_ROOT if repo is None else repo
    files: list[Path] = []
    for production in _PRODUCTION_DIRS:
        base = root / production
        if not base.is_dir():
            continue
        for package in sorted(base.iterdir()):
            if package.is_dir() and not package.name.startswith("."):
                files.extend(_src_py_files(package))
    return files


# ---------------------------------------------------------------------------
# Dynamic import collector
# ---------------------------------------------------------------------------

_DYNAMIC_IMPORT_CALLS = frozenset({"import_module", "__import__"})
_DYNAMIC_LOADER_CALLS = frozenset({"spec_from_file_location"})


def _static_module_name(node: ast.expr) -> str | None:
    """The module name a dynamic-import argument determines, or None.

    Two forms are honest static text and get resolved:

    * a plain string constant — ``import_module("tools._conformance")``;
    * an f-string whose LEADING literal already contains a ``.``, e.g.
      ``f"loops.lenses.{name}"``. The placeholder cannot change the top-level
      package once a dot has been passed, so the root is determined even though
      the full name is not.

    Everything else — a bare variable, a concatenation, an f-string that
    interpolates before the first dot — is a computed name. This function does
    not guess at those; the caller classifies and counts them.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if "." in first.value:
                return first.value
    return None


class _DynamicImportCollector(ast.NodeVisitor):
    """Runtime dynamic-import calls, split by whether the target is static.

    ``literal`` — the imported name is fixed by the source text, so the rule
    can resolve it and MUST judge it. This is honest code: nothing about
    ``importlib.import_module("tools._conformance")`` is obfuscated, and it was
    invisible to the r1 rule only because :class:`_ImportCollector` implements
    ``visit_Import``/``visit_ImportFrom`` and no call handling at all
    (sol MEDIUM r2).

    ``computed`` — the name is assembled at runtime. Following those means
    evaluating strings, which is the "whole-program analysis wearing a test's
    name" the arbiter convergence ruling forbids chasing. They are a CLASSIFIED
    BOUNDARY: not chased, but enumerated and counted, exactly as Rule 12
    handles container/getattr/partial forms.

    TYPE_CHECKING blocks are exempt, matching :class:`_ImportCollector`: the
    call never executes, so it creates no runtime dependency to invert.
    """

    def __init__(self) -> None:
        self.literal: list[tuple[str, int]] = []  # (module, lineno)
        self.computed: list[tuple[str, int]] = []  # (call description, lineno)
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

    @staticmethod
    def _called_name(func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_type_checking:
            self.generic_visit(node)
            return
        name = self._called_name(node.func)

        if name in _DYNAMIC_LOADER_CALLS:
            self.computed.append((f"{name}() — path-based loader", node.lineno))
            self.generic_visit(node)
            return

        if name in _DYNAMIC_IMPORT_CALLS:
            arg = node.args[0] if node.args else None
            module = _static_module_name(arg) if arg is not None else None
            if module is None:
                self.computed.append((f"{name}() — computed module name", node.lineno))
            elif module.startswith("."):
                # A relative dynamic import resolves against `package=`.
                pkg = next(
                    (kw.value for kw in node.keywords if kw.arg == "package"), None
                )
                anchor = _static_module_name(pkg) if pkg is not None else None
                if anchor is None:
                    self.computed.append(
                        (f"{name}() — relative, computed anchor", node.lineno)
                    )
                else:
                    self.literal.append((anchor, node.lineno))
            else:
                self.literal.append((module, node.lineno))

        self.generic_visit(node)


def _collect_dynamic_imports(path: Path) -> _DynamicImportCollector:
    """Parse a file and return its dynamic-import collector."""
    collector = _DynamicImportCollector()
    collector.visit(ast.parse(path.read_text(), filename=str(path)))
    return collector
