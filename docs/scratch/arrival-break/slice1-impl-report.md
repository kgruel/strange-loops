# Slice 1 impl report — wire v1 pin

Branch `slice/arrival-wire-v1`, worktree `~/Code/loops-slice1`, based on `68c7aa57`
(verified: both `7984a5de` and `68c7aa57` are ancestors of HEAD).

Contract: `docs/scratch/arrival-break/slice1-impl-brief.md`. Binding facts:
`decision:design/arrival-wire-v1-seam-triage` (parent ruling 2026-08-26 + sub-ruling
`01M172M74FZ9E27V34QKDF7Y77`, 2026-08-29) and
`decision:design/arrival-backend-neutral-protocol`. Panel evidence:
`slice1-panel-synthesis.md` @ 7984a5de.

## Scope delta

All four contract changes plus the docs pass landed. **No deviations from the contract**
— nothing was descoped, nothing was added beyond it. Two items the brief left to my
judgement are recorded as design points below; one ratchet obligation (Rule 18) was
discharged that the brief did not name.

Commits:

| Commit | Unit |
| --- | --- |
| `680b241b` | the wire v1 pin — all three code changes plus tests and fixtures |
| `2f444f8d` | the architecture-doc pass |
| (this file) | the implementation report |

Changes 1–3 landed as one commit deliberately. They are one ruling, and the brief itself
requires both mint sites in one change; splitting them would have meant per-hunk staging
of shared test files (`test_arrival_store.py` carries both a `body.t` assertion change
and the new tick-observer test) for no reviewer benefit. The mutation demonstrations
below name the exact line to revert for each change, which is what the oracle actually
needs — commit boundaries were never the revert mechanism.

## Design points

### 1. Does arrival decode REFUSE a body that still carries `t`? — YES, by grammar

The brief left this open and asked for justification. Refusal, and specifically
**refusal that costs no code**.

`t` is simply absent from the arrival body's allowed-field set, so a body carrying it
fails the same unknown-field rule that already refuses any other stray key
(`arrival_body._ALLOWED`, checked through `jsonl_codec.row_object_fault`). There is no
branch that mentions `t`, nothing that sniffs for the old shape, and no compat flag.

This is the dissolution answer rather than the detection answer: the alternative — a
tolerant decode, or an explicit "this looks like a legacy body" check — would be a
detector asserting a verdict about an encoding that has no instances. Zero `.arrival`
stores exist (verified: `git ls-files | grep .arrival` is empty, and the parent ruling
records the same finding against live config), and the break has no compat mode by
ratified design, so there is nothing for tolerance to buy. The full-break posture means
the only bodies that will ever exist are ones this grammar wrote.

Consequence handled deliberately: the legacy batch validator refuses a nested batch and a
tick-inside-a-batch by reading each row's `t`. Without a discriminator there is no such
claim to refuse — a nested batch is an object with an unknown `rows` field, a tick is an
object with unknown `name`/`since` fields, and both now fail the fact field rules on
exactly those grounds. The refusals did not weaken; they stopped being a separate rule.
Documented at `arrival_body._validate_batch`.

### 2. Where does the batch same-observer rule live? — the arrival batch grammar, arrival-only

The brief noted `arrival._validate` is deliberately kind-agnostic (kind-specific rules
live in `_placement_fault`) and asked me to justify placement.

Not `_validate`: correct, it is kind-agnostic by design and putting a batch rule there
would break the separation the `_placement_fault` split exists to protect.

Not `_placement_fault` either, and this is the sharper reason: that function answers "why
may this record not sit at this ordinal". A batch-rows rule is not about placement, and
implementing it there would force `arrival.py` to know the row-body grammar — a layer it
deliberately does not have. `arrival.py` treats `body` as opaque, checking only that it is
JCS-canonicalizable (`_check_body`). Teaching it to read `body["rows"][i]["observer"]`
would be the record grammar reaching into the body grammar.

So the rule lives in `arrival_body._validate_batch`, beside the structural batch rules it
is a sibling of (no nesting, no ticks, no duplicate id). One function
(`_refuse_mixed_observers`) called on both the encode and the decode path, because a
grammar rule enforced in one direction is one a determined caller routes around by
hand-assembling the body it could not build.

**Scoped to the arrival seam and NOT added to the legacy line codec.** Ruling 4 says "a
wire-grammar refusal at the arrival seam", and the scoping is load-bearing rather than
literal-minded: the legacy codec is what slice 4's migration sidecar reads historical
`.jsonl` logs with. Adding a rule that postdates those logs would convert any historical
mixed-observer batch from a migratable record into a hard refusal — a new failure mode
introduced into migration by a rule meant to protect new writes. The sidecar's own output
is still guarded, because it constructs bodies through `body_of_batch`. Pinned by
`test_the_line_codec_does_NOT_carry_the_same_observer_rule`.

### 3. Genesis-read plumbing in merge

`merge_store` already opens the target log (`log = ArrivalLog(canonical)`, merge.py:279)
for the existence check and the CAS append, so the destination genesis was one call away
— it did not need a new open, which was the panel's one flagged non-trivial cost inside
candidate A. The custodian is read once per merge attempt at the call site and threaded
`_entries_for(source_rows, held, custodian)` → `_entry_for(kind, rows, custodian)` as an
explicit parameter.

Threaded rather than re-derived per record for two reasons: `_entry_for` has no log in
scope and giving it one would hand a pure record-assembly function an I/O dependency; and
the read belongs to the attempt, which is the unit the retry loop re-runs. `ArrivalLog.genesis()`
memoizes on the genesis line bytes, so the cost is one `open`+`readline` per attempt.

**The label is the TARGET's genesis observer, not the source's.** The record being minted
is the target's own — merge is admission into another lineage, and the envelope describes
the record, not its provenance. `test_a_merged_tick_names_the_TARGETS_custodian` uses a
three-way distinct fixture (target custodian / source custodian / tick name) so the
assertion cannot pass by fixture coincidence.

### 4. The module fork: `arrival_body` imports the shared row domain from `jsonl_codec`

I initially planned to invert the dependency — move the validation core into
`arrival_body` so "the runtime does not depend on the sidecar". I rejected that on
evidence. The ratified deletion list
(`decision:design/arrival-backend-neutral-protocol`) kills `jsonl_store.py` and the
bare-codec *mode*; `jsonl_codec.py` is not on it, and cannot be — `line_of_record` /
`serialize_object` produce the derived `.jsonl` projection and `derived_log_merge.py`
consumes it, both surviving the break. The runtime keeps depending on the line codec
regardless, so inverting bought nothing and maximised the diff in the one module whose
byte-stability the slice's NON-NEGOTIABLE rests on.

What is shared is exactly one function, `jsonl_codec.row_object_fault`: the per-field
domain rules, which describe a **sqlite row** and belong to neither framing. It returns a
fault string rather than raising — the shape `arrival._placement_fault` and
`arrival._key_shape_fault` already use in this codebase — so each framing raises its own
error class (`ArrivalBodyError` vs `JsonlCodecError`) over one set of rules. The `allowed`
set is precisely where they fork. Field tuples and nullability moved to named module
constants (`FACT_NULLABLE`, `TICK_NULLABLE`) for the same one-definition reason.

Legacy messages are byte-identical: `row_object_fault` takes a `frame` word, `"line"` for
the codec and `"body"` for arrival, so a body's refusal does not send the reader looking
for a line.

### 5. The unminted-log refusal (not in the brief; found before editing)

`ArrivalStore`'s class docstring promises an unminted log "refuses appends with the
mint-first message", and `test_an_unminted_log_opens_empty_and_refuses_appends` pins
`GenesisRefused, match="mint a genesis first"` on the fact path.

Reading the genesis for the tick label introduces a *new* way to hit an unminted log: the
observer kwarg evaluates before `append_marked` runs, so a raw `genesis()` would have
raised `GenesisRefused("... does not exist")` for ticks — same class, different message,
and the documented promise quietly false for one row class. `ArrivalStore._custodian`
re-spells the refusal, mirroring what `_genesis_lineage_id` already does in the same file.
Pinned by a new test (`test_a_tick_on_an_unminted_log_still_refuses_with_the_mint_first_message`).
The fact path is untouched — the ternary is lazy, so `genesis()` is never evaluated for a
fact.

### 6. Rule 18 ratchet (obligation discharged, not in the brief)

`tests/architecture/test_rule_18_arrival_vocabulary_denylist.py` states its own trigger:
a module born on the arrival surface joins `_SCAN_TARGETS` **at birth**. `arrival_body.py`
is such a module, so it joins in the same change. `jsonl_codec.py` does not join and will
not — it is the legacy framing by definition, and its vocabulary is that mode's honest
vocabulary (the same reasoning the rule already applies to `jsonl_store.py`).

## Test counts

Per-suite, clean baseline on the worktree before any edit vs. after. Env verified as the
worktree's own: `command -v python` → `/Users/kaygee/Code/loops-slice1/.venv/bin/python`,
`engine.__file__` → `/Users/kaygee/Code/loops-slice1/libs/engine/src/engine/__init__.py`.

| Suite | Before | After | Δ | Accounting |
| --- | --- | --- | --- | --- |
| `libs/engine/tests` | 1913 passed, 1 skipped | 1937 passed, 1 skipped | +24 | 23 new in `test_arrival_body.py`, 1 new unminted-log tick refusal |
| `libs/store/tests` | 176 | 177 | +1 | `test_a_merged_tick_names_the_TARGETS_custodian` |
| `tests/architecture` | 98 | 98 | 0 | Rule 18 target added; the rule is one test over a list |
| `libs/atoms/tests` | 517 | 517 | 0 | untouched |
| `libs/custody/tests` | 13 | 13 | 0 | untouched |
| `libs/lang/tests` | 655 | 655 | 0 | untouched |
| `libs/sdk/tests` | 324 | 324 | 0 | untouched |
| `libs/sign/tests` | 37 | 37 | 0 | untouched |
| `tests/chaos` | 12 | 12 | 0 | untouched |

No test was deleted or skipped. Every count delta is a named addition.

**Two count discrepancies, reconciled rather than waved through:**

1. `pytest spec` collects **zero** tests, so `pytest tests/architecture spec` and
   `pytest tests/architecture` both report 98. This is correct, not a gap: `spec/` holds
   conformance *vectors* and their generators, no test modules. The vectors are consumed
   by `test_conformance_fold.py` (atoms), `test_conformance_replay.py` /
   `test_conformance_lens.py` (engine), `test_conformance.py` (sdk) and
   `test_conformance_merge.py` (store) — all inside the package suites above, all green.
2. `libs/engine/tests` and `libs/store/tests` cannot be run in one pytest invocation
   (`ImportPathMismatchError` — both packages have a `tests.conftest`). Pre-existing, not
   caused by this slice; the suites are run separately, which is how the counts above are
   taken.

Legacy-codec byte stability spot-check: `test_jsonl_codec.py` + `test_jsonl_golden_fixtures.py`
were 104 passed before the change and 104 passed immediately after the `jsonl_codec`
refactor, before any consumer was rewired.

## Mutation verification

Each change was reverted in isolation, the suite re-run, and the source restored (`git
diff --stat` empty after each). The gate can reproduce these exactly.

| # | Revert | Result |
| --- | --- | --- |
| 1 | `arrival_body._validate_batch`: drop the `_refuse_mixed_observers(rows)` call | **2 failed** — `test_a_batch_spanning_observers_is_refused_on_construction` and `..._on_decode_too`, both `DID NOT RAISE ArrivalBodyError`. Both directions fail, which is the point of the rule being one function called twice. |
| 2 | `store/merge.py` `_entry_for`: `observer=custodian` → `observer=stripped[1]` | **1 failed** — `test_a_merged_tick_names_the_TARGETS_custodian`, asserted value `+ pulse` (the retired tick-name convention). 30 passed. |
| 3 | `arrival_store._write`: `self._custodian()` → `committed_row[1]` | **1 failed** — `test_ticks_ride_as_records_naming_the_custodian_not_the_tick`, asserted value `+ pulse`. 19 passed. |

Mutations 2 and 3 fail *different* tests in *different* packages, which is the property
the brief was protecting: before this slice nothing asserted the merge path's tick
observer, so a single-site fix would have gone green and wrong.

## Fixture and vector assessment

**Conformance vectors: NULL BLAST for both changes.** The panel verified this for the
observer respell and explicitly did not assess it for the `body.t` drop; I checked the
drop myself and it is also null.

- `grep -rl '"t":' spec/conformance/vectors/` → **0 files**.
- `grep -rl '"lin"|"ord"|"rh"' spec/conformance/` → **0 files** (no checked-in vector
  embeds an arrival envelope at all, confirming the panel's finding independently).
- The four generators (`generate_fold/lens/merge/replay.py`) import neither
  `engine.arrival*` nor `engine.jsonl_codec`; their only arrival mentions are two prose
  strings in vector descriptions.

So nothing under `spec/` was regenerated, and nothing needed to be. An arrival-envelope
vector family remains net-new work gated on this pin, not a regen — unchanged from the
panel's assessment.

**Checked-in arrival records:** `git ls-files | grep .arrival` → empty. A repo-wide
`grep -rl '"rh"'` finds 10 files: three arrival source/test files that construct records
programmatically, three architecture docs (handled in the doc pass), and three
`docs/scratch/arrival-branch-review/*.log` review transcripts, which are historical
receipts and correctly left alone.

**Python fixture regen surface — what actually changed.** Larger than the panel's ~2–3
estimate, because that estimate covered the observer respell only:

| File | Change |
| --- | --- |
| `test_arrival_store.py` | tick-observer assertions rewritten to the ruled semantics; body-literal `t` dropped (2 sites); `body["t"]` assertion → `"t" not in body` |
| `libs/store/tests/test_arrival_merge.py` | `_fact_body`/`_tick_body` lose `t`; the tick fixture's `observer=body["name"]` → the log's genesis observer; `arrival_store()` gains an `observer` parameter |
| `test_arrival_coordinate_d0.py`, `test_seal_rebase_d2.py`, `test_query_facts.py`, `test_arrival_cas_head.py`, `test_audit_rebase_d3.py` | `object_of_*` → `body_of_*` (these build arrival bodies, not legacy lines) |
| `test_admission_verification.py`, `test_derived_log_merge.py` | same, plus `json.loads(serialize_batch(rows))` → `body_of_batch(rows)` |
| `test_arrival_cas_head.py` | `head_by_walking_the_log` now dispatches on `record["k"]`; it expands bodies BY HAND on purpose, so it had to learn the new reading independently rather than borrow `rows_of_record` |
| `test_arrival_authority_gate.py`, `test_arrival_projection.py` | `body["t"]` assertions and body literals |
| `test_arrival_derived_log.py` | `test_a_line_is_the_record_body_and_nothing_else` renamed to `..._plus_the_discriminator_and_nothing_else` — its premise genuinely changed, so it now asserts that no body carries `t`, that every line does, that the line discriminators are the record kinds, and that stripping `t` recovers the body exactly |

Legacy fixtures that correctly KEEP `t` and were left alone: `test_jsonl_codec.py`,
`test_jsonl_golden_fixtures.py`, `test_jsonl_store.py`, `test_canonical_audit.py`, and the
torn-line literal in `test_audit_rebase_d3.py:546`. One site in
`test_derived_log_merge.py` hand-writes *derived-log* lines and so needed `t` restored
explicitly — it now routes through `legacy_object_of_body`, which is the same restoration
`write_derived_log` performs.

## Oracle status

1. **Suites green, counts reconciled** — table above; all nine suites pass.
2. **Inner-signature preservation** — `test_dropping_t_moves_no_inner_commitment` computes
   `fact_commitment_hash` before the drop and again from the row recovered out of a t-less
   body, and asserts equality plus that the inner signature rides verbatim. No existing
   signed fixture stopped verifying at any point; **no contract breach to report.**
3. **Byte-stable round trip** — `test_encode_decode_encode_is_byte_stable` (fact, signed
   fact, tick) and `test_a_batch_round_trips_byte_stably`, asserted on serialized bytes
   rather than dict equality.
4. **Mutation evidence** — three demonstrations above.
5. **`git ls-files`** — verified from git's view; no `.loops/`, no store file, no `.jsonl`
   or `.log` artifact staged at any point.
6. **Docs** — no `body.t` mention survives outside legacy-codec/sidecar context (the two
   remaining occurrences in `wire-format.html` are the ruling's own statement of what was
   dropped); `protocol.html` §06 states the ruled law; `wire-format.html` status flipped to
   pinned. All five arrival docs re-parsed with balanced tags after editing.

Additionally verified beyond the oracle: the derived `.jsonl` projection's bytes are
unchanged by the drop, asserted against the legacy encoder for fact, tick and batch
(`test_the_derived_log_line_is_unchanged_by_the_drop` and its batch sibling). This was the
tripwire worth having — the derived log is the one artifact a body-shape change could have
silently altered for every last-0.x reader.

## Deviations

**None.** No contract item was skipped, softened, or exceeded. The two items the brief
delegated (refusal posture, rule placement) are decided and justified above; the two
additions not named in the brief — the unminted-log refusal preservation and the Rule 18
registration — are obligations the existing code and ratchets imposed on the change, not
scope growth, and both are recorded here rather than left for the gate to discover.
