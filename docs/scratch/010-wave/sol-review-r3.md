# Sol HIGH review — 0.10.0 wave round 3 (closing verification)

Reviewed `git diff 05b4247...HEAD` at `0a3fb43`, comprising the r3 fix
merge (`cad6211`, `6523c07`, `c9307b2`) and hygiene.

## Closing verdict

- **CLOSED:** 3
- **PARTIAL:** 3
- **NOT-CLOSED:** 0
- **Overall convergence: DOES NOT CLOSE**

The production snapshot defect and two ratchet-hardening items converge.
Three ordinary Python/repository shapes still pass silently:

1. a function-local import can shadow a clean outer `renderer` definition;
2. assigning `run_cli` into a registry subscript is neither followed nor
   counted by the boundary census;
3. Python placed beside an existing `apps/*/src/` directory passes the
   source-layout completeness rule while remaining outside both derivations.

These are not machinery-generates-machinery hardening or deliberately
obfuscated smuggling. They are direct, honest-code-shaped constructions, and
the latter two defeat the specific countability/completeness claims added in
r3. They therefore block the 090 convergence condition.

## 1. `vertex_fold()` one-snapshot bracket — CLOSED

Implementation:
`libs/engine/src/engine/vertex_reader.py:1155-1215`

The `StoreReader.snapshot()` bracket encloses every contributing single-store
read: declared-kind facts, kind statistics, `live_edge()`, and the explicit
undeclared `kind` fallback.

### R2 replay

The exact r2 interleaving appends an unsealed `"after"` fact immediately before
`live_edge()`. The merged regression passed:

```text
test_fold_rows_and_edge_describe_one_commit PASSED
returned pair: (["before"], 0)
```

The fold rows pin the deferred transaction before the concurrent commit, and
the edge read remains on that same snapshot.

### One fresh attempt

I moved the append later: immediately before
`facts_by_kind("surprise")` in the explicit undeclared-`kind` fallback, after
the fold rows and edge metadata had already been read. Without an encompassing
snapshot this can produce a new `"surprise"` row with the old zero edge.

Observed:

```text
hook_fired: True
surprise payloads: []
edge_facts: 0
edge_since: None
```

The late row remained invisible to the fallback read. This is the coherent
pre-commit result; the post-commit result would contain the row and report one
edge fact.

Verdict: **CLOSED**.

## 2. Rule 12 shadowing fail-closed — PARTIAL

Implementation: `tests/test_architecture.py:1450-1532`

### R2 replay

The r3 regression replayed all twelve requested shadows:

```text
assignment, parameter, tuple unpack, dict subscript, getattr,
partial, decorator, for target, with target, comprehension target,
class-body assignment, global declaration
```

Every shape now returns `resolved == 0` with one fail-closed
`unresolvable` finding. The grouped regression passed.

### One fresh attempt

A local import is also a Python local binding, but `_lexical_bindings()` does
not index `Import` or `ImportFrom` aliases as shadows:

```python
def renderer(data, fidelity, width):
    return None

def site(argv):
    from evapp.views import bad as renderer
    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
```

Here `bad` is repository-local and declares `piped`. This is a normal command
override shape: the module supplies a default renderer and one function imports
a specialized renderer under the same local name.

Observed scanner result:

```text
_RendererScan(
    piped=[],
    unresolvable=[],
    resolved=1,
    external=0,
)
```

The resolver looks past the actual local binding and resolves the clean outer
definition, recreating the r2 false-green class. `tests/test_architecture.py:
1492-1521` enumerates many binding forms but omits imports.

Verdict: **PARTIAL**. The twelve named shapes close, but ordinary local import
binding remains a silent evasion.

## 3. Rule 12 boundary census, baseline zero — PARTIAL

Implementation: `tests/test_architecture.py:1340-1430,1804-1842`

### R2 replay

The exact four out-of-scope aliases are now classified:

```text
registry = {"go": run_cli}             -> container (dict)
reflective = getattr(painted, "run_cli") -> reflective (getattr)
wrapped = decorate(run_cli)            -> higher-order call
partialed = functools.partial(run_cli) -> higher-order call
```

The replay produced four census entries. With
`_RUNNER_BOUNDARY_BASELINE = 0`, any such repository addition fails the
cardinality assertion. The merged regression passed.

### One fresh attempt

The equally ordinary incremental registry spelling is not counted:

```python
runners = {}
runners["go"] = run_cli
runners["go"](..., render=...)
```

Observed:

```text
aliases: ["run_cli"]
boundary census: []
render violations: []
run_cli calls seen: 0
```

At `tests/test_architecture.py:1407-1412`, the census skips a plain callable
RHS as “modelled.” But `_local_aliases_for()` cannot bind a name from the
subscript target, and `_run_cli_calls()` cannot follow the later subscript
call. The boundary is therefore neither modelled nor counted.

This is not a counted deliberate-indirection residue under the arbiter ruling:
the r3 mechanism reports population zero.

Verdict: **PARTIAL**.

## 4. Renderer allowlist mechanics — CLOSED

Implementation: `tests/test_architecture.py:1688-1691,1735-1747,1867-1902`

### R2 replay

All three r2 mechanics are closed:

- the allowlist is `dict[path, reason]`;
- cardinality is pinned to baseline zero;
- resolved `piped` findings and unresolvable findings are separate buckets,
  and allowlisting suppresses only the latter.

The regression containing one resolved `piped` renderer and one unresolvable
renderer passed: the allowlist path can reach only `scan.unresolvable`;
`scan.piped` is appended unconditionally.

### One fresh attempt

A whitespace-only reason fails `reason and reason.strip()`. Adding one
otherwise valid path with prose also exceeds the zero baseline until the
baseline is deliberately edited. Both conditions fail before suppression is
applied.

Verdict: **CLOSED**.

## 5. Hostile `Window` sentinels — CLOSED

Implementation and ratchets:
`apps/loops/tests/test_surface.py:1222-1292,1295-1350`

### R2 replay

The exact transformations are no longer fixed points:

```text
query.strip().lower() != query sentinel
sorted(fields) != fields sentinel
```

Strings have surrounding whitespace and mixed case. Tuple sentinels have three
distinct hostile elements in neither ascending nor descending order. Numeric
sentinels are negative and away from zero/one. The structural hostility test
and the wire-value test both passed.

### One fresh attempt

I tried a plausible whitespace normalizer:

```python
" ".join(window.query.split())
```

Observed:

```text
input:  "  MiXeD Query STRING  "
output: "MiXeD Query STRING"
caught: True
```

No further transform family was chased. Defeating a finite value vector always
remains possible with a tailored fixed-point transform; under the closing
ruling, machinery that attempts to prove every possible transform costs more
than the drift risk guarded here.

Verdict: **CLOSED**.

## 6. Underscore packages and source-layout completeness — PARTIAL

Implementation: `tests/test_architecture.py:41-93,349-393`

### R2 replay

Both exact r2 exclusions are caught:

- `_app_names()` includes `_nsapp` and `_solo`;
- an app containing Python with no `src/` directory is returned by
  `_app_dirs_missing_src()`.

Both merged regressions passed.

### One fresh attempt

The completeness check proves only that an app containing any Python also has
a directory named `src`; it does not prove that the Python is under that
directory:

```text
apps/
  mixed/
    src/
      README.md
    flatpkg/
      __init__.py
      main.py
```

Observed:

```text
_app_names(apps): ()
_app_dirs_missing_src(apps): []
```

`tests/test_architecture.py:355-359` finds Python anywhere under the app, then
accepts the app solely because `app_dir / "src"` exists. The flat package
remains outside `APPS` and `_source_roots`, so Rule 3 and Rule 12 both miss it.
An empty, docs-only, or partially migrated `src/` beside misplaced Python is an
ordinary repository state, not deliberate smuggling.

Verdict: **PARTIAL**.

## Suite and hygiene receipts

All requested suites are green:

```text
apps/loops/tests:           2403 passed, 1 xfailed
libs/engine/tests:          1137 passed
apps/tasks/tests:            258 passed (101 deprecation warnings)
libs/atoms/tests:            440 passed
tests/test_architecture.py:    36 passed
```

The initial combined targeted invocation encountered pytest's duplicate
`tests.conftest` import-path collision; rerunning the targets as their normal
separate suite invocations passed.

No product or test source was changed in this verification. This report is the
only new file from the review; the pre-existing untracked
`docs/scratch/010-wave/sol-review-brief-r3.md` was left untouched.
