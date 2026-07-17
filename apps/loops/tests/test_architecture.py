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
   keyword — only ``renderer=``.
2. No raw terminal-width probe (``shutil.get_terminal_size`` /
   ``os.get_terminal_size``) is read without an ``isatty`` check in the
   same enclosing function — the shape that would let a caller reconstruct
   a concrete width by hand for what should be a piped, width-free render.
   (Two of apps/loops's three such probes are in ``cli/dispatch.py`` and
   ``cli/output.py`` — the Operation-IR pilot path used by fold/emit/read/
   cite, which does not go through ``run_cli`` at all, so rule 1 alone
   would not catch a regression there.)

Both allowlists start EMPTY — every current call site is already compliant
(verified 2026-07-17 while building this ratchet).
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


# ---------------------------------------------------------------------------
# Rule 1: run_cli() call sites use renderer=, never the legacy render=
# ---------------------------------------------------------------------------


class _RunCliCallCollector(ast.NodeVisitor):
    """Find ``run_cli(...)`` calls and record which of render=/renderer=
    (or both/neither) each one passes."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, set[str]]] = []  # (lineno, {'render','renderer'})

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_run_cli = (isinstance(func, ast.Name) and func.id == "run_cli") or (
            isinstance(func, ast.Attribute) and func.attr == "run_cli"
        )
        if is_run_cli:
            kw_names = {kw.arg for kw in node.keywords if kw.arg is not None}
            self.calls.append((node.lineno, kw_names & {"render", "renderer"}))
        self.generic_visit(node)


# Shrink-only. Empty — every current run_cli() call site already uses only
# ``renderer=``. A new entry needs the same justification e8643a6 records:
# painted's automatic offered-width guarantee does not cover it, and the
# callback re-derives ctx.width/ctx.is_tty by hand instead.
_RENDER_KWARG_EXCEPTIONS: set[str] = set()


def test_run_cli_sites_use_renderer_not_render():
    """Every ``run_cli(`` call in apps/loops/src passes ``renderer=`` (the
    (data, fidelity, width) contract painted gates on ctx.is_tty for free),
    never the legacy ``render=`` (ctx, data) contract."""
    _check_exceptions(_RENDER_KWARG_EXCEPTIONS)

    violations = []
    for py_file in _py_files(LOOPS_SRC):
        rel = _rel(py_file)
        collector = _RunCliCallCollector()
        collector.visit(ast.parse(py_file.read_text(), filename=str(py_file)))
        for lineno, kwargs in collector.calls:
            if not kwargs:
                # Neither render= nor renderer= — e.g. a fetch_stream-only
                # live delivery call. Not this rule's concern.
                continue
            if "render" in kwargs and rel not in _RENDER_KWARG_EXCEPTIONS:
                violations.append(
                    f"  {rel}:{lineno} — run_cli(render=...) uses the legacy "
                    "(ctx, data) contract; use renderer=(data, fidelity, width) "
                    "instead so painted's offered-width guarantee applies"
                )

    assert not violations, (
        "run_cli() call sites must use renderer=, not the legacy render= "
        "(see module docstring — this is the piped-width-None safety net):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Rule 2: raw terminal-width probes are always isatty-guarded
# ---------------------------------------------------------------------------

_PROBE_NAMES = ("get_terminal_size",)


class _FunctionScopeCollector(ast.NodeVisitor):
    """Collect (name, node) for every function/async-function definition,
    plus module-level statements outside any function."""

    def __init__(self) -> None:
        self.functions: list[ast.AST] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append(node)
        self.generic_visit(node)


# Shrink-only. Empty — the 3 current probes (cli/dispatch.py, cli/output.py,
# cli/views/fold.py) all gate on isatty in the same expression/enclosing
# function already.
_UNGUARDED_PROBE_EXCEPTIONS: set[str] = set()


def test_terminal_size_probes_are_isatty_guarded():
    """Every raw ``get_terminal_size()`` read in apps/loops/src has an
    ``isatty`` check in its enclosing function — the shape that keeps a
    piped/non-tty channel from ever seeing a fabricated concrete width.

    Function-scoped (not line-scoped) because the real guard is often a
    multi-line ternary or an early-return guard clause a few lines above the
    probe, not textually adjacent to it.
    """
    _check_exceptions(_UNGUARDED_PROBE_EXCEPTIONS)

    violations = []
    for py_file in _py_files(LOOPS_SRC):
        rel = _rel(py_file)
        if rel in _UNGUARDED_PROBE_EXCEPTIONS:
            continue
        source = py_file.read_text()
        if not any(name in source for name in _PROBE_NAMES):
            continue
        tree = ast.parse(source, filename=str(py_file))
        collector = _FunctionScopeCollector()
        collector.visit(tree)

        covered_lines: set[int] = set()
        for fn in collector.functions:
            segment = ast.get_source_segment(source, fn) or ""
            if any(name in segment for name in _PROBE_NAMES):
                if "isatty" not in segment:
                    violations.append(
                        f"  {rel}:{fn.lineno} function {fn.name!r} reads "
                        "get_terminal_size() without an isatty guard in scope"
                    )
                covered_lines.update(
                    range(fn.lineno, (fn.end_lineno or fn.lineno) + 1)
                )

        # Module-level occurrences (outside any function) — check the whole
        # file, since there's no enclosing function scope to segment on.
        module_level_hit = any(
            name in line
            for i, line in enumerate(source.splitlines(), start=1)
            if i not in covered_lines
            for name in _PROBE_NAMES
        )
        if module_level_hit and "isatty" not in source:
            violations.append(
                f"  {rel} reads get_terminal_size() at module level without "
                "an isatty guard anywhere in the file"
            )

    assert not violations, (
        "get_terminal_size() must always be isatty-guarded — an unguarded "
        "probe can fabricate a concrete width for a piped channel (see "
        "module docstring):\n" + "\n".join(violations)
    )
