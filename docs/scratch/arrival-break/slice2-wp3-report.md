# Slice 2 / WP3 impl report — admission extraction

Branch: `slice2/wp3-admission`, off `0d38c969` (verified `git merge-base HEAD
slice/arrival-backend-contract` = `0d38c969`). Worktree: `~/Code/loops-s2wp3`.

Contract: `docs/scratch/arrival-break/slice2-wp3-brief.md`. Design sections bound:
`slice2-design-proposal.md` §C (all) and §D.3. SD-1 holds — the coordinate machinery
(`_stage_arrival_coordinates` / `_check_arrival_provider_agreement` / `_stamp_arrival_axis`)
is projection and was not touched.

---

## 0. Baseline, captured on clean `0d38c969` before any edit

Package-scoped runs, because a root `uv run pytest` misses each member's own dev group
(`hypothesis`) and a combined engine+store invocation collides on `tests.conftest`:

| Suite | Command | Baseline | Final | Delta |
|---|---|---|---|---|
| engine | `uv run --package engine pytest libs/engine/tests -q -p no:randomly` | 1989 passed, 1 skipped | **1990 passed, 1 skipped** | +1 |
| store | `uv run --package store pytest libs/store/tests -q -p no:randomly` | 180 passed | **180 passed** | 0 |
| architecture | `uv run pytest tests/architecture -q -p no:randomly` | 99 passed | **99 passed** | 0 |

**The one delta is the sol-LOW r1 regression test** added in §7
(`test_admission_callback_ownership.py`, one test). Every other delta is zero, and that is
the intended result for an extraction: the suites are the same tests over the same
behaviour, which is what makes "green unmodified in intent" checkable — see §4 for the one
test whose *scenario* did change, and how it was caught without a failure to point at.

*(At the original hand-off the engine suite was 1989 and every delta was zero; §7 landed
after sol's review.)*

Lint is not a CI gate for these packages (CI runs `ruff check libs/custody libs/sign`
only), but the three touched source files were compared against their own baseline
contents **in-tree**, so config resolution matches: baseline 61 findings, final 60
(`I001` 3→2). No new class of finding. The first comparison attempt, run from a
scratchpad directory, resolved a different ruff config and produced a meaningless
16-vs-61 — recorded because the number is wrong, not because it is interesting.

---

## 1. What moved

`engine/admission.py` grew 134 → 720 lines; `store/merge.py` shrank 857 → 525;
`sqlite_store.py` 2860 → 2822. Net across the change: +719 / −450 over 8 files.

| Moved | From | To |
|---|---|---|
| the admission op (§04 steps 1–8, caller side) | `merge.py` `_merge_into_arrival` | `admission.admit_records` |
| `MergeDivergence` / `_comparable` / `_COMPARED_FIELDS` / `_refuse_divergence` | `merge.py` | `admission` |
| `AdmissionUnverified` | `merge.py` | `admission` |
| `_source_registry` / `_verify_admitted_rows` | `merge.py` | `admission` |
| `_entries_for` → `_drafts_for`, `_entry_for` → `_draft_for` | `merge.py` | `admission` |
| `_SourceRows` → `SourceRows` | `merge.py` | `admission` |
| `fact_commitment_hash` / `_fact_commitment_hash` / `_canonical_bytes` | `sqlite_store.py` | `admission` |

**Extraction stopped at delegation.** `_merge_into_arrival` still exists and still owns
the arm; no merge arm was deleted, and `merge_store`'s three-way dispatch is byte-identical.

**What deliberately stayed in `store`:** `_read_source` / `_read_arrival_source` /
`_read_index_source` (reading a source is the caller's business), `_target_state` and
`_rederive_after_append` (the sqlite projection is the §07 projection half's obligation),
`_pinned_head` (not in the §C.3 table, and `test_arrival_merge_pin.py` imports it by that
path), and `MergeResult` (`store`'s public result type).

**Public surface unchanged.** `merge.py` imports `MergeDivergence` and
`AdmissionUnverified` back from `engine.admission` and names them in a new `__all__`, so
`store.MergeDivergence`, `store/__init__.py`, and every `from store.merge import …` in the
suites keep working untouched. `sqlite_store.py` imports the commitment back under **both**
historical names, so `from engine.sqlite_store import fact_commitment_hash` (two test
files) and `… import _fact_commitment_hash` (two more) are unaffected.

---

## 2. Design choices, one line each

1. **The op takes two callbacks, not paths.** `target_state` and `rederive` cross the lib
   boundary as callables because the sqlite projection is the caller's and `engine` may not
   import `store` to reach it; both are re-invoked per attempt, which is what makes a retry
   make progress.
2. **`target_state` returns a completed `Head`, not a `ResumeMark`.** Store composes
   `_target_state` + `_pinned_head` in the closure, so `_pinned_head` stays put (matching
   the enumerated scope), the op speaks contract vocabulary, and the anchor read moves from
   append-time to read-time *within the same attempt* — behaviour-equivalent, because F1's
   enforcement point is the full-head compare under the lock in `append_marked_many`.
3. **`_entry_for` → `_draft_for`, returning `RecordDraft`.** The design asks for the draft
   constructor; a function that returns a draft while still named for `Entry` is exactly the
   trail a rename is supposed to sweep. The one stale prose pointer
   (`test_arrival_merge.py:301`) was updated in the same change — one line, no assertion
   touched.
4. **`_entries_of` is the draft→`Entry` seam, and is named as slice-5 residue.** The op
   still calls `append_marked_many` directly (the brief pins that loop as the op), so it
   converts at the call; when slice 5 routes this through `ArrivalLedger.append`, the
   conversion moves behind the ledger and this function dies. It duplicates
   `FileLedger.append`'s conversion today; that is the cost of not rewiring in this slice.
5. **`fact_commitment_hash`'s two spellings collapsed to one definition.** `sqlite_store`
   held the same function under a public and a private name; only one crossed, and
   `sqlite_store` re-binds both by alias. No third `_canonical_bytes` was minted and
   `arrival.py`'s spelling was not touched (slice 5's, named in the design).
6. **`AdmissionResult`, not `MergeResult`, is what the op returns.** `engine` cannot import
   `store`'s public result type; `_merge_into_arrival` maps the four counts across.
7. **`engine/__init__.py`'s lazy map repoints** `fact_commitment_hash` to
   `engine.admission` — the honest home. `engine.sqlite_store`'s binding still works, so
   nothing had to change with it.
8. **`_canonical_bytes`'s docstring was rewritten for its new home, not carried verbatim.**
   It named the legacy migration op (`sl store reanchor`), and `reanchor` is a Rule 18
   denied term — a docstring cannot cross onto the arrival surface carrying retired
   vocabulary. The information survives; the retired identifier is left named where it
   lives, in `sqlite_store`.
9. **`APPEND_ATTEMPTS` moved with the loop** and became the op's default rather than a
   parameter merge passes; nothing outside `merge.py` referenced the old `_APPEND_ATTEMPTS`.
10. **`merge.py`'s `engine.admission` import is module-level, breaking that module's
    otherwise all-lazy import discipline.** A re-export cannot be lazy without
    `__getattr__` machinery, and `store/__init__.py` already imports `store.merge`
    eagerly, so the deferral would buy nothing. Measured rather than assumed: on the
    `sdk.emit` path `rfc8785` costs ~0.4ms and `dataclasses` is already loaded before
    `engine.admission` is reached, so `engine.admission` itself measures 968µs cumulative
    with no child import attributed to it. Rule 16 is unaffected — it judges a bare
    `import engine`, which stays lazy.

---

## 3. Rule 18

`libs/engine/src/engine/admission.py` joined `_SCAN_TARGETS`, with the join trigger named
at the site: custody moved into it, which is the rule's own stated trigger. The comment
also records why the §F completeness ratchet does not cover it — the ratchet claims only
what the `arrival*.py` naming convention can identify, and widening it to *guess* at
custody would turn a location claim into a verdict claim. Rule 18 is green with
`admission.py` scanned (99/99 architecture tests pass, unchanged).

Rule 4 is green: no `engine → store` import was introduced. The one direction that exists
is `admission` reaching `sqlite_store` for `FACT_COLUMN_INDEX` **inside a function**, never
at import — which is what keeps `sqlite_store`'s module-level import of the commitment from
being a cycle. Rule 16 is green: `engine.admission`'s new module-level `hashlib` /
`dataclasses` / `rfc8785` do not reach a bare `import engine`, which stays lazy.

---

## 4. Deviations and findings

### D1 — `_entries_for` and `_SourceRows` moved, and §C.3's table names neither

`finding:slice2-wp3-forced-moves-beyond-the-table` @ `01M17DVAVXYN5A7BVYYRATDSXZ`.

Rule 4 forces it exactly as it forces the `MergeDivergence` trio. `_entries_for` calls
`_comparable`, `_refuse_divergence` and the draft constructor, and it produces the
`admitted` set `_verify_admitted_rows` consumes — all four of which the table moves. Leaving
it behind would mean either `engine` importing `store`, or `store` importing four private
`engine` names back across the boundary to reassemble a loop that no longer lives anywhere
whole. `_SourceRows` is the op's input shape and `_source_registry` reads its `.canonical`,
so it crossed as public `SourceRows`. Reported because the enumerated table is what a gate
checks against.

### D2 — the old-canon test scenario was silently half-built, and no test failed

`finding:slice2-wp3-old-canon-scenario-half-built` @ `01M17DVK2DBBB5VG27YRYJBQ47`.

`test_tick_chain.py`'s `_build_old_canon_store` patches `sqlite_store._canonical_bytes` to
build a store whose commitments predate the JCS swap. Once the fact commitment lived in
`engine.admission`, that patch reached the **tick chain only**: the fixture became old-canon
in its chain and JCS in its fact signatures — a store the helper's docstring does not
describe. `TestReanchor` never asserts fact verification *before* `reanchor`, so all 51
tests stayed green over a scenario that had stopped being the scenario.

Measured rather than argued, with a throwaway probe run on both sides (the baseline arm on a
disposable detached worktree at `0d38c969`, since deleted):

| Arrangement | `verify_facts` before `reanchor` |
|---|---|
| baseline `0d38c969`, patch `sqlite_store` only | `ok=False`, 3 breaks |
| after the move, test unmodified | **`ok=True`, 0 breaks** |
| after the move, patch `sqlite_store` + `admission` | `ok=False`, 3 breaks |

Fixed by patching both modules inside the same `monkeypatch.context()`, with the reason
named at the site. The general shape is worth carrying past this WP: **a module-global
monkeypatch is a seam that a move can sever without any assertion noticing**, so a function
that moves has to be checked against what *patches* it, not only against what calls it.

### Not a deviation, recorded for the gate

`sl emit` was first run with `topic=` where the `finding` kind folds by `name`; the CLI
warned and stored the fact unfolded (`@ 01M17DV11GB0GPQR5YV6R8GGTQ`). The finding was
re-emitted correctly with `name=`. Two facts exist for D1; only the second folds.

---

## 5. Mutation demonstration — the op is on the live path

Three mutations, each on **moved** code, each restored with `git diff` verified empty
afterwards. The store suite was re-run green (180) after the last restore.

| # | Mutation | Result |
|---|---|---|
| a | `_refuse_divergence` returns before raising | `TestDivergenceRefusal` — **3 failed**, 28 passed |
| b | `_verify_admitted_rows` returns before checking | `test_admission_verification.py` — **5 failed**, 13 passed |
| c | `admit_records` hands `_drafts_for` the **source's** genesis observer | `test_a_merged_tick_names_the_TARGETS_custodian` — **1 failed** |

Mutation (c) is the one that does double duty: it proves the `RecordDraft` constructor is on
the live path, and it is the specific wrong implementation slice-1's destination-genesis
tick observer semantics exists to refuse — the test's own three-way-distinct fixture
(target custodian, source custodian, tick name) catches it on the value, not by coincidence.

**The revert-the-delegation arm was deliberately not run.** Restoring a faithful inline copy
of the loop in `merge.py` passes by construction — the code would be the same code in a
different file — so that arm cannot discriminate and its passing would say nothing. The
brief's "e.g. break the op's refusal" licenses exactly the three above, which do.

---

## 6. Oracle checklist

| # | Item | Status |
|---|---|---|
| 1 | `test_arrival_merge.py` + `test_admission_verification.py` green unmodified in intent | **yes** — one prose pointer updated in the former (§2.3), no assertion or import touched |
| 2 | Rule 4 green — no `engine → store` import | **yes** |
| 3 | Rule 18 green with `admission.py` scanned | **yes** |
| 4 | Mutation demo shows the op is on the live path | **yes** — §5, three mutations |
| 5 | Full engine + store suites green, deltas accounted | **yes** — §0, all deltas zero |
| 6 | `git ls-files` clean on all changes | **yes** |

---

## 7. sol-LOW r1 — S2WP3-L-1, the callback mapping was caller-owned

**Blocking finding, fixed.** `_drafts_for` writes every proposed source id into the
mapping it dedups against — that is how one source carrying an id twice appends it once —
but it writes them *before* the compare-and-swap append that would make them true. While
that code was private to `store.merge` the mapping was always a fresh `dict` built by a
SELECT one call earlier, so the write could not reach anyone. **The extraction is what made
it reachable**: ownership of a value that crosses a callback boundary is a question the
boundary has to answer, and this one had not been asked. Neither the gate nor I could see
it structurally, because the consumer it harms — a backend serving `target_state` out of an
owned, incrementally-maintained cache — does not exist in-repo yet. It is exactly the
second backend the contract exists for.

Sol's repro: owned cache + a compare-and-swap interloper → attempt 1 injects the ids, loses
the race, and attempt 2 dedups the records away against attempt 1's own proposals. Silent
drop, reported as `AdmissionResult(facts_added=0, facts_skipped=2)`.

**Fix arm, per the arbiter ruling: construction over detection.** `admit_records` takes a
defensive copy of the mapping on entry, every attempt, so mutating caller-owned state
becomes inexpressible. The documentation arm ("callbacks must return a fresh dict") was
ruled out and not taken — it is vigilance, and it would have made a legitimate
implementation of the contract silently wrong. One dict per attempt is noise against the
I/O. The op's docstring now states the copy as a **guarantee this side keeps**, not as a
freshness obligation on the caller.

**Regression test:** `libs/engine/tests/test_admission_callback_ownership.py` — a fake
backend whose `target_state` returns the SAME owned mapping on every call, seeded with one
genuinely-held row, plus an interloper appending between the pin read and the append so
attempt 1 is guaranteed to lose. It asserts both properties the finding names: both records
land on the retry (`facts_added=2, facts_skipped=0`, and both ids present in the log), and
the caller's mapping comes back exactly as it went in. The seeded row makes "unmutated"
bidirectional — nothing injected, nothing removed.

**Mutation demo:** removing `held = dict(held)` fails the new test with
`assert (0, 2) == (2, 0)` — sol's counts, reproduced exactly. Restored; `git diff` clean;
suites re-run (engine 1990, store 180, architecture 99).

Sol's other finding (L-2, `rederive` raising after a successful append leaves the derived
log stale) is verified pre-existing at the wave base and deferred to slice 5 — not touched
here.
