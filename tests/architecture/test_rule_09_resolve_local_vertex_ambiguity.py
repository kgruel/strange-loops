"""Rule 9: every resolve_local_vertex caller handles the ambiguity refusal."""

from __future__ import annotations

import ast

from ._helpers import (
    REPO_ROOT,
    _OptOutCallCollector,
    _rel,
    _src_py_files,
)

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
