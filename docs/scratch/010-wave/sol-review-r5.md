# Sol HIGH review — 0.10.0 wave round 5 (pure replay close)

Reviewed `git diff 0a3fb43...HEAD` at `fcff09a`. The r4 behavior is in the
single test commit `a9407bc`; this round replayed only the three findings left
partial by `docs/scratch/010-wave/sol-review-r3.md`.

## Final verdict

- **CLOSED:** 3
- **NOT-CLOSED:** 0
- **Whole review-loop convergence: CLOSES**

All six items in the r3 closing set are now closed: the three already closed
in r3 remain outside the deliberately narrow r4 scope, and the three r3
partials all reject or count their original constructions under r4. There is
no live finding under the arbiter's convergence criterion.

## 1. Function-local import as renderer — CLOSED

Exact replay:

```python
def renderer(data, fidelity, width):
    return None

def site(argv):
    from evapp.views import bad as renderer
    return run_cli(argv, fetch=lambda: {}, renderer=renderer)
```

`evapp.views.bad` retains the original `piped` parameter.

Observed:

```text
_RendererScan(
    piped=["... renderer bad() declares a 'piped' parameter ..."],
    unresolvable=[],
    resolved=1,
    external=0,
)
```

The scope model now selects the function-local import rather than looking
through it to the clean module-level definition. The repository-local import
is followed, and `bad()` is reported.

Verdict: **CLOSED**.

## 2. Runner registry subscript assignment — CLOSED

Exact replay:

```python
runners = {}
runners["go"] = run_cli
runners["go"](..., render=...)
```

Observed:

```text
aliases: ["run_cli"]
boundary census:
  evasion.py:5 — run_cli is stored into a container
  (subscript assignment); classified out of scope, not walked
render violations: []
run_cli calls seen: 0
```

The call through the registry remains deliberately outside the walk, as the
arbiter ruling permits, but the incremental slot assignment is no longer
silent: it contributes one classified boundary entry. With
`_RUNNER_BOUNDARY_BASELINE = 0`, introducing this exact repository shape fails
the cardinality ratchet.

Verdict: **CLOSED**.

## 3. Mixed flat package beside an existing empty `src/` — CLOSED

Exact replay:

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
_misplaced_app_python(apps):
  ["mixed/flatpkg/__init__.py", "mixed/flatpkg/main.py"]
```

The package remains outside `_app_names()`, as before, but the layout ratchet
now checks containment of each Python file rather than mere existence of a
directory named `src`. Both misplaced files are reported.

Verdict: **CLOSED**.

## Replay regression receipt

The three merged regressions corresponding to these constructions also pass:

```text
3 passed, 43 deselected
```

No fresh evasion was constructed or chased.

## Non-blocking observation

The exact local-import replay's diagnostic attributes the imported definition
to the caller path:

```text
evapp/cli.py:1 — renderer bad() ...
```

The definition is actually `evapp/views.py:1`. This is a provenance blemish in
the finding text, not a false green: the imported callable is resolved and its
`piped` parameter is reported. Per the pure-replay constraint, I did not chase
or expand it.

## Suite and hygiene receipts

Both requested suites are green:

```text
tests/:             46 passed
apps/loops/tests:   2403 passed, 1 xfailed
```

`git diff --check 0a3fb43...HEAD` is clean. This report is the only file changed
by the r5 verification; the pre-existing untracked
`docs/scratch/010-wave/sol-review-brief-r5.md` was left untouched.
