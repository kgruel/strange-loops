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

**Sol S2WP2-L-1, fixed — a short import now refuses.** The first version compared with
`zip(..., strict=False)` and nothing else, so an import that ended BEFORE the target's head
stopped comparing at the import's end and fell through to the empty-remainder branch,
returning the target's head. Sol's repro: target at ordinals 0–3, a valid manifest-clean
export captured at ordinal 1, and `import_prefix` reported success. Everything the import
carried DID agree, which is what made it dangerous rather than obvious — the operation was
claiming agreement through ordinal 3 while ordinals 2–3 were never compared against anything.

Per the arbiter's ruling it **refuses**, and accept-as-no-op is ruled out: §08 asks for
agreement THROUGH the target's head, and a prefix that stops short structurally cannot
establish that claim. `HeadMismatch` is the honest refusal — nothing disagrees anywhere, so
it is not a fork; the export was simply captured at a head behind this target's, and
re-exporting at or past that head is exactly the fix `HeadMismatch` tells a caller to make.
The message names both heights.

The length check is now explicit and runs FIRST, and the surviving `zip` compares
`imported[:overlap]` under `strict=True` — so the property is stated by the code rather than
inherited from a zip's truncation rule. My own test was pinning the bug: it asserted the
short import returned the target's head. It is now split into the refusal (sol's repro) plus
`test_re_importing_the_same_prefix_changes_nothing`, the same-length idempotent accept, which
is the negative control that stops the new refusal from over-firing.

One edge stated rather than defended: importing into an **empty** target under a configured
`max_atomic_records` adopts the genesis and only then meets the limit refusal inside
`replicate`, leaving a genesis-only replica behind. That is a valid prefix and re-import is
idempotent, so nothing is corrupt — but it is a place where "refuse before mutation" holds
per-operation rather than across the pair. Pre-checking the limit in `import_prefix` would
buy a tidier failure and duplicate the limit rule in a second place; not worth it for a
minimal importer, and named so the gate can disagree.

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

### 1.10 The Protocol-surface assertion is plain class introspection, not a typing internal

**Gate F-1, fixed.** The first spelling asserted against
`ArrivalLedger.__protocol_attrs__` — a `typing.Protocol` private that only exists on Python
3.12+. Both pyprojects declare `requires-python >= 3.11`, so that assertion passed on the
interpreter it was written on (3.13) and would have **errored** on one the package supports.
A test that is a function of the interpreter is not a ratchet.

The respelling is `_declared_surface(protocol)`: the public names in the class's own `vars()`
that are callable, unioned with its non-underscore `__annotations__`. Nothing but plain class
introspection, stable across every version in range. Annotations are folded in so that an
ATTRIBUTE added to the Protocol is caught the same way a method would be — the claim is
"these nine rows and nothing else", and a row does not stop counting by being spelled as data.

Two assertions, and the distinction between them is the point:

* `RATIFIED_LEDGER_OPS <= offered` is about the **adapter**, which may legitimately offer more
  (`head_at`, `import_prefix`).
* `_declared_surface(ArrivalLedger) == RATIFIED_LEDGER_OPS` is about the **Protocol**, which
  may not. Exact equality, so both an extra row and a missing row fail.

`RATIFIED_LEDGER_OPS` is written out as a literal rather than derived. Deriving it from
`ArrivalLedger` is precisely what the assertion exists to check, so a derived expectation would
agree with the Protocol no matter what the Protocol said. The literal is §A.2's table standing
beside the code.

The query-separation ratchet is untouched and still **derives** its op names from
`LEDGER_MUTATIONS` rather than hand-copying them.

---

## 2. Deviations

Three, each also emitted as a `finding` fact so the report and the store can be cross-checked
against each other. None was optional; each is recorded so the gate can rule on it rather than
discover it.

### D1 — WP2 edited WP1's contract module: `LEDGER_MUTATIONS` grew

`finding:slice2-wp2-contract-module-grew-ledger-mutations` @ `01M17E5119XBNFF2RWFEG0KE2S`.

Argued in §1.6. The op itself stays off the `ArrivalLedger` Protocol; only the mutation set
grew, from three names to four. **Open for the gate:** should §08's portable import gain an
op-table row in the contract, or stay adapter-level? WP2 took the narrower reading.

### D2 — F1's site-B call moved into the shared batch writer

`finding:slice2-wp2-f1-site-b-moved-into-shared-writer` @ `01M17E57EJG1NMYQJM550QSRWF`.

Argued in §1.2. Behaviour is unchanged and both sites are still independently revertible;
what is stale is the **line WP1's report cites** for the site-B revert. Named because a gate
re-running WP1's mutation instructions verbatim would otherwise be confused by a hunk that no
longer applies.

### D3 — `adopt_genesis` is net-new arrival.py surface beyond replicate

`finding:slice2-wp2-adopt-genesis-is-net-new-arrival-surface` @ `01M17E5EFB4KCABW4VZJJ0QEXW`.

Argued in §1.5. The brief's scope item 3 (import into a new empty replica) cannot be built
without it — `mint` builds and signs its own genesis and has no way to publish one that
already exists. It is not a second appender: it cannot run on an existing log, and it shares
`mint`'s `O_EXCL` ceremony rather than copying it. Named anyway, because a gate checking
"did WP2 add primitives beyond replicate?" should find it announced.

### Not deviations, recorded for the gate

**Two tests in `test_arrival_contract.py` were edited, both intent-preserving and both
anticipated by WP1 in the file itself.**

* `test_capabilities_claims_nothing_the_adapter_does_not_have` — WP1's report §5 says
  "`capabilities()` must change in the same commit … and will fail otherwise. That is
  deliberate." The two WP2-anticipating assertions flipped to the positive claim; the
  cross-check loop that makes the test a ratchet is untouched, and one assertion was added
  (`ARCHIVE` stays absent).
* `test_the_ledger_satisfies_the_ledger_surface_it_claims` — WP1's inline comment says "When
  WP2 lands these, this assertion is what tells it to update the capability report in the same
  change." `assert not isinstance(ledger, ArrivalLedger)` became `assert isinstance(...)`, and
  assertions were added pinning the Protocol surface at exactly §A.2's nine rows and that
  `import_prefix` is offered, is NOT on the Protocol, and IS in `LEDGER_MUTATIONS`. Gate F-1
  respelled the Protocol-surface assertion off a `typing` private — §1.10, evidence in §4.4.

No other test file was modified. The fourteen arrival test files are green and unmodified.

**One stray fact in the store, accounted for.** The first emit of D1 was malformed — the slug
went in as a trailing word instead of `name=`, so it stored as
`finding/<no-fold> @ 01M17E4T09ZPFME9D24C3QHYCG` and never folded. Its payload carries
`agent=s2wp2-impl`, so a gate cross-checking report against store would otherwise find a
WP2-stamped finding this report does not name. It is superseded in full by
`01M17E5119XBNFF2RWFEG0KE2S` and carries no claim that fact does not.

**A refusal-set gap was met and NOT re-filed.** A gap in a replication batch, a supplied `rh`
that does not recompute, a foreign lineage: none has a member in the ratified five, so each
surfaces as this backend's own family, untranslated. That is exactly the gap WP1 already
raised as `finding:slice2-wp1-refusal-set-gaps` (D4), so it is cited rather than duplicated.
Its consequence for WP2 is stated in §1.4 and is load-bearing for the vectors: a vector may
only name a contract refusal, so those cases are pinned by unit tests instead.

---

## 3. Test-count table

| Suite | Baseline | Now | Delta | Accounted by |
|---|---|---|---|---|
| engine | 1989 passed, 1 skipped | 2034 passed, 1 skipped | **+45** | `test_arrival_transfer.py` (+34), `test_conformance_replicate.py` (+11) |
| store | 180 | 180 | 0 | no store file touched |
| architecture | 99 | 99 | 0 | Rule 18 green with no new module born; no new `_SCAN_TARGETS` entry needed |

New-test breakdown, so the +45 is legible rather than a number:

| File | Count | Covers |
|---|---|---|
| `test_conformance_replicate.py` | 11 | the 10 vectors, plus an exact-inventory check (§4.6) so a dropped fixture fails naming itself and an unclassified one fails too |
| `test_arrival_transfer.py` | 34 | export ×5 (byte identity, streaming, clock-free manifest, codec refusal, captured-head bound), §12 byte-identity gate ×2, §12 snapshot-under-concurrent-writer gate ×1, import ×13 (empty replica, remainder-only, same-length idempotent accept, short-import refusal, agreement refusal, codec/framing, five manifest claims parametrized, suffix-as-prefix, tampered record), `adopt_genesis` ×3, replicate's own-family refusals ×8 (empty, wrong digest, foreign lineage, batch hole, atomic limit + the under-limit control, unpinned, fork type, empty batch), byte-identity at file and line level ×2 |

Vector families: 10 vectors across the three §D.2 families — exact-suffix (4),
same-height (3, including the negative control), catch-up (3).

Wider net, all green and unchanged from WP1's baseline: sdk 324, apps/loops 2530 + 1 xfail,
lang 655, atoms 517, sign 37, custody 13, chaos 12, `tests/architecture` 99. Root `tests/`
runs 111 (the 99 architecture tests plus `tests/chaos`'s 12); no file under `tests/` was
touched, which `git diff --name-only 0d38c969..HEAD` shows.

---

## 4. Mutation evidence

Both demonstrations the brief names, plus one extra arm because the fork refusal has two
independently reachable halves. `git diff` clean and the suite re-green after each restore.

### 4.1 (a) Weaken the same-height-fork refusal — the whole check

```python
# revert, in ArrivalLog._refuse_divergent_batch:
-            if mine is not None and mine != candidate.get(_RH):
+            if False and mine is not None and mine != candidate.get(_RH):
```

```
FAILED test_conformance_replicate.py::...[replicate-same-height-fork-at-the-head-refuses]
FAILED test_conformance_replicate.py::...[replicate-same-height-fork-below-the-head-refuses]
FAILED test_arrival_transfer.py::test_the_arrival_layer_raises_its_own_fork_type_not_the_contracts
3 failed, 41 passed
```

Two things worth reading off this. The negative control
(`replicate-same-height-agreement-is-not-a-fork`) **stayed green**, so the vectors are
discriminating between fork and stale-head rather than firing on any overlap. And
`test_import_refuses_a_target_that_disagrees_about_its_own_prefix` also stayed green — import's
§08 prefix-agreement gate is a genuinely separate site (`FileLedger._refuse_disagreeing_prefix`)
with its own pin, which is the honest answer to "is the fork logic duplicated?": there are two
checks because they refuse two different things (the overlap you were HANDED versus the overlap
you were about to SKIP), and each is independently covered.

### 4.2 (a′) Narrow the fork check to the head ordinal only

The sharper mutation, because it is the shape a plausible implementation would actually take:

```python
-                if _is_int(candidate.get("ord")) and candidate["ord"] <= head["ord"]
+                if _is_int(candidate.get("ord")) and candidate["ord"] == head["ord"]
```

```
FAILED test_conformance_replicate.py::...[replicate-same-height-fork-below-the-head-refuses]
FAILED test_arrival_transfer.py::test_the_arrival_layer_raises_its_own_fork_type_not_the_contracts
2 failed, 42 passed
```

Exactly the below-the-head vector, and the at-the-head one stays green — the two arms of the
fork check are independently pinned.

### 4.3 (b) Make replicate re-coordinate (assign instead of validate)

```python
# revert, in ArrivalLog.append_records' build:
-            return candidates[index]
+            c = candidates[index]
+            return build_record(
+                lin=head["lin"], ordinal=head["ord"] + 1, prev=head[_RH],
+                k=c["k"], body=c["body"], observer=c["observer"],
+                origin=c["origin"], at=c["at"], sig=None,
+            )
```

```
FAILED test_conformance_replicate.py::...[replicate-catch-up-from-a-genesis-only-replica]
FAILED test_conformance_replicate.py::...[replicate-catch-up-preserves-signed-records-byte-for-byte]
FAILED test_arrival_transfer.py::test_export_import_export_is_byte_identical
FAILED test_arrival_transfer.py::test_a_replica_preserves_a_carried_in_signature
FAILED test_arrival_transfer.py::test_import_appends_only_the_remainder_to_an_agreeing_target
FAILED test_arrival_transfer.py::test_import_of_a_prefix_the_target_already_holds_changes_nothing
FAILED test_arrival_transfer.py::test_replicate_refuses_a_record_whose_supplied_digest_is_wrong
FAILED test_arrival_transfer.py::test_replicate_refuses_a_foreign_lineage_as_this_backends_own_fault
FAILED test_arrival_transfer.py::test_replicate_refuses_an_internally_inconsistent_batch_and_lands_none_of_it
FAILED test_arrival_transfer.py::test_a_replicated_suffix_is_byte_identical_to_the_source_bytes
10 failed, 34 passed
```

**The result that justifies the vector design.** Both failing catch-up vectors are the ones
carrying SIGNED records. `replicate-catch-up-preserves-authored-time-and-origin` — an exact
suffix with distinctive `at` and `origin` values and no signature — **stayed green**, because a
re-coordinator assigning the same lineage, ordinal and predecessor to an exact suffix
reproduces identical record hashes. `at` and `origin` survive the rebuild (`Entry` carries
both); a signature does not (`Entry` has no signer field, and `append_marked_many` builds every
record with `sig=None`). So the signature is not decoration in that family — it is the only
content that makes assigning observably different from validating, and a catch-up family
without one would have passed this mutation.

### 4.4 Gate F-1 — the Protocol-surface assertion, both directions

The respelling (§1.10) has to keep the property the old one bought, so it is demonstrated in
both directions rather than merely re-run.

**Extra row — a tenth op declared on the Protocol:**

```python
+    def import_prefix(self, prefix: ExportedPrefix) -> Head:
+        """A tenth op, declared beyond the ratified table."""
+        ...
```

```
E   AssertionError: assert frozenset({...}) == frozenset({...})
E     Extra items in the left set:
E     'import_prefix'
FAILED test_arrival_contract.py::test_the_ledger_satisfies_the_ledger_surface_it_claims
```

**Missing row — `export` dropped from the Protocol:**

```python
-    def export(self, *, through: Head, codec: str) -> ExportedPrefix:
-        """Deterministic portable records plus a manifest, for a captured prefix."""
-        ...
```

```
E   AssertionError: assert frozenset({...}) == frozenset({...})
E     Extra items in the right set:
E     'export'
1 failed, 28 passed
```

Worth reading off the second one: **only that assertion fired.**
`isinstance(ledger, ArrivalLedger)` stayed true, because the adapter offers a superset of a
shrunken Protocol — which is exactly why the surface needs an equality assertion of its own
and cannot be left to the runtime check. Restored after each; `git status --short` clean at
`arrival_contract.py`, engine **2034 passed, 1 skipped** at the tip.

The query-separation ratchet was not touched and still derives its op names from
`LEDGER_MUTATIONS` (`test_arrival_contract.py:183,191`).

### 4.5 Sol S2WP2-L-1 — the short-import refusal

```python
# revert, in FileLedger._refuse_disagreeing_prefix:
-        if len(imported) < overlap:
+        if False and len(imported) < overlap:
             ...
-            self.scan(through=head), imported[:overlap], strict=True
+            self.scan(through=head), imported, strict=False
```

```
FAILED test_arrival_transfer.py::test_import_refuses_a_prefix_that_ends_before_the_targets_head
1 failed, 33 passed
```

Exactly the new test, and `test_re_importing_the_same_prefix_changes_nothing` stayed green
under both the fix and the mutation — the refusal discriminates "stops short of the head"
from "reaches the head with an empty remainder" rather than refusing every already-have-it
import. Restored; `git status --short` clean at `arrival_file_backend.py`.

### 4.6 Sol S2WP2-L-2 — the vector inventory

The old family check asked only whether a family was non-empty, so it went green until a
family lost its LAST vector. Now the inventory is exact, both directions.

Removed `spec/conformance/vectors/replicate/replicate-catch-up-preserves-authored-time-and-origin.json`:

```
E   AssertionError: missing: ['replicate-catch-up-preserves-authored-time-and-origin'];
E   unclassified: []
```

It fails naming itself, with two catch-up siblings still present. Worth noting which fixture
sol's probe happened to delete: the **unsigned** catch-up vector is the one whose silent
absence would have quietly gutted §4.3's evidence, since it is the control proving that an
exact suffix without a signature cannot distinguish assigning from validating. Restored; the
area is back to 10 vectors.

### 4.7 Restoration

`git checkout libs/engine/src/engine/arrival.py` after each; `git status --short` empty, and
45 passed on the two files. Re-run at the branch tip after the last restore: engine **2034
passed, 1 skipped**, store 180, architecture 99 — the §3 counts, measured again rather than
inferred from the restore.
