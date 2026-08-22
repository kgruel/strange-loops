# WP-5 — admission signature verification (slice D, §D4 arm 1, opt-in)

Branch `slice/D-wp5`, worktree `wt-wp5`, base `1d8e64f5` (off `feat/arrival-libs`,
WP-1 arrival coordinate merged).

Commits:

- `3280707e` feat(engine): key_registry — the selective authority walk
- `87f3aba0` feat(store): opt-in admission signature verification in merge_store

## File by file

### `libs/engine/src/engine/arrival.py` (+132/-27)

**`KeyRegistry`** (new, exported) — one log's key history: `lineage` plus
`introductions: dict[observer, tuple[(key, introduced_ordinal), ...]]`. Its one
question is `keys_valid_at(observer, position)`, which is the ruled slice-A
placement clause verbatim: valid at N iff introduced at a position < N. Genesis
self-certification is deliberately not expressible on the registry — it is a
property of one record verifying against its own body, settled by the walk
before any registry exists.

**`_keys_valid_at(introductions, observer, position)`** (new, private) — the
placement clause, in ONE place. Both consumers call it: the live walk through
`_resolve` (which previously inlined the same list comprehension) and a finished
`KeyRegistry` through `keys_valid_at`. This is the "one placement-rule
implementation" DP-r2-03 requires; there is no second spelling of "valid at N".

**`key_registry(log, verify)`** (new, exported) — the selective walk. Structural
over the whole log via `ArrivalLog.walk` (density, record hashes, chain linkage
come free, over every record). Envelope signatures verified for
registry-forming records ONLY: the genesis, self-certifying against its own
`body["key"]`, and every `KEY_INTRODUCTION_KIND` record including the
authorization rule that the introduction's own signature must verify under a key
already valid for the introducing record's observer. Ordinary records' envelopes
are never verified. A registry-forming record that fails raises
`AuthorshipUnverified`.

**`_walk_authority(log, verify, *, verify_ordinary)`** (new, private) — the one
authority walk, in both widths. `verify_ordinary` is the ONLY difference between
the two public verbs; the structural walk, genesis self-certification, the
introduction authorization rule and the placement clause are shared by
construction, not by convention.

**`verify_authorship`** — behavior unchanged (its 15-test suite passes
untouched); it is now `_walk_authority(..., verify_ordinary=True)`'s rows. Its
docstring gains one paragraph naming the shared machinery.

**`_resolve`** — three inlined lines replaced by the `_keys_valid_at` call.
No behavior change.

### `libs/store/src/store/merge.py` (+206/-27)

**`merge_store(..., verify: Verify | None = None)`** — opt-in. `None` (the
default, and every existing caller in the tree — `receive.py:71` included) takes
the identical path it always took. The docstring states the scope exactly: a
supplied verifier establishes that every admitted signed fact row's authorship
claim verifies under the SOURCE's own key history — source self-consistency, not
target-operator trust.

**Non-arrival target + `verify`** raises `ValueError` naming why: the sqlite arm
decides its admission set inside `INSERT OR IGNORE` and is held byte-identical by
a seam rule, so it has no admission set to check. Accepting the verifier and
skipping the work would report a verification that never ran.

**`AdmissionUnverified`** (new refusal class) — both halves of the one claim
(unverifiable source key history, unverifiable admitted row) surface as this one
type, and both messages carry the exact scope sentence. Nothing is appended in
either case.

**`_source_registry(source_rows, verify)`** (new) — builds the source's
`key_registry`, wrapping `AuthorshipUnverified` into `AdmissionUnverified`.
Returns `None` when verification was not requested OR the source has no arrival
log — the ruled D4-Q1 posture: a legacy transport `.db` carries rows and no key
history, so it is ADMITTED making no claim, not refused.

**`_verify_admitted_rows(admitted, registry, verify)`** (new) — per admitted
fact row with a non-NULL signature (index 6), recompute
`engine.sqlite_store.fact_commitment_hash(kind, ts, observer, origin, payload)` —
the same content-only commitment the live emit path signs — and require some key
`registry.keys_valid_at(row_observer, source_ordinal)` to verify it. Unsigned
admitted rows pass without a claim.

**`_SourceRows`** — groups carry `(kind, rows, source_ordinal)`; new `canonical`
field holds the source's arrival log when it has one. `_read_arrival_source`
supplies `record["ord"]` (previously dropped); `_read_index_source` supplies
`None` for both, which is the shape the no-claim admission is expressed in.

**`_entries_for`** — additionally returns `admitted`, the surviving FACT rows
paired with their source ordinal. Deduplicated rows are structurally absent from
it, which is what makes G-D4-2 true rather than merely tested. Split batches need
no special case: the admission set is per-row.

**Call placement** — verification runs inside the CAS retry loop, right after
`_entries_for` and before the `dry_run` early return. Inside the loop because a
retry re-runs dedup and the admission set it produces is the set the claim is
about; before the dry-run return because a dry run answers "what would this merge
do", and clean counts for a merge that would refuse is a wrong answer (documented
decision).

**`_entry_for` docstring** — one paragraph separating not-signing from
not-checking; the "no signer, ever" claim is unchanged and still true.

### `libs/engine/tests/test_arrival_key_registry.py` (new, 9 tests)

Registry contents; the placement clause asked of the registry directly
(strictly-after, both sides); observer binding; both halves of the selective
boundary (a bad ordinary envelope does not refuse the registry — proved by
`verify_authorship` refusing the SAME log — while a forged introduction and a
non-self-certifying genesis do); structural coverage still whole-log; and both
verbs agreeing on a clean log.

### `libs/store/tests/test_admission_verification.py` (new, 18 tests)

Keyed stub signer/verifier kit (`conftest`'s `stub_sign` is key-blind and cannot
express a forgery; the library still takes an injected `Verify` and imports no
crypto). Gates:

| gate | tests |
|---|---|
| G-D4-1 | forged carried signature on an admitted row refuses, target unchanged; same row signed by the log's own key admits; same forgery admits with no verifier passed (the opt-in cost, made visible); a key introduced only later does not verify an earlier row; a key valid for another observer does not verify the row |
| G-D4-2 | bad envelope on an all-deduped record still merges; forged carried signature on a deduped row does not refuse; bad ordinary envelope on an ADMITTED record does not refuse. The first and third assert `verify_authorship` refuses the same log, so the fixture is provably non-vacuous |
| G-D4-3 | split batch — surviving row verified and admitted; forged survivor in a split batch refuses; legacy `.db` source admits with explicit no-claim (with a forged signature landing, so the cost of the ruled arm is visible in the suite) |
| G-D4-4 | forged key introduction refuses even though every admitted row is ordinary and unsigned; same source merges when the introduction is real; non-self-certifying genesis refuses |
| posture | unsigned admitted rows admit with no claim; dry run verifies; verifier on a sqlite target refuses rather than being ignored |

## Break / restore

Committed at `87f3aba0` first; each break applied to the committed tree and
reverted with `git checkout --`.

| break | edit | result |
|---|---|---|
| B1 — row verification disabled | `merge.py`: force `signature = None` in `_verify_admitted_rows` | **5 failed, 13 passed** — G-D4-1's forged-row test, the later-key and wrong-observer tests, the split-batch forgery, and the dry-run test. G-D4-2/3-legacy/G-D4-4 unaffected, as they should be |
| B2 — key introductions no longer verified (DP-r2-03's "skip all envelope verification" arm) | `arrival.py`: `if _SIG in record and verify_ordinary:` | store gates **1 failed, 17 passed** — exactly `TestForgedKeyIntroduction::test_an_introduction_no_valid_key_signs_refuses_the_merge` (G-D4-4). engine gates **1 failed, 8 passed** — exactly `test_a_forged_key_introduction_refuses_the_registry` |
| B3 — every envelope verified (DP-r2-03's "straight refactor" arm) | `arrival.py`: `if _SIG in record:` | store gates **2 failed, 16 passed** — exactly the two G-D4-2 tests, `test_a_bad_envelope_on_an_all_deduped_record_still_merges` and `test_a_bad_ordinary_envelope_on_an_ADMITTED_record_does_not_refuse` |
| restore | `git checkout --` both files | store gates **18 passed**, engine gates **9 passed**, tree clean |

B2 and B3 together are the point: the selective boundary is pinned from BOTH
sides, and neither wrong arm of DP-r2-03 survives the suite.

## Suites (all foreground, `uv run --all-packages pytest`, `-p no:randomly`)

| suite | baseline | actual | delta |
|---|---|---|---|
| atoms | 517 | **517 passed** | — |
| engine | 1841 + 1 skip | **1850 passed, 1 skipped** | +9 (new registry suite) |
| sdk | 324 | **324 passed** | — |
| lang | ~655 | **655 passed** | — |
| store | 157 | **175 passed** | +18 (new admission suite) |
| architecture (`tests/architecture`) | 98 | **98 passed** | — |
| apps/loops | 2525 + 1 xfail | **2525 passed, 1 xfailed** | — |

(`pytest tests` reports 110 = 98 architecture + 12 chaos.)

**Default-path proof.** `test_arrival_merge.py` 30 passed and
`TestDivergenceRefusal` 5 passed, both files untouched (`git diff` over the four
changed files does not include them). `test_merge.py`, `test_conformance_merge.py`,
`test_properties_merge.py`, `test_receive.py`, `test_fact_signature_transport.py`:
47 passed, untouched. No caller in the tree passes `verify`, so every production
merge path is byte-identical.

**Lint.** `ruff check` on the four files reports 3 E501s, all three pre-existing
in the sqlite arm's SQL literals (verified by stashing my changes: 3 before,
3 after). No new lint.

## Fence

`git diff --stat 1d8e64f5..HEAD` is exactly four files:
`libs/engine/src/engine/arrival.py`, `libs/engine/tests/test_arrival_key_registry.py`,
`libs/store/src/store/merge.py`, `libs/store/tests/test_admission_verification.py`.
No `sqlite_store.py`, no `witness.py`, no `store_reader.py`. `git status --short`
clean.

## Gaps / follow-ups

1. **`AdmissionUnverified` is not re-exported from `store/__init__.py`.** Its
   sibling `MergeDivergence` is, so a caller catching one and not the other is a
   real asymmetry. `store/__init__.py` is outside the stated fence, so I left it;
   it reaches as `store.merge.AdmissionUnverified` today. One-line follow-up.
2. **No production caller passes `verify`.** The parameter is opt-in and
   currently only the suite exercises it. Wiring it through `receive_store`
   (`receive.py:71`) is a scope call for a later package — `receive.py` is
   outside the fence.
3. **Arms 2 and 3 unchanged, as ruled.** Target-side trust (verifying against the
   TARGET's key chain) stays blocked on key-introduction transport, which this
   merge still does not carry; the refusal messages and the docstring say so
   rather than implying a stronger claim.
4. **Registry cost.** A verified merge walks the source log twice — once in
   `_read_source`, once in `_source_registry`. Both are O(source) and only on the
   opt-in path; folding them into one walk would couple the registry to the row
   reader for no correctness gain, so I left them separate.
