# Slice 2 / WP5 report — contract-text execution, doc pass, residue sweep

Brief: `docs/scratch/arrival-break/slice2-wp5-brief.md`. Rulings executed:
`decision:design/arrival-slice2-contract-text` @ `01M17M3RJJGC79KXH776Z4DQBR`
(five rulings). Branch: `slice/arrival-backend-contract`, from e7513164.

## Step 0 — worktree (DEVIATION, mechanical)

The brief's `git worktree add ~/Code/loops-s2wp5 slice/arrival-backend-contract`
FAILED as written: the wave branch was already checked out at
`~/Code/loops-s2int` (clean, exactly e7513164 — the integration worktree).
Resolved with `--force`, which permits a second checkout of the same branch:

```
git -C /Users/kaygee/Code/loops worktree add --force ~/Code/loops-s2wp5 slice/arrival-backend-contract
```

Chosen over removing `loops-s2int` because that worktree is not mine and I
cannot know whether its owner is still holding it.

**Consequence the gate must know: `~/Code/loops-s2int` is now a STALE checkout
of this branch** — its files stop matching the branch tip at my first commit.
The WP5 worktree is `~/Code/loops-s2wp5`. Both hold `slice/arrival-backend-contract`;
only s2wp5 is at the tip.

## Pre-edit baseline (verified, matches the brief's oracle 1)

| Suite | Command | Result |
|---|---|---|
| engine | `uv run --package engine pytest libs/engine/tests -q` | 2062 passed, 1 skipped |
| store | `uv run --package store pytest libs/store/tests -q` | 180 passed |
| lang | `uv run --package lang pytest libs/lang/tests -q` | 671 passed |
| architecture | `uv run pytest tests/architecture -q` | 99 passed |
| apps | `uv run --package loops pytest apps -q` | 2530 passed, 1 xfailed |

## Work log

### Ruling 3 — `head_at` joins the contract

**Classification (the brief asks for it explicitly): `head_at` is a ledger
READ, so it does NOT join `LEDGER_MUTATIONS`.** Resolving a watermark reads the
record already sitting at that ordinal; it changes nothing. The two sets answer
different questions — `RATIFIED_LEDGER_OPS` is "what the contract's §03 table
declares", `LEDGER_MUTATIONS` is "what the custody/reads separation must keep
away from a query handle". Filing a read as a mutation would make
`test_a_query_handle_never_reaches_a_ledger_mutation` refuse a handle that is
allowed to hold it. Pinned as an assertion pair in the surface test rather than
left to review memory.

**Adapter signature: no alignment needed.** `FileLedger.head_at(self, watermark:
Watermark) -> Head` (`arrival_file_backend.py:600`) already had the ruled shape;
the Protocol line mirrors it verbatim.

Changes:

- `arrival_contract.py` — `head_at` declared on `ArrivalLedger`, placed beside
  `head` (its sibling read, and the adapter's own ordering).
- `test_arrival_contract.py` — `RATIFIED_LEDGER_OPS` is the TEN-row literal;
  comment and `_declared_surface` docstring say ten; added the `head_at`
  on-Protocol / not-in-`LEDGER_MUTATIONS` pin.
- `test_arrival_registry.py:196` — "nine-op equality" → "ten-op" (stale
  cross-reference to the literal that just changed).
- `backend-contract.html` §03 — tenth row, `head_at(watermark)`.
  **Choice the ruling left open:** the Profile cell is `Authority / Replica`, by
  analogy with `head`/`read`/`scan`, which are the same kind of custody-side
  read. Not `Archive`: `verify` is the only op the table grants Archive.
- `backend-contract.html` §07 — the sentence connecting the verified
  `projected_through` obligation to `head_at`, refs ruling 3.

**Mutation demos (oracle 2a/2b), both on the exact-equality assertion:**

| # | Mutation | Result |
|---|---|---|
| a | drop `head_at` from the `ArrivalLedger` Protocol | FAILS `_declared_surface(ArrivalLedger) == RATIFIED_LEDGER_OPS` — "Extra items in the **right** set: 'head_at'" |
| b | add an eleventh op the adapter DOES offer (`import_prefix`) | FAILS the same assertion — "Extra items in the **left** set: 'import_prefix'" |
| b (first attempt) | add an eleventh op the adapter does NOT offer (`compact`) | FAILS one line earlier, at `isinstance(ledger, ArrivalLedger)` — still caught, but it proves the `runtime_checkable` half, not the left side of the equality. Re-run with `import_prefix` to hit the ruled demo. |

All three restored; `git diff` on `arrival_contract.py` confirmed clean of the
mutations before committing.

### Ruling 2 — typed `NotSupported` under `ContractRefusal`

Changes:

- `arrival_contract.py` — `NotSupported(ContractRefusal)`, exported. Its
  docstring carries the ruling's narrow form: **deliberate absence only**, and
  everything the contract text does not name stays backend-specific by design.
- `arrival_file_backend.py:295` (pre-signed draft) and `:699` (`Incremental`
  verify scope) — both now `raise NotSupported`, same messages.
- `test_arrival_contract.py` — the two tests that pinned `NotImplementedError`
  now pin `NotSupported`; **new** `test_both_deliberate_absences_refuse_under_the_contract_root`
  pins the ruling's actual claim (catchable at the root, both sites, and
  `NotSupported` is not an `engine.arrival.ArrivalError` — a caller that never
  imported the file backend can still catch it).

**Checked and deliberately NOT changed:** `arrival_store.py:118`
`class ArrivalCanonicalUnsupported(NotImplementedError)`. Pre-existing on main
(commit f345fb7b, well before this arc), on `ArrivalStore` — which the slice
contract says is NOT modified — and not on the contract surface at all. Ruling
2 names exactly two sites; widening it to every `NotImplementedError` in the
package would be the detector overreach the scope-the-claim practice warns
about. `jsonl_store.py:234` `JsonlCanonicalUnsupported` is the same case.

**Mutation demo (oracle 2c):**

| # | Mutation | Result |
|---|---|---|
| c | revert the `Incremental` site to `NotImplementedError` | FAILS 2 tests: `test_incremental_verification_is_absent_rather_than_faked` (the type pin) and `test_both_deliberate_absences_refuse_under_the_contract_root` (the root-catchability pin) — the builtin escapes `except ContractRefusal`, which is exactly the failure mode the ruling names |

Restored; diff verified to hold only the intended 3 changed lines.

**Engine suite after both ruled code changes: 2063 passed, 1 skipped.**
Delta from the 2062+1s baseline is **+1**, fully accounted: the one new
root-catchability test. No test was removed or renamed.

### The five ruled doc texts (backend-contract.html)

| Ruling | Where | What landed |
|---|---|---|
| 1 | §06, after the verification-levels paragraph | `doc-callout is-security` "Verification never repairs" — the §E candidate text, all five sentences, word-for-word including the carve-out. The only addition is the trailing ruling ref, in the house style (`decision:design/arrival-slice2-contract-text`, ruling 1) — the same shape §02's "Ruled — descriptor residence" callout uses. |
| 2 | §04, new `<h3>Typed refusals</h3>` after "Network retries" | The five text-named conditions under one backend-neutral root; deliberate absence typed `NotSupported` under it; everything else backend-specific BY DESIGN, with the scope-the-claim reason. |
| 3 | §03 table + §07 | Tenth row `head_at(watermark)`; §07 paragraph tying the verified `projected_through` obligation to it. |
| 4 | §08 "Portable import" | Prose tightened: import is a procedure over §03's operations, not an operation of its own; the table gives it no row. |
| 5 | §08, after Portable import | `doc-callout is-open` "Contract debt — resumable import", leading with the brief's sentence verbatim, then the mechanism from `finding:s2wp2-gate-f2-import-atomic-limit-no-progress`. |

**Ruling 4, prose-check outcome — the tightening WAS warranted.** §08 never
named an `import` op, so on its face no row is implied. But
`arrival_contract.py:333` justifies keeping `import_prefix` off the Protocol by
citing §08's silence ("§08 describes portable import in prose and the ratified
op table gives it no row") — the code cited a doc property the doc did not
state. The added sentence makes the two agree, which is what stops the next
adapter author from reading §08 as a required op.

**Stale "the ruling is still open" prose, in code — swept (3 sites).** Ruling 1
closed the F2 question; three docstrings still told a reader it was pending, and
the gate's HTML diff would not have looked at them:

- `arrival_contract.py` `ArrivalLedger.verify` — now states the MUST and the
  carve-out, refs ruling 1.
- `arrival_file_backend.py` `FileLedger.verify` — "whether that is a contract
  MUST" → it is, as of ruling 1; the adapter held it beforehand.
- `test_arrival_registry.py` `test_opening_a_store_whose_projection_is_absent_refuses`
  — the boundary is ruled (absent ⇒ create permitted; present ⇒ touch
  forbidden), and **permitted is not required**: the ruling is about
  verification, not opening, so this refusal stays conforming and the test still
  records observed behavior. Whether the registry's open should materialize is a
  slice-5 question.

**HTML balance (oracle 3):** all five arrival files parse balanced under a
stack-based `HTMLParser` check (`ok backend-contract / index / protocol /
wire-format / witness-protocol`, exit 0).

### Doc pass + residue sweep

**WP4-F1 (`finding:s2wp4-gate-f1-descriptor-for-calltime-import`) — closed.**
`arrival_registry.py`'s module docstring dropped the bare word "Pure" and now
scopes the claim: no-adapter-import is an IMPORT-TIME property (the one
`test_importing_the_registry_does_not_drag_the_adapter_in` pins); CALLING
`descriptor_for` reaches `engine.residence`, which imports `engine.arrival` at
module level — pre-existing, slice-5's to fix. The adapter SURFACE stays out
either way.

**`libs/engine/CLAUDE.md`:**

- The **store table itself needed no row change** — its five rows are still
  accurate, and `ArrivalStore` is unchanged by design ("ArrivalStore NOT
  modified" is in the slice contract). What was missing was everything beside
  it, so the surrounding text gained two paragraphs.
- New: the backend contract as a **second, additive path** — the three modules,
  what each half does, and the explicit statement that production still
  resolves through suffix dispatch (SD-7 stands; slice 5 rewires).
- New: `admission.py` holds §04's backend-neutral half (`admit_records`,
  `fact_commitment_hash`) while the fence and coordinate assignment stay in the
  adapter.
- The "Verification is `canonical_audit.py`, and it never opens a store"
  paragraph now says this is a contract MUST for every adapter, not just this
  package's discipline. That paragraph is the evidence §E cited for F2, so
  leaving it as local discipline after the ruling would have been the same
  contradiction in reverse.

**`libs/store/CLAUDE.md`:**

- The "Below:" dependency line names `engine.admission`, which the arrival arm
  now reaches for.
- "Merge dedup" said `INSERT OR IGNORE` as though it described merge — it
  describes ONE of three arms. Added the three-arm dispatch and, load-bearing
  for the sweep, that **what a foreign row may become is no longer decided in
  this lib**: the arrival arm delegates to `engine.admission.admit_records`.

**Conformance §12 reality check (item 8) — outcome: NO text change needed.**

- §01's Profile table already says "full-head CAS append" and §03's `append`
  row already says "compare the full head", so F1's fix left nothing stale.
- §08's "Exact replication" prose matches what the replicate vectors exercise
  (exact suffix, stale-pin refusal, same-height fork vs. agreement).
- §12's "Executable gates" are imperatives on a conformance suite, not claims
  that gates exist. Nothing there asserts something slice 2 did not build.

**Cross-doc contradiction sweep (item 11) — nothing contradicted.**
`protocol.html`'s "No silent repair" callout (refuse corruption, never rewrite)
and `witness-protocol.html`'s "a repair that intentionally starts a new lineage
is explicit" both point the same way as F2. `witness-protocol.html`'s
incremental-verification workflow is the WITNESS's, and is not contradicted by
the file adapter declining the INCREMENTAL level — §06 lets a backend advertise
the levels it has, and `capabilities()` does. `index.html` carries no
build-status claims about the arrival break, so there was nothing to bring in
line with what slice 2 built.

## Faithfulness check on the ruled text (the gate's own diff, run here first)

The §06 callout was compared programmatically against the §E candidate in
`slice2-design-proposal.md`: strip tags, normalise typographic quotes/dashes and
whitespace, remove the appended house-style ruling ref, compare. **Result:
MATCH — word for word, all five sentences including the carve-out.** The only
addition to the ruled language is the trailing
`(decision:design/arrival-slice2-contract-text, ruling 1)`, in the same shape
§02's existing "Ruled — descriptor residence" callout uses. The §08 debt marker
likewise leads with the brief's sentence verbatim.

## Oracle status — full integrated suite, post-change

| Suite | Baseline | After WP5 | Delta |
|---|---|---|---|
| engine | 2062 passed, 1 skipped | **2063 passed, 1 skipped** | **+1** — the new `test_both_deliberate_absences_refuse_under_the_contract_root`. Nothing else added, removed or renamed. |
| store | 180 | **180** | 0 |
| lang | 671 | **671** | 0 |
| architecture | 99 | **99** | 0 |
| apps | 2530 passed, 1 xfailed | **2530 passed, 1 xfailed** | 0 — no `NotImplementedError` pin exists in apps src or tests, so the refusal-type change does not reach it |

Every delta is accounted for. Oracle 2's three mutation demos are in the two
sections above; oracle 3's tag-balance check passes on all five arrival files;
oracle 4 verified below.

**Two extra sweep checks, both clean:**

- `engine/__init__.py` does **not** re-export the contract refusal family (no
  `arrival_contract` entry in `_LAZY_IMPORTS`), so `NotSupported` needing to
  join a package-level export list does not arise. Its one slice-2 change is
  WP3's `fact_commitment_hash` repoint to `engine.admission`, already correct.
- No residual `"nine"` anywhere in `libs/engine/src/`, `libs/engine/tests/` or
  `docs/architecture/`. The WP1–WP4 scratch reports still say nine and are left
  alone — they are historical receipts of what was true when written, not
  living claims.

## Deviations

1. **Step 0 worktree (mechanical).** Recorded above and emitted as
   `finding:s2wp5-worktree-branch-already-checked-out`
   (`01M17N5CGDY49RDJCM4QJRC0B7`). `~/Code/loops-s2int` is a STALE checkout of
   this branch; the gate must use `~/Code/loops-s2wp5`.

No scope deviations. Every non-goal held: no consumer rewiring, no op beyond
the ruled tenth, no resumable importer, no KDL grammar change, no
`_canonical_bytes` consolidation, and `residence.py` is diff-empty.

## Raised, not fixed

`finding:s2wp5-capabilities-carries-no-wire-version`
(`01M17N5N77G3Q4ZARA0WR9RJTS`) — §12 requires `capabilities()` to report
"protocol AND WIRE versions"; `Capabilities` carries one `protocol_version`
field, filled with `GRAMMAR_VERSION`, so the typed surface cannot report a wire
version at all — while wire v1 is separately pinned and §08 export already
selects a codec by name. Left alone deliberately: the contract text is the
authority, and adding a field is a contract-surface change. The gate ruled
exactly one surface addition (`head_at`); taking a second would be executing a
ruling I was not given. Suggested home: the DuckDB-arc contract-text package,
beside the deferred §08 import op-row.

## Files changed (all on `slice/arrival-backend-contract`)

| File | What |
|---|---|
| `libs/engine/src/engine/arrival_contract.py` | `head_at` on the Protocol; `NotSupported`; `verify` docstring states the ruled MUST |
| `libs/engine/src/engine/arrival_file_backend.py` | two sites raise `NotSupported`; `verify` docstring cites the ruling |
| `libs/engine/src/engine/arrival_registry.py` | WP4-F1 import-time scoping |
| `libs/engine/tests/test_arrival_contract.py` | ten-row literal; the `head_at` classification pin; two type pins flipped; the new root-catchability test |
| `libs/engine/tests/test_arrival_registry.py` | stale "ten-op" cross-ref; the absent-projection docstring, now that its boundary is ruled |
| `docs/architecture/arrival/backend-contract.html` | the five ruled texts |
| `libs/engine/CLAUDE.md` | contract path, admission's new half, verification-MUST |
| `libs/store/CLAUDE.md` | `engine.admission` dependency; three-arm merge |
| `docs/scratch/arrival-break/slice2-wp5-report.md` | this report |
