# Slice 3 / WP3 impl brief — the compare-on-open seam

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice3-witness-minimum` @ `01M17S26ZC1JFC51VEVSG4ZA67` (ratified);
design §D + §E's WP3 row + §0.4 (slice3-design-proposal.md). WP1's landed module at
`9ed893fe` on `slice3/arrival-witness` is your substrate — read its report's HANDOFF
sections (both rounds) and the finding folds; where module and proposal disagree, the
module + folds are the truth. Deviations are reportable (finding fact + report),
never silent.

## Scope (§D + §E WP3 row + the ruled additions)

1. **`AttestedLedger`** wrapping in `BackendRegistry.open` — ALWAYS ON, no flag (§D.1;
   a configuration switch for a safety property is receipt_mode's rejected shape).
   Compare-on-open consumes the journal via WP1's read rules; **journaling on
   commit** (§D.3): a successful append's `Commit.before/after` is the descent
   evidence, journaled as an ADVANCE entry — the O(1)-unchanged-open design.
2. **The §0.4 lazy-reader fix** (arbiter-ruled into this WP): `_open_file_backend`
   eagerly builds `FileQuery`→`StoreReader`, which raises on a missing index — a
   store with no projection cannot open through the registry, blocking `mint` and
   contradicting the ratified F2 carve-out. Build the reader lazily,
   adapter-confined, no contract text.
3. **Bootstrap receipt producer** (first-contact journaling — slice 4's sidecar calls
   this at migration; slice 6 exits on its presence). **Audit producer** (§D.5: the
   full chain-plus-projection audit, journaling an AUDIT entry with the covered
   head). **Staleness reporting** (the open path only REPORTS staleness — no
   scheduler). **Trust-reset producer** (the operator ceremony entry, opening a new
   epoch).
4. **Bindings canonical form** (WP1 handoff gap, named): `bindings.jsonl` matches
   location as an exact string — the seam must pass ONE canonical form (the
   descriptor's resolved location) or a symlinked/relative path manufactures a first
   contact through the hole the binding closes. Decide and pin the canonicalization.
5. **The `IndeterminateComparison` posture** — the WP's flagged design point, YOURS
   to choose with rationale (the module raises it on incomplete reads; the store
   cannot testify to what this machine previously accepted — only journal repair or
   the trust-reset ceremony resolves it): does the seam surface it as a refusal
   demanding an operator decision, or proceed under an EXPLICITLY LABELED
   degradation? Choose, justify against the witness-protocol's never-silent rule,
   and flag the choice prominently for the gate.
6. **Composition-boundary hardening** (sol r1 seed, carried): `unaccounted_heads`'
   injected lookup — the seam supplies it; a fabricated-Head lookup can lie, so the
   seam's lookup must come from the verified walk/`head_at`, stated in the report.
7. **`.at_least` is ROLLBACK-ONLY; `HeadUnreadable` answers nothing** — the seam
   honors both (WP1's handoff, now explicit).

## Review lenses (apply, don't cite)

- Two-valued classifiers: wherever the seam collapses outcomes into proceed/refuse,
  ask for the third honest answer.
- Closed-set names: if a seam name enumerates causes, ask whether the set grows.
- WP1's write-path lesson: a read rule closed can be reopened by a write path — your
  journaling-on-commit writes to the journal WP1 reads; the gate will byte-compare a
  concurrent-writer scenario (WP1's own suggestion), so build for it.

## Non-goals

No module changes beyond consuming its API (behaviors you believe wrong are FINDINGS).
No vectors (WP2 runs in parallel — no file overlap: you touch engine/arrival_registry.py,
engine/arrival_file_backend.py, new seam code + tests; WP2 touches spec/ + its consumer
test). No scheduler, nothing signed, no store migration, no consumer rewiring beyond
the seam. No `.vertex` grammar.

## Oracle (the gate re-runs from scratch; §E WP3's eight items condensed)

1. **The item that matters** (§E): truncated log + stale-ahead index → typed refusal
   WITH THE INDEX BYTES UNCHANGED afterward — detection precedes repair.
2. Compare-on-open classifies correctly against real stores: unchanged (O(1) — prove
   no full walk on the journaled-commit path, e.g. by op-count or trace), advanced,
   rollback refusal, fork refusal, first contact (bootstrap), replacement (bindings).
3. Journaling on commit: append → journal entry appears; next open takes the O(1)
   path. Concurrent-writer byte-compare: two processes appending while a third opens
   — journal stays parseable, comparisons stay sound.
4. The §0.4 fix: minted-log-no-index opens through the registry (ledger usable, mint
   reachable); query materialization behavior per the F2 carve-out; the WP4 finding's
   pinning test updated honestly.
5. IndeterminateComparison posture: pinned by test per your choice; the never-silent
   property demonstrated.
6. Mutation demos: (a) drop the journaling-on-commit → the O(1)-path test fails;
   (b) pass a non-canonical location to bindings → the replacement test fails;
   (c) make the seam swallow IndeterminateComparison → its test fails. Restored clean.
7. Engine + architecture suites green; counts reconciled; `git ls-files` clean.

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s3wp3 -b slice3/wp3-seam 9ed893fe`
  (step 0: verify merge-base = 9ed893fe).
- Report AS YOU GO: `docs/scratch/arrival-break/slice3-wp3-report.md`. Loops emissions
  from MAIN checkout cwd, payload `agent=s3wp3-impl slice=3 wp=3 role=implementer`
  (finding folds by name=). Facts only; never stage `.loops/`. Tests never touch the
  real `$XDG_STATE_HOME`.
- Commits conventional, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip, files, counts, mutation results, design
  choices one line each (the IndeterminateComparison posture FIRST), deviations.
