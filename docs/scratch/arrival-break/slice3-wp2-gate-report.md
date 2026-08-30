# Slice 3 / WP2 gate report — the `comparison` conformance family

**GATE: PASS.** Two non-blocking observations, no blocking findings, no module or
vector change required.

Target: `slice3/wp2-vectors` @ `9735ce3f` (3 commits over WP1's `9ed893fe`).
Gate worktree: `~/Code/loops-s3wp2-gate` on `slice3/wp2-vectors-gate`, created fresh
from `9735ce3f`, own `uv sync --all-packages`. Binaries verified resolving inside the
gate worktree before any measurement: `python` at
`/Users/kaygee/Code/loops-s3wp2-gate/.venv/bin/python`, `engine` imported from
`/Users/kaygee/Code/loops-s3wp2-gate/libs/engine/src/engine/__init__.py`, pytest 9.1.1,
ruff 0.16.5. The implementation report was read from git bytes
(`git show 9735ce3f:docs/scratch/arrival-break/slice3-wp2-report.md`) and treated as the
review's target, not its authority. Every number below is one I re-derived; nothing is
carried over from the report.

Sequencing note: all clean-tree measurement (items 1, 4, 5, 7) ran before any
destructive cycle, so the architecture rules were judged on the pristine post-commit
tracked set. Every mutation and ratchet-defeat cycle below was followed by
`git checkout` and a `git status --porcelain` check — **`--porcelain`, not `git diff`,
so an untracked stray would have been caught too**. Every restore came back empty, and
the final tree is byte-identical to `9735ce3f`.

---

## Oracle item 1 — counts, reproducibility, ruff, Rules 17/18. **PASS**

**Suites, in separate processes** (WP1 measured 29 cross-suite pollution failures when
they share one):

| Suite | Measured | Expected |
|---|---|---|
| `libs/engine/tests` | **2188 passed, 1 skipped** | 2188 + 1s |
| `tests/architecture` | **99 passed** | 99 |

**The +30 is decomposed and the baseline measured directly rather than inferred.**
`--collect-only` on the new consumer gives exactly **30 tests: 26 parametrized ids + 4
named** (`..._inventory_is_exactly_what_is_on_disk`,
`..._outcome_slot_holds_only_the_seven_ratified_strings`,
`..._every_ratified_outcome_is_exercised_by_some_vector`,
`..._the_runner_stays_on_the_pure_surface`). Re-running the engine suite with
`--ignore=libs/engine/tests/test_conformance_comparison.py` gives **2158 passed, 1
skipped** — the brief's stated baseline, confirmed empirically in this worktree rather
than assumed from arithmetic. Delta is +30 and all of it is in the new file.

**26 vector JSONs by three independent counts, each re-derived:**

| Method | Count |
|---|---|
| `git ls-files spec/conformance/vectors/comparison/` | **26** |
| generator `Wrote` lines on a fresh run | **26** |
| `VECTOR_INVENTORY` union, imported from the consumer | **26** |
| (on-disk `*.json`, as a fourth) | **26** |

`git check-ignore -v` on all 26 exits 1 — **nothing is ignored**, so the gitignore trap
is closed.

**Generator byte-reproducible.** Regenerated, then `git status --porcelain` — empty.
That checks untracked strays as well as tracked diffs, so the generator neither drifted
nor emitted an unfiled file.

**ruff clean.** `uv run ruff check` on the two new files
(`spec/conformance/generate_comparison.py`,
`libs/engine/tests/test_conformance_comparison.py`) → `All checks passed!`, exit 0. The
report's "ruff clean" claim is scoped honestly: repo-wide `ruff check .` returns 1699
errors, but the repo carries no root `[tool.ruff]` and CI runs ruff only on
`libs/custody libs/sign` (`.github/workflows/ci.yml:65`), so repo-wide was never the
standard. Both new files are clean under the config that actually reaches them.

**Rule 17 is not a vacuous green — verified by executing the rule's own scan set**, not
by trusting the pass. `_scan_targets()` returns 193 files including
`spec/conformance/generate_comparison.py` and `spec/conformance/SCHEMA.md`; the
generator is enrolled by the `spec/conformance/generate_*.py` glob and the target list
is filtered through `git ls-files`, so this is the post-commit tracked set by
construction. **Rule 18** enrolls engine modules by the
`libs/engine/src/engine/arrival*.py` glob; WP2 adds no engine module, so 99 → 99 is the
correct delta rather than a missed case.

## Oracle item 2 — the inventory ratchet, both directions, re-run by me. **PASS**

| Direction | Result |
|---|---|
| Drop `comparison-epoch-below-the-reset-head-is-rollback` | `AssertionError: missing: ['comparison-epoch-below-the-reset-head-is-rollback']; unclassified: []` — **fails naming the dropped vector**, 1 failed / 28 passed |
| Add a `replicate-basic-two-way.json` stray | `AssertionError: missing: []; unclassified: ['replicate-basic-two-way']` **plus** `vector name must match its file stem` — **2 failed** / 29 passed |

The stray is caught twice, as the report claimed: the inventory files it as
unclassified and the per-vector envelope catches the name/stem mismatch, so a *copied*
vector cannot slip in under a new filename. Both restores clean.

## Oracle item 3 — all four mutation demos, re-run by me. **PASS**

Each mutation was applied to the module, the vectors run, the module restored, and
`git status --porcelain` verified empty before the next. **All four reproduce the
report's exact failure counts and the exact named vectors.**

### (a) classifier's rollback arm returns `UNCHANGED` — **3 failed, 27 passed**

```
FAILED [comparison-classify-rollback]
FAILED [comparison-epoch-below-the-reset-head-is-rollback]
FAILED [comparison-journal-the-known-head-is-the-maximum-ordinal]
```

Three families and both vector forms, as claimed.

### (b) epoch reset-**EXCLUSIVE** (`entries[index + 1:]`) — **5 failed, 25 passed**

```
FAILED [comparison-epoch-below-the-reset-head-is-rollback]
FAILED [comparison-epoch-ends-at-the-reset-entry-is-unchanged]
FAILED [comparison-epoch-scopes-the-equivocation-check-too]
FAILED [comparison-incomplete-a-bound-still-refuses-below-itself]
FAILED [comparison-incomplete-a-torn-line-yields-a-lower-bound]
```

The ends-at-reset vector's failure mode is the one that answers first contact:

```
AssertionError: expected read state 'established', got NoneType
```

`known` falls to `None`, which is the empty-epoch state that classifies
`first-contact` — the silent re-acceptance
`finding:s3wp1-epoch-scope-is-reset-inclusive` was raised to close.

### (b2) trust-epoch filter dropped entirely — **5 failed, 25 passed**

Same five vectors. **The two epoch mutations are distinguishable, and I verified the
distinction verbatim rather than accepting the claim** — this is what shows the vectors
pin the *scope* rather than one arithmetic:

| Vector | under (b) reset-exclusive | under (b2) filter dropped |
|---|---|---|
| `comparison-epoch-ends-at-the-reset-entry-is-unchanged` | read state collapses: `expected read state 'established', got NoneType` | epoch **count** wrong: `assert 3 == 1` |
| `comparison-epoch-scopes-the-equivocation-check-too` | epoch count | **spurious refusal**: `JournalEquivocation: journal holds 2 different records at ordinal 200 in the current trust epoch` |

Under (b2) the equivocation check reaches the abandoned pre-reset pair at ordinal 200
and refuses a journal the operator already resolved. That is a different defect from
(b)'s, and it fails differently — exactly as the report claimed.

### (c) `established_head()` returns the bound instead of refusing — **5 failed, 25 passed**

```
FAILED [comparison-header-a-kindless-object-is-not-absorbed]
FAILED [comparison-header-both-markers-together-are-unclassifiable]
FAILED [comparison-incomplete-a-bound-still-refuses-below-itself]
FAILED [comparison-incomplete-a-headerless-journal-yields-a-bound]
FAILED [comparison-incomplete-a-torn-line-yields-a-lower-bound]
```

Every bounded vector. The kindless-object vector reproduces BLOCKING-1's silent
re-acceptance through a vector, verbatim:

```
AssertionError: assert 'unchanged' == None
  where 'unchanged' = <Outcome.UNCHANGED: 'unchanged'>.value
  where <Outcome.UNCHANGED: 'unchanged'> = compare(HeadAttestation(head=Head(..., ordinal=91, ...)), Head(..., ordinal=91, ...), None)
```

## Oracle item 4 — schema honesty. **PASS** (all four sub-claims)

Checked by a **sweep over all 26 vectors**, not by sampling, since these artifacts
outlive this repo.

### (i) The heads/journal split — every read rule is structurally unreachable from `compare`

The claim is not merely true, it is provable from the signature. `compare` is

```python
def compare(known: HeadAttestation | None, presented: Head, at_known: Head | None) -> Outcome
```

`known` is **one already-selected attestation**. There is no line list, no entry
tuple, no epoch, no skip record. So:

- **Max-ordinal rule** — *which* of several entries becomes *K* is decided before
  `compare` is called; `compare` receives the winner and cannot see the field. The
  `comparison-journal-the-known-head-is-the-maximum-ordinal` fixture makes the point
  concrete: the journal's **last line is ordinal 5** while `K` is the max at 6, and the
  vector answers `rollback`. Last-line semantics would answer `unchanged`. No
  heads-form vector can state that scenario, because a heads vector has no lines.
- **Equivocation** — two entries at the maximum with different hashes cannot be
  expressed at all: the parameter holds one `HeadAttestation`, not a collection. The
  refusal is raised by `_known_of` during the read, before `compare` exists.
- (Also unreachable, by the same argument: epoch scoping, the incomplete-read bound —
  `known` is typed `HeadAttestation | None` with no third inhabitant, so a bound cannot
  be passed in — and header classification.)

The split is honoured in the fixtures, not just the prose. Sweep of input keys by form:
`heads` carries `['at_known', 'form', 'known', 'presented']`, `journal` carries
`['at_known', 'form', 'journal', 'presented']`. No heads vector carries a journal.

### (ii) `expected.read` vs `expected.outcome`, and `outcome: null` is not an eighth string

SCHEMA.md §11 states **both** claims explicitly: the `expected` table types `outcome`
as "One of the seven strings above, or `null`" and `read` as `journal`-only, and the
prose says outright *"`outcome: null` is not an eighth outcome... a normative vector
carrying something like `\"declined\"` would read to an implementer as a value to
return."*

Sweep result: **all 26 vectors carry an outcome in the seven ∪ {null}**, and all seven
ratified strings are reached. The `expected` key sets are clean per form — `heads`
vectors carry **only** `outcome` (no stale `read` riding along, which the runner's early
return at line 266 would never have caught).

**I tried to defeat the ratchets rather than trusting them:**

| Defeat attempt | Result |
|---|---|
| Set a vector's outcome to `"declined"` | **2 failed** — `AssertionError: comparison-incomplete-a-torn-line-yields-a-lower-bound names 'declined'`, and separately `the read declined, but the vector states an outcome` |

Caught twice, and note the outcome-slot ratchet globs the disk, so it catches an **edit
to an existing vector**, not only a newly added file.

### (iii) `skipped` is a count — no reason strings anywhere. **Verified by grep + sweep**

`skipped` is an integer in every journal vector (`null` only in the equivocation vector,
which refuses before anything is counted — honest, since there is nothing to count).
A grep for skip-reason prose (`not readable`, `line N:`, `carries both`, `no header`,
`reason`) hit two files; **both hits are in the human-readable `description` field**,
never in an `expected` slot. `expected` carries counts only. SCHEMA.md states the reason
("one of them necessarily embeds the host's own JSON parser error text; pinning it would
be the same overreach as naming an exception class").

### (iv) `sound_answer` scoped to rollback-only, and the deferred slot is unused

Sweep: `sound_answer` is present **iff** `read == "bounded"` (5 vectors), and its values
across those five are `{"rollback", null}` — one `"rollback"` (the below-the-bound case)
and four `null`. **No vector asserts `lineage-replaced` against a bound**, and the
consumer's `SOUND_ANSWERS` frozenset is `{None, "rollback"}`, so the deferred value is
not merely unused, it is inexpressible. The arbiter's deferral holds.

Both guards defeated-tested:

| Defeat attempt | Result |
|---|---|
| `sound_answer: "lineage-replaced"` | `AssertionError: assert 'lineage-replaced' in frozenset({None, 'rollback'})` |
| Flip the below-bound vector's `sound_answer` to `null` | `AssertionError: assert None == 'rollback'` |

See non-blocking observation 1 for what `sound_answer` does and does not verify.

## Oracle item 5 — fold-behavior coverage, checked against fixture bytes. **PASS**

For each behavior I read the fixture's actual lines rather than accepting that a
green vector with a matching name encodes the ruling. In every case the vector sits on
the ruling and its *plausible neighbor* is the pre-ruling behavior.

**1. Reset-inclusive epoch** (`s3wp1-epoch-scope-is-reset-inclusive`) —
`comparison-epoch-ends-at-the-reset-entry-is-unchanged`: lines are
`[header, bootstrap@0, advance@100, trust-reset@90]` — **the last line is the reset**,
which is the exact shape the fold names. Expected `read: established`, `entries: 3`,
`epoch: 1`, `known` = the reset head at 90, presented 90, `outcome: unchanged`. The
literal-prose neighbor (entries *after* the reset) gives an empty epoch and
`first-contact`. Note `entries: 3` vs `epoch: 1`: the abandoned advance@100 is retained
as evidence and excluded as a claim, which is the fold's other half.
Its sibling `-below-the-reset-head-is-rollback` proves *which* head the epoch selected.

**2. Incomplete read is a lower bound** (amended `s3wp1-mid-file-journal-damage-unstated`)
— `comparison-incomplete-a-torn-line-yields-a-lower-bound` is built on **WP1's own
refutation fixture**: `[header, bootstrap@0, trust-reset@90, UNPARSEABLE, advance@91]`,
i.e. the epoch `[90-reset, 92, 91]` with the 92 line torn and 91 surviving *after* it.
Expected `read: bounded`, `at_least` = 91, `skipped: 1`, `outcome: null`. Two wrong
neighbors are both excluded: refusing the file (the pre-amendment behavior) and
`established@91 → unchanged` (the silent re-acceptance the refutation found).
`comparison-incomplete-a-bound-still-refuses-below-itself` carries the positive half —
presented **89**, genuinely below the bound of 91, `sound_answer: "rollback"`.

**3. Headerless yields a bound, not a refusal** (the gate's own WP1 stale-oracle note) —
`comparison-incomplete-a-headerless-journal-yields-a-bound`: the fixture has **no header
line at all**, two readable entries, expected `read: bounded`, `skipped: 1` (the absence,
counted without a line number), `outcome: null`. **Encoded correctly**: a bound, not the
refusal the round-0 oracle and §B.3 prose would have produced.

**4. Nothing readable declines, and the re-mint consequence**
(`s3wp1-gate-all-entries-unreadable-silent-tofu`) —
`comparison-incomplete-nothing-readable-declines-every-comparison` is the gate's own
pure-skew demonstration as a fixture: a v2 header plus two v2 entries at ordinals
4216/4217, giving `entries: 0`, `epoch: 0`, `skipped: 2`, `read: unreadable`,
`outcome: null`. `comparison-incomplete-a-re-mint-against-lost-content-is-not-first-contact`
runs the **same journal** but presents **a fresh genesis at ordinal 0** and still
declines — §D.4's "a replacement wearing the old name", which is the operator-facing
consequence and the case that previously answered first-contact. First contact stays
reachable exactly where it is honest: the empty and header-only journals both give
`read: none` with `skipped: 0`.

**5. Three-way header classification** (`s3wp1-sol-l1-...`) — all three rows present,
and all three built on the same "loss at 92 masked by 91" shape so the discriminator is
consistent:

| Row | Vector | Fixture | Expected |
|---|---|---|---|
| kindless + type marker = header | `-a-later-builds-header-is-still-a-header` | v2 header with an extra `issuer` field | `established`, `skipped: 0`, `unchanged` |
| **both** markers = unclassifiable | `-both-markers-together-are-unclassifiable` | line carries `type: arrival-head-observation` **and** `kind: advance` at ordinal 92 (keys verified) | `bounded@91`, `skipped: 1`, `outcome: null` |
| anything else kindless = skipped | `-a-kindless-object-is-not-absorbed` | `{}` in the ordinal-92 position — BLOCKING-1's exact byte pattern | `bounded@91`, `skipped: 1`, `outcome: null` |

The middle row never absorbs and never refuses the file, and the later-build header is
`established` with **zero skips** — the right neighbor check, since `bounded`-with-a-skip
would have passed as coverage while encoding the opposite ruling.

## Oracle item 6 — purity. **PASS**

- **Namespace ratchet fires.** Injecting `from engine.arrival_head_attestation import
  state_root` into the consumer → `AssertionError: the runner imports 'state_root'`,
  1 failed / 29 passed. Restored clean.
- **Generator asserts its temp XDG before the first append.** Verified in source
  (`generate_comparison.py:804-806`): it sets `XDG_STATE_HOME` to a `TemporaryDirectory`
  then asserts **both** `state_root() == Path(tmp)/"loops"` and
  `journal_path(LINEAGE).is_relative_to(tmp)` before any write.
- **Hostile run.** I pointed `XDG_STATE_HOME` at a fresh empty scratch directory and
  regenerated. The generator wrote **0 files** into it (`find` count 0) and `git status
  --porcelain` stayed empty. The generator cannot land fixture journals in an operator's
  real state root.
- **Fixtures built through the real `append_entry`**, with damage/ambiguity/foreign-build
  lines spliced afterwards — correct, since those are by definition what the writer would
  never produce.

## Oracle item 7 — negative controls. **PASS**

- **Agreeing duplicates are not equivocation.**
  `comparison-journal-duplicate-entries-at-the-maximum-agree`: two `advance` entries both
  at ordinal 6 with the **same** record hash (`fd36ffd784…` twice — verified identical).
  Expected `read: established`, `skipped: 0`, `unchanged`. A refusal that fired here would
  have stopped meaning what it says.
- **Unknown fields on a v1 entry read fine.**
  `comparison-journal-unknown-fields-on-a-v1-entry-are-read`: a `v: 1` entry carrying
  `"corroboration": {"facts": 41, "ticks": 7}` and `"issued_by": "a-later-build"` →
  `established`, `skipped: 0`, `unchanged`. Preserved-and-ignored, per §B.3.

Both present, both passing, both genuinely controls rather than restatements.

---

## Findings

**No blocking findings.** No loops emission was made, per the mechanics (facts only for
blocking findings).

### NON-BLOCKING 1 — `sound_answer` is verified by vector-internal arithmetic, not by the module

`sound_answer` is the one `expected` field no module call ever checks. I confirmed the
mechanism from both ends:

- The runner (lines 312-319) recomputes `below` from the **vector's own** bound and
  presented head and asserts the vector's stated `sound_answer` matches. It asks the
  module nothing.
- The module has no API that could be asked. `established_head()` raises
  `IndeterminateComparison` on `HeadLowerBound`, and `HeadLowerBound` has fields
  `['at_least', 'skipped']` and **zero public methods** — so on a bound, `compare` is
  never reached and no code path answers `rollback`.

This is **correct** as built: the arbiter scoped bound semantics to rollback-only and
deferred enforcement, WP3's seam is the forcing consumer, and SCHEMA.md words the field
honestly as *"What a bound may soundly answer"* — a normative statement about
conforming implementations, not a claim about today's code.

The reason to record it: the WP2 report's §2 says the bound vectors "carry a positive
claim" and that the bound is "sound to refuse a presented head below it", which a WP3
reader could take as behavior these vectors verify. They do not. `sound_answer` is a
forward-looking normative slot whose only enforcement today is internal consistency.
Scoping the claim: the vectors make a **location claim** (this is where a bound's sound
answer would be stated), not a verdict claim (the implementation answers rollback here).
Worth one sentence in the WP3 handoff so the seam knows it owns this field's first real
consumer.

### NON-BLOCKING 2 — the purity ratchet is a name list, so an aliased import evades it

`test_the_runner_stays_on_the_pure_surface` checks `globals()` against four literal
names. `from engine.arrival_head_attestation import state_root as _sr` passes green
(30 passed) while `import state_root` fails.

Applying scope-the-claim to my own finding: this is **not worth fixing**. A name ratchet
catches drift, not adversaries, and the real protection here is structural rather than
enumerated — the runner calls only `parse_journal_lines`, `established_head` and
`compare`, none of which resolves a path, so an imported-but-uncalled name touches
nothing. The test's own docstring claim ("checked against this module's actual namespace
rather than its source, so the assertion cannot be satisfied by a name that merely looks
absent") is about source-versus-namespace and is **accurate**; it does not overclaim
adversarial coverage. Recorded for completeness, not as a change request.

---

## Verdict

**GATE: PASS.**

| # | Oracle item | Verdict |
|---|---|---|
| 1 | Counts (2188+1s / 99 separate, +30 = 26+4, baseline 2158+1s measured directly), 26 by three independent counts, generator byte-reproducible, ruff clean, Rules 17/18 on the post-commit tracked set | **PASS** |
| 2 | Inventory ratchet both directions, re-run by me — drop fails naming it, stray fails unclassified *and* on name/stem | **PASS** |
| 3 | All four mutation demos re-run by me — 3 / 5 / 5 / 5, exact vectors, the two epoch mutations distinguishable verbatim, all restores byte-clean | **PASS** |
| 4 | Schema honesty — form split structurally proven, read/outcome separated, `null` not an eighth string (defeat-tested), skipped is a count, `sound_answer` rollback-scoped with the deferred value inexpressible | **PASS** |
| 5 | All five brief-named fold behaviors encoded on the ruling and not a neighbor, verified against fixture bytes; headerless correctly a bound | **PASS** |
| 6 | Purity — namespace ratchet fires on injection, generator asserts temp XDG, hostile-XDG run wrote nothing | **PASS** |
| 7 | Both negative controls present and genuine | **PASS** |

The round's core claim holds: these vectors are honest about what they pin. The
form split is structural rather than stylistic, the schema refuses to mint an eighth
outcome or to pin one host's error prose, and every one of the four rulings WP1 fought
over is encoded on the amended behavior rather than the design's superseded text.
