"""Rule 13: production code never imports a non-production root."""

from __future__ import annotations

from pathlib import Path

from ._helpers import (
    REPO_ROOT,
    _PRODUCTION_DIRS,
    _collect_dynamic_imports,
    _collect_imports,
    _has_python,
    _imports_module,
    _production_src_files,
)


def _non_production_roots(repo: Path | None = None) -> tuple[str, ...]:
    """Top-level import names that are NOT production, derived from the tree.

    Derived rather than hand-listed, same reason as :func:`_lib_names` and
    :func:`_app_names`: a hand-written mirror is a silent pass for every
    directory added after it was written (docs/RATCHETS.md). ``tools/`` arrived
    in this wave and would have needed remembering; the next one will not.

    Exclusions are by what is GENUINELY not an import root, which is a shorter
    list than the first cut claimed:

    * **dot-prefixed** — ``.venv``, ``.git``. A leading dot is not a legal
      identifier, and ``import_module(".venv")`` is parsed as a *relative*
      import, so these cannot be reached as top-level names by any spelling.
    * **holds no Python** — ``data/``, ``dist/``. Nothing to import; naming
      them would be noise in the failure message and walking them would be
      slow. This is also what keeps ``__pycache__`` out: it holds ``.pyc``,
      never ``.py``.
    * the production dirs themselves, which the other derivations own.

    A DUNDER PREFIX IS NOT AN EXCLUSION, and the r1 docstring's claim that it
    was — "not importable as top-level names" — was simply false. sol MEDIUM r2
    put ``__support__/helper.py`` at the repo root and ``import
    __support__.helper`` in production, and all 52 tests stayed green:
    ``__support__`` is a perfectly legal identifier and a perfectly good import
    root. Only ``__pycache__`` ever motivated the filter, and the has-Python
    test already handles that one on its actual property.
    """
    root = REPO_ROOT if repo is None else repo
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            entry.name
            for entry in root.iterdir()
            if entry.is_dir()
            and not entry.name.startswith(".")
            and entry.name not in _PRODUCTION_DIRS
            and _has_python(entry)
        )
    )


def _top_level(module: str) -> str:
    """The root package of a dotted module name."""
    return module.split(".", 1)[0]


def _production_imports_of_non_production(repo: Path | None = None) -> list[str]:
    """Runtime imports of a non-production root from shipped source.

    Covers both the static forms (``import x`` / ``from x import y``) and the
    dynamic forms whose target is fixed by the source text.
    """
    root = REPO_ROOT if repo is None else repo
    roots = _non_production_roots(root)
    violations: list[str] = []
    for py_file in _production_src_files(root):
        rel = py_file.relative_to(root).as_posix()
        collector = _collect_imports(py_file)
        for name in roots:
            for lineno in _imports_module(collector.runtime_modules, name):
                violations.append(f"  {rel}:{lineno} — imports non-production root {name!r}")
        for module, lineno in _collect_dynamic_imports(py_file).literal:
            name = _top_level(module)
            if name in roots:
                violations.append(
                    f"  {rel}:{lineno} — dynamically imports non-production "
                    f"root {name!r} ({module!r})"
                )
    return sorted(violations)


def _production_computed_dynamic_imports(repo: Path | None = None) -> list[str]:
    """The classified boundary: dynamic imports whose target is not static."""
    root = REPO_ROOT if repo is None else repo
    out: list[str] = []
    for py_file in _production_src_files(root):
        rel = py_file.relative_to(root).as_posix()
        for what, lineno in _collect_dynamic_imports(py_file).computed:
            out.append(f"  {rel}:{lineno} — {what}; classified out of scope, not resolved")
    return sorted(out)


# The classified-boundary census, same doctrine as Rule 12's
# _RUNNER_BOUNDARY_BASELINE: out-of-scope indirection is not chased, but the
# population is COUNTED, because a boundary that grows silently is
# indistinguishable from a rule that stopped working.
#
# Unlike Rule 12's, this baseline is NOT zero, and it cannot be: the repo has a
# real, reviewed population of computed dynamic imports. All six were inspected
# when this was set — five lazy-loader registries that resolve module paths out
# of module-level tables of literal strings (atoms, engine and lang's __getattr__
# shims; the CLI's main and cli.registry), plus lens_resolver's
# spec_from_file_location, which loads a user lens by filesystem path. None
# reaches a script tree. Resolving them would mean constant-folding a lookup
# table, which is the dataflow analysis the arbiter ruling declines to build.
#
# Shrink-only. Raising this means a NEW computed dynamic import entered shipped
# code: read it, satisfy yourself it cannot reach a non-production root, then
# raise it deliberately.
_DYNAMIC_IMPORT_BOUNDARY_BASELINE = 6


def test_production_does_not_import_a_non_production_root():
    """Nothing shipped may import ``tools/``, ``benchmarks/``, ``tests/``, ….

    **Why this is not folded into an existing rule.** Rule 4 (the lib DAG) and
    Rule 3 (libs don't import apps) both enumerate their forbidden targets from
    a *production* derivation — ``LIBS`` from ``libs/``, ``APPS`` from
    ``apps/*/src`` — so a top-level ``tools/`` is not in either target set and
    both stay green on an import of it. Widening Rule 4's target set covers only
    half the hole: Rule 4's source set is libs, and apps must not import these
    either, while apps have no allowlist concept for Rule 4 to hang the check on
    (apps import libs freely by construction). The boundary is
    production-vs-non-production, which is a different axis from both, so it
    gets stated once here rather than bolted onto a rule that means something
    else. Rule 11's docstring makes the same argument for coexisting with
    Rule 4.

    sol MEDIUM (2026-07-27) found this the way it had to be found: adding
    ``import tools._conformance`` to ``libs/engine/src/engine/witness.py`` left
    all 46 tests green. The relocation's containment claim rested on "imported
    by nothing" — a fact about today, not a ratchet. This is the ratchet.

    **Dynamic imports count too, when they are honest.** r2 found that
    ``importlib.import_module("tools._conformance")`` and
    ``__import__("tools._conformance")`` both walked straight past the r1 rule.
    Nothing about either is obfuscated — they are the ordinary spelling of a
    lazy import — so a literal argument is judged exactly like a static
    ``import``. A COMPUTED argument is a different thing: following it means
    evaluating strings, so it is classified and counted instead (see
    ``_DYNAMIC_IMPORT_BOUNDARY_BASELINE``), the same split Rule 12 draws
    between modelled bindings and its container/getattr boundary.

    **No allowlist.** The correct number of production imports of a script tree
    is zero, and it is zero today, so there is nothing to grandfather. An
    exception here would be the shape docs/RATCHETS.md warns about: a baseline
    that grows. (The dynamic-import census is a different instrument — it
    counts what the rule declines to resolve, not what it permits.)
    """
    roots = _non_production_roots()
    files = _production_src_files()

    # Countable boundaries — a walk that finds nothing passes vacuously, which
    # is how a derived rule dies quietly (Rule 12's lesson).
    assert roots, (
        "no non-production roots derived — either the repo layout changed or "
        "_has_python stopped finding Python; this rule would pass vacuously"
    )
    assert "experiments" in roots, (
        f"'experiments' missing from the derived non-production roots {roots} — "
        "non-production script and experiment trees must be seen by the derivation"
    )
    assert files, (
        "no production source files walked — _production_src_files went empty, "
        "so this rule would pass against any import"
    )

    # The classified-boundary census, asserted BEFORE the violations so a
    # silently growing boundary cannot hide behind a green violation list.
    boundary = _production_computed_dynamic_imports()
    assert len(boundary) <= _DYNAMIC_IMPORT_BOUNDARY_BASELINE, (
        f"{len(boundary)} dynamic imports in shipped code now take a target "
        "this rule cannot resolve statically (baseline "
        f"{_DYNAMIC_IMPORT_BOUNDARY_BASELINE}). These are NOT automatically "
        "violations — a computed module name is a classified boundary, not an "
        "evasion — but the population may not grow unobserved. Read each, "
        "confirm it cannot reach a non-production root, then raise the "
        "baseline deliberately:\n" + "\n".join(boundary)
    )

    violations = _production_imports_of_non_production()
    assert not violations, (
        "Shipped code imports a non-production root. Those trees are dev "
        f"tooling — {', '.join(roots)} — run under the workspace env and "
        "excluded from the wheel (see [tool.hatch.build] only-include), so a "
        "runtime import of one ships a dangling dependency. Move the code into "
        "a lib or an app:\n" + "\n".join(violations)
    )


def _synthetic_repo_tree(tmp_path: Path, entries: dict[str, str]) -> Path:
    """Write a throwaway repo root and return it."""
    for rel, body in entries.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    return tmp_path


def test_rule13_catches_sols_exact_evasion(tmp_path: Path):
    """sol MEDIUM's construction verbatim: a lib importing ``tools``.

    ``import tools._conformance`` from ``libs/engine`` — the import that passed
    all 46 tests before this rule existed.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/_conformance.py": "LOOPS_ROOT = 1\n",
            "libs/engine/src/engine/witness.py": "import tools._conformance\n",
        },
    )
    assert _non_production_roots(repo) == ("tools",)
    assert _production_imports_of_non_production(repo) == [
        "  libs/engine/src/engine/witness.py:1 — imports non-production root 'tools'"
    ]


def test_rule13_catches_an_app_importing_a_script_tree(tmp_path: Path):
    """The half a widened Rule 4 would have missed: the source is an app.

    Rule 4's source set is libs only, so an app reaching into ``benchmarks/``
    would stay green under any amount of target-set widening there.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "benchmarks/_profile.py": "VALUE = 1\n",
            "apps/loops/src/loops/main.py": "from benchmarks import _profile\n",
        },
    )
    assert _non_production_roots(repo) == ("benchmarks",)
    assert _production_imports_of_non_production(repo) == [
        "  apps/loops/src/loops/main.py:1 — imports non-production root 'benchmarks'"
    ]


def test_rule13_derivation_ignores_python_free_and_hidden_dirs(tmp_path: Path):
    """A directory is a boundary only if it is an import root.

    ``data/`` holds no Python and cannot be imported; ``.venv/`` is not a legal
    top-level name. Naming either would be noise in the failure message, and
    walking ``.venv`` for the rest of the rule would be slow and wrong.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "data/fixture.json": "{}\n",
            ".venv/lib/site.py": "\n",
            "__pycache__/junk.py": "\n",
            "tools/gen.py": "\n",
            "libs/atoms/src/atoms/__init__.py": "\n",
        },
    )
    assert _non_production_roots(repo) == ("tools",)


def test_rule13_ignores_test_trees_and_a_same_named_lib(tmp_path: Path):
    """Two floors at once.

    A lib's own ``tests/`` is not shipped source, so an import there is not a
    production import — ``_production_src_files`` walks ``src`` only. And the
    match is on the top-level import name, so a lib genuinely named ``tools``
    would be matched by ``libs/``'s derivation, not this one: production dirs
    are excluded from the roots before any comparison happens.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/gen.py": "\n",
            "libs/engine/src/engine/store.py": "import atoms\n",
            "libs/engine/tests/test_gen.py": "import tools.gen\n",
        },
    )
    assert _non_production_roots(repo) == ("tools",)
    assert _production_imports_of_non_production(repo) == []


def test_rule13_sees_a_type_checking_import_as_exempt(tmp_path: Path):
    """Matches Rule 4 and Rule 11 exactly: an annotation-only reference creates
    no runtime dependency, and the collector records runtime imports only."""
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/gen.py": "\n",
            "libs/engine/src/engine/x.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    import tools.gen\n"
            ),
        },
    )
    assert _production_imports_of_non_production(repo) == []


def test_rule13_catches_sols_r2_dynamic_import_evasions(tmp_path: Path):
    """sol MEDIUM r2, construction 1: both literal dynamic-import spellings.

    ``importlib.import_module("tools._conformance")`` and
    ``__import__("tools._conformance")`` each left all 52 tests green, because
    ``_ImportCollector`` handles ``visit_Import``/``visit_ImportFrom`` and no
    calls at all. Both are ordinary lazy-import code with a literal argument —
    no computed string, no obfuscation — so both must go red.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/_conformance.py": "LOOPS_ROOT = 1\n",
            "libs/engine/src/engine/witness.py": (
                "import importlib\n"
                '_c = importlib.import_module("tools._conformance")\n'
            ),
            "libs/engine/src/engine/other.py": '_c = __import__("tools._conformance")\n',
        },
    )
    assert _production_imports_of_non_production(repo) == [
        "  libs/engine/src/engine/other.py:1 — dynamically imports "
        "non-production root 'tools' ('tools._conformance')",
        "  libs/engine/src/engine/witness.py:2 — dynamically imports "
        "non-production root 'tools' ('tools._conformance')",
    ]
    # Neither is a boundary member: both targets resolved.
    assert _production_computed_dynamic_imports(repo) == []


def test_rule13_catches_the_from_importlib_import_module_spelling(tmp_path: Path):
    """The match is on the CALL name, not on how importlib was bound.

    ``from importlib import import_module`` makes the call an ``ast.Name``
    rather than an ``ast.Attribute``; the CLI uses this spelling, so a rule that
    only understood the dotted form would miss the one already in the repo.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/gen.py": "\n",
            "apps/loops/src/loops/main.py": (
                "from importlib import import_module\n"
                '_m = import_module("tools.gen")\n'
            ),
        },
    )
    assert _production_imports_of_non_production(repo) == [
        "  apps/loops/src/loops/main.py:2 — dynamically imports "
        "non-production root 'tools' ('tools.gen')"
    ]


def test_rule13_catches_sols_r2_importable_dunder_root(tmp_path: Path):
    """sol MEDIUM r2, construction 2: ``__support__/helper.py`` at the repo top.

    ``__support__`` is a legal identifier and a real import root; Python
    imported it fine while all 52 tests passed, because the r1 derivation
    excluded every ``__``-prefixed name on a rationale that was false.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "__support__/helper.py": "VALUE = 1\n",
            "libs/engine/src/engine/witness.py": "import __support__.helper\n",
        },
    )
    assert _non_production_roots(repo) == ("__support__",)
    assert _production_imports_of_non_production(repo) == [
        "  libs/engine/src/engine/witness.py:1 — imports non-production root "
        "'__support__'"
    ]


def test_rule13_pycache_is_not_a_false_positive(tmp_path: Path):
    """Dropping the dunder filter must not resurrect ``__pycache__``.

    It was the only directory that filter was ever really for. It is excluded
    on its actual property instead — it holds ``.pyc``, never ``.py`` — which is
    the same test that excludes ``data/`` and ``dist/``. Belt and braces: even a
    stray ``.py`` inside one is skipped, because ``_has_python`` ignores any
    path with ``__pycache__`` in it.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "__pycache__/helper.cpython-313.pyc": "",
            "tools/gen.py": "\n",
            "libs/atoms/src/atoms/__init__.py": "\n",
        },
    )
    assert _non_production_roots(repo) == ("tools",)

    stray = _synthetic_repo_tree(
        tmp_path / "stray", {"__pycache__/oops.py": "\n", "tools/gen.py": "\n"}
    )
    assert _non_production_roots(stray) == ("tools",)


def test_rule13_computed_dynamic_import_is_classified_not_flagged(tmp_path: Path):
    """A computed target is a boundary member, not a violation.

    The rule declines to evaluate strings — that is the arbiter's ruling, not an
    oversight — so this must neither be silently dropped nor reported as an
    evasion. It lands in the census, where the population is counted.
    """
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/gen.py": "\n",
            "libs/engine/src/engine/lazy.py": (
                "import importlib\n"
                "def load(path):\n"
                "    return importlib.import_module(path)\n"
            ),
        },
    )
    assert _production_imports_of_non_production(repo) == []
    assert _production_computed_dynamic_imports(repo) == [
        "  libs/engine/src/engine/lazy.py:3 — import_module() — computed module "
        "name; classified out of scope, not resolved"
    ]


def test_rule13_resolves_an_fstring_prefix_past_the_first_dot(tmp_path: Path):
    """``f"loops.lenses.{name}"`` fixes its ROOT even though the full name floats.

    A placeholder after the first dot cannot change the top-level package, so
    this resolves rather than joining the census — which is what keeps the two
    real lens_resolver call sites out of the baseline. The mirror case, where
    interpolation happens BEFORE any dot, stays computed.
    """
    resolved = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/gen.py": "\n",
            "libs/engine/src/engine/a.py": (
                "import importlib\n"
                'def f(n): return importlib.import_module(f"tools.sub.{n}")\n'
            ),
        },
    )
    assert _production_imports_of_non_production(resolved) == [
        "  libs/engine/src/engine/a.py:2 — dynamically imports non-production "
        "root 'tools' ('tools.sub.')"
    ]
    assert _production_computed_dynamic_imports(resolved) == []

    floating = _synthetic_repo_tree(
        tmp_path / "floating",
        {
            "tools/gen.py": "\n",
            "libs/engine/src/engine/b.py": (
                "import importlib\n"
                'def f(p): return importlib.import_module(f"{p}.sub")\n'
            ),
        },
    )
    assert _production_imports_of_non_production(floating) == []
    assert len(_production_computed_dynamic_imports(floating)) == 1


def test_rule13_dynamic_import_in_type_checking_is_exempt(tmp_path: Path):
    """Matches Rule 4, Rule 11 and the static half of this rule: a call that
    never executes creates no runtime dependency, and is not a boundary member
    either."""
    repo = _synthetic_repo_tree(
        tmp_path,
        {
            "tools/gen.py": "\n",
            "libs/engine/src/engine/x.py": (
                "import importlib\n"
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                '    _a = importlib.import_module("tools.gen")\n'
                "    _b = importlib.import_module(SOMETHING)\n"
            ),
        },
    )
    assert _production_imports_of_non_production(repo) == []
    assert _production_computed_dynamic_imports(repo) == []
