"""Rule 10: disclosure renderers do no store I/O."""

from __future__ import annotations

import ast

from ._helpers import (
    REPO_ROOT,
    _CallNameCollector,
)

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
