"""Residence ratchet — every tasks-vertex read must name its store.

friction:tasks-read-write-residence-split. The tasks vertex is *packaged*
(it ships inside the installed strange-loops package) while its store is
*workspace-relative* (named by the cwd). So a reader that resolves the store
from the vertex path silently reads the packaged-adjacent store instead of
the workspace one the writers appended to. The fix at each call site is to
pass ``store=workspace_store(vp)``.

That fix has been missed twice (b7d44c0, then 88fe23b). Per CLAUDE.md's
ratchet test, the durable form is structural, not review vigilance: enumerate
every ``engine.vertex_*`` call in ``apps/tasks`` and require ``store=``,
with a shrink-only allowlist for the sites that are legitimately
package-relative on *both* sides (the ``project`` vertex, whose writers use
``store_path_for("project")``).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "strange_loops"

# Readers that resolve a store from the vertex path unless told otherwise.
_READERS = {"vertex_facts", "vertex_ticks", "vertex_summary", "vertex_read"}

# Shrink-only allowlist: (module path relative to _SRC, enclosing function,
# callee) -> why this site may omit ``store=``. Entries may be removed, never
# added without a reviewed reason — and a stale entry fails the second test.
_PACKAGE_RELATIVE: dict[tuple[str, str, str], str] = {
    ("commands/dashboard.py", "_project_summary", "vertex_summary"): (
        "project vertex — writers use store_path_for('project'), package-relative on both sides"
    ),
    ("commands/project.py", "fetch_project_status", "vertex_read"): "project vertex",
    ("commands/project.py", "fetch_project_status", "vertex_summary"): "project vertex",
    ("commands/project.py", "fetch_project_log", "vertex_facts"): "project vertex",
    ("commands/project.py", "cmd_project_bridge", "vertex_facts"): (
        "reads the project vertex (the bridge's tasks-vertex read passes store=)"
    ),
}


def _call_sites() -> list[tuple[tuple[str, str, str], int, bool]]:
    """Every _READERS call under apps/tasks/src as (key, lineno, has_store)."""
    sites: list[tuple[tuple[str, str, str], int, bool]] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else None
                )
                if name not in _READERS:
                    continue
                has_store = any(kw.arg == "store" for kw in call.keywords)
                sites.append(((rel, node.name, name), call.lineno, has_store))
    return sites


def test_tasks_vertex_reads_name_their_store():
    """Rule: no un-allowlisted vertex_* read may resolve its own store."""
    sites = _call_sites()
    assert sites, "the AST walk found no vertex_* calls — the ratchet went blind"

    offenders = [
        f"{rel}:{lineno} {func}() -> {callee}(...) without store="
        for (rel, func, callee), lineno, has_store in sites
        if not has_store and (rel, func, callee) not in _PACKAGE_RELATIVE
    ]
    assert not offenders, (
        "tasks-vertex reads must pass store=workspace_store(vp) — the vertex is "
        "packaged, the store is workspace-relative (friction:tasks-read-write-"
        "residence-split):\n  " + "\n  ".join(offenders)
    )


def test_residence_allowlist_is_shrink_only():
    """Every allowlist entry must still name a real store-less call site."""
    live = {key for key, _lineno, has_store in _call_sites() if not has_store}
    stale = sorted(key for key in _PACKAGE_RELATIVE if key not in live)
    assert not stale, (
        "stale residence allowlist entries — the call site moved, was renamed, "
        "or already passes store=. Remove them; the allowlist only shrinks:\n  "
        + "\n  ".join(str(k) for k in stale)
    )
