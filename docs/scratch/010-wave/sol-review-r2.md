# Sol HIGH review — 0.10.0 wave round 2 (verification)

Reviewed `git diff b10515f...HEAD` at `05b4247`
(`merge(010-fix-r1)`).

## Summary

- Round-1 P2s: **1 CLOSED, 4 PARTIAL, 0 NOT-CLOSED**
- Round-1 note: **CLOSED**
- Current actionable residue: **5 P2**
  - four partially closed round-1 ratchet findings;
  - the separately flagged `vertex_fold()` snapshot-coherence race.
- P1: **0**

Every exact round-1 repro/evasion is caught now. The production
`live_edge()` race is fixed. The other four fixes are regression-complete but
not ratchet-complete: new, ordinary Python/data-shape evasions still pass.

## Per-finding verification

### 1. `live_edge()` false-in-every-snapshot count — CLOSED

Production: `libs/engine/src/engine/store_reader.py:245-310`  
Regression tests: `libs/engine/tests/test_store_reader.py:668-761`

The round-1 trace-callback interleaving now returns `(0, None)`, equal to a
fresh post-commit read. Boundary resolution and aggregation are in the same
SQLite statement, so they share one statement snapshot on the one
`StoreReader` connection.

Executed exact regression:

```text
test_concurrent_seal_cannot_produce_an_incoherent_count PASSED
raced == fresh == (0, None)
```

New attacks against the statement-count test:

- A second cursor on the same connection is not an evasion. SQLite's trace
  callback reported both statements.
- `executescript("SELECT 1; SELECT 2;")` is not an evasion. The callback
  reported both constituent statements.
- A **second connection is an evasion of the structural statement-count
  test**. I resolved the boundary on an untraced second connection and ran the
  aggregate on `reader._conn`. The ratchet saw exactly one non-PRAGMA
  statement, while the original concurrent seal produced:

  ```text
  raced: (1, 999.0)
  fresh: (0, None)
  non-PRAGMA statements seen by ratchet: 1
  ```

  This does not reopen the production finding because the paired behavioral
  concurrency regression catches that implementation: `raced != fresh`.
  It does mean `test_live_edge_is_a_single_statement` is not independently a
  construction proof, despite its docstring calling it “the ratchet.” It
  proves one statement on one instrumented connection, not that all reads
  which contribute to the answer use that connection/snapshot.

The PRAGMA-drift argument is sound for this repository's supported migration.
`SqliteStore._ensure_chain_schema()` only adds chain columns, and adds
`fact_cursor` before `window_hash`. If `window_hash` is added after the probe,
the already-selected literal boundary `0` over-reports the edge
conservatively. If the probe sees `window_hash`, it also sees the earlier
`fact_cursor` addition. A hypothetical external migration which drops or
renames a chain column could make the query fail loudly, but cannot silently
produce the round-1 understated/mixed edge through the supported additive
path.

Verdict: **CLOSED**. The implementation and behavioral regression close the
reported race. Note the narrower limitation of the statement-count assertion.

### 2. Rule 12 `run_cli` assignment alias — PARTIAL (P2)

Implementation: `tests/test_architecture.py:1149-1248`  
Regression tests: `tests/test_architecture.py:1611-1655`

The exact round-1 form is caught:

```python
runner = run_cli
runner(..., render=...)
```

The fixed-point assignment collector also caught these new forms:

```text
tuple unpacking: seen=1, violations=1
walrus binding:  seen=1, violations=1
```

New ordinary evasions still produce `seen=0, violations=0`:

```python
runners = {"go": run_cli}
runners["go"](..., render=...)

runner = getattr(painted, "run_cli")
runner(..., render=...)

runner = decorate(run_cli)
runner(..., render=...)

runner = functools.partial(run_cli)
runner(..., render=...)
```

The first two are explicitly named as an accepted “known boundary” in the
Rule 12 preamble (`tests/test_architecture.py:1100-1104`), but they are direct,
working reintroductions of the forbidden contract. The decorator and
`functools.partial` forms are the same missing `Call`-valued alias class. The
collector excludes all `Call` RHS values to avoid mistaking
`rc = run_cli(...)` for a callable; it consequently cannot distinguish a
runner's return value from a higher-order call which returns a runner.

Verdict: **PARTIAL, P2**. The exact assignment regression and several nearby
forms are closed; container, reflective, and higher-order aliases still evade
the repository-wide contract rule.

### 3. Rule 12 renderer scope/import resolution — PARTIAL (P2)

Implementation: `tests/test_architecture.py:1251-1502`  
Allowlist use: `tests/test_architecture.py:1403-1407,1552-1574`  
Regression tests: `tests/test_architecture.py:1676-1824`

Both round-1 evasions are caught:

- the first of several sibling nested `renderer` definitions taking `piped`;
- a `renderer=` imported from a repository module outside `lenses/`.

Relative import plus re-export is also covered. A chain over four import hops
does not pass silently; `_resolve_callable()` returned:

```text
re-export chain for 'renderer' exceeded 4 hops
```

That bound is acceptable for correctness because the result is loud, although
it is a maintenance ceiling rather than semantic resolution.

The new scope model is nevertheless not a Python binding model. It indexes
only `def` bindings. It does not give assignments, parameters, comprehension
targets, or other local bindings the shadowing force they have at runtime.
A clean outer `def renderer(...)` therefore masks a bad runtime binding with
the same name. Every one of these executed cases returned
`resolved=1, violations=0`:

```python
def renderer(data, fidelity, width): ...       # clean outer decoy
def bad(data, fidelity, width, *, piped=False): ...

def by_assignment():
    renderer = bad
    return run_cli(..., renderer=renderer)

def by_parameter(renderer=bad):
    return run_cli(..., renderer=renderer)

def by_tuple():
    renderer, other = bad, None
    return run_cli(..., renderer=renderer)

def by_dict():
    renderer = {"bad": bad}["bad"]
    return run_cli(..., renderer=renderer)

def by_getattr():
    renderer = getattr(Box, "bad")
    return run_cli(..., renderer=renderer)

def by_partial():
    renderer = functools.partial(bad)
    return run_cli(..., renderer=renderer)

def by_decorator():
    renderer = decorate(bad)
    return run_cli(..., renderer=renderer)

[run_cli(..., renderer=renderer) for renderer in [bad]]

class C:
    renderer = bad
    result = run_cli(..., renderer=renderer)
```

Direct complex keyword expressions such as
`renderer=(renderer := bad)` do fail loudly. The evasion is specifically the
resolver finding a clean outer definition before it accounts for the nearer
non-`def` binding.

The `_RENDERER_BINDING_EXCEPTIONS` mechanics are also not shrink-only in
enforcement:

- `_check_exceptions()` checks only that each path exists
  (`tests/test_architecture.py:172-175`);
- adding any existing source path is accepted without a pinned baseline,
  cardinality check, or required reason;
- an entry suppresses **all** renderer-binding violations in that file at
  `tests/test_architecture.py:1573-1574`, including resolved functions which
  explicitly take `piped`, although the comment describes only intentionally
  unresolvable bindings.

The allowlist is empty today, so this is not a current repository exemption.
It is a non-enforced “shrink-only” claim and a broad future bypass.

Verdict: **PARTIAL, P2**. The exact sibling/import regressions are closed and
unresolved direct expressions are loud, but normal local shadowing still makes
the resolver select a callable different from the one Python will call.

### 4. Window wire fidelity — PARTIAL (P2)

Implementation: `apps/loops/src/loops/surface.py:1286-1300`  
Ratchet: `apps/loops/tests/test_surface.py:1194-1282`

The exact round-1 mutation is caught:

```text
"edge_since": window.edge_facts
CAUGHT: mis-wires ['edge_since']; got 104, expected 105.5
```

The distinct sentinels successfully cover omissions, direct cross-wiring,
constants unequal to the sentinel, tuple-to-list conversion, and optional
`None` arms.

The one-vector scheme does not prove general value fidelity when an encoder
applies a transform for which that particular sentinel is a fixed point. I
replaced the encoder's query and fields arms with:

```python
"query": window.query.strip().lower() if window.query is not None else None,
"fields": sorted(window.fields) if window.fields is not None else None,
```

Both sentinel tests passed because `"query-sentinel"` is already stripped and
lowercase, and `fields` contains one element. Real values were corrupted:

```text
input query:  "  MiXeD Query  "   -> "mixed query"
input fields: ("z", "a")           -> ["a", "z"]
faithful wire values: "  MiXeD Query  ", ["z", "a"]
```

The same blind-spot class exists for one-element `unindexed`/`stale` tuples and
positive numeric sentinels under ordering/sign/clamping transforms which leave
the chosen value unchanged.

Verdict: **PARTIAL, P2**. The reported cross-wire is closed. The stronger
documented claim that the ratchet proves wire value fidelity remains evadable
by plausible encoder transforms.

### 5. APPS derivation exclusion holes — PARTIAL (P2)

Implementation: `tests/test_architecture.py:40-80`  
Regression tests: `tests/test_architecture.py:286-360`

The exact round-1 namespace-package evasion is caught, as is a bare immediate
`src/*.py` module. A nested namespace tree such as
`src/acme/plugins/deep.py` contributes `acme`, so Rule 3 catches imports at any
depth below that top-level namespace.

New exclusion cases:

- A legal underscore-prefixed namespace package is deliberately skipped:

  ```text
  apps/x/src/_nsapp/feature.py
  _app_names(...) excludes "_nsapp"
  import _nsapp.feature succeeds when that src is on sys.path
  ```

  The docstring's claim that underscore-prefixed entries are not names a lib
  could legally import is false. Leading underscores are legal identifiers.

- An app using a flat/non-`src` package layout is invisible:

  ```text
  apps/x/nsapp/__init__.py
  _app_names(...) excludes "nsapp"
  import nsapp succeeds when apps/x is the configured package root
  ```

  Repository convention may prefer `src/`, but no completeness rule enforces
  that convention. A new app can therefore select a valid alternate packaging
  layout and fall outside Rule 3 and Rule 12's derived roots.

- Matching is exact-case. With derived name `Camel`,
  `_imports_module([("camel.feature", 1)], "Camel")` returns no hit. This is a
  platform-dependent hole rather than a portable Python evasion: case-variant
  imports normally fail on case-sensitive filesystems but can resolve on
  case-insensitive packaging/filesystem combinations. At minimum, the rule
  does not make case collisions loud.

Verdict: **PARTIAL, P2**. Namespace packages, immediate modules, and nested
namespace depth are closed. Legal underscore names and unenforced source-root
layouts remain silent exclusions; case handling remains platform-sensitive.

### 6. Round-1 diff-hygiene note — CLOSED

Commit `bba7c48` removes the three trailing spaces. Both
`git diff --check b10515f...HEAD` and the working diff check are clean.

## Flagged residues

### `vertex_fold()` same-class snapshot race — CONFIRMED, P2

`libs/engine/src/engine/vertex_reader.py:1138-1187`

The single-store head path performs each per-kind fact read, kind statistics,
and `live_edge()` as separate autocommit statements. `live_edge()` is now
internally coherent, but it is not in the same snapshot as the rows it
describes.

Reproduced by starting with one fact sealed by a tick, appending an unsealed
second fact immediately before `vertex_fold()` calls `live_edge()`, and then
letting the fixed `live_edge()` run:

```text
returned folded keys: ["before"]
returned edge_facts: 1
returned edge_since: 200.0

coherent pre-commit:  folded keys ["before"],          edge_facts 0
coherent post-commit: folded keys ["before", "after"], edge_facts 1
```

The returned pair is true in neither snapshot. This is the same defect class
as round 1, one level up: individually coherent statements assembled into an
incoherent answer. Priority **P2**: it can disclose staleness metadata for a
fact absent from the rendered fold (or omit metadata for rows it includes),
but it does not corrupt the store.

### RATCHETS.md generalizations — qualified, documentation priority

`docs/RATCHETS.md:133-140`

1. **“A documented known boundary is an advertised hole.”**

   Useful adversarial-review heuristic, but overreach as universal doctrine.
   A documented boundary is an advertised **attack surface**. It becomes a hole
   when the supposedly enforced invariant remains reachable through it. That
   is exactly true for Rule 12's `getattr` and container boundaries, so the
   heuristic correctly predicts the evasions above. It is not true where a
   boundary is genuinely out of scope, separately enforced, or fails loudly.

2. **“Cannot-resolve must be loud.”**

   Sound for an in-scope negative architecture rule: an unclassified skip is
   indistinguishable from a pass and therefore cannot support the rule's
   claim. It is overbroad without “in scope” and “unclassified.” Rule 12 itself
   intentionally permits bindings proven to leave the repository. The durable
   doctrine is: **in-scope cannot-resolve must fail loudly; out-of-scope must
   be explicitly classified and countable, never an unobserved `continue`.**

Priority: **note / docs clarification**, not a production P2. The immediate P2
is the implementation mismatch: the current known boundaries are real
evasion paths and the purported shrink-only allowlist is not mechanically
shrink-only.

## Full verification

All requested suites are green:

```text
apps/loops/tests:          2402 passed, 1 xfailed
libs/engine/tests:         1136 passed
apps/tasks/tests:           258 passed (101 deprecation warnings)
libs/atoms/tests:           440 passed
tests/test_architecture.py:  26 passed
```

No source fix was made in this verification round; this report is the only
repository change.
