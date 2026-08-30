# Sol review brief — arrival-break slice 3, integration round (per-WP, LOW)

You have CONVERGED all three slice-3 WPs individually (WP1 journal, WP2 comparison
vectors r3, WP3 seam r3). This round reviews what came AFTER: the integration of
the three onto the wave branch surfaced a vein of pre-existing debt in the journal
read semantics, and consuming it produced three ratified design amendments, three
new vectors, a vector-schema field, and a doc catch-up. None of it has had
cross-family review. The integration seam is historically where this arc's worst
findings live — treat this as a fresh review, not a formality.

## 1. Anchor

- Worktree: this directory (`~/Code/loops-s3wp1`), branch `slice3/arrival-witness`,
  tip `b98ec734`. Diff spec: `git diff eab3742c...b98ec734` (eab3742c = the WP3
  merge, the last state any of your prior rounds saw parts of).
- Suites: engine per-package, architecture SEPARATELY. Claimed at tip: engine 2278
  passed + 1 skipped + 0 failed, arch 99, generator byte-reproducible, ruff clean.
- Real `$XDG_STATE_HOME` untouched (autouse isolation).

## 2. Unverified fixes/changes, by commit

- `0918d119` — 7 comparison vectors amended to WP3's ruled journal semantics
  (six shared one root: unbound fixture resets; three symptoms). Duplicate vector
  split into two claims. SCHEMA.md gained follows-binding and dedup sections.
- `fa1d4d87` + `ff96cc37` — AMENDMENT #4: per-cause skip weighting. `_Skips`
  accumulator with named-cause methods (`missed()`/`re_asserted()`); a dedup
  (re-assertion) skip is recorded but carries ZERO weakening weight. Crash-retry
  regression + injected-collision test.
- `d39e6cfa` + `90fe36a1` — AMENDMENT #5: weakening epoch-scoped by PHYSICAL LINE
  position. weight = f(cause) × g(position); a weakening-class line-skip before
  the boundary reset's line weighs zero; structural absences (headerless) exempt
  from position-scoping; `at_least` verified already epoch-scoped and pinned; no
  boundary ⇒ full weight. Disclosure sentence in `trust_reset`'s docstring.
- `6954c0a0` — vector batch: the pre-wired flip (byte-identical re-assertion,
  bounded→established), NEW reset-mismatch vector (removes a line so identity
  still matches and ONLY position is stale), NEW healing vector (damage below
  boundary → established), NEW per-skip-not-per-read composite (two same-cause
  losses straddling the boundary → bounded, skipped 2 weakening 1). SCHEMA
  CHANGE: `expected.weakening` joins `expected.skipped` on every journal vector,
  consumer asserts `weakening <= skipped` and `weakening > 0` iff
  bounded/unreadable.
- `0a5aecce` — crossdoc report committed (docs only).
- `b94413de` merge — witness-protocol.html catch-up (new §04b unsigned-journal
  section, §07 read-states + weighting rewrite, §08 matrix rows, disclosure
  sentence, "Not claimed" additions).
- `b98ec734` — ARBITER-APPLIED (prose-only, no independent gate — you are its
  only verification): `_degraded`'s docstring opening corrected from "an
  incomplete read is PERMANENT" to persists-until-operator-acts + recorded-
  forever-weighed-until-decreed. Verify the paragraph now agrees with shipped
  behavior and the rest of that long docstring was not invalidated.

## 3. Verify each — empirically where possible

1. Amendment #4 mutation demo: re-assertions weigh again → crash-retry regression
   fails with the permanent bound. Re-run.
2. Amendment #5 mutation demo: position scoping reverted → damage-behind-boundary
   regression re-bounds (2 failed claimed). Re-run.
3. **THE MATCH PREDICATE, RE-JUDGED UNDER ACCEPTANCE LOAD.** Your r3 verdict
   called the stripped-text dedup comparison "conservative — only creates
   verification/refusal." That judgment is STALE: under amendment #4 a FALSE
   dedup match silently discards a real line and the read still claims
   ESTABLISHED (acceptance-side), where before it merely degraded. Re-examine
   the predicate as acceptance-load-bearing: can two GENUINE distinct claims
   strip-collide (whitespace variants, unicode normalization, any writer path
   that could emit byte-different-but-strip-identical lines)? The injected-
   collision test asserts the safety backstop (established-but-low K → ADVANCED
   demands vouched at_known) — verify that backstop holds on every path that
   reaches it, not just the tested one.
4. The reset-mismatch vector: apply your own weakest-passing-implementation
   standard — confirm identity-only checking (amendment #1's defeated shape)
   fails exactly this vector and passes the rest of the family.
5. The weakening schema field: do the consumer's two invariants actually
   discriminate? Construct a wrong-weighting implementation (weighs everything /
   weighs nothing) and confirm some vector catches each direction.
6. The composite vector: per-read weighting in either direction (any-zero ⇒
   established; any-skip ⇒ bounded) must fail it. Verify both.
7. Doc-code agreement: witness-protocol §04b/§07 vs `arrival_head_attestation.py`
   semantics — spot-check the weighting section, the two-mechanism healing story
   (positioned damage heals via weighting; a failed ceremony attempt heals via
   the epoch walk short-circuiting — a voided-reset note can only come from
   ABOVE the boundary by construction), and the §08 matrix rows against actual
   refusal/skip behavior.
8. Counts: engine 2278+1s+0f, arch 99 (separate process), 31 vector JSONs
   tracked (`git ls-files`), generator regenerated twice → identical digest.

## 4. Try-to-defeat seeds

- **The N+1-descendant acceptance** (design:arrival-reset-descendant-acceptance,
  disclosed in docstring + §04b, ceremony-vocabulary ruling deferred to the
  slice-6 gate): after a reset to N, a restored backup at N+1 that validly
  descends from N is accepted via ADVANCED even when N+1 is the abandoned head;
  the detected-fork case (stale branch restores, real store later hits
  SAME_HEIGHT_FORK) is known and ceremony-recoverable. Attack: is a SILENT LOOP
  constructible within the current grammar — a sequence of resets/restores/
  replays where abandoned state is accepted and NO later open ever surfaces a
  typed refusal or fork? If yes, the deferral is unsound and that is a blocking
  finding.
- **Amendment interaction**: dedup (zero weight) × position (zero weight below
  boundary) × structural exemption — construct a journal exercising all three
  simultaneously and check the read's answer is right and the skip records
  complete. Categories multiplying is where weighting bugs live.
- **The healing story's edge**: a journal whose ONLY valid reset is the last
  line (boundary at tail — everything below decreed past); and a journal whose
  boundary reset is itself followed only by skipped lines. What does `at_least`
  read? Any path to an inflated or deflated bound?
- **Fixture order as frozen output**: the generator docstring says inserting a
  line into a reset-bearing fixture silently stales its `follows`. Is there any
  guard (generator-side or consumer-side) that catches a stale hand-edit, or is
  a corrupted-but-plausible vector expressible? If inexpressible only by
  discipline, say so — that may be an accepted residual, but name it.

## 5. Verdict format

Per-item PASS/FAIL + evidence. New findings: `S3I-L-<n>`, file:line, severity
(BLOCKING/NON-BLOCKING), concrete failure scenario. Then one line: **CONVERGED**
or **NOT CONVERGED** (with the blocking list).
