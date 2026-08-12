# sol MEDIUM review — Track B round 3

Review date: 2026-07-27

Reviewed:

- loops `f59eed2...ae0911e` (single implementation commit `ae0911e`;
  `ce06ed5` and `5012e24` ignored as arbiter receipts)
- loops-go unchanged at `590e70f` on `feat/track-b-batch`

## Overall verdict

**PASS — TRACK B CONVERGED.**

Both Rule 13 constructions from r2 are closed under exact replay. The new
computed-import census has the ratified population of six, its members and
ordering are correct, the two `lens_resolver` f-string imports resolve outside
the census, and the `__pycache__` exclusion remains non-vacuous without
reintroducing the dunder-root hole.

## Pure replay

### 1. Literal dynamic imports — CLOSED

I independently appended each r2 construction to
`libs/engine/src/engine/witness.py`.

With:

```python
import importlib
_conformance = importlib.import_module("tools._conformance")
```

the architecture suite went red with Rule 13 naming
`libs/engine/src/engine/witness.py:828` as dynamically importing the
non-production root `tools`. Result: **1 failed, 58 passed**.

After reverting that construction, with:

```python
_conformance = __import__("tools._conformance")
```

the same rule went red and named
`libs/engine/src/engine/witness.py:827`. Result:
**1 failed, 58 passed**.

Both literal dynamic-import spellings are therefore judged like their static
equivalent, and neither enters the computed-import boundary.

### 2. Importable dunder root — CLOSED

I recreated the r2 package and production import:

```text
__support__/helper.py
libs/engine/src/engine/witness.py: import __support__.helper
```

Python imported the helper successfully and printed its sentinel value. The
architecture suite nevertheless went red with Rule 13 deriving `__support__`
as a non-production root and naming the witness import. Result:
**1 failed, 58 passed**.

The temporary import, helper, generated `.pyc`, and directories were removed.
`witness.py` has no remaining diff.

## Computed-import census

The committed census reports exactly the ratified baseline of six:

| Member | Classification check |
|---|---|
| `apps/loops/src/loops/cli/registry.py:107` | computed `import_module(module_path)`; the callers populate it with production view-module strings |
| `apps/loops/src/loops/lens_resolver.py:408` | `spec_from_file_location(module_name, path)`; intentionally path-based user-lens loading |
| `apps/loops/src/loops/main.py:73` | computed `import_module(mod)` from the production-only `_REEXPORTS` table |
| `libs/atoms/src/atoms/__init__.py:133` | computed `import_module(module_path)` from `_LAZY_IMPORTS` |
| `libs/engine/src/engine/__init__.py:302` | computed `import_module(module_path)` from `_LAZY_IMPORTS` |
| `libs/lang/src/lang/__init__.py:147` | computed `import_module(module_path)` from `_LAZY_IMPORTS` |

All six calls exist at the cited sites and match the ratified classification;
no member is misclassified.

The boundary-length assertion is evaluated before
`_production_imports_of_non_production()` builds and asserts the violation
list, so growth cannot hide behind an otherwise empty violation result.

The two calls at `apps/loops/src/loops/lens_resolver.py:161` and `:440` use
`f"loops.lenses.{name}"`. `_static_module_name` returns the leading literal
`loops.lenses.`, whose first dot fixes the top-level package as `loops`.
Collector inspection showed both in `literal` and neither in `computed`; only
the path loader at line 408 remains a census member. This refinement is
correct.

## `__pycache__` spot-check

The dunder-name filter is gone. `_has_python` instead ignores every `.py` path
whose parts contain `__pycache__`, which excludes both the ordinary
`.pyc`-only directory and the belt-and-braces synthetic case containing a
stray `__pycache__/oops.py`.

The focused regression
`test_rule13_pycache_is_not_a_false_positive` passed, as did the f-string and
both replay regression tests: **4 passed**.

## Non-blocking note

One wording slip jumps out without affecting behavior: the
`_DynamicImportCollector` docstring says the literal
`importlib.import_module("tools._conformance")` call “is obfuscated.” The test
docstrings, Rule 13 explanation, and implementation correctly treat it as
**not** obfuscated. This is editorial and does not block convergence.

## Committed-state close

After all perturbations were reverted:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -q
59 passed in 2.44s
```

No loops-go rerun was needed because it is unchanged this round.

## Final convergence verdict

**PASS — TRACK B BATCH CONVERGED.**

The r2 contact round's two remaining Rule 13 findings are closed, the requested
new assertions are correctly classified and exercised, and the committed
loops suite is green.
