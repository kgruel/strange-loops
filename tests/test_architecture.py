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

LIBS = ("atoms", "custody", "engine", "lang", "sign", "store")
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
            opted_out = any(
                kw.arg == "allow_ambiguous"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
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
                    f"  {key} calls {callee}(allow_ambiguous=True)"
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


class _ImportAliasCollector(ast.NodeVisitor):
    """Local name → originally-imported symbol, across the whole module.

    ``from engine import declaration_generation as dg`` records ``dg`` →
    ``declaration_generation``. Without this, renaming at the import site was
    enough to walk past the rule (sol round 2 evasion 1) — the check has to
    match on what a name RESOLVES to, not how the call site spells it.
    Function-local imports count: this module imports inside function bodies by
    convention, which is exactly where such an alias would live.
    """

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            self.aliases[a.asname or a.name] = a.name
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            if a.asname:
                # `import engine.vertex_reader as vr` — the tail is what
                # attribute calls off it would resolve against.
                self.aliases[a.asname] = a.name.rsplit(".", 1)[-1]
        self.generic_visit(node)


class _CallNameCollector(ast.NodeVisitor):
    """Call names in a function body, resolved through import aliases.

    Collects ``f()`` and ``m.f()``. Each name is recorded BOTH as written and
    as the symbol it was imported under, so an alias cannot hide an anchor.
    """

    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        self.names: set[str] = set()
        self._aliases = aliases or {}

    def _record(self, name: str) -> None:
        self.names.add(name)
        origin = self._aliases.get(name)
        if origin:
            self.names.add(origin)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            self._record(func.id)
        elif isinstance(func, ast.Attribute):
            self._record(func.attr)
        self.generic_visit(node)


def _reachable_functions(
    entry: str, by_name: dict[str, ast.FunctionDef], licensed: set[str],
    aliases: dict[str, str],
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
        collector = _CallNameCollector(aliases)
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
        alias_collector = _ImportAliasCollector()
        alias_collector.visit(tree)
        aliases = alias_collector.aliases

        entry = spec["entry"]
        licensed = set(spec["licensed"])
        assert entry in by_name, f"{rel}: no function named {entry}"
        for name in licensed:
            assert name in by_name, (
                f"{rel}: licensed gatherer {name} is missing — a stale "
                "allowlist entry silently widens this rule"
            )

        violations = []
        for name in _reachable_functions(entry, by_name, licensed, aliases):
            collector = _CallNameCollector(aliases)
            collector.visit(by_name[name])
            for leaked in sorted(collector.names & _STORE_IO_ANCHORS):
                violations.append(f"  {rel}:{name} calls {leaked}")

        assert not violations, (
            "Disclosure render paths must not reach the store — resolving an "
            "anchor at render time is the fetch-then-disclose defect "
            f"(Rule 10). Licensed gatherers for this path: "
            f"{', '.join(sorted(licensed))}.\n" + "\n".join(violations)
        )
