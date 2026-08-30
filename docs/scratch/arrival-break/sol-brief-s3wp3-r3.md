# Sol review brief — arrival-break slice 3 / WP3, round 3 (per-WP, LOW)

Round 3. Verifies the fixes for your r2 findings S3WP3-L-3 (ceremony unwired) and
S3WP3-L-4 (two-line replay), PLUS a third fix for a finding the round surfaced:
S3WP3-L-5, the replayed-advance acceptance vector — the arbiter refuted the impl's
"refusal-side, never a way in" classification by construction (a replayed historical
advance sets K to a genuine abandoned head; a store restored from the pre-reset
backup presents it exactly → UNCHANGED, which verifies nothing by design → the
ceremonially-abandoned state opens silently).

## Anchor

- Branch: `slice3/wp3-seam`, NEW tip `886d5619`. Diff: `git diff d86a580b...886d5619`
  (5 commits). Unverified fixes, by commit:
  - `621120a3` — L-3 (trust_reset wired to judgment-free `last_entry`, now
    `(position, entry)`) + L-4 (`follows` = physical-line-position + identity;
    TOCTOU answered by read-back raising `TrustResetNotHonored` — no append lock
    exists by design).
  - `639097df` — L-5: read-time byte-duplicate skip. A line byte-identical to an
    earlier line is a re-assertion → existing skip channel, new reason. Per-line,
    type-agnostic, order-agnostic, read-side only. ONE CARVE-OUT: headers exempt
    (no head claim; a doubled header is the create-race artifact WP1 tolerates —
    deduping one would turn a tolerated race into a permanently weakened read).
  - `470e5e66` — repairs the impl's own position-only test: the mutation demo
    caught it hollow (its construction bound a reset to an empty journal, so BOTH
    halves mismatched — it passed against a build with no position check at all).
    Now identity matches on both sides, only the line moves, and the test asserts
    identity-equality itself so a non-isolating construction fails loudly.
  - `3cc1b047`, `886d5619` — report commits; the second flips the divergence
    narrative (K=10 claim) to the ruling's truth.
- Arbiter-applied fixes since r2: NONE.
- Suites: engine per-package, architecture separately. Real `$XDG_STATE_HOME`
  untouched (autouse isolation). Claimed counts: engine 2233 + 1 skipped, arch 99.

## The fixes' claims — verify each

1. **L-3**: current-epoch equivocating journal → ceremony succeeds and appends.
   Mutation demo reverts THE CALL SITE (the r2 hole was helper-pinned-caller-
   unwired) → 3 failed, led by the ceremony-succeeds test. Re-run it.
2. **L-4**: `follows` = (physical line ordinal, identity) — physical lines counted
   over every line INCLUDING skipped ones (pinned by a test with an unreadable line
   between reset and predecessor). Read-back: `trust_reset` verifies its own entry
   is honored, raises `TrustResetNotHonored` otherwise. Mutation demo: position
   half dropped → 1 failed, the FRESH-BYTES construction (post-`470e5e66` this is
   the test that genuinely isolates position — confirm it now does; its first
   version was hollow).
3. **L-5**: dedup reverted → 9 failed, sharpest being
   `test_a_restored_abandoned_backup_does_not_open_unchanged` failing with "the
   abandoned state opened unchanged". Re-run; confirm the acceptance vector is
   dead on the fixed tip (construct it independently if you prefer).
4. **Consequence reconciliation**: your r2 two-line repro now yields K=8 with TWO
   skip records (dedup catches both copied lines before position-binding fires);
   the divergence comment, finding pointer, and 10-assertion are updated, not
   left contradicting. Verify no test still encodes the K=10 world.
5. **Collision direction**: the injected-collision test constructs byte-identical
   lines for two GENUINE independent events and asserts skip → K reads low → the
   presenting store takes the ADVANCED branch and pays a verified walk.
   Verification-side, never acceptance. Re-run.
6. **Fixture honesty**: two impl fixtures modeled a post-reset advance as
   byte-identical to a pre-reset one — a shape no real store produces (a restored
   store re-advances through different history). The dedup gate surfaced them;
   they are corrected. Spot-check the corrections model reality.
7. Counts: engine 2233+1s (+4 over r2's 2229 claimed... verify the actual delta
   from 886d5619), arch 99, ruff clean, `git diff --check` clean.

## Try-to-defeat seeds

- **The headers-exempt carve-out**: the impl exempted header lines from dedup on
  its own judgment (arbiter accepts provisionally — YOUR check is the
  verification). A doubled header is a tolerated create-race artifact — but can a
  REPLAYED header (copied to a later position, possibly from a foreign journal)
  do damage the exemption now lets through? Headers claim no head — verify that
  is true at the parse layer, not just in prose.
- **Foreign-journal concatenation with ADVANCES**: cross-lineage lines are NOT
  byte-duplicates of anything local, so dedup never fires. Walk what a foreign
  advance line does in this lineage's journal file: does it parse into K at all?
  Whatever the outcome, it must be refusal-side/typed — any silent path into K
  from a foreign line is a finding.
- **Truncate-then-replay**: truncation realigns positions, so replay after
  truncation should still be expressible — CONFIRM it reproduces and lands within
  the documented residual (journal-rollback territory, signed grammar the named
  upgrade). A surprise here — e.g. it produces acceptance beyond the documented
  bound — is a finding; mere reproduction is the residual working as documented.
- **TOCTOU race**: an automated append landing between the ceremony's tail-read
  and its append → the fresh reset's position claim is stale → skipped →
  read-back raises `TrustResetNotHonored`. Verify the operator can NEVER believe
  a voided ceremony succeeded.
- **Dedup evasion within the threat model**: the model is literal replay of
  existing bytes by benign machinery. Anything byte-modified is forgery (signed
  grammar territory) — but check the boundary is honest: does any BENIGN
  mechanism in this codebase rewrite journal lines in transit (encoding
  normalization, trailing whitespace, JSON re-serialization) such that a "replay"
  arrives byte-different and sails past dedup?

## Verdict format

Per-fix PASS/FAIL + evidence. New findings: `S3WP3-L-<n>` continuing, file:line,
severity, concrete failure scenario. Then one line: **CONVERGED** or
**NOT CONVERGED** (with the blocking list).
