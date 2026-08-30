# Sol review brief — arrival-break slice 3 / WP3, round 2 (per-WP, LOW)

Round 2, verifying the fixes for your r1 blocking findings S3WP3-L-1 (alias
first-contact bypass) and S3WP3-L-2 (trust-reset replay).

## Anchor

- Branch: `slice3/wp3-seam`, NEW tip `d86a580b` (fix at `f9839a26`, report at tip).
  Diff: `git diff 16ac9099...d86a580b` — 5 files: the two engine modules, their two
  test files, the WP report. NOTE a ruled scope deviation: WP1's module
  `arrival_head_attestation.py` is modified (the L-2 read-time fix site is
  `_epoch_of` and cannot live elsewhere — arbiter-ordered). Verify the WP1-module
  change is confined to: `_epoch_of` read-time validation, the reset record shape
  (`follows`), the factored line scan, and fixtures now binding their resets.
- Arbiter-applied fixes since your r1: NONE.
- Suites: engine per-package, architecture SEPARATELY. Real `$XDG_STATE_HOME`
  stays untouched (autouse isolation).

## The fixes' claims — verify each

1. **L-1 fix**: object-identity sweep fires ONLY when the presenting spelling has no
   binding of its own — live-stats each recorded binding, compares `(st_dev,
   st_ino)`, match ⇒ routed through that binding (LineageReplaced when lineage
   differs). Never records an inode; unstattable bindings skipped. Sits in the
   binding arm ahead of the journal read and before `_Earned` is minted — only ever
   refuses EARLIER, `_write` untouched; since the AST ratchet cannot see an ordering
   regression, a byte-compare test holds it. Unchanged opens still gather only
   `verify:open` (op-count asserted). Docstring narrowed: `canonical_location` no
   longer asserts identity; residual (distinct dev/ino aliases, e.g. two network
   mounts) documented.
2. **L-1 mutation demo** (fix committed first, tree byte-clean after revert): sweep
   reverted → 1 failed / 56 passed, the case-variant test — the alias spelling
   silently first-contacts. Re-run it.
3. **L-1 CI portability**: the construction test probes the filesystem's case
   behavior and skips WITH a record naming the portable test that covers the
   judgment; `match_identity` takes injected identities so newest-wins,
   unstattable-skipped, and absent-presenting are pinned on every platform. On this
   macOS worktree the construction test genuinely runs. Verify BOTH halves — and
   that test-only injection cannot leak into the production path (production uses
   live stats).
4. **L-2 fix**: reset record shape gains REQUIRED `follows` = predecessor journal
   entry's identity (deliberately NOT the deferred signed `previous`). Read-time
   validation in `_epoch_of` is load-bearing: a reset is honored only when its
   `follows` matches the entry actually preceding it, and the walk CONTINUES to an
   earlier valid boundary on rejection (rejecting a replay must not reject the
   reset it was copied from). Mismatch → the EXISTING skip-with-record channel,
   never a refusal. Append-time guard in `trust_reset()` too. No compat arm.
5. **L-2 mutation demo**: read-time validation reverted → 4 failed / 154 passed,
   your repro leading, K measured directly = 5 on a journal that reached 8 (your
   number). Re-run it. Also re-run your OWN r1 repro against the fixed tip: K must
   stay 8 and the replay must land as a skip record.
6. **The near-miss (impl-disclosed, deserves your adversarial eye)**: append-time
   binding first went through `read_journal`, which REFUSES an equivocating journal
   — bricking the recovery ceremony exactly when it is needed; an existing
   equivocation test caught it. Fixed by factoring the line scan so `last_entry`
   reaches entries WITHOUT the judgment built on top. Assess: does any other
   caller now reach entries judgment-free who shouldn't? Is `last_entry`'s
   judgment-bypass scoped to exactly the append path?
7. Counts: engine 2222 passed + 1 skipped (+13 over r1's 2209), architecture 99,
   ruff clean, `git diff --check` clean.

## Try-to-defeat seeds

- **Two-line replay**: copy BOTH an old predecessor entry AND its old reset from an
  earlier journal state, append the pair — the reset's `follows` now matches its
  actual predecessor. Walk what effective K becomes. Is any SILENT epoch
  resurrection expressible by benign sync machinery (the gruel.network combine
  case), or does the re-appended predecessor change the honest bound such that
  every outcome stays typed refusal/degradation?
- **L-1 skip path**: the sweep fires only when the presenting spelling has NO
  binding. Construct a presenting spelling that HAS a binding of its own (stale,
  same-store-bound-earlier, deleted-store) — any silent acceptance route around
  LineageReplaced left?
- **Genuine second reset**: an operator legitimately resets twice (same boundary,
  later time) — still honored? A legit reset must not be rejected as a replay.

## Verdict format

Per-fix PASS/FAIL + evidence. New findings: `S3WP3-L-<n>` continuing your
numbering, file:line, severity, concrete failure scenario. Then one line:
**CONVERGED** or **NOT CONVERGED** (with the blocking list).
