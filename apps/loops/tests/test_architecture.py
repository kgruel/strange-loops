"""Architecture-style ratchets, scoped to apps/loops (mirrors the repo-root
``tests/test_architecture.py`` — AST-based, no runtime imports needed).

## Terminal-width probes stay isatty-guarded (S0, 0.8.0 TUI migration net)

painted's ``run_cli`` offers exactly one width-computation seam:
``_offered_width`` (installed ``painted/cli/runner.py``) — geometry at a real
viewport, ``None`` at a pipe or file redirect. Every call site on the
``renderer=`` contract gets that for free, and repo-root **Rule 12** enforces
that every ``run_cli`` site in every app and lib is on it.

This file keeps the half Rule 12 cannot see. apps/loops has a second render
path — the Operation-IR pilot used by fold/emit/read/cite — that never goes
through ``run_cli`` at all and computes its own width. Three raw
``shutil.get_terminal_size`` probes live there (``cli/dispatch.py``,
``cli/output.py``, ``cli/views/fold.py``). The rule: every such probe has a
real ``isatty`` reference (an actual ``Name``/``Attribute`` AST node, not a
text substring) in its enclosing function — the shape that would otherwise
let a caller reconstruct a concrete width by hand for what should be a piped,
width-free render.

The historical lesson both rules descend from: commit e8643a66 ("apply
GPT-5.5 codex adversarial review") fixed ``store``/``store stats`` renderers
that passed ``ctx.width`` unconditionally, clipping the piped/agent channel
to an inherited ``COLUMNS`` value. The project store recorded it as "caller
discipline, not an invariant" (0.8.0 S3 panel review, Amendment 3).
0.10.0 S1 finished converting it: the ``render=`` sites are gone repo-wide
and the ``piped=`` kwarg they justified is deleted, so the register is now
the offered width itself. See the Rule 12 preamble in
``tests/test_architecture.py``.

### Residual risk accepted, not covered by this rule

Static/AST-based, stopping short of true control-flow analysis — matching the
repo-root file's own scope:

- **Dead-branch guards** — an ``isatty`` reference inside an ``if False:``
  block (or any other statically-unreachable branch) still counts as
  "present in the enclosing function", because Python's AST does not prune
  unreachable code. Closing this requires control-flow analysis, which is out
  of scope here; in practice an ``isatty`` reference only ever shows up
  because someone wrote a real guard, not as camouflage.

The allowlist starts EMPTY — every current probe is already compliant
(verified 2026-07-17 while building this ratchet, re-verified 2026-07-26 when
the run_cli half moved to the repo root).
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
    ``from shutil import get_terminal_size as gts`` still recognizes ``gts()``
    as a terminal-size probe. Always includes the bare name itself (an
    unaliased import, or the case with no matching import at all —
    module-attribute calls like ``shutil.get_terminal_size(...)`` are matched
    separately, on ``Attribute.attr``, regardless of aliasing)."""
    aliases = {imported_name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == imported_name:
                    aliases.add(alias.asname or alias.name)
    return aliases


# ---------------------------------------------------------------------------
# Raw terminal-width probes are always isatty-guarded
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
