# sol MEDIUM review — Track B batch

Review date: 2026-07-27

Reviewed:

- loops `2cc0568...92451e0`
- loops-go `94f7987...76c8378`

## Overall verdict

**FIX-ROUND-NEEDED.**

The replay-order fixture is genuinely discriminating, its known-gap skip retires
itself correctly, and the generator relocation preserves the generated semantics.
There are no P1 findings. Two P2 issues prevent merge-readiness:

1. `tie.db` violates the protocol's ULID invariant even though its ids have the
   right length.
2. Top-level `tools/` creates an unguarded import edge that the hardened
   architecture suite does not see.

The ledger and the description of the SPEC edits also need factual cleanup.

## Ranked findings

### P2 — tie fixture ids are not ULIDs

`tools/gen_tie_fixture.py::_fid` emits ids such as
`TIEA0000000000000000000000`. They are 26 characters, but `I` is excluded from
the Crockford alphabet. This contradicts loops-go SPEC lines 150 and 173-175,
which define `facts.id` as a 26-character Crockford-base32 ULID.

Empirical checks against the reference workspace:

```text
is_ulid("TIEA0000000000000000000000") -> False
ULID.from_str(...) -> ValueError: Encoded ULID can only consist of letters in
0123456789ABCDEFGHJKMNPQRSTVWXYZ.
```

All five ids fail identically. The current Python writer accepts them through
`id_override`, and the current Go reader treats ids as opaque strings, so the
suite stays green. A conforming consumer that validates the stated store format
can reject the fixture before reaching the oracle. Use canonical ULIDs whose
lexicographic slots still construct the required order.

### P2 — `tools/` is an architecture-ratchet hole

There are no existing production imports from `tools/`; searches of `libs/` and
`apps/` found none. That condition is not enforced.

In a `/tmp` copy of loops I added this runtime import to
`libs/engine/src/engine/witness.py`:

```python
import tools._conformance
```

The complete hardened architecture suite still reported:

```text
46 passed in 1.76s
```

The reason matches the implementation report: `LIBS` derives only from `libs/`,
`APPS` and Rule 12 derive from `apps/*/src`, and the app-containment rule walks
`apps/`. That also means a production dependency on top-level `tools/` is
invisible. The containment claim currently rests on “imported by nothing,” not
on a ratchet. Add an explicit production-roots-must-not-import-tools rule (or an
equivalent structural barrier).

### P3 — the ledger contains stale state and drops one format prerequisite

The requested inventory is present and mostly traces cleanly to the grounding,
but these statements are not current at the reviewed tips:

- Lines 13-15 say loops-go is at `94f7987`, is untouched, and that nothing in
  the queue has partially landed. The reviewed branch is at `76c8378`, and the
  same ledger later records family 3 as delivered.
- Line 10 says nothing in the ledger resolves an open question, while lines
  121-135 explicitly settle Q4 through the relocation.
- Grounding §4 says witness-axis families require both a witness-exposing
  reader and a third artifact form carrying store fixture + cursor + expected
  state at that cursor. The ledger carries the reader prerequisite and Q1's
  cursor-form decision, but silently drops the explicit artifact-schema
  prerequisite.

These are ledger accuracy problems, not refutations of its five-member queue or
family blocker table.

### P3 — “status parentheticals only” is not an accurate description of the SPEC diff

No normative MUST/SHOULD rule changed, but the edits are not limited to status
parentheticals:

- §4.6: the normative rule is untouched; its italic parenthetical updates
  fixture status and adds a new design/impossibility diagnosis.
- §6.2: the italic parenthetical is a factual status update locating the new
  store fixture.
- Appendix: non-normative provenance and oracle inventory are expanded outside
  any parenthetical.

The safe claim is “no normative change,” not “status parentheticals only.”

## Per-item verdicts

### 1. Negative control — CONFIRMED

Baseline committed state passes the three asserted facets:
`entities`, `log`, and `tags`. The test compares each facet to `expected` and
also rejects equality with `expected_rowid_order`.

Perturbations in `/tmp/tb-scratch`:

| Reader order | Result |
|---|---|
| `ORDER BY rowid` | all three facets fail; `entities.z` keeps `tag:"z"` instead of `"z2"`, log becomes `[z2,x,y,z,w]` instead of `[w,z,y,x,z2]`, tags become `[y,z,w]` instead of `[y,x,z2]` |
| `ORDER BY id` | test fails; log puts `w` fourth rather than first, and tags become `[x,w,z2]`; `entities` happens to agree |
| `ORDER BY ts` | all three facets fail; equal-ts rows follow the wrong order |
| `ORDER BY ts, id` | all three facets pass |

Thus rowid replay, id-only replay, and omission of the id tie-break are all
detected. No requested perturbation remained green.

### 2. Self-retiring skip — CONFIRMED

`TestSameTSIDTieBreakTopNEviction` computes `got` before calling `Skipf`. It
first rejects the rowid answer, then checks Python agreement and calls
`t.Fatal`; only the still-divergent case reaches the skip.

I simulated the gap closing by replacing only `got["top"]` with
`fx.Expected["top"]` after replay. The test failed, rather than skipped, with:

```text
Go's TopN now agrees with Python ... The gap closed: move `top` into
TestSameTSIDTieBreak's facet list, delete this test, and retire FINDINGS §3.
```

The premise can expire visibly.

### 3. Q6 impossibility claim — CONFIRMED

The current fold boundary has no id or equivalent order token:

- `store.ReadFacts` selects `id` but scans it into a local string; `Fact` has no
  `ID` field.
- The reader injects only `_ts` into `Payload`, and `Payloads` returns only the
  payload maps.
- `atoms.DecodeFold` constructs `TopN` with target/key/by/n/desc only.
- `TopN.build` receives an unordered `map[string]any` target and the current
  payload. It explicitly falls back to key-string tie-breaking.

For incumbents tied on both `by` and `_ts`, the retained map contains no fact
from which their prior arrival order can be reconstructed. The sequential
replay slice establishes call order, but the current state value does not
preserve that information for subsequent incremental application. Closing the
gap requires changing what crosses or survives the fold boundary (for example,
id/order metadata or an ordered target representation), not a content-derived
comparison available in the current code.

### 4. Generator relocation fidelity — CONFIRMED

The old executable cross-repo path injection is gone. Searches across both
current repos found no executable generator use of `Code/loops-go/tools`,
`sys.path.insert`, or `Path.home()`. Historical explanations in docstrings and
READMEs still quote the removed `sys.path.insert` expression; unrelated
production uses of `Path.home()` are outside this relocation.

All generators resolve the destination exclusively from `--loops-go` or
`$LOOPS_GO_REPO`; there is no checkout guess. A diff against the three old
scripts shows relocation plumbing, provenance naming, and the documented M1
order correction, without changes to vector cases or expected-state logic.

Execution from committed loops state succeeded:

- `gen_tie_fixture.py --loops-go /tmp/tb-scratch`
- `gen_vectors.py --loops-go /tmp/tb-scratch`

Regenerated fold and parse vectors differed from the committed artifacts only
in the allowed provenance keys.

### 5. Architecture-ratchet contact — FINDING

See the P2 architecture finding. Nothing already imports `tools/`, but a
production `libs/` import was accepted by all 46 architecture tests. The
current truth is unenforced.

### 6. Ledger doc — FINDING

The load-bearing requested content is present:

- five queue members with the grounding's statuses and blocker distinctions;
- five families, with the witness-reader prerequisite on 1/2/4/5;
- the four settled grounding verdicts: JCS gate satisfied, five-not-eight,
  oracle/vector name-count collision, and live-ceremony refutation;
- Q1-Q3 and Q5 open, Q4 settled;
- new Q6 and fixture-schema-drift entries.

The stale repo-state assertions, Q4 contradiction, and dropped explicit third
artifact-class prerequisite are the P3 ledger finding above.

### 7. SPEC.md edits — REFUTED

The “no normative change” half is confirmed. The “status parentheticals only”
half is refuted by the hunk classification above: §4.6 adds a design diagnosis,
and the conformance appendix changes outside a parenthetical.

### 8. Tie fixture internals — FINDING

Generation provenance is sound:

- Regenerating with the committed generator changed only `python_commit` in
  `tie.expected.json`; after removing the two allowed provenance keys, the JSON
  diff was empty.
- The regenerated `tie.db` was byte-identical to the committed database:
  SHA-256
  `d3f765c017bc80fc45e675030b6ca21338451e5d884a11d9fae1ede63989fc5c`.
- Schema and row-by-row fact comparisons were also identical.

This confirms the expected states are engine-generated rather than hand-written.
The finding is the invalid-ULID construction described at P2.

## Closing gates

Fresh committed-state runs:

```text
loops:    UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -q
          46 passed in 1.88s

loops-go: GOCACHE=/tmp/gocache go test ./internal/conform/ -count=1 -v
          PASS; 8 top-level tests pass, 1 known-gap test skips
```
