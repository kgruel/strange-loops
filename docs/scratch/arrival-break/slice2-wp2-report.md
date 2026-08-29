# Slice 2 / WP2 report — replicate, export, minimal portable import

Branch: `slice2/wp2-replicate`, off the slice-2 wave branch at `0d38c969`
(`git merge-base HEAD slice/arrival-backend-contract` = `0d38c969`, verified at step 0).
Contract: `docs/scratch/arrival-break/slice2-wp2-brief.md`; design
`docs/scratch/arrival-break/slice2-design-proposal.md` §A.2 (replicate/export rows), §D.2;
ratified fact `design:arrival-break-slice2-backend-contract` @ `01M177MHWHD5HM574VSTDE17X8`.
WP1's report (`slice2-wp1-report.md` @ `0d38c969`) is the substrate: its §1.5
(Protocol-incomplete adapter), §1.7 (`max_atomic_records`) and D2 (projection stores no
head hash) bind directly.

Baselines measured in this worktree at `0d38c969` before any edit, with the per-package
invocation the repo uses:

| Suite | Baseline |
|---|---|
| engine | 1989 passed, 1 skipped |
| store | 180 passed |
| architecture | 99 passed |

These match WP1's "Now" column exactly.

---

## 1. Design points

### 1.1 One batched appender with two build strategies, not a second appender

SD-3 says replicate is composition over `ArrivalLog.append_record`. It cannot be a *loop*
over it: `append_record` goes through `_append_under_lock`, which opens its own descriptor
on the lock file, and `flock` is per open-file-description — an outer lock plus per-record
appends **deadlocks inside one process**, which is exactly the trap `append_marked_many`'s
docstring already documents.

So the batched machinery was **extracted, not duplicated**. `_append_many_under_lock(
build_each, count, *, pin)` now holds the fence, the compare-and-swap, the per-record
`_check_follows` + `encode_record` chain, the single write and the single fsync.
`append_marked_many` and the new `append_records` are that method under a different
`build_each` — assign-a-coordinate versus carry-the-coordinate — which mirrors the shape
`_append_under_lock(build)` has always had for the single-record case. Net effect on the
appender count: unchanged at two (one single, one batched), with the batched one now
serving both callers instead of one.

`build_each(head, index)` receives the head the record must follow — the log's real head at
index 0 — which is what lets `append_records` classify the batch against the log inside the
fence and before a byte moves, with no extra hook parameter.

### 1.2 F1's site B moved into the shared writer, deliberately

`append_marked_many`'s `_refuse_stale_head(head, pin)` call now lives in
`_append_many_under_lock`. Replication must inherit WP1's full-head CAS, not get a sibling
copy of it — a second CAS site is precisely what construction-over-detection rules out.
Site A (in `append_marked`'s `build`) is untouched, so the two sites are still two, still
independently revertible, and WP1's site-A/site-B mutation demos still discriminate. **The
line WP1's report cites for the site-B revert has moved**; the behaviour it pins has not.

### 1.3 `_completed_candidate` is the one carried-in build

`append_record`, `append_records` and `adopt_genesis` all accept a record that already
carries its coordinate, and all three now share one spelling of "complete it without
assigning anything": `rh` is computed only when absent, and a supplied `rh` is left exactly
as it arrived so `encode_record` can **check** it. Three copies of that rule is how one path
quietly starts trusting a digest the others check.

### 1.4 The refusal taxonomy has one axis, and `ForkedHeight` is not an `AppendRejected`

Two claims, and they need to stay distinguishable:

* **The log is not where your batch assumed** → `StaleHead` → `HeadMismatch`. Covers the
  gap case (batch starts above head + 1) and the agreeing-overlap case (a stale re-send).
  Both are honest head mismatches: a batch implies the head it follows, and that implied
  head is not this log's. Re-reading is the fix, which is what `HeadMismatch` tells a caller.
* **The log holds a DIFFERENT record at a height this batch would fill** → `ForkedHeight` →
  `SameHeightFork`. Retrying cannot clear it.

`ForkedHeight` descends from `ArrivalError` and **not** from `AppendRejected`, for WP1
§1.2's reason: `store.merge_store` retries on `AppendRejected`, and a fork caught by that
loop would spin rather than surface.

Everything else a malformed batch can be — non-monotonic ordinals, a `rh` that does not
recompute, a foreign lineage — stays this backend's own `AppendRejected` /
`ArrivalGrammarError`, untranslated. The ratified refusal set has no member for "this
candidate is malformed", and picking one would be the verdict claim
`finding:slice2-wp1-refusal-set-gaps` (D4) already flagged. Consequence for the vectors:
those cases are pinned by unit tests, never by a vector, because a vector may only name a
contract refusal — `"AppendRejected"` in a language-neutral vector would pin a Python class
on a Go implementer.

A replica at head N handed a divergent record at ordinal N+1 **accepts** it. Nothing is at
that height to disagree with, so there is no fork to claim yet; replication is not
authorship verification, and `SameHeightFork` is scoped to an occupied height.

### 1.5 `adopt_genesis`, and `mint`'s publish ceremony extracted

Import into a new empty replica cannot go through `mint`: mint builds and signs its own
genesis, and a replica whose ordinal 0 differed from the authority's by one byte would be a
different lineage wearing the same id. `ArrivalLog.adopt_genesis(path, record)` publishes a
genesis that was minted elsewhere, held to the same two structural gates a walk holds
ordinal 0 to — `encode_record` (grammar, supplied `rh` checked) and `_placement_fault(rec,
0)` (genesis kind, no `prev`, signed, self-naming, well-formed founding key). Structural
only: whether the genesis self-certifies is `verify_authorship`'s question, asked with an
injected verifier, and this path stays as pure as `walk` is about the same record.

The `O_EXCL` staging ceremony is now `_publish_genesis`, shared by both — so the race
argument that makes minting safe is stated once and inherited, rather than copied into a
second creation path where it could drift.

### 1.6 `import_prefix` is NOT on the `ArrivalLedger` Protocol, but IS in `LEDGER_MUTATIONS`

§08 describes portable import in prose; the ratified op table (§A.2) gives it no row, and
WP1 established the precedent with `head_at` — an adapter-level op the Protocol does not
declare. Growing the Protocol is a contract decision for the gate, not an implementation
choice, so `import_prefix` lives on `FileLedger` alone.

`LEDGER_MUTATIONS` is a different question and gets the opposite answer: it is the safety
ratchet behind the custody/reads separation, and a mutating op missing from it is a hole
whether or not the contract names the op. It grew to four. This is the one edit WP2 makes
to WP1's contract module.

`import_prefix` returns a `Head`, not a `Commit`: an import into an empty replica has no
`before` to name, and manufacturing one would be the first lie a replica told about where
it came from.

### 1.7 Import checks the manifest rather than trusting it, and does its own prefix agreement

A manifest travels with the bytes, so it is exactly as trustworthy as they are. Every field
is re-derived from the decoded records and compared — protocol, lineage, captured head,
count, and that the prefix starts at ordinal 0. A self-disagreeing export refuses as
`ArrivalCorrupt` (the backend's own family, per D4) rather than as an invented contract
refusal.

The §08 non-empty-target rule — "exact prefix agreement through the target head" — is
import's own job and is composed over `scan`, not over `replicate`. Slicing the remainder
off and handing it to `replicate` would skip the agreement check entirely, since
`replicate`'s fork check only sees the overlap it is *handed*. So `_refuse_disagreeing_prefix`
walks the target's own prefix beside the import and refuses `SameHeightFork` at the first
ordinal whose `rh` differs; only then is the verified remainder handed to `replicate`.

An import that is a strict prefix of what the target already holds returns the target's
head unchanged. Nothing was missing — that is not a failure, and it is not a no-op to hide.

### 1.8 The export codec frames records with their newline, and the manifest says so

Each element of `ExportedPrefix.records` is one record's line **including** its `\n`, so
`b"".join(prefix.records)` reproduces the log's own prefix bytes exactly. That makes the
byte-identity gate a direct comparison rather than a reassembly, and it makes "export equals
the file's prefix" checkable in one line. The framing is a manifest field, not a convention,
because a reader can only rely on it if the export states it — and `_decoded` enforces it.

The manifest carries **no clock and no host**: every field derives from the captured head and
the grammar. That is what makes export → import → export byte-identical rather than
byte-identical-except-for-a-timestamp. `count` is `through.ordinal + 1` by density and needs
no drain to compute; the drain proves it, because a walk that found a gap would have refused
before reaching the head.

A codec this backend does not have raises `ValueError` — a caller bug against
`capabilities().export_codecs`, not a contract refusal. Same D4 reasoning.

### 1.9 `capabilities()` grew by exactly what was built

`Profile.REPLICA` joins `AUTHORITY` because `replicate` now exists; `export_codecs` becomes
`("arrival-jsonl-v1",)`. `Profile.ARCHIVE` stays absent — nothing here offers a read-only
sealed mode. WP1's `test_capabilities_claims_nothing_the_adapter_does_not_have` cross-checks
both claims against the object and still does.

## 2. Deviations

_(filled in as they arise)_

## 3. Test-count table

_(filled in at the end)_

## 4. Mutation evidence

_(filled in at the end)_
