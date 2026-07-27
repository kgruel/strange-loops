# Sol HIGH review — 0.10.0 wave round 1

Reviewed `git diff main...feat/010-surfacing` at `b10515f`.

## Verdict

- P1: 0
- P2: 5
- Notes: 1

The production code has one reproduced correctness race in `live_edge()`. All
four requested ratchet families also admit constructed evasions that remain
green. The S1 caller migration itself, historical-read suppression, aggregate
suppression, Window threading, and the seven tasks sites held under the checks
below.

## Findings

### P2 — `live_edge()` can return a count that is false in every coherent database snapshot

`libs/engine/src/engine/store_reader.py:271-288`

The newest chained tick, its cursor rowid, and the edge aggregate are three
independent SELECT statements. `StoreReader` does not open a read transaction,
so a writer can append a fact and seal it with a new tick after the old boundary
has been read but before the count is read. The count then sees the newly
committed fact while retaining the old tick boundary and reports it as live,
even though the newly committed tick already seals it.

Reproduced with two connections and a trace callback that performs the
fact+tick commit immediately before the aggregate SELECT:

```python
reader = StoreReader(path)  # f1 is already sealed by tick 1

def race(sql):
    if sql.startswith("SELECT COUNT(*), MIN(ts)"):
        writer = make_store(path)
        writer.append(Fact.of("note", "tester", body="sealed-concurrently"))
        writer.append_tick(Tick(name="seal-2", ts=datetime.now(UTC),
                                payload={}, origin="test"))
        writer.close()

reader._conn.set_trace_callback(race)
print(reader.live_edge())
reader._conn.set_trace_callback(None)
print(reader.live_edge())
```

Observed:

```text
{'raced_live_edge': (1, 1785120725.5160441), 'fresh_live_edge': (0, None)}
```

This is a real race for the intended read path: sealing is exactly the
concurrent operation that turns a live fact into a covered fact. Make boundary
resolution and aggregation one SQLite statement/snapshot, or explicitly bracket
the method in a read transaction, and retain the interleaving as a regression
test. The same snapshot should ideally cover the surrounding fold read as well;
today `vertex_fold()` can also read rows and edge metadata from different
commits.

### P2 — Rule 12's `run_cli` walk is bypassed by one ordinary assignment

`tests/test_architecture.py:1040-1068`, `tests/test_architecture.py:1100-1140`

The alias collector follows `from ... import run_cli as alias`, but not a plain
assignment. Existing direct calls keep `seen_calls` nonzero, so anti-vacuity
does not help. I added this source file in an isolated `git archive HEAD` tree:

```python
from painted import run_cli

def deprecated_site(argv):
    runner = run_cli
    return runner(argv, fetch=lambda: {},
                  render=lambda ctx, data: None)
```

Reproduction:

```text
$ pytest -q tests/test_architecture.py::test_run_cli_sites_use_renderer_not_render
.                                                                        [100%]
1 passed
```

The test preamble acknowledges variable-threaded calls as a boundary, but this
review's explicit criterion is that a constructed evasion which passes is a
finding. Track simple assignment aliases (and invalidate them on reassignment),
or reject any invocation of a name bound from `run_cli` through a small
module-local symbol table.

### P2 — Rule 12's piped-parameter scan resolves the wrong nested renderer

`tests/test_architecture.py:1071-1079`, `tests/test_architecture.py:1143-1210`

`_functions_by_name()` stores only one definition per spelling. That is already
the wrong model for `apps/tasks/src/strange_loops/cli.py`, which contains six
different nested functions all named `renderer`. Every `renderer=` binding in
that module is checked against whichever same-named definition overwrote the
others.

I changed only the first shipped renderer:

```diff
-    def renderer(data, fidelity, width):
+    def renderer(data, fidelity, width, *, piped=False):
```

Reproduction:

```text
$ pytest -q tests/test_architecture.py::test_no_lens_entry_point_takes_a_piped_argument
.                                                                        [100%]
1 passed
```

A second constructed form also passed: a `renderer=` name imported from a
non-`lenses/` module whose function declares `piped`. Line 1190 explicitly
skips that binding. Preserve all definitions per name and resolve by lexical
scope, while also inspecting imported renderer definitions within repository
source roots (or fail closed on unresolved repository-local bindings).

### P2 — the `fields(Window)` ratchet proves key presence, not wire fidelity

`apps/loops/tests/test_surface.py:1194-1214`,
`apps/loops/src/loops/surface.py:1286-1300`

The test constructs only `Window()` and checks only whether every field name is
a key. An encoder can wire a key to the wrong field or a constant and remain
green. In an isolated tree I changed:

```diff
-        "edge_since": window.edge_since,
+        "edge_since": window.edge_facts,
```

Reproduction:

```text
$ pytest -q apps/loops/tests/test_surface.py::test_window_wire_shape_covers_every_field
.                                                                        [100%]
1 passed
```

The broken encoder maps `Window(edge_facts=7, edge_since=42.0)` to
`edge_since == 7`. Seed every dataclass field with a distinct, JSON-safe
sentinel and assert the corresponding encoded value, including the intentional
tuple-to-list conversions.

### P2 — APPS derivation silently excludes importable namespace-package apps

`tests/test_architecture.py:39-59`

`_app_names()` includes only immediate `src` children containing
`__init__.py`. PEP 420 namespace packages and importable single-module apps are
therefore absent from `APPS`, so Rule 3 does not recognize imports from them.

In an isolated tree I added:

```text
apps/evasion/src/nsapp/feature.py       # no nsapp/__init__.py
libs/atoms/src/atoms/ratchet_evasion.py # contains: import nsapp.feature
```

`nsapp.feature` is importable when that app's `src` is on `PYTHONPATH`, but:

```text
$ pytest -q tests/test_architecture.py::test_libs_do_not_import_apps
.                                                                        [100%]
1 passed
```

Derive top-level import names from all immediate `src` entries (`*.py` modules
and directories, including namespace packages), or separately enforce the
regular-package convention and make a missing `__init__.py` fail rather than
silently removing the app from the dependency ratchet.

## Note — diff hygiene

`git diff --check main...feat/010-surfacing` exits nonzero for three trailing
spaces:

```text
apps/loops/tests/golden/test_kind_stat.py:40
apps/loops/tests/golden/test_stream_paths.py:83
apps/loops/tests/golden/test_stream_paths.py:93
```

## Checks that held / suspicions killed

- Register-collapse callers: a source-wide search found no surviving
  non-test `piped=` call into a lens and no hook call site that invokes the
  changed functions. `autoresearch.py` merely re-exports `fold_view`; that lens
  already defaulted `piped` from `width is None` before this wave. Graph,
  confluence, and horizon do change direct-call output for
  `(width=None, piped omitted/False)`; I reproduced confluence changing from the
  human card to the agent ledger. No repository caller constructs that old
  contradictory state. This is external direct-caller compatibility blast
  radius, not an in-repo regression.

- Offered-width seam: inspected the installed painted runner. Every
  `renderer=` static/live path calls `_offered_width()`, whose return is
  `ctx.width`/current geometry only when `ctx.is_tty`, else `None`. JSON
  bypasses rendering entirely. The migrated three-argument order is correct.

- Tasks fidelity: all six CLI wrappers use `(data, fidelity, width)` and the
  dashboard is the seventh site; `task list` delegates to the migrated task
  status wrapper. `zoom_from_fidelity()` clamps both ends and accepts a `Zoom`
  unchanged.

- Dashboard truncate guard: at concrete width 37, main and this branch produced
  the same SHA-256 across all four zooms:
  `671568983af8489ed80cac4f80e79f5bb42e4b6260d692e1c4e5f5a18596b681`.
  The guard changes only `width=None`, where preserving the complete one-line
  payload is intended.

- Historical/aggregate edge leakage: `at is not None or as_of is not None`
  suppresses edge collection before `WitnessFold` wrapping; aggregates take a
  separate branch and retain `(0, None)`. No head edge leaks through those
  paths.

- Other live-edge cases: pre-chain schema and no chained tick deliberately
  count the whole visible store; `""`/`None` cursor sentinels resolve to rowid
  zero; an unresolvable cursor conservatively counts from zero; `_decl.*`-only
  tails report `(0, None)` by the explicit read-surface contract. Existing
  tests cover pre-chain/no-tick/sealed/backfill/declaration cases. These hold as
  documented; only the multi-statement snapshot race above makes the returned
  count false relative to a coherent head.

- Window seam: `project()` copies both edge fields and every subsequent
  transform updates the Window with `dataclasses.replace`, preserving them.
  Default JSON names both keys explicitly. The value-fidelity ratchet is the
  missing piece, not the current mapping.

- Broader verification:

  ```text
  apps/loops/tests: 2401 passed, 1 xfailed
  libs/engine/tests: 1134 passed
  apps/tasks/tests: 258 passed
  libs/atoms/tests: 440 passed
  tests/test_architecture.py: 14 passed
  ```
