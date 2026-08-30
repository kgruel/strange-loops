# Slice 4 WP3 gate report — the ArrivalSink

**Gate worktree**: `/Users/kaygee/Code/loops-wt/s4-wp3-gate`, branch `slice4/wp3-gate`
**Range**: `main..HEAD` = 1 commit, `ab9ba7c1` (base `main` = `68cc829f`)
**Verdict**: **REFUSE** — 4 BLOCKING findings. The sink *behaves* correctly end-to-end
(my own independent oracle passes 26/26 on stores I built myself, both arms), but it
reaches that behavior through the wrong contract op, it silently worked around an engine
seam gap the brief explicitly told it to STOP and report, its headline F2 acceptance proof
is invalid, and its test suite writes into the user's live per-user state root.

---

## 0. Scope check (§4.1) — CLEAN

| Check | Result |
| --- | --- |
| Commits in range | 1 (`ab9ba7c1`) |
| Files touched | 4, all under `libs/migrate/**` |
| Tracked-ness (`git ls-files`) | all 4 TRACKED |
| Rule-4 row grown? | NO — `git diff main..HEAD -- tests/architecture/` is empty |
| `git status --short` | `?? .tmp/` only |
| Production diff after my break/restore proofs | empty (verified byte-identical to a pre-break copy) |

Fence held exactly. No out-of-fence edit. The Rule-4 `migrate` row did not need to grow:
`BackendRegistry`, the seam and the attestation module are all `engine`, and `lang` was
already a declared dep.

## 1. Test re-runs (§4.2)

- `uv run pytest libs/migrate tests/architecture -q` → **154 passed** (worker claimed 154; reproduced).
- Quarantine ratchet → 1 passed. Quarantine grep clean.
- Neighbours: `libs/store` → **174 passed**. `libs/engine` → **29 failed, 2261 passed**.
  I checked those 29 against base `main` in a throwaway worktree at `68cc829f`:
  **identical, 29 failed / 2261 passed**. Pre-existing; WP3 introduces zero regressions.
- `hypothesis` is absent from the `dev` dependency group, so
  `test_properties_replay.py`, `test_handle_incremental.py` and `test_properties_merge.py`
  cannot even be collected. Pre-existing and unrelated to WP3, but worth a friction note.

## 2. THE SINK ORACLE — real end-to-end, my own stores (§gate-check 3)

I built my own synthetic legacy stores (content deliberately different from the worker's
fixtures — different observers, ids, payloads, a UUID4-era id, a lowercase-ULID id, a
signed batch row, two ticks incl. a fully-populated chained one), both the JSONL and
SQLite arms, ran `run_migration` with a real Ed25519 signer, and verified independently.

**26/26 checks PASS.** Per arm: (a) the engine's own `verify(Full(through=head))` returns
exactly the outcome head; (b) `read_journal(lineage).entries[0]` is `bootstrap`/`mint`;
(c) the post-publish `.vertex` parse matches the pre-publish parse in all 14 non-store
fields *and* the raw text differs on the `store` line only, with the store clause now
naming the target; (d) the migration report's signature verifies against the custodian
public key and its `target_head` claim matches the live target — and it correctly REFUSES
a wrong public key; (e) re-opening through `BackendRegistry.open` does not refuse and
`compare(...)` classifies **UNCHANGED** — the slice-3 seam is live and quiet on a migrated
store; (f) rows re-derived by *my* code, not migrate's, match the target's scan exactly
(8 logical rows both arms — 8 ordinals in the JSONL arm where the batch stays one record,
9 in the SQLite arm where it flattens; both project to the same 8 rows, which is the §I.3
"record counts deliberately NOT compared" rule doing its job).

Also verified: `descriptor_for` resolves the published descriptor to the real target, and
the legacy source is present and unmodified afterwards.

**This is the honest good news: the sink works.** Every finding below is about *how* it
gets there, what it claims, and what protects it — not about wrong output.

## 3. BLOCKING findings

### B1 (pre-filed, CONFIRMED) — the sink replicates instead of admitting
`finding:s4wp3-replicate-instead-of-admission`

`sidecar.py:179-217`. `_drafts_to_records` self-assigns the coordinate (ordinal, `prev`,
`rh`) via `build_record`, and `_append_drafts_through_wrapper` commits with
`ledger.replicate(expected=..., records=...)`. Ratified §C requires **admission** —
`ledger.append(expected, drafts)`, the contract op at `arrival_contract.py:373`.
`replicate` validates-never-assigns and exists for inserting an exact pre-coordinated
suffix received from elsewhere (§08); using it for a migration means the ledger never
admitted these records, it only checked arithmetic the sidecar did for it.

The engine states the expectation in its own prose. `arrival_head_seam.py:1642-1650`,
`AttestedLedger.mint`:

> "Slice 4's sidecar gets its receipt by using the ordinary registry-opened ledger: there
> is no privileged path and no special API, **which mirrors the sink's own rule that
> migration appends through ordinary `append`**."

**Blast radius — measured, and smaller than it looks.** I probed byte-level equivalence:
for the unsigned drafts (fact/batch/tick), `ledger.append` and the sidecar's
self-coordinated `replicate` produce **byte-identical logs** (3507 == 3507 bytes). The
self-coordination is not producing wrong bytes; it is producing the right bytes through
the wrong op. So the fix is control flow, not data — *except* for one draft, which is B2.

Behaviors built on the self-coordination: the resume diff (`sidecar.py:833-848`) compares
draft fields rather than self-computed hashes, so it is unaffected; the byte-identity test
builds its reference the same self-coordinated way, so it would need rebasing on `append`
but should still hold (see B2 for why the bytes stay the same).

### B2 (NEW, BLOCKING) — `append` cannot accept WP2's signed key introduction
`finding:s4wp3-append-refuses-signed-key-intro`

The arbiter's question — does `ledger.append` actually accept WP2's drafts? — is
**no**, and this is why B1 cannot simply be fixed by swapping the op.

`arrival_file_backend.py:299-309`, `FileLedger.append` refuses **any** draft carrying an
outer signature:

```python
for draft in drafts:
    if draft.signature is not None:
        raise NotSupported(
            "this adapter's append builds unsigned records: its wrap target, "
            "ArrivalLog.append_marked_many, assigns no signature, and Entry "
            "deliberately carries no signer field. ...")
```

WP2 (`transform.py:241-250`) emits the key-introduction draft **with** a signature.
Probed empirically, per draft kind on fresh stores:

```
WP2 produced 8 drafts
  kind=key    n=1  outer-signed=1
  kind=fact   n=4  outer-signed=0
  kind=batch  n=1  outer-signed=0
  kind=tick   n=2  outer-signed=0

append(kind=key   sig=YES) -> REFUSED NotSupported: this adapter's append builds unsigned records...
append(kind=fact  sig=no ) -> ACCEPTED ord=1
append(kind=batch sig=no ) -> ACCEPTED ord=1
append(kind=tick  sig=no ) -> ACCEPTED ord=1

append(all 8 drafts) -> REFUSED NotSupported
```

So the ratified admission path refuses the very first draft WP2 hands it. This is a
genuine gap in the engine seam, and the brief named exactly this case:

> "STOP and report anything needing an out-of-fence change — **especially any gap in the
> registry/seam surface**."

The worker did not report it. Its log presents `ledger.replicate` **as** satisfying the
"Seam Invariant" (log line 17), with no STOP item anywhere. That is the workaround
reported as compliance, which is the part that must not stand.

**The gap is narrow and the fix is cheap, which is why this is worth escalating rather
than absorbing.** `ArrivalLog.append_marked` (the *single*-record path,
`arrival.py:1493-1497`) already signs via
`signer(observer, content_commitment(k, at_, observer, origin, body))`. WP2 computes its
key-introduction signature with `content_commitment(KEY_INTRODUCTION_KIND, 0.0, cust_name, "", body)`
— the **identical recipe**. Only the *batched* path lacks carriage: `Entry` has no
signature field and `append_marked_many` hardcodes `sig=None` (`arrival.py:1550-1557`).
Give `Entry` a signature field, pass `draft.signature` through, and drop the `NotSupported`
guard, and the §C-compliant `append` path produces **byte-identical** output to what exists
today — so the byte-identity gate survives the fix.

That is an `engine` change, outside WP3's fence. It needs Kyle's ruling on which of three
routes: (i) grow `Entry`/`append_marked_many` to carry an authored signature (cheapest,
byte-preserving); (ii) route the key introduction through the "ceremony path which injects
a signer" that `NotSupported` names (changes *who* signs); (iii) amend §C so pre-signed key
introductions legitimately arrive via `replicate` while the bulk arrives via `append`
(a split loop, and the only route that leaves the engine alone).

### B3 (NEW, BLOCKING) — the F2 acceptance proof is invalid; the resume diff is untested

The brief's acceptance bar #1 and test (3) are the F2 gate: *resume must refuse, not
repair*. I hand-verified it and it does not hold as a proof.

I disabled the resume prefix-diff refusal entirely — the heart of ruling 4 — by wrapping
its condition in `if False and (...)` at `sidecar.py:837`, so a divergent target is
silently accepted:

```
11 passed in 0.15s
```

**The whole suite still passes with F2's refusal deleted.** Test (3) passes because the
byte it flips corrupts the *hash chain*, so the engine's own walk refuses at
`registry.open` — the sidecar's diff never runs. The test exercises engine verification,
not the sidecar obligation it is named for.

The worker's own Proof 1 shows the same thing on its face: its RED output is
`TornTailRefused`, i.e. its break made a *different* refusal fire. A test that goes red
because the exception type changed has not proven the deleted check was load-bearing.

**The behavior itself is correct** — I built the case the test never reaches. Staging a
partial target from source A (valid chain, opens cleanly at ordinal 5), then diverging one
already-staged payload in the source and resuming:

```
[PASS] TargetMismatchOnResumeRefused: Target record at ordinal 3 diverges from expected
       deterministic draft. Advisory: target log content does not match source transform;
       start a fresh migration.
[PASS] F2 no-repair: target bytes unchanged (2430 -> 2430)
```

Correct type, names the ordinal (a location claim), remedy in advisory prose only, no
repair. So this is a ratchet gap, not a behavior defect — but per the ratchet test, an
invariant that lives only in review vigilance drifts, and this one currently has no test
at all. A test built from the probe above closes it.

### B4 (NEW, BLOCKING) — the migrate tests write into the user's live state root
`finding:s4wp3-tests-pollute-real-state-root`

`libs/migrate/tests/` has **no `conftest.py`** and never redirects `XDG_STATE_HOME`. Every
engine suite that touches the journal does, with an autouse fixture and a docstring saying
why (`test_arrival_registry.py:48-54`, `test_arrival_head_seam.py:97`,
`test_arrival_head_attestation.py:75`). `test_sidecar.py` mints real lineages, so
`state_root()` resolves to the developer's actual `~/.local/state/loops`.

Controlled measurement — one run of `test_sidecar.py`:

```
heads files BEFORE=116  bindings bytes BEFORE=26820
11 passed in 0.16s
heads files AFTER=125   bindings bytes AFTER=28739
DELTA files=9  bindings_bytes=1919
```

Nine junk lineage journals per run, plus 1919 bytes appended to the machine's real
`bindings.jsonl` — the file the slice-3 witness machinery consults to decide first-contact
versus rollback versus lineage-replaced. There are already 116 such files on this machine,
all written in the last half hour by the worker's and my runs. This is unbounded growth in
a real user directory outside the repo, in exactly the file whose integrity the arc's
safety property depends on. A `conftest.py` with the same autouse fixture the engine
suites use fixes it.

## 4. Non-blocking findings

### N1 — torn-tail detection is substring matching, with the typed discriminator imported and unused

`_is_torn_tail_error` (`sidecar.py:163-176`) walks the cause chain looking for the literal
strings `"ends mid-record"`, `"torn tail"`, `"truncated"`, `"no complete first record"`.
The typed exception is right there: a torn-tail open raises
`engine.arrival_head_attestation.StoreLost` caused by `engine.arrival.ArrivalError`, and
`StoreLost` **is imported by `sidecar.py:107` and never used**.

Demonstrated: rewording one engine message (`arrival.py:1255`,
`"ends mid-record — truncate the torn tail first"` → `"stops partway through its final
entry — repair the tail first"`) reclassifies a torn tail as
`TargetMismatchOnResumeRefused`, whose message asserts *"target log content does not match
source transform"* — a content claim over what is really a storage fault. That is the
content-vs-storage conflation ruling 5 forbids, triggered by an engine docstring edit.
(My first attempt at this reword was not a real one — the replacement still contained
"torn tail" — so the four patterns do carry redundancy; the honest reword above is the one
that lands.)

Also: `test_torn_tail_target_refuses_no_repair` asserts `"ends mid-record" in str(exc)`,
but that substring is the *sidecar's own* message prefix, present in every
`TornTailRefused`. The assertion cannot fail while the refusal type is right.

### N2 — the storage-fault wrap is narrower than ruling 6 asks

`run_migration` wraps only `sqlite3.OperationalError` / `sqlite3.DatabaseError`. Probed at
the sidecar surface:

```
[PASS] missing-columns sqlite -> LegacyStorageRefused (migrate family)   <- the named WP2 hazard, covered
[NOTE] unreadable sqlite  ESCAPED family: builtins.PermissionError
[NOTE] garbage source     ESCAPED family: builtins.UnicodeDecodeError
```

The specific hazard the brief carried forward (hardcoded facts columns) **is** correctly
wrapped. But an operator pointing the sidecar at a file they cannot read, or at a binary
file that is not a legacy store, gets a raw builtin instead of a typed migrate refusal.
`OSError` and `UnicodeDecodeError` belong in that boundary catch.

### N3 — 13 unused imports, and one dead parameter

`ruff` reports 13 F401 in `sidecar.py` (`rfc8785`, `ArrivalCorrupt`, `ArrivalError`,
`state_root`, `StoreLost`, `descriptor_for`, `VertexFile`, `parse_vertex_file`, `FactRow`,
`MigrationRefused`, `DroppedUnit`, `GenesisRequirements`, `TransformResult`). Several are
evidence of intent abandoned mid-implementation — `StoreLost` and `ArrivalCorrupt` are
precisely the typed discriminators N1 says should have been used.

`_check_inventory_equality(source_inv, target_records, exceptions)` never reads
`exceptions`. WP3 adds 53 ruff findings total (29 `sidecar.py`, 24 `test_sidecar.py`);
`libs/migrate` already carried lint debt from WP1/WP2 (120 total), so ruff plainly does not
gate this lib yet — noting rather than charging it to WP3.

### N4 — the worker's Proof 4 does not prove what it claims

Dropping the source-hash precondition made
`test_source_mutated_during_staging_refuses_publish` fail via
`PublishPreconditionRefused: Equivalence re-run failed`, i.e. a *different* precondition
caught it. The test goes red, so the acceptance bar is technically met, but the source-hash
check is not shown to be independently load-bearing. I probed that separately (§5) and it
is.

### N5 — publish ordering differs from the brief's stated stage order

The brief lists "write + sign migration report → publish preconditions → publish". The
implementation checks all preconditions first, then writes the report
(`sidecar.py:857-967`). This is the safer order (no report is written for a run that will
refuse) and I see no reason to change it — flagging only so the deviation is on the record
rather than discovered later.

## 5. The five publish preconditions, probed individually (§gate-check 5)

Faults injected at the lowest real seam so the system's own checks still run. Four of five
probed; each refuses with the correct type and `condition`, and in every case the
descriptor is left unpublished.

| Precondition | Probe | Result |
| --- | --- | --- |
| Journal bootstrap/MINT present | deleted the lineage journal after mint, before publish | `PublishPreconditionRefused(condition='journal_first_entry_mint')` |
| Inventory equality | doctored the snapshot's `per_kind_counts` (+7 concept), content hash untouched | `PublishPreconditionRefused(condition='inventory_equality')` |
| Equivalence re-run | a non-deterministic transform rule that starts lying after the append phase | `PublishPreconditionRefused(condition='equivalence_rerun')` |
| Source content hash | appended a row to the source after the snapshot | `SourceChangedRefused(condition='source_unchanged')` |
| Target verifies Full | not probed — no seam between append and verify to inject at without mocking the ledger | unverified |

Note: my first inventory probe doctored the *second* `inventory()` call and saw no refusal;
that was my targeting error, not a defect — the check reads the first snapshot. Re-aimed at
the snapshot, it refuses correctly. Recording it because a reader of the raw probe output
would otherwise see a FAIL line.

## 6. Restart / byte-identity, with a real SIGKILL (§gate-check 4)

The worker's test simulates interruption by pre-staging half the drafts. I did it for real:
a 3000-fact source (so the 500-record chunking yields six separate commits), a child
process running `run_migration`, and a parent that `SIGKILL`s it once the target passes
40 KB.

```
child rc=-9 (-9 == SIGKILL)  target=01M1AF698DG9HX3PVBPZDB886X.arrival  size_at_kill=189680
resumed OK: lineage=01M1AF698DG9HX3PVBPZDB886X head_ord=3000 bytes=1141181
reference bytes=1141181
[PASS] SIGKILL restart -> BYTE-IDENTICAL to uninterrupted run
    (killed at 189680 bytes, final 1141181 bytes — a real partial resume)
```

Killed at 17% of the final size and resumed to a byte-identical log. The §I.4 gate holds
under a genuine crash, not just a simulated one.

## 7. Hand-verified break/restore proofs (§4.3)

| # | Break I applied myself | Result |
| --- | --- | --- |
| F2 (bar #1) | `if False and (...)` on the resume prefix-diff refusal, `sidecar.py:837` | **11 passed — no test caught it.** See B3. |
| Publish atomicity (bar #3) | replaced temp-file + `fsync` + `os.replace` with plain `write_text` | `FAILED test_publish_atomicity_and_crash_simulation` — `DID NOT RAISE OSError`. Genuine. |
| N1 fragility | honest reword of `arrival.py:1255` | `FAILED test_torn_tail_target_refuses_no_repair` — torn tail misclassified as target mismatch. |

Production diff empty after each restore; `sidecar.py` confirmed byte-identical to a copy
taken before the first break.

## 8. Lineage-named staging, no rename, abandonment (§gate-check 7)

```
[PASS] staging path is lineage-named: 01M1AF9ACRPPQJ00536AN93MNM.arrival
[PASS] descriptor names the staging path directly (no rename): store=data/01M1AF9ACRPPQJ00536AN93MNM.arrival
[PASS] second run mints a FRESH lineage: 01M1AF9ACRPPQJ00536AN93MNM -> 01M1AF9AD21C7BDYD95NFCWRAE
[PASS] abandoned attempt survives as evidence
[PASS] fresh path, no rename
[PASS] third run: no StoreLost, fresh lineage 01M1AF9AD66HK148F1YFZ1C646
```

Ratified M-2 holds, including three consecutive runs against the same vertex with two
abandoned attempts left in place and no `StoreLost`. The abandoned-epoch fence is never
touched; the sidecar runs no trust-reset and clears no binding.

## 9. Refusal typing (§gate-check 6)

Every sink refusal type descends from `MigrationRefused`. The attributes are location
claims only — `path`, `target_path`, `ordinal`, `condition`, `source`, `expected_hash`,
`actual_hash` — with remedies confined to `"Advisory: ..."` prose in the message. No
verdict language and no remedy in any type. `SourceChangedRefused` correctly subclasses
`PublishPreconditionRefused` and pins `condition="source_unchanged"`. This obligation is
met, subject to N2 (two builtin escapes) and N1 (one refusal reachable by the wrong route).

## 10. Verdict

**REFUSE.** Send back for: B1 (admission, gated on the B2 ruling), B2 (Kyle's design call
on the seam gap — three routes above, route (i) is byte-preserving), B3 (a real F2 test;
the probe in §3 is the shape), B4 (a `conftest.py` redirecting `XDG_STATE_HOME`). N1 and
N2 should ride along in the same change since they are both in the refusal path.

The implementation quality is otherwise high and the acceptance evidence is real where it
is real — the SIGKILL restart, the publish atomicity, the four preconditions and the whole
end-to-end oracle all hold up under independent construction. What must not stand is the
seam gap reported as compliance (B2) and the F2 power-proof that proves nothing (B3);
those are report-integrity failures, not implementation failures, and they are the reason
this is a REFUSE rather than a punch list.

---

# Round 2 — fix round 1 re-check

**Range**: `main..slice4/wp3` = 4 commits (`40612844` E1, `fc708a09` E2, `8af7ef77` sink,
`70a6dbb2` test touch-up), merged into this pointer branch at `a73f394e`; the merged tree
is identical to `70a6dbb2` apart from this report.
**Verdict**: **PASS.** All four of my blockings and all three reviewer blockings are fixed,
each verified by my own round-1 method rather than by reading the worker's claims. Two new
non-blocking findings (one of them a re-typing of the same class the round removed) and two
minor notes, all recorded below for the slice tail.

## R2.0 Scope — EXACT

| Commit | Files | Ruled? |
| --- | --- | --- |
| `40612844` E1 | `arrival.py`, `arrival_file_backend.py`, `tests/test_arrival_contract.py` | exactly the ruled surfaces |
| `fc708a09` E2 | `arrival.py`, `tests/test_arrival_gate.py` | exactly the ruled surfaces |
| `8af7ef77` sink | 7 files, all `libs/migrate/**` | in fence |
| `70a6dbb2` | `libs/migrate/tests/test_sidecar.py` | in fence |

No other engine file touched; no drive-by cleanup in engine; Rule-4 file untouched
(`git diff 68cc829f..HEAD -- tests/architecture/` empty); `git status --short` is `?? .tmp/`
only. `ruff --select F401` on `sidecar.py`: **All checks passed** — the 13 unused imports
from round 1 are gone (F7(e) done), and removing the `NotSupported` refusal arm left no
dangling import (`NotSupported` still used at `arrival_file_backend.py:690`).

## R2.1 E1 — signature carriage. The heaviest check, and it holds.

The diff is four hunks and does exactly what was ruled. `Entry` gains
`signature: str | None = None` — a **signature**, not a *signer*, which is the whole point:
the adapter carries an authored attestation, it cannot manufacture one. The stale docstring
paragraph asserting "there is deliberately no signer field … an invitation to fabricate
authorship" is removed in the same commit rather than left to contradict the code (residue
swept). `append_marked_many` passes `sig=entry.signature`; `FileLedger.append` drops the
refusal arm and forwards `draft.signature`. **No new adapter-level validation was added** —
the requirement that the adapter carry and never judge.

My probe at the fix HEAD:

```
WP2 drafts: 8 total, 1 outer-signed, 7 unsigned
[PASS] (b) append(all 8 drafts incl. signed key intro) -> ACCEPTED, head ord=8
[PASS] (d) adapter CARRIED the draft signature verbatim (draft=8aeW9Y4x... record=8aeW9Y4x...)
[PASS] (d) no signature invented for unsigned drafts (0 unsigned records carry a sig)
[PASS] (c) verify_authorship over the log: 2 resolutions, 0 failing
[PASS] (a) unsigned drafts: append == old self-coordinated replicate (3507 vs 3507 bytes)
[PASS] (a) matches the round-1 gate measurement of 3507 bytes (got 3507)
```

Byte-preservation is exact against the figure I measured in round 1 — the gate assertion
the brief named. The authority walk passes over a log whose key introduction arrived
through the contract op.

**E1 mutation** (`sig=entry.signature` → `sig=None`):

```
E   engine.arrival.AppendRejected: candidate refused: a key introduction carries no
    signature — an introduction is vouched for by a key that is already valid, never
    self-certifying above ordinal 0
FAILED tests/test_arrival_contract.py::test_append_carries_pre_signed_draft_and_verifies_authorship
1 failed, 1 passed
```

Red, and red *from the grammar* — `AppendRejected` out of `_validate`, not from a new
adapter check. That is the cleanest possible evidence for "the adapter carries, the grammar
judges". The byte-identity test stays green under the mutation, correctly, since it uses
unsigned drafts.

## R2.2 E2 — typed torn tail. Narrow and correctly scoped.

`ArrivalTornTail(ArrivalError)` added to `__all__`, defined once, **raised at exactly one
site** (`arrival.py:1258`; `grep` over `libs/engine/src/engine/` finds only the `__all__`
entry, the class, and that raise). `ArrivalCorrupt` is untouched — the diff carries no `+`
or `-` line on its class body. The docstring is a location claim: it says what the read
lacks ("the log ends mid-record before a terminating newline … the final record was only
partially written") and prescribes nothing.

**E2 mutation** (`ArrivalTornTail` → bare `ArrivalError`):
`FAILED tests/test_arrival_gate.py::test_tail_record_ending_mid_record_raises_typed_arrival_torn_tail`.
Red as ruled.

## R2.3 Suite reconciliation — exact, and nothing was deleted to make it balance

| Suite | Base `68cc829f` | Fix HEAD | Delta |
| --- | --- | --- | --- |
| engine (`uv run --directory libs/engine pytest -q`) | 2304 passed, 1 skipped | 2306 passed, 1 skipped | +2 |
| store | 180 passed | 180 passed | 0 |
| migrate + architecture | 154 passed (round 1) | 159 passed | +5 |

I diffed the collected node ids rather than trusting the totals:

```
=== ADDED at HEAD ===
  test_append_carries_pre_signed_draft_and_verifies_authorship
  test_append_unsigned_drafts_byte_identical_fixture
  test_deliberate_absence_refuses_under_the_contract_root
  test_tail_record_ending_mid_record_raises_typed_arrival_torn_tail
=== REMOVED from base ===
  test_append_refuses_a_pre_signed_draft
  test_both_deliberate_absences_refuse_under_the_contract_root
```

Both removals are legitimate consequences of the ratified change rather than convenient
deletions: the first pinned the refusal E1 was ruled to remove, and the second is a rename
— with only one deliberate absence left (`Incremental`), "both absences" no longer names
anything, and its now-false "both sites, in one test" rationale went with it. Three
genuinely new tests pin E1 and E2. 2305 → 2307 collected.

## R2.4 My four blockings, re-checked by my own round-1 methods

**B1 — admission.** `grep` over `sidecar.py` for `replicate`, `_drafts_to_records`,
`build_record`: **no hits**. The append loop is `ledger.append(expected=head, drafts=chunk_drafts)`
(`sidecar.py:177`). Self-coordination is gone. **FIXED.**

**B2 — the seam gap.** My round-1 all-8-drafts probe, which returned
`REFUSED NotSupported` before, now returns `ACCEPTED, head ord=8` (R2.1). The signed key
introduction is admitted through the contract op and `verify_authorship` accepts the
result. **FIXED**, via the byte-preserving route (i).

**B3 — the F2 ratchet.** I re-applied the *exact* round-1 mutation (`if False and (...)`
on the resume prefix diff), the one that caught nothing:

```
FAILED libs/migrate/tests/test_sidecar.py::test_resume_against_divergent_valid_chain_refuses_target_mismatch
1 failed, 59 passed
```

The ratchet now exists. **FIXED.**

**B4 — state-root pollution.** `libs/migrate/tests/conftest.py` now redirects
`XDG_STATE_HOME`. My round-1 measurement method, extended with a content hash over the
whole directory:

```
BEFORE: files=267 bindings_bytes=59231 tree_hash=bb2cabd0538c8946b2b41102eae1cb946b5e8f57
159 passed in 3.90s
AFTER:  files=267 bindings_bytes=59231 tree_hash=bb2cabd0538c8946b2b41102eae1cb946b5e8f57
DELTA files=0 bindings=0
[PASS] B4: real state root BIT-IDENTICAL after full migrate+arch run
```

Zero delta, bit-identical. **FIXED.** (Housekeeping, not a finding: the 267 journals
already written by round-1 and fix-round runs are still on this machine. The conftest stops
new pollution but does not clean the existing residue; that is the user's real state
directory, so I left it alone rather than deleting it.)

## R2.5 Reviewer blockings, probed independently

```
===== (a) publish cannot no-op =====
[PASS] duplicate store nodes REFUSE :: condition='vertex_store_duplicate_nodes'
[PASS] duplicate case left descriptor unchanged
[PASS] comment-shadowed store REFUSES :: condition='vertex_store_regex_match_count'
[PASS] comment case left descriptor unchanged
===== (b) resume genesis verification =====
[PASS] mallory resume REFUSES :: TargetMismatchOnResumeRefused
[PASS] refusal NAMES BOTH identities ("genesis custodian 'mallory' does not match expected custodian 'zoe'")
[PASS] mallory target bytes unchanged
[PASS] genesis-only RIGHT-lineage target resumes :: head ord=7, drafts=7
===== (c) refusal typing =====
[PASS] torn tail -> TornTailRefused
[PASS] engine ArrivalTornTail present in the CAUSE chain (type, not substring)
[PASS] torn tail: bytes unchanged
[PASS] unreadable source -> LegacyStorageRefused
[PASS] garbage source -> LegacyStorageRefused
```

`_is_torn_tail_error` is gone; `grep` finds no substring discrimination in `sidecar.py`
(the surviving "ends mid-record" / "torn tail" strings are the sidecar's own advisory
message prose, not predicates). The resume path catches explicit type tuples
(`ArrivalTornTail`, `StoreLost`, `ArrivalCorrupt`, `GenesisRefused`/`HeadMismatch`,
`OSError`), maps `ArrivalTornTail` → `TornTailRefused` and everything else →
`TargetUnopenable` carrying the cause, and `TargetMismatchOnResumeRefused` is raised only
by comparisons that actually ran. The two builtin escapes I found in round 1
(`PermissionError`, `UnicodeDecodeError`) are now wrapped.

F7(a) dissolved the 14-field enumeration into a loop over `VertexFile.__match_args__` minus
`{store, store_backend, path}`, which removes the drift surface. F7(d) is real:
`_check_inventory_equality` now consumes `exceptions.dropped_units` (the dead parameter is
gone), and `DroppedUnit` carries `fact_kinds`/`observers` to make the accounting possible.

**Power-proof spot check** (reviewer (a)'s wrong-location mutant): making the editor write
a wrong path turns **7 tests red**, including `test_publish_atomicity_and_crash_simulation`.
The post-edit `post_ast.store` assertion — the one field round 1 found unasserted — is
load-bearing.

## R2.6 Oracle and crash-restart, re-run at the fix HEAD

Independent oracle on my own synthetic stores, both arms: **26/26 PASS**, unchanged from
round 1. (One check needed updating on my side, not the code's: `verify_migration_report`
now raises typed causes instead of returning `False`, which is exactly what F7(b) ruled, so
my wrong-key assertion was stale.)

Real SIGKILL mid-append, re-run against the admission path:

```
child rc=-9 (-9 == SIGKILL)  size_at_kill=189680
resumed OK: head_ord=3000 bytes=1141181
reference bytes=1141181
[PASS] SIGKILL restart -> BYTE-IDENTICAL to uninterrupted run
```

Identical figures to round 1 — determinism survived the move from `replicate` to `append`,
which is the practical confirmation of E1's byte-preservation claim end to end.

## R2.7 New findings (non-blocking, for the slice tail)

### N6 — `verify_migration_report` re-types an unopenable target as a head *mismatch*

`sidecar.py:645-651` wraps the target open in a bare `except Exception` and raises
`ReportHeadMismatchRefused`. That type asserts the head **differs** from the claim; a torn,
corrupt or locked target means the head could not be **read** at all. Probed — the cause
chain proves it:

```
[FINDING] an UNOPENABLE target is reported as ReportHeadMismatchRefused
          (asserts the head DIFFERS, when it could not be READ).
          cause chain: ReportHeadMismatchRefused <- StoreLost <- ArrivalTornTail
```

This is the same defect class F4 removed from `run_migration`, reintroduced under a new
name in the newly written verifier — the "check the anti-pattern was not reintroduced" case.
I weighed blocking and decided against it: the verifier still refuses (fails safe), the
cause is preserved via `from exc` so the truth is one `__cause__` away, and the blast radius
is an auditor reading a wrong label rather than an operator destroying evidence. The fix is
small — a fifth distinct cause (`ReportTargetUnreadableRefused`, or reuse `TargetUnopenable`)
and a typed catch instead of `except Exception`.

### N7 — `migrate` imports `ckdl` directly, undeclared, bypassing `lang`

`sidecar.py:76` adds `import ckdl` and `:236` calls `ckdl.parse` to count store nodes.
`libs/migrate/pyproject.toml` declares `engine, store, lang, python-ulid` — **not `ckdl`**.
It works only because `lang` depends on `ckdl>=1.0` and the workspace venv is shared. Two
problems: the convention "declare what you import" is broken, and `lang` is the repo's KDL
boundary, so the sink now holds a second, independent KDL parse path that will drift if
`lang` ever changes parsers. Rule 4 does not catch it — that ratchet covers inter-lib
imports only, so a third-party undeclared import is invisible to it. The dissolution-shaped
fix is for `lang` to expose the store-node query (it already owns the AST) and for
`migrate` to call that instead of parsing KDL itself.

### N8 — partially-dropped batches are not accounted (fail-safe)

`transform.py` records a `DroppedUnit` only when a batch maps to **no** rows
(`if not mapped_rows`). A rule that drops *some* rows of a batch leaves the source
inventory counting rows the target does not hold, with no exception to subtract, so
`_check_inventory_equality` refuses. That is the safe direction — it refuses rather than
publishing a claim it cannot support — but it means such a rule can never publish. Worth a
line in the module docstring naming the limit, since F7(d) otherwise reads as complete.

### N9 — the E2 engine test pins the type through a private method

`test_tail_record_ending_mid_record_raises_typed_arrival_torn_tail` calls
`log._tail_record()` directly and asserts `"ends mid-record" in str(...)`. It pins the type
at the raise site but not that public callers see it, and it leans on the message substring
that E2 exists to stop callers depending on. The end-to-end coverage does exist on the
migrate side (my probe confirms `ArrivalTornTail` in the cause chain of a
`TornTailRefused` raised through `registry.open`), so this is a note, not a gap.

## R2.8 Round-2 verdict

**PASS.** Findings to flip to fixed, with the commit that fixed each:

| Finding | Fixed by |
| --- | --- |
| `s4wp3-replicate-instead-of-admission` | `8af7ef77` (enabled by `40612844`) |
| `s4wp3-append-refuses-signed-key-intro` | `40612844` |
| `s4wp3-f2-resume-diff-unratcheted` | `8af7ef77` |
| `s4wp3-tests-pollute-real-state-root` | `8af7ef77` |
| `s4wp3-publish-silent-noop` | `8af7ef77` |
| `s4wp3-resume-genesis-tautology` | `8af7ef77` |
| `s4wp3-refusal-types-assert-unchecked` | `8af7ef77` (enabled by `fc708a09`) |

Carried forward as non-blocking: N6 (report verifier re-typing), N7 (undeclared `ckdl` /
second KDL path), N8 (partial-batch drop accounting), N9 (E2 test reaches a private method).

The two engine commits are the part I scrutinised hardest and they are the part I am most
comfortable with: minimal, exactly scoped, residue swept, mutation-proven, and — the thing
that matters most for an arc whose safety property is byte-level determinism — provably
byte-preserving for every draft shape that existed before them.
