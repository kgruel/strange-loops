# Cut A (AUTHORITY) — implementation report

Branch: `slice/arrival-authority` off `feat/arrival-libs` @ `3b303d5d`.
Contract: `decision:design/arrival-sliceA-authority` @ `01M0B0Z14T9ATPRAJTKBBMCQQT`
+ `docs/dev/arrival-sliceA-authority-design-2026-08-18.md` (RATIFIED).
Implementer: sliceA-impl. Date: 2026-08-18.

## Commits (in order)

1. `2184400b` feat(engine): genesis carries the founding key; the first arrival verifier
2. `d9a1686a` feat(engine): residence grows the arrival answer; probe's .arrival arm
3. `f345fb7b` feat(engine): ArrivalStore — rows land in the log first; ceremonies re-point
4. `1b920fc1` test(arch): Rule 18 judges the funnel; the two unavoidable names carry entries
5. `083eb0c1` docs(scratch): cut-A implementation report
6. `2d862367` test(engine): the probe classification matrix under the arrival mode
7. fix(engine): the reconcile→append race (this report's final commit)

## What was built, per doc §9

**§9.1 — probe's `.arrival` arm.** `probe_target` dispatches `.arrival` →
`_probe_arrival` (`target_type="arrival_log"`, `canonical_mode="arrival"`,
corroboration via plain `open('rb')` + `arrival.decode_record` only — the
pure-inspection contract holds, and the docstring pins that no `ArrivalLog`
method may ever be used there). The half-migrated store is named and pinned
from BOTH sides: a `.db` with an `.arrival` sibling is `derived_index` over
the arrival log even when a `.jsonl` also exists (arrival wins per Law 1;
the reason string says the `.jsonl` is a projection), and probing the
`.jsonl` itself in that configuration classifies as the new `derived_log`
type — a projection, not a store, `writable=False`. `_probe_vertex` computes
mode through `residence.canonical_mode`, removing the second spelling of the
switch. Tests: `test_probe_arrival_matrix.py` (13 tests, all three entry
points, plus a whole-matrix "exactly one custody holder" pin).

**§9.2 — residence.** `canonical_mode(declared) -> "arrival"|"jsonl"|"sqlite"`
replaces the deleted boolean; `index_path_for` gains the arrival arm
(`with_suffix(".db")`); `log_path_for` is deleted and replaced by the
explicit-mode inverse `canonical_for(index_path, mode)` (the bijection is
`with_suffix` in both directions and pinned by test — `arrival_path_for` is
re-exported but documented as a different question, per the known
`alcove.db.arrival` shape). `canonical_store_path` / `resolve_store_path` /
`sqlite_sidecars` untouched. `ARRIVAL_SUFFIX` and the companion-path helpers
are imported from `engine.arrival` and re-exported — one spelling.
Libs-side sweep: `jsonl_store` (open/ensure/log-path sites), `preflight`
(three-mode dispatch + a scoped `_arrival_preflight` whose `agreed` stays
`None` — no innocence claim for an audit that does not exist yet),
`compiler` (mode-based store dispatch, EventStore fallthrough preserved),
`ceremony` (comment updated to the mode vocabulary). `declaration`,
`handle`, `vertex_reader`, `canonical_audit`, `libs/store` ride the funnel
unchanged. Tests in `test_residence.py` updated to the three-arm mode.

**§9.3 — genesis body {protocol, lineage, key}.** `ArrivalLog.mint` gains a
required `key` argument (raw-32-byte-base64 wire shape, checked at mint and
in `_placement_fault`'s ordinal-0 arm); the keyless variant's refusal
message teaches that a keyless genesis belongs to the migration sidecar.
Slice-0's "minimal body" tests updated to the ratified three fields
(slice-0-scoped per the ruling; the two tests now pin `{protocol, lineage,
key}` and the keyless refusal).

**§9.4 — the first verifier.** `verify_authorship(log, verify)` implements
the ruled rule verbatim: a key is valid at position N iff introduced at a
position < N, or N is the genesis position and the record is
self-certifying; self-certification legal at ordinal 0 and nowhere else.
Key introductions are arrival-native records (`KEY_INTRODUCTION_KIND =
"key"`; body carries the introduced observer + key; must be signed —
`_placement_fault` enforces the structure at append and on the walk). Keys
bind to observers (genesis key → genesis observer; introduced key → the
observer the body names); resolution consults the log and NOTHING else.
Crypto is injected (`Verify` callable), never imported — engine still has
no `sign` dependency; the tests compose real Ed25519 the way an app does.
Trace rows are `KeyResolution(ordinal, observer, key, introduced_lineage,
introduced_ordinal)`. 15 tests in `test_arrival_authority.py`.

**§9.5 — the write path + ceremonies (`arrival_store.py`, new).**
`ArrivalStore(SqliteStore)` over the proven seam (`_write_fact_row` /
`_write_tick_row` / `_ceremony_persist`); `open_canonical_store` and
`ensure_index` grow the arrival arm. Record mapping: `body` = the line
codec's object for the COMMITTED row (payload as verbatim TEXT — existing
fact signatures survive; cut B can hand `body` straight back to the codec);
`k` = row class (`fact`/`tick`/`batch`), so fact kinds cannot collide with
structural kinds. Fact records signed by the injected `fact_signer` over
the arrival content commitment. Cursor = the ratified three-field resume
mark, stamped from exact under-lock offsets (`ArrivalLog.append_marked` /
`walk_marked`, added to arrival.py; `_verify_from` now tracks byte offsets
internally — public `walk`/`walk_from` yield unchanged). Catch-up consumes
forward or refuses (`ArrivalCanonicalUnsupported`) — never rebuilds; an
absent index builds forward from ordinal 0 (destroys nothing).
`absorb_genesis` re-points through two new seam hooks on `SqliteStore`
(`_genesis_lineage_id`, `_genesis_payload`): arrival mode stamps
`own_lineage` = `ArrivalLog.lineage()` (the `_decl.genesis` row id IS that
lineage — the legacy CAS invariant rides), payload sheds both era pins;
legacy modes byte-identical (S3, pinned by
`test_legacy_absorb_payload_is_untouched` plus the untouched
`test_jsonl_ceremonies.py` suite). Absorb with no arrival genesis refuses
with the movement order ("mint movement 1 first"). `adopt_lineage` refuses
structurally (restamp is cut B's repair verb); `reanchor` stays refused.
16 tests in `test_arrival_store.py`.

**§9.6 — ratchets.** Rule 18 `_SCAN_TARGETS` += `residence.py`, `probe.py`,
and `arrival_store.py` (the third is an instantiation decision beyond the
ruled two: a NEW module born on the arrival surface joins at birth — noted
in the task fact). Two `_ALLOWED` entries, both commented and
shrink-tracked (see deviations). Rule 17's `_ALLOWLIST` was NOT disturbed:
the funnel prose rewritten this cut was residence/probe's, which Rule 17
does not cover; `test_allowlist_has_no_stale_entries` passes with zero
deletions forced.

**§9.7 — `late_arrivals`.** KEEP, per §5.1; one clause added to
`diff_interval_report`'s docstring naming the witness-time sense vs the
custody coordinate.

**§9.8 — the gate.** `test_arrival_authority_gate.py`:
- **G1** answered literally: mint (movement 1), facts by two observers, a
  key introduction at ordinal 2, a declaration absorb (movement 2), a seal
  tick; delete `.db` + `-wal`/`-shm` + any `.jsonl`; identity (lineage),
  records (kinds, verbatim payloads, the declaration row), authorship
  (`verify_authorship`), and ordering (dense ordinals) all answer from the
  `.arrival` alone via `walk()`; `own_lineage` re-derives with `store_meta`
  gone (the `_decl.genesis` body's id == `log.lineage()`).
- **G2** the exclusivity trace: second key at stated ordinal 2, every
  projection deleted, every signature verified, trace emitted as
  `(key, lineage, ordinal)` rows — all coordinates in THIS log, the keys
  physically present at those coordinates; plus a chdir-isolated run
  showing the verifier has nothing else to consult.
- **G3** `git diff --stat main -- apps/` empty (also verified manually: 0
  lines).

## Deviations from the design doc (all recorded in the task fact)

1. **`is_jsonl_canonical` survives as an unexported shim with ONE Rule 18
   allowlist entry** (doc §4.1 says deleted; §4.5 says the allowlist must
   not grow). The doc's premise — "every apps/ call site rides the funnel
   API unchanged" — is falsified by a direct symbol import at
   `apps/loops/src/loops/commands/store.py:142` (lazy, executed before the
   mode check): deleting the symbol would ImportError every `loops store`
   read verb in EVERY mode, and apps/ is diff-empty for the whole wave, so
   the caller cannot move until the CLI-surface cut. The shim is one line
   (`canonical_mode(declared) == "jsonl"` — behavior-identical for every
   pre-existing input; `.arrival` answers False, which correctly skips the
   jsonl agreement gate), is not in `__all__`, is named by nothing else in
   libs, and carries a tripwire test
   (`test_the_retired_boolean_survives_only_for_the_cli_lazy_import`)
   naming the apps line so cut B+ cannot lose the pairing. Filed as a
   FINDING (census error, independent of this slice's changes).
2. **A second Rule 18 allowlist entry for `def reanchor`** in
   arrival_store: the refusing override must carry the legacy method name
   or it overrides nothing. Same shape as JsonlStore's refusal; falls away
   when the base method retires.
3. **`_placement_fault` stays pure** (doc §2.5 asks the genesis arm to
   verify the signature "against that key"): the function's callers (walk,
   append, open) carry no verifier, and §2.5 itself rules the verifier
   injected-never-imported. Resolution: shape checks (key present, decodes
   to 32 bytes) in `_placement_fault`; cryptographic self-certification is
   `verify_authorship`'s first act, pinned by
   `test_a_genesis_signed_by_a_key_other_than_its_own_is_refused` and
   `test_mint_key_and_signer_disagreeing_is_caught_by_the_verifier`.
4. **`_SCAN_TARGETS` gains three modules, not two** (the ruled two plus the
   new `arrival_store.py`, which did not exist when the ruling was made).
5. **Observer-binding of keys** — the ruled clause is key-positional only;
   binding keys to observers (genesis key → genesis observer, introduced
   key → the body-named observer, a record tried only against its own
   observer's keys) is an instantiation decision: observer-agnostic
   resolution would let one observer's record verify under another's key
   and authorship would stop being an answer.
6. **Arrival-mode open-time out-of-band detection is narrower than
   jsonl's**, stated in the module docstring rather than silently: the
   ratified mark is exactly three fields (counts custody dissolved), so the
   stamped-counts insert check has no arrival equivalent; the arrival
   agreement audit is cut B's, beside re-derivation. Not a narrowing of the
   C2 residual (which is about `_authority_fault`, and stays at its
   confirmed width — no chain-to-genesis proof was added to any O(1) path).

## Post-review fix: the reconcile→append race

Advisor review before close found a real gap: `_write` reconciled without a
lock, so a fact/tick-kind record another writer landed in the log between
the reconcile and the append would be skipped forever — the stamped mark
claiming consumption it never performed, silently. Fixed two ways, matched
to what each path can afford:

- `_write` detects the gap by the append's own coordinate (not the
  reconciled ordinal + 1 ⇒ an interloper landed), rolls the staged INSERT
  back — our record is already durable in the log — and catch-up consumes
  everything forward, interloper included. No data loss, no retry needed.
- `_ceremony_persist` cannot resolve a gap after the fact (the record it
  would strand is the ceremony itself), so it pins the append to the
  reconciled head via `append_marked(..., following=)` — a new
  compare-and-swap arm checked UNDER the log's lock — and a race refuses
  (`AppendRejected`) before any byte is written: the ceremony rolls back
  with the log byte-identical and is retryable.

Known residual crash window, stated for cut B to inherit rather than
rediscover: a crash between the arrival-mode ceremony's log fsync and its
sqlite COMMIT leaves the `_decl.genesis` record durable with the
`own_lineage` marker unstamped; catch-up tails the row in, after which
`_own_lineage_in_txn` answers AmbiguousGenesis and `adopt_lineage` refuses
— a dead end until cut B's restamp verb. The correct refusal posture for
this cut, but a real state.

## Mutation-verification demonstrations

Each invariant test was shown to fail under a targeted break, then the code
restored and the suite re-run green:

- **Verifier — self-certification above ordinal 0**: the clause is doubly
  enforced (registration-after-resolution AND the `introduced < ordinal`
  filter); breaking either alone is an equivalent mutant (the other guard
  holds — verified: each single mutant left all 15 tests green), breaking
  BOTH fails `test_self_certification_is_refused_above_ordinal_zero`.
  Recorded so a reviewer knows the redundancy is understood, not missed.
- **Verifier — genesis self-certification skipped** (`if not verify(...)` →
  `if False`): fails `test_a_genesis_signed_by_a_key_other_than_its_own_is_
  refused` and `test_mint_key_and_signer_disagreeing_is_caught_by_the_
  verifier`.
- **Store — `_genesis_lineage_id` override removed**: fails
  `test_absorb_projects_the_arrival_lineage_and_sheds_the_pins` (+1).
- **Store — `_genesis_payload` override removed** (pins return): fails the
  same pin-shedding test.
- **Store — structural-kind skip removed from `_index_record`**: 16
  failures across the store suite and both G2 tests.
- **Probe — the half-migrated tie broken the wrong way** (arrival-sibling
  checks conditioned on no legacy log): 4 failures, including all three
  half-migrated pins and the one-custody-holder matrix pin.
- **Store — write gap guard removed** (`if False:`): fails
  `test_a_record_landing_between_reconcile_and_append_is_never_skipped`.
- **Store — ceremony `following=` pin dropped**: fails
  `test_a_ceremony_racing_an_interloper_refuses_before_any_byte`.
- **Ratchet — Rule 18 growth bites**: `JSONL_OFFSET_PROBE = 1` appended to
  residence.py fails the denylist scan; removed, green.

## Suite counts

| suite | baseline (pre-change) | final |
| --- | --- | --- |
| `libs/engine/tests` | 1621 passed, 1 skipped | **1678 passed, 1 skipped** |
| `tests/architecture` | 98 passed | **98 passed** |
| `libs/sdk/tests` | — | 313 passed |
| `libs/store/tests` | — | 131 passed |
| `apps/loops/tests` | — | 2525 passed, 1 xfailed (run for safety; apps/ diff-empty) |

New tests: 15 (authority/verifier) + 16 (store) + 4 (gate) + 14 (probe
matrix) + residence updates; slice-0's two minimal-body pins updated to the
ratified body.

## Liveness evidence

All runs execute from the worktree source (workspace editable install):
`engine.arrival.__file__` resolves to this worktree; asserted in-session
that the live module exposes `mint(key=)`, `verify_authorship`, and
`canonical_mode` (`inspect.signature` / module file path printed).

## Lint/type state

`ruff` and `pyright` clean on every file authored this slice (`arrival.py`,
`arrival_store.py`, `residence.py`, `probe.py`, new tests). Files edited
inside legacy modules (`sqlite_store.py`, `jsonl_store.py`, `preflight.py`,
`compiler.py`, `ceremony.py`) carry pre-existing diagnostics (repo CI lints
only `libs/custody` + `libs/sign`); my edits added none — the touched-file
ruff total went 83 → 82 (one pre-existing SIM105 fixed in passing).
