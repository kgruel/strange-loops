# sol MEDIUM review — Track B round 2

Review date: 2026-07-27

Reviewed:

- loops `92451e0...f59eed2` (`5012e24` ignored as arbiter documentation)
- loops-go `76c8378...590e70f`

## Overall verdict

**FIX-ROUND-NEEDED.**

All four r1 findings are closed. The regenerated tie fixture preserves the
negative control, the original `tools/` evasion is now caught, and the ledger
corrections match the r1 wording.

The new-rule contact nevertheless found two honest-code evasions in Rule 13.
A production module can dynamically import a literal non-production module, or
statically import from an importable dunder-named top-level root, while all 52
architecture tests stay green. The new ratchet therefore does not yet enforce
its stated boundary.

## Closings

### 1. P2 ULID — CLOSED

The five ids in the committed regenerated `tie.db`, in rowid order, are:

```text
0TBREAKE000000000000000000
0TBREAKC000000000000000000
0TBREAKB000000000000000000
0TBREAKA000000000000000000
0TBREAKD000000000000000000
```

All five return `True` from the reference
`store.rebirth.is_ulid`. All five also parse with
`ulid.ULID.from_str` and round-trip to the same string. This checks both the
Crockford shape and the parser's timestamp-range constraint.

Canonicalized JSON comparison of `expected` and `expected_rowid_order` between
the r1 cut (`76c8378`) and the regenerated fixture (`590e70f`) is empty. The
derived state is unchanged; only ids and provenance changed.

The four reader perturbations in `/tmp/tb2-scratch` reproduce the r1 profile:

| Reader order | Result against `TestSameTSIDTieBreak` |
|---|---|
| `ORDER BY rowid` | red: `entities`, `log`, and `tags` fail |
| `ORDER BY id` | red: `log` and `tags` fail; `entities` passes |
| `ORDER BY ts` | red: `entities`, `log`, and `tags` fail |
| `ORDER BY ts, id` | green: all three facets pass |

The replacement ids therefore remain valid ULIDs without weakening or changing
the fixture's discriminating behavior.

### 2. P2 `tools/` hole — CLOSED

I replanted the r1 construction verbatim in
`libs/engine/src/engine/witness.py`:

```python
import tools._conformance
```

The suite went red with Rule 13 naming
`libs/engine/src/engine/witness.py:50`; the result was 1 failed and 51 passed.
After reverting only that import, the suite returned to 52 passed. This closes
the exact r1 finding. The broader new-rule contact below is a separate finding.

### 3. P3 ledger — CLOSED

The ledger now satisfies the r1 wording:

- repo state is explicitly dated and scoped to the reviewed tips, naming
  loops-go `76c8378` on `feat/track-b-batch` and family 3 as the one partially
  landed item;
- the framing no longer says that nothing is resolved while recording Q4 as
  settled: Q1/Q2/Q3/Q5 remain open, while Q4 is correctly described as settled
  by the shipped relocation and merely recorded by the ledger;
- the missing third artifact-class prerequisite is restored as
  **store fixture + cursor + expected fold state at that cursor**, jointly
  required with a witness-exposing reader for families 1/2/4/5;
- that schema prerequisite is explicitly distinguished from Q1, which asks for
  the cursor's form inside the artifact and therefore presumes that the
  artifact class already exists.

This directly resolves the stale-state, Q4-framing, and dropped-prerequisite
issues in the r1 report.

### 4. P3 claim wording — CLOSED

The ledger adopts the accurate claim, **"no normative change."** It also states
why the old "status parentheticals only" description was false: §4.6 gained a
design diagnosis as well as a status update, §6.2 gained a factual relocation
update, and the conformance appendix expanded outside a parenthetical. This is
the SPEC-diff description requested by r1.

## New-rule contact — Rule 13

**EVASION-FOUND.**

### Construction 1: literal dynamic imports

In the production witness module, each of these ordinary runtime forms was
accepted:

```python
import importlib
_conformance = importlib.import_module("tools._conformance")
```

```python
_conformance = __import__("tools._conformance")
```

The first construction left both `tests/test_architecture.py` and the full
suite at 52 passed. The second left all 52 architecture tests green. Both use a
literal module name; there is no computed string or deliberate obfuscation.

The cause is direct: `_ImportCollector` implements `visit_Import` and
`visit_ImportFrom`, but no call handling for `importlib.import_module` or
`__import__`. Rule 13 therefore sees neither dynamic dependency.

### Construction 2: an excluded but importable root

I added a top-level Python package:

```text
__support__/helper.py
```

and a production import:

```python
import __support__.helper
```

Python imported it successfully, while all 52 architecture tests passed.
`_non_production_roots` excludes every name beginning with `__`, but
`__support__` is a valid top-level Python identifier and import root. The
helper's statement that dunder-prefixed entries are not importable as
top-level names is therefore incorrect.

The other suggested angles do not expose an additional hole:

- `from tools import x` and `import tools.x` are both represented in the
  collector's runtime-module list; the exact static import is empirically red,
  and a regression test already exercises the `from root import x` form.
- An ordinary newly added, visible top-level directory containing a `.py` file
  is found by the shape derivation.
- A relative import cannot honestly traverse from a shipped package to an
  unrelated repo-top package; an import beyond the package root is invalid.
- The rule asserts that roots, `tools`, and production files are all nonempty,
  so total vacuity is guarded. The dunder construction shows that the root
  derivation can still be selectively incomplete.

## New-finding audit — legacy fixture ULIDs

The reported count is correct:

| Store | Facts | Invalid by `store.rebirth.is_ulid` |
|---|---:|---:|
| `proc.db` | 5 | 5 |
| `merge_ab.db` | 4 | 4 |
| `merge_ba.db` | 4 | 4 |
| **Total** | **13** | **13** |

`proc.db` uses `FIXTURE...` ids; the merge stores use `FIXA...` and
`FIXB...`. These contain Crockford-excluded characters. The deliberate-non-call
claim is also correct: `gen_store_fixture.py` and `gen_merge_fixture.py` still
construct those strings directly and contain no reference to `fixture_ulid`;
only `gen_tie_fixture.py` calls the new seam.

**Bundling verdict: no test is lying about validity.** `TestM1StoreReplayParity`
asserts read/replay parity and explicitly says its result is ULID-independent.
`TestMergeCommutativity` asserts preservation of `(ts, id)` ordering and equal
derived state; it does not assert Crockford validity. Corpus and test searches
found no validity assertion over these three databases. Parking their id,
schema, and provenance regeneration together therefore leaves a documented
SPEC-format defect, but it does not leave a suite claiming that these ids are
valid.

## Committed-state suites

Fresh runs before closing:

```text
loops:
  UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -q
  52 passed in 1.98s

loops-go:
  GOCACHE=/tmp/gocache go test ./internal/conform/ -count=1 -v
  PASS; 8 top-level tests pass, 1 documented TopN test skips
```

## Batch convergence

**FIX-ROUND-NEEDED.**

The fix round closes every r1 item, but Rule 13's required adversarial contact
finds live, non-obfuscated production-to-non-production import paths. Closing
those contacts, with regression tests for literal dynamic imports and an
importable dunder-named root, is the remaining batch work.
