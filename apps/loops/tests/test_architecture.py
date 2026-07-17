"""Architecture-style ratchets, scoped to apps/loops (mirrors the repo-root
``tests/test_architecture.py`` — AST-based, no runtime imports needed).

## The piped ⇒ width=None invariant (S0, 0.8.0 TUI migration safety net)

painted's ``run_cli`` offers exactly one width-computation seam:
``_offered_width`` (installed ``painted/cli/runner.py``) — ``ctx.width if
ctx.is_tty else None``. Every call site using the ``renderer=`` contract
(``(data, fidelity, width) -> Block``) gets this for free: painted computes
``width``, the app never touches ``ctx`` directly, and a piped/non-tty
channel is *structurally* incapable of receiving a concrete width.

The legacy ``render=`` contract (``(ctx, data) -> Block``) has no such
guarantee — the callback reads ``ctx.width``/``ctx.is_tty`` itself, and
historically got this wrong: commit e8643a66 ("apply GPT-5.5 codex
adversarial review") fixed ``store``/``store stats`` renderers that passed
``ctx.width`` unconditionally, clipping the piped/agent channel to an
inherited ``COLUMNS`` value. The project store records the lesson as
"caller discipline, not an invariant" (thread surfaced in the 0.8.0 S3
panel review, docs/scratch/080-overnight/s3-codex-advisor-panel-s3-
constraints.md, Amendment 3). This test converts that discipline into two
enumerable properties so it can't regress silently under the coming
lens-signature migration (which deletes the now-redundant ``piped=`` kwarg
from register-split lenses — safe only once this invariant is enforced,
not just followed).

1. No ``run_cli(`` call site in apps/loops/src uses the legacy ``render=``
   keyword — only ``renderer=``. Aliased imports
   (``from painted import run_cli as rc``) are tracked, and ``**kwargs``
   unpacking into the call (``run_cli(**opts)``) is treated as a violation
   requiring the allowlist, since the keys can't be verified statically.
2. No raw terminal-width probe (``shutil.get_terminal_size`` — aliased
   imports tracked the same way) is read in a function that lacks a real
   ``isatty`` reference (an actual ``Name``/``Attribute`` AST node, not a
   text substring) — the shape that would let a caller reconstruct a
   concrete width by hand for what should be a piped, width-free render.
   (Two of apps/loops's three such probes are in ``cli/dispatch.py`` and
   ``cli/output.py`` — the Operation-IR pilot path used by fold/emit/read/
   cite, which does not go through ``run_cli`` at all, so rule 1 alone
   would not catch a regression there.)

### Residual risk accepted, not covered by either rule

Both rules are static/AST-based and stop short of true data-flow or
control-flow analysis — matching the repo-root ``test_architecture.py``'s
own scope (import/AST shape checks, not execution semantics):

- **Truly dynamic dispatch** — ``getattr(painted, "run_cli")(...)``, a
  function reference threaded through a variable or passed as a callback
  and invoked elsewhere, or ``run_cli`` reassigned to a new name via
  plain assignment (``rc = run_cli``) rather than an import statement — is
  NOT tracked. No current call site does this (every call is a direct
  ``Name``/``Attribute`` call immediately following a ``from painted
  import run_cli [as alias]`` or a ``painted.run_cli(...)``/module-attribute
  form), and introducing indirection at a call site this ratchet exists to
  guard is itself a smell a reviewer should catch — full data-flow analysis
  to close this gap would be disproportionate to a repo-scoped test.
- **Dead-branch guards** — an ``isatty`` reference inside an ``if False:``
  block (or any other statically-unreachable branch) still counts as
  "present in the enclosing function" for rule 2, because Python's AST does
  not prune unreachable code. Closing this requires control-flow analysis,
  which is out of scope here; in practice an ``isatty`` reference only ever
  shows up because someone wrote a real guard, not as camouflage.

Both allowlists start EMPTY — every current call site is already compliant
(verified 2026-07-17 while building this ratchet; re-verified 2026-07-17
after tightening both rules against alias-evasion and substring-matching).
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
LOOPS_SRC = REPO_ROOT / "apps" / "loops" / "src"


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _check_exceptions(exceptions: set[str]) -> None:
    """Assert every allowlisted path still exists — stale entries must go."""
    for exc in exceptions:
        assert (REPO_ROOT / exc).exists(), f"Stale exception: {exc} no longer exists"


def _local_aliases_for(tree: ast.AST, imported_name: str) -> set[str]:
    """Local names that resolve to ``imported_name`` in this file via
    ``from <module> import imported_name [as alias]`` — so
    ``from painted import run_cli as rc`` still recognizes ``rc(...)`` as a
    ``run_cli`` call, and ``from shutil import get_terminal_size as gts``
    still recognizes ``gts()`` as a terminal-size probe. Always includes the
    bare name itself (an unaliased import, or the case with no matching
    import at all — module-attribute calls like ``painted.run_cli(...)``
    are matched separately, on ``Attribute.attr``, regardless of aliasing)."""
    aliases = {imported_name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == imported_name:
                    aliases.add(alias.asname or alias.name)
    return aliases


# ---------------------------------------------------------------------------
# Rule 1: run_cli() call sites use renderer=, never the legacy render=
# ---------------------------------------------------------------------------


class _RunCliCallCollector(ast.NodeVisitor):
    """Find ``run_cli(...)`` calls (including aliased-import forms) and
    record each one's named keywords plus whether it unpacks ``**kwargs``."""

    def __init__(self, run_cli_aliases: set[str]) -> None:
        self._aliases = run_cli_aliases
        # (lineno, {'render','renderer', ...named kwargs...}, has_starstar)
        self.calls: list[tuple[int, set[str], bool]] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_run_cli = (isinstance(func, ast.Name) and func.id in self._aliases) or (
            isinstance(func, ast.Attribute) and func.attr == "run_cli"
        )
        if is_run_cli:
            kw_names = {kw.arg for kw in node.keywords if kw.arg is not None}
            has_starstar = any(kw.arg is None for kw in node.keywords)
            self.calls.append((node.lineno, kw_names, has_starstar))
        self.generic_visit(node)


# Shrink-only. Empty — every current run_cli() call site already uses only
# ``renderer=`` with no **kwargs unpacking. A new entry needs the same
# justification e8643a6 records: painted's automatic offered-width guarantee
# does not cover it, and the callback re-derives ctx.width/ctx.is_tty by hand
# instead (or, for a **kwargs entry, the unpacked keys can't be verified
# statically not to include render=).
_RENDER_KWARG_EXCEPTIONS: set[str] = set()


def test_run_cli_sites_use_renderer_not_render():
    """Every ``run_cli(`` call in apps/loops/src passes ``renderer=`` (the
    (data, fidelity, width) contract painted gates on ctx.is_tty for free),
    never the legacy ``render=`` (ctx, data) contract — and never unpacks
    ``**kwargs`` into the call (unverifiable statically; must be allowlisted
    if ever needed)."""
    _check_exceptions(_RENDER_KWARG_EXCEPTIONS)

    violations = []
    for py_file in _py_files(LOOPS_SRC):
        rel = _rel(py_file)
        if rel in _RENDER_KWARG_EXCEPTIONS:
            continue
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        aliases = _local_aliases_for(tree, "run_cli")
        collector = _RunCliCallCollector(aliases)
        collector.visit(tree)
        for lineno, kw_names, has_starstar in collector.calls:
            if "render" in kw_names:
                violations.append(
                    f"  {rel}:{lineno} — run_cli(render=...) uses the legacy "
                    "(ctx, data) contract; use renderer=(data, fidelity, width) "
                    "instead so painted's offered-width guarantee applies"
                )
            elif has_starstar:
                violations.append(
                    f"  {rel}:{lineno} — run_cli(**...) unpacks keyword "
                    "arguments; cannot statically verify render= isn't among "
                    "them — allowlist if this is intentional"
                )
            # Neither render=/renderer= nor **kwargs, or renderer= cleanly —
            # not this rule's concern (e.g. a fetch_stream-only live call).

    assert not violations, (
        "run_cli() call sites must use renderer=, not the legacy render= "
        "(see module docstring — this is the piped-width-None safety net):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 2: raw terminal-width probes are always isatty-guarded
# ---------------------------------------------------------------------------


class _FunctionScopeCollector(ast.NodeVisitor):
    """Collect every function/async-function definition node."""

    def __init__(self) -> None:
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append(node)
        self.generic_visit(node)


def _calls_probe(node: ast.AST, probe_aliases: set[str]) -> bool:
    """True if *node*'s subtree contains a call to the terminal-size probe —
    either a bare/aliased name (``gts()`` after ``from shutil import
    get_terminal_size as gts``) or a module-attribute call
    (``shutil.get_terminal_size()``, alias-proof since it matches on the
    attribute name regardless of what the module is bound to)."""
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        if isinstance(func, ast.Name) and func.id in probe_aliases:
            return True
        if isinstance(func, ast.Attribute) and func.attr == "get_terminal_size":
            return True
    return False


def _has_isatty_reference(node: ast.AST) -> bool:
    """True if *node*'s subtree contains a real ``isatty`` identifier
    reference — a ``Name`` or an ``Attribute`` access — as opposed to the
    substring appearing only inside a string literal or comment (comments
    aren't in the AST at all; a string constant is an ``ast.Constant``, which
    this deliberately does NOT match on, so a docstring or error message that
    happens to mention "isatty" can't fool this check)."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == "isatty":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "isatty":
            return True
    return False


# Shrink-only. Empty — the 3 current probes (cli/dispatch.py, cli/output.py,
# cli/views/fold.py) all have a real isatty Name/Attribute reference in the
# same enclosing function already.
_UNGUARDED_PROBE_EXCEPTIONS: set[str] = set()


def test_terminal_size_probes_are_isatty_guarded():
    """Every raw ``get_terminal_size()`` read in apps/loops/src (including
    aliased imports) has a real ``isatty`` reference in its enclosing
    function — the shape that keeps a piped/non-tty channel from ever
    seeing a fabricated concrete width.

    Function-scoped (not line-scoped) because the real guard is often a
    multi-line ternary or an early-return guard clause a few lines above the
    probe, not textually adjacent to it. AST-node-based (not substring)
    so a comment or string mentioning "isatty" can't satisfy the guard — see
    the module docstring for the (accepted, documented) dead-branch gap this
    still doesn't close.
    """
    _check_exceptions(_UNGUARDED_PROBE_EXCEPTIONS)

    violations = []
    for py_file in _py_files(LOOPS_SRC):
        rel = _rel(py_file)
        if rel in _UNGUARDED_PROBE_EXCEPTIONS:
            continue
        source = py_file.read_text()
        if "get_terminal_size" not in source:
            continue  # cheap pre-filter; the real check is AST-based below
        tree = ast.parse(source, filename=str(py_file))
        probe_aliases = _local_aliases_for(tree, "get_terminal_size")
        collector = _FunctionScopeCollector()
        collector.visit(tree)

        covered: list[ast.AST] = []
        for fn in collector.functions:
            if _calls_probe(fn, probe_aliases):
                covered.append(fn)
                if not _has_isatty_reference(fn):
                    violations.append(
                        f"  {rel}:{fn.lineno} function {fn.name!r} reads "
                        "get_terminal_size() without a real isatty reference "
                        "in scope"
                    )

        # Module-level occurrences (outside any function) — no enclosing
        # function scope to check, so require isatty anywhere in the module.
        covered_spans = {(fn.lineno, fn.end_lineno) for fn in covered}
        module_level_hit = any(
            isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Name) and n.func.id in probe_aliases)
                or (isinstance(n.func, ast.Attribute) and n.func.attr == "get_terminal_size")
            )
            and not any(
                lo is not None and hi is not None and lo <= n.lineno <= hi
                for lo, hi in covered_spans
            )
            for n in ast.walk(tree)
        )
        if module_level_hit and not _has_isatty_reference(tree):
            violations.append(
                f"  {rel} reads get_terminal_size() at module level without "
                "a real isatty reference anywhere in the file"
            )

    assert not violations, (
        "get_terminal_size() must always be isatty-guarded — an unguarded "
        "probe can fabricate a concrete width for a piped channel (see "
        "module docstring):\n" + "\n".join(violations)
    )
