# GATE REPORT — WP-5 (admission signature verification, D4 arm 1)

Independent gate. Target `5c756f2d` (`3280707e` engine + `87f3aba0` store +
report), base `feat/arrival-libs`. Branch `slice/D-wp5-gate`.

**Same-family caveat, stated up front.** The implementer was a Claude opus agent
and so am I. The specific risk is that I *recognise* its reasoning as sound
because it reasons the way I do, rather than because it is. I mitigated that by
re-deriving the contract from `design-proposal.md` §D4 **before** reading the
implementation, and by refusing to accept any load-bearing prose claim without an
executable probe — in particular the "unspellable" comment in §3 below, which
reads persuasively and which I attacked three ways instead of believing. Where a
probe of mine produced a suspicious result I re-ran it before reporting; two of my
first-cut probes had methodology bugs and are documented as such rather than as
findings. The codex cross-family pass remains the real independent check.

## VERDICT: **PASS** — 1 minor finding (W5-1), 1 scope observation (W5-2).

Nothing blocking. The selective boundary is correctly implemented and pinned from
both sides, admission verification is genuinely transactional, and the default
path is byte-identical.

---

## 1. Scope — clean

`git diff --name-status feat/arrival-libs..HEAD`:

| Status | Path |
|---|---|
| A | `WP5-REPORT.md` |
| M | `libs/engine/src/engine/arrival.py` |
| A | `libs/engine/tests/test_arrival_key_registry.py` |
| M | `libs/store/src/store/merge.py` |
| A | `libs/store/tests/test_admission_verification.py` |

Exactly the fence. `libs/store/tests/` shows **one file changed, 565 insertions,
zero deletions** — no existing test was edited, weakened, or removed. The 27
deletions in the stat are all inside `merge.py`, and all of them are lines
replaced in place (signature widenings and the `groups` tuple gaining an ordinal);
no behaviour was deleted.

## 2. Suite reconciliation — all seven green

| Suite | Result | Delta |
|---|---|---|
| atoms | 517 passed | 0 |
| engine | **1850 passed, 1 skipped** | **+9** |
| sdk | 324 passed | 0 |
| lang | 655 passed | 0 |
| store | **175 passed** | **+18** |
| arch | 98 passed | 0 |
| apps/loops | 2525 passed, 1 xfailed | 0 |

Reconciles exactly and without needing a baseline run: `test_arrival_key_registry.py`
collects **9**, `test_admission_verification.py` collects **18**, and the scope
diff proves no pre-existing test file was modified or deleted — so the deltas
*are* the new files. Matches the implementer's claimed +9 / +18.

`TestDivergenceRefusal` (`test_arrival_merge.py:727`) is untouched and passes
(5 passed).

## 3. Contract conformance — `key_registry`

Checked against §D4's specification clause by clause.

**Structural walk over everything.** `_walk_authority` iterates `log.walk()` in
full; density, record hashes and chain linkage are established for every record.
Their `test_the_whole_log_is_still_walked_structurally` pins it.

**Envelope verification ONLY for registry-forming records.** The boundary is one
expression: `if _SIG in record and (verify_ordinary or forming)`, with
`forming = record["k"] == KEY_INTRODUCTION_KIND`. Genesis is verified above this,
outside the `verify_ordinary` guard, so it is verified in **both** widths —
correct, since genesis self-certification is what roots the registry. Ordinary
envelopes are never verified in registry mode.

**The previously-valid-key authorization chain** is inherited rather than
reimplemented: a key introduction goes through `_resolve`, which resolves against
keys already valid for the *introducing* record's observer at that ordinal.

**ONE placement-rule implementation — verified by grep, not by assertion.**
`grep -rn "introduced <" libs/` returns exactly **one** hit,
`arrival.py:1606`, inside `_keys_valid_at`. Both consumers route through it: the
live walk via `_resolve`, and a finished registry via `KeyRegistry.keys_valid_at`.
There is no second copy of the validity clause anywhere in `libs/`.

### The one place I expected a hole — and it is closed

`_walk_authority` adds a key to the registry unconditionally:

```python
if forming:
    named = record["body"]["observer"]
    registry.setdefault(named, []).append((record["body"]["key"], ordinal))
```

The verification above it is guarded by `if _SIG in record`. So **an unsigned key
introduction would join the registry without ever being verified** — defeating
G-D4-4 — and the code defends this only with a prose comment ("the placement rules
make an unsigned introduction unspellable"). Against a *foreign* source log, whose
bytes an attacker controls, "unspellable via our API" would be worth nothing. I
attacked it three ways:

| Attack | Result |
|---|---|
| Append an unsigned introduction through the API | `AppendRejected: a key introduction carries no signature` |
| Hand-edit a real introduction's bytes to strip `sig` | `ArrivalCorrupt: rh does not recompute` |
| **Strip `sig` AND recompute a valid `rh`** | **`ArrivalCorrupt: a key introduction carries no signature`** |

The third is the real attack, and it is refused by the structural validator
(`arrival.py:486-491`) that `walk()` applies to every record before the registry
sees it. The comment is load-bearing-true, enforced by a structural rule rather
than by convention. **Not a finding** — but this is the assumption the whole
selective boundary rests on, so it is recorded as verified rather than assumed.

## 4. Contract conformance — `merge_store`

**Post-dedup admission set.** `_entries_for` now returns `admitted` — populated
only inside the survives-dedup branch, and only `if t == "fact"`. A row the dedup
drops never enters it.

**Verified against `fact_commitment_hash`, keyed by observer and source
position.** `_verify_admitted_rows` computes
`fact_commitment_hash(row[1], row[2], observer, row[4], row[5])`. I checked the
mapping rather than trusting it: `FACT_FIELDS = ("id","kind","ts","observer","origin","payload")`
and `fact_commitment_hash(kind, ts, observer, origin, payload_text)` — the
argument order is correct, and `row[6]` is indeed `signature`. Candidate keys come
from `registry.keys_valid_at(observer, ordinal)`, so a key valid for a *different*
observer, or introduced *later*, is not a candidate. Both are pinned by their
tests (`..._for_ANOTHER_observer...`, `..._introduced_only_LATER...`).

**Unsigned admitted rows admit, making no claim** — `if signature is None: continue`.

**Split batches** need no special handling because the admission set is per-row;
their `test_a_partly_deduped_batchs_survivors_are_verified_and_admitted` and
`test_a_forged_survivor_in_a_split_batch_refuses` cover both directions.

**Legacy source = explicit no-claim, NO refusal (D4-Q1).** Verified directly: a
transport `.db` carrying a row with a blatantly forged signature
(`sig:TOTALLY-FORGED`), merged **with** a verifier, **admits** —
`facts_added=1`, no exception. Correct per the ruling.

**Docstrings claim source self-consistency, not target trust.** The
`merge_store` docstring, `AdmissionUnverified`, `_source_registry` and
`_verify_admitted_rows` each state the scope explicitly, and both refusal messages
carry it into the exception text ("source self-consistency … not target-operator
trust in the source's keys"). This is the claim §D4 ruled, worded as ruled.

### Transactionality — verified, and my first probe was wrong

Structurally, `_source_registry` runs before the retry loop and
`_verify_admitted_rows` runs inside it but **before** `if dry_run or not entries`
and before any append, so a refusal precedes all writes.

My first probe hashed the whole target directory and reported "byte-identical:
False" for both refusal classes. **That was my error, not a finding** — the hash
included the sqlite index, which the merge's own read path touches. Re-run against
the canonical arrival log alone:

| Refusal class | Canonical log | Records | Target ids |
|---|---|---|---|
| Forged signature on an admitted row | **byte-identical** | 2 → 2 | `['t-1']` |
| Forged key introduction (bad key history) | **byte-identical** | 2 → 2 | `['t-1']` |

Nothing is appended on either failure half.

### Default path byte-identical — verified on the same fixture

My first attempt compared two separately-minted targets, which of course differ
(fresh lineage, fresh timestamps); that comparison was meaningless. Redone
correctly by building one fixture, `shutil.copytree`-ing it, and merging one copy
with `verify` and one without:

- `MergeResult` identical (`facts_added=1, facts_skipped=0, …`)
- **canonical log byte-identical**
- target ids identical

The sqlite arm is untouched, and supplying `verify` to a non-arrival target raises
`ValueError` rather than silently skipping the work — an honest addition, not a
contract divergence.

## 5. Independent break/restore — B2 (assigned)

Reduced the boundary to `if _SIG in record and verify_ordinary` (key introductions
no longer envelope-verified):

| Suite | Before | After break | After restore |
|---|---|---|---|
| engine `test_arrival_key_registry.py` | 9 passed | **1 failed**, 8 passed | 9 passed |
| store `test_admission_verification.py` | 18 passed | **1 failed**, 17 passed | 18 passed |

The failures are exactly `test_a_forged_key_introduction_refuses_the_registry` and
`TestForgedKeyIntroduction::test_an_introduction_no_valid_key_signs_refuses_the_merge`
— G-D4-4 in both suites, as the implementer's table claims.

**The more interesting half:** every G-D4-2 test stayed **green** under that break.
So the boundary's refusing side and its admitting side are pinned by *different*
tests and neither is a proxy for the other. That is what "pins the selective
boundary exactly" has to mean, and it holds.

I also confirmed the admitting side directly: a source whose ordinary envelope is
signed by a non-verifying key, carrying a row the target already holds, **merges**
(`facts_skipped=1`, no refusal). Their `assert_whole_log_verifier_refuses` helper
is a genuine positive control — it makes `verify_authorship` refuse the same log,
so the envelope really is bad and the case cannot pass vacuously. That is a piece
of test design I would not have thought to demand.

---

## FINDINGS

### W5-1 — MINOR — hardcoded column indices, recurrence of a previously-ruled finding

`_verify_admitted_rows` reads the row positionally:

```python
signature = row[6] if len(row) > 6 else None
observer = row[3]
digest = fact_commitment_hash(row[1], row[2], observer, row[4], row[5])
```

The indices are **correct today** — I verified all six against `FACT_FIELDS` and
`fact_commitment_hash`'s signature. The objection is that this is the identical
anti-pattern I filed as **F-4** in the WP-1a gate (`committed_row[6] if is_fact
else committed_row[10]`), which was ruled and fixed there by deriving the offset
(`FACT_CONTENT_COLUMNS.index("signature")`). New code in a neighbouring module has
reintroduced it, so the ratchet did not hold across the package boundary.

**Fix:** derive the offsets from `FACT_CONTENT_COLUMNS` as WP-1a's fix does. Cheap,
and it makes this loop survive a future content column instead of silently reading
the wrong field.

### W5-2 — OBSERVATION, not a divergence — ticks are never verified

`admitted` collects only `if t == "fact"`, so a tick row carrying a signature is
admitted without its authorship claim being checked. This **matches §D4**, which
scopes arm 1 to "each **admitted** (post-dedup) **fact row** carrying a non-NULL
signature", so it is conformant and I am not filing it as a finding. Recording it
so the codex pass and any arm-2 work start from the explicit fact that tick
authorship is outside the claim this merge makes — not from the assumption that
"admission verification" covers everything admitted.

---

## What I could not verify

Nothing material was left unverified. Two limits worth stating honestly:

- The injected `Verify` in these tests is a deterministic keyed stub, not real
  crypto. That is the library's design (`libs/sign` is deliberately not a
  dependency) and the right call for tests, but it means these gates prove the
  **key-placement and selection logic**, not any cryptographic property. A real
  signer is out of this package's scope.
- I did not attempt concurrent-merge races against the retry loop; admission
  verification runs inside the loop and re-derives per attempt, which is the
  correct structure, but I did not exercise two mergers at once.

## Bottom line

**WP-5 PASSES.** The redesigned arm 1 is implemented as ruled: a selective walk
whose boundary is one expression and one shared placement rule, verification of
exactly the post-dedup admission set against the content-only commitment, a legacy
source admitted with an explicit no-claim, and refusals that append nothing and
claim only source self-consistency. Both sides of the selective boundary are
pinned by independent tests, and the assumption the boundary rests on — that an
unsigned key introduction cannot be spelled — is enforced structurally, which I
confirmed against a fully-forged foreign log rather than taking the comment's word
for it.

W5-1 should be fixed as housekeeping; it is a ratchet leak rather than a defect.
Sending to the codex cross-family pass.
