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
