# Slice 2 / WP2 gate report — replicate, export, minimal portable import

**GATE: PASS.** Two NON-BLOCKING findings, no BLOCKING findings, no emissions.

Target: `slice2/wp2-replicate` @ `1d0fc887` (5 commits over wave base `0d38c969`;
`git merge-base 1d0fc887 slice/arrival-backend-contract` = `0d38c969`, re-verified).
Gate worktree: `~/Code/loops-s2wp2-gate` on `slice2/wp2-replicate-gate`, fresh
`uv sync --all-packages`. Baseline measured in a second throwaway worktree
(`~/Code/loops-s2wp2-base`, detached at `0d38c969`, removed after use) rather than
taken from the report.

Inputs, pinned so they are reproducible:

- brief — `git show cd34c499:docs/scratch/arrival-break/slice2-wp2-brief.md`
- impl report — `git show 1d0fc887:docs/scratch/arrival-break/slice2-wp2-report.md`
- design §A.2 / §D.2 — `docs/scratch/arrival-break/slice2-design-proposal.md`
- contract of record — `docs/architecture/arrival/backend-contract.html` §§03, 04, 08, 12

Every claim below was re-derived in this worktree. The impl report was read as the
target of the review, never as its authority; where a probe went past what the report
asserts, that is marked.

---

## Oracle

### 1. Brief oracle — PASS

**Vector families and their consumer.** Three families, ten vectors, all tracked:

```
$ git ls-files 'spec/conformance/vectors/*replicate*' | wc -l
10
```

`replicate-exact-suffix-*` (4), `replicate-same-height-*` (3, including the
negative control), `replicate-catch-up-*` (3). `test_conformance_replicate.py`
loads them the way `test_conformance_replay.py` loads its two areas — one
`sorted(dir.glob("*.json"))`, one `parametrize(ids=lambda p: p.stem)`, envelope
asserted before body — plus `test_every_replicate_family_has_vectors`, which is
net-new and is what stops a family that loses its last vector from passing
vacuously. 10 + 1 = the claimed 11.

The consumer's accept arm asserts `[dict(r) for r in commit.records] == offered`,
which is a direct "nothing was assigned" claim rather than an inference from the
resulting bytes.

**The gitignore trap is clear.** Regenerating the frozen vectors leaves the tree
byte-identical, and nothing under the vector directory is ignored:

```
$ uv run --package engine python spec/conformance/generate_replicate.py
$ git status --short          # empty
$ git status --short --ignored spec/conformance/vectors/replicate/   # empty
```

**export → import → export byte-identical.** Verified directly, not only through the
test. On a four-record log, `b"".join(export(through=head).records)` equals
`log.path.read_bytes()` exactly (1231 bytes), and a partial export through ordinal 1
is a true byte prefix of the same file (669 bytes). The test
`test_export_import_export_is_byte_identical` makes both the round-trip claim and the
stronger one — the replica's own file equals the authority's file — so a copy that
round-tripped the wire format while storing something else would not satisfy it.

**Snapshot consistency under a concurrent writer.**
`test_a_snapshot_holds_while_another_writer_appends` drains a captured export one
record at a time while a second thread appends throughout, and asserts
`authority.head().ordinal > captured.ordinal` at the end — so it fails rather than
passes vacuously if the writer never got ahead. Readers take no lock (confirmed at
source, below), which is what makes it a genuine race.

**Counts, both ends measured.**

| Suite | Baseline @ `0d38c969` (measured) | Tip @ `1d0fc887` (measured) | Delta |
|---|---|---|---|
| engine | 1989 passed, 1 skipped | 2033 passed, 1 skipped | **+44** |
| store | 180 passed | 180 passed | 0 |
| architecture | 99 passed | 99 passed | 0 |

The +44 is accounted for exactly: `--collect-only -q` on the two new files collects
**44 tests** (`test_arrival_transfer.py` 33, `test_conformance_replicate.py` 11).
`test_arrival_contract.py` is the only other test file in the diff and its net test
count is unchanged — assertion bodies only, no test added or removed. Wider net, all
green and all measured here: sdk 324, apps/loops 2530 + 1 xfailed, lang 655, atoms
517, sign 37, custody 13, chaos 12, root `tests/` 111. Every number in the report's §3
reconciles.

### 2. Mutations, re-run here — PASS

Each applied to the code at its current home, run against the two new files, then
`git checkout --` with `git status --short` empty before the next.

**(a) Fork refusal disabled** (`if False and mine is not None and ...`):

```
FAILED test_arrival_transfer.py::test_the_arrival_layer_raises_its_own_fork_type_not_the_contracts
FAILED test_conformance_replicate.py::...[replicate-same-height-fork-at-the-head-refuses]
FAILED test_conformance_replicate.py::...[replicate-same-height-fork-below-the-head-refuses]
3 failed, 41 passed
```

The agreement negative control `replicate-same-height-agreement-is-not-a-fork` stayed
**GREEN**, so the family discriminates fork from stale re-send rather than firing on any
overlap. `test_import_refuses_a_target_that_disagrees_about_its_own_prefix` also stayed
green, which is the honest answer to "is the fork logic duplicated?" — see item 4.

**(a′) Fork check narrowed to the head ordinal** (`<=` → `==`):

```
FAILED test_arrival_transfer.py::test_the_arrival_layer_raises_its_own_fork_type_not_the_contracts
FAILED test_conformance_replicate.py::...[replicate-same-height-fork-below-the-head-refuses]
2 failed, 42 passed
```

Exactly the below-the-head vector; the at-the-head one stayed green. The two arms are
independently pinned.

**(b) replicate re-coordinates** (return a rebuilt record instead of the candidate):

```
FAILED test_export_import_export_is_byte_identical
FAILED test_a_replica_preserves_a_carried_in_signature
FAILED test_import_appends_only_the_remainder_to_an_agreeing_target
FAILED test_import_of_a_prefix_the_target_already_holds_changes_nothing
FAILED test_replicate_refuses_a_record_whose_supplied_digest_is_wrong
FAILED test_replicate_refuses_a_foreign_lineage_as_this_backends_own_fault
FAILED test_replicate_refuses_an_internally_inconsistent_batch_and_lands_none_of_it
FAILED test_a_replicated_suffix_is_byte_identical_to_the_source_bytes
FAILED test_conformance_replicate.py::...[replicate-catch-up-from-a-genesis-only-replica]
FAILED test_conformance_replicate.py::...[replicate-catch-up-preserves-signed-records-byte-for-byte]
10 failed, 34 passed
```

Ten failures including both byte-for-byte tests, and the **UNSIGNED** catch-up vector
`replicate-catch-up-preserves-authored-time-and-origin` stayed **GREEN**.

**Assessment of the signature-only-discriminator argument: the claim is true, and it is
stated as a family property.** Three independent legs:

1. *Empirical* — the mutation's failure pattern is exactly the split the argument
   predicts. A re-coordinator handed an exact suffix assigns the same lineage, ordinal
   and predecessor, so it reproduces identical record hashes; `at` and `origin` survive
   the rebuild because `Entry` carries both, which is why the unsigned catch-up vector
   cannot see the difference.
2. *Source* — `Entry` has no signer field, and says so deliberately: "There is
   deliberately no signer field… A signer here would be a parameter with no caller and
   an invitation to fabricate authorship" (`arrival.py:810-814`). The assign path builds
   every record with `sig=None`. So a signature is the one piece of content the
   assigning path structurally cannot carry.
3. *Documented* — `SCHEMA.md` §10 states it as a family property, not a fixture
   accident: "**At least one vector in this family carries SIGNED records, and that is a
   property of the family rather than an accident of its fixtures.**"

A catch-up family without a signed vector would have passed mutation (b). It is pinned
in the schema so a future regeneration cannot quietly drop it.

### 3. F1 continuity after D2's move — PASS

`_refuse_stale_head` has exactly two call sites (`arrival.py:1491`, `:1707`), textually
distinguishable (`headr` vs `head`), so each is still the mutable unit WP1 designed.

**Site A is untouched, verified rather than assumed.** WP2's diff of `arrival.py`
contains zero lines mentioning `headr`, and `test_arrival_cas_full_head.py` has no diff
at all against `0d38c969`.

Both WP1 demos re-derived at their current homes:

| Mutation | Current home | Result |
|---|---|---|
| Site A → ordinal-only compare | `append_marked`'s `build` (unmoved) | `test_site_a_refuses_a_head_rewritten_to_the_same_ordinal`, `test_site_a_refuses_a_head_from_another_lineage` — **2 failed, 65 passed** |
| Site B → ordinal-only compare | `_append_many_under_lock` (moved) | `test_site_b_…_same_ordinal`, `test_site_b_…_another_lineage`, **plus** `[replicate-exact-suffix-refuses-a-stale-full-head-pin]` — **3 failed, 64 passed** |

**The independence property survives, and site B's blast radius grew by exactly the
right thing.** Neither mutation trips the other site's tests. Site B now also fails one
WP2 vector because `append_records` genuinely shares that CAS rather than owning a
sibling copy of it — which is the behaviour D2 claims and the outcome
construction-over-detection wants. WP1's report cites a stale line for the site-B
revert; the hunk still applies verbatim at the new location, and the impl report names
this. Nothing is weakened.

### 4. Deviations, verified — PASS (one question characterized, not ruled)

**D1 — `LEDGER_MUTATIONS` 3 → 4.** Verified on all three legs.

The op-table reading is correct: `ArrivalLedger.__protocol_attrs__` is exactly
`['append', 'capabilities', 'export', 'head', 'mint', 'read', 'replicate', 'scan',
'verify']` — the nine §03 rows and nothing else. §08 describes portable import in prose
and gives it no row, so keeping `import_prefix` off the Protocol matches the ratified
contract.

**The query-separation ratchet still derives, and D1's growth extends it.**
`test_no_ledger_mutating_op_is_reachable_from_a_query_handle` reads `LEDGER_MUTATIONS`
directly (both as a set intersection against `dir(query)` and per-op over every
reachable value), so nothing was hand-copied. Proven live rather than read: exposing a
stub `import_prefix` on `FileQuery` fails that test —

```
FAILED test_arrival_contract.py::test_no_ledger_mutating_op_is_reachable_from_a_query_handle
```

— so adding the name to the set bought real coverage, not bookkeeping.

*Characterized for the slice gate's contract-text package, not ruled here:* should §08's
portable import gain a §03 op-table row, or stay adapter-level? WP2 took the narrower
reading and the precedent (`head_at`) supports it. The question is a contract decision.

**D3 — `adopt_genesis`.** Every claim verified.

`_publish_genesis` is the single home for the ceremony: `grep -n O_EXCL` over
`libs/engine/src/engine/arrival.py` returns one `os.open(..., O_CREAT|O_EXCL|O_WRONLY)`
call, inside `_publish_genesis`, reached by both `mint` and `adopt_genesis`. There is no
second genesis path. Behaviourally:

```
adopt_genesis over an existing log     -> GenesisRefused ("a lineage is opened once…")
adopt_genesis with a tampered rh       -> ArrivalGrammarError (supplied digest CHECKED)
after the refusal                      -> no log, no .tmp staging residue
```

**`import_prefix` does its own §08 prefix agreement, and I constructed the case that
shows why it must.** The impl claims replicate's fork check "only sees the overlap it is
handed". That is true and it is load-bearing.

Take a target holding `[g, r1, r2]` (head ordinal 2) and an import holding `[g, r1′]`
where `r1′ ≠ r1`. The remainder `import_prefix` would hand `replicate` is
`[record for record in imported if record["ord"] > 2]` — **empty**. Replicate is handed
no overlap, so it has nothing to refuse. With `_refuse_disagreeing_prefix` no-op'd:

```
=== D3 sharp case — divergent import whose remainder is EMPTY ===
ord-1 rh differ? True
!! IMPORT ACCEPTED — fork silently blessed
target bytes unchanged: True
```

The worst possible shape: a silent success, reporting the target's head, while the two
histories disagree at ordinal 1. With the gate in place it refuses `SameHeightFork` and
names the ordinal.

The longer variant degrades differently and just as badly. With an import of
`[g, r1′, r2′, r3′]` the remainder is `[r3′]`, whose `prev` names `r2′`; hash chaining
means it cannot corrupt the target, but `replicate` alone refuses **`HeadMismatch`** —
a *retryable* claim — where `import_prefix` correctly refuses `SameHeightFork`. That is
precisely the spin the `ForkedHeight` taxonomy exists to prevent, reintroduced one layer
up. Exactly one test pins this site
(`test_import_refuses_a_target_that_disagrees_about_its_own_prefix`, the sole failure
under the no-op), and it is independent of replicate's fork check — both mutations in
item 2 left it green. Two checks, two different claims, each independently covered.

### 5. The two flipped WP1 assertions — PASS

Both are WP1's own WP2-anticipating pins, flipped to positive form, intent preserved,
no ratchet loop weakened.

`test_the_ledger_satisfies_the_ledger_surface_it_claims` — WP1's inline comment asked
for exactly this flip. `assert not isinstance(ledger, ArrivalLedger)` became
`assert isinstance(...)`, the offered-ops set grew to include `replicate`/`export`, and
three assertions were **added** pinning `import_prefix` as offered, off the Protocol, and
in `LEDGER_MUTATIONS`. The docstring's location-claim-not-verdict framing is untouched.

`test_capabilities_claims_nothing_the_adapter_does_not_have` — the cross-check loop that
makes it a ratchet is byte-identical:

```python
for op, claimed in (("replicate", Profile.REPLICA in caps.profiles),
                    ("export", bool(caps.export_codecs))):
    assert hasattr(ledger, op) == claimed, (
        f"capabilities and the adapter disagree about {op!r}"
    )
```

It still fails on any disagreement in either direction. WP1's `Profile.REPLICA not in
caps.profiles` pin was not simply deleted — it was replaced by `Profile.ARCHIVE not in
caps.profiles`, so the "something must stay honestly absent" shape survives the flip.

### 6. Design-point audit — PASS

**One `_completed_candidate` spelling, three carried-in paths, no unchecked digest.**
`grep -rn _completed_candidate` gives one definition (`:707`) and exactly three call
sites: `adopt_genesis` (`:960`), `append_records` (`:1602`), `append_record` (`:1744`).
It computes `rh` only when absent and leaves a supplied one untouched, and
`encode_record` is the checker — `_validate(record, require_rh=True)` followed by
`_bad("rh does not match the record it is attached to")`. Verified behaviourally on all
three paths: `adopt_genesis` refuses a tampered `rh` (above), replicate has
`test_replicate_refuses_a_record_whose_supplied_digest_is_wrong`, `append_record` was
already pinned by WP1. No path trusts a digest another checks.

**`ForkedHeight` is not an `AppendRejected`, and merge's retry cannot spin.**

```
ForkedHeight MRO: ['ForkedHeight', 'ArrivalError', 'Exception', 'BaseException']
issubclass(ForkedHeight, AppendRejected) -> False
```

`store/merge.py:308` catches `AppendRejected` and `continue`s the retry loop. A
`ForkedHeight` escapes it and surfaces. (Today the loop calls `append_marked_many`, so
a fork cannot arise there yet — the taxonomy is pre-emptive rather than fixing a live
spin, which is the right time to get it right.) `SameHeightFork` and `HeadMismatch` are
both `ContractRefusal` subclasses, so the adapter's translation stays inside the
ratified set.

**Export framing makes `b"".join(records)` the log's own prefix bytes.** Verified
directly on a real log for both a full and a partial prefix (item 1). `_decoded`
enforces the framing on the way back in, and refuses an export whose manifest claims
`newline-terminated` while an element lacks its newline.

**The manifest carries no clock and no host.** Seven fields — `protocol`, `codec`,
`framing`, `lineage`, `through_ordinal`, `through_record_hash`, `count` — every one
derived from the captured head or the grammar. `count` is `through.ordinal + 1` by
density.

**Capabilities are honest.** `REPLICA` joined `AUTHORITY`, `export_codecs ==
("arrival-jsonl-v1",)`, `ARCHIVE` absent, and the cross-check loop above holds all of it
against the object.

### 7. The named edge — PASS, and sharper than the report states

Reproduced exactly. `FileLedger(ArrivalLog(replica), max_atomic_records=2)`, an empty
target, a four-record export:

```
refused AtomicLimitExceeded: 3 records exceeds this backend's configured atomic limit of 2
replica exists after the refusal: True
replica line count: 1 | is genesis-only: True
replica genesis == source genesis bytes: True
re-import: same AtomicLimitExceeded, state unchanged: True
limit 3 completes: True | bytes identical: True
```

**The refuse-before-mutation argument holds as stated.** §04 scopes the rule to the
append transaction and to "the request" — "refuse before mutation when the request
exceeds the backend's limit" — and `replicate` does refuse before any byte moves. The
genesis adoption is a separate operation that completed successfully first. So the
property holds per-operation and not across the pair, which is what the report says. The
resulting artifact is a valid one-record prefix, byte-identical to the authority's
genesis.

**Characterized for the slice gate's contract-text package.** The report frames the
residue as harmless because "re-import is idempotent, so nothing is corrupt". That is
true, and it understates the situation: while `max_atomic_records < count - 1` the pair
can **never** complete. Idempotent, but no progress is possible — I ran the re-import
twice and got the identical refusal with identical state. There is contract text bearing
on this, which is why it belongs in the package rather than in the report's margin:

- §04: "A backend whose safe limit is one remains conforming and **imports by verified
  single-record steps**." The contract explicitly anticipates that an importer under a
  limit makes incremental progress.
- §12: "Exercise configured record, batch, nesting, **import**, and decompression
  limits." Import limits are named conformance surface.

**NON-BLOCKING for WP2**, on three grounds: the brief scoped import to §08's default;
`max_atomic_records` defaults to `None`, so no live path reaches this; and a resumable
importer is a design, not a fix. It is the slice gate's to rule alongside D1's
op-table question.

### 8. The flock deadlock rationale — PASS

**The claim is true, proven rather than read.** A second open-file-description on the
same lock file, in the same process, blocks on `LOCK_EX`:

```
outer LOCK_EX held on fd 3
RESULT: inner LOCK_EX BLOCKED for 3s in-process -> flock is per open-file-description
```

Both `_locked_head` (`:1759`) and `_append_under_lock` (`:1845`) do a fresh
`self.lock_path.open("ab")` per acquisition, so a loop over `append_record` beneath an
outer lock would genuinely deadlock in-process. Extracting the batched machinery rather
than looping is correct.

**`append_records` is the only new batched writer, and no sibling CAS exists.** Two
writers total, unchanged in count: `_append_under_lock` (`:1764`, called by
`append_marked` and `append_record`) and `_append_many_under_lock` (`:1678`, called by
`append_marked_many` and `append_records`). Two `_refuse_stale_head` sites, one per
writer. Corroborating detail the design depends on: `walk()` takes no lock ("The reader
holds no lock", `arrival.py:1131`; no `flock` in its body), which is why `_hashes_at`
can walk *inside* the write fence to answer the below-the-head fork question without
self-deadlocking — and the below-the-head vector passing is the empirical half of that.

---

## Findings

**F-1 (NON-BLOCKING) — a test asserts on a typing internal below the declared Python
floor.** `test_arrival_contract.py:270` reads `ArrivalLedger.__protocol_attrs__`, added
to `typing.Protocol` in Python 3.12. Both `pyproject.toml:8` and
`libs/engine/pyproject.toml:7` declare `requires-python = ">=3.11"`. CI pins 3.13
(`.github/workflows/ci.yml`), so this is green everywhere it runs today; on 3.11 the
test would ERROR with `AttributeError` rather than silently pass, which is why it is
non-blocking rather than a hole. Sole usage of the attribute in the repo — no precedent
either way. A version-independent respelling exists (`hasattr` against the Protocol
class); which spelling to take is the implementer's call, not the gate's.

**F-2 (NON-BLOCKING) — import under a configured atomic limit cannot make progress; for
the slice gate's contract-text package.** Detailed in item 7. The report names the
residue; the sharper fact is that the pair can never complete while the limit is below
the remainder, and §04 and §12 both have text bearing on incremental import under a
limit. Routed to the slice gate rather than back to WP2.

**Carried forward, not a finding:** D1's open question — should §08 portable import gain
a §03 op-table row, or stay adapter-level? Characterized in item 4, deliberately not
ruled here. The contract-text package now has two items.

**Report-vs-store cross-check, as the report invites.** All three finding facts exist and
say what the report says they say
(`slice2-wp2-contract-module-grew-ledger-mutations`, `…-f1-site-b-moved-into-shared-writer`,
`…-adopt-genesis-is-net-new-arrival-surface`). The stray no-fold fact
`01M17E4T09ZPFME9D24C3QHYCG` is present in `.loops/data/project.jsonl` exactly as
described: `kind: finding`, payload carries `agent: s2wp2-impl`, no `name` field so it
never folded, and its message is substantively identical to the folded D1 fact at
`01M17E5119XBNFF2RWFEG0KE2S`. It carries no claim that fact does not. The report's
account of it is accurate.

---

## State at the end of this review

All mutations restored; `git status --short` empty. Measured at the tip after the last
restoration rather than inferred from it: engine **2033 passed, 1 skipped**, store 180,
architecture 99. The baseline worktree was removed. No loops facts were emitted — the
launch contract gates emissions on BLOCKING findings, and there are none.

**GATE: PASS.**
