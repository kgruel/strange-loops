# Slice 3 / WP2 impl brief — the comparison conformance family

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice3-witness-minimum` @ `01M17S26ZC1JFC51VEVSG4ZA67` (ratified);
design §C + §E's WP2 row (slice3-design-proposal.md). WP1's landed module is your
substrate: `engine/arrival_head_attestation.py` at `9ed893fe` on `slice3/arrival-witness`
— read its report (`slice3-wp1-report.md`) and the finding folds named below; the module
went through four sol rounds and two gate rounds, and several of its behaviors are
NEWER than the design doc. Where module and proposal disagree, the module + finding
folds are the truth (the rulings amended the design with receipts). Deviations are
reportable (finding fact + report), never silent.

## Scope

1. **The `comparison` vector family** in `spec/conformance/vectors/comparison/`, built
   at the replicate tier (the strongest existing pattern —
   `test_conformance_replicate.py`'s consumer + `VECTOR_INVENTORY` exact two-way
   equality with what's on disk + a generator under `spec/conformance/`).
2. **Coverage** (§E WP2 row): the plan's three named refusals (rollback / same-height
   fork / rewrite) plus replacement, unchanged, advanced, first contact, and
   equivocation. Vectors pin outcome STRINGS (`.value`), never exception types
   (language-neutral — the replicate family's own stated reason).
3. **Behaviors your vectors MUST encode from the finding folds** (each has a fold in
   .loops/data/project.jsonl — read them):
   - `s3wp1-epoch-scope-is-reset-inclusive`: the trust epoch INCLUDES the reset entry
     — a journal ending at the reset compares against the reset head (unchanged, not
     first-contact).
   - The amended mid-file ruling (`s3wp1-mid-file-journal-damage-unstated` fold): an
     incomplete read yields a LOWER BOUND — sound for rollback below the bound,
     refuses the proceed answers (`IndeterminateComparison`). If the family covers
     journal-read scenarios, encode the bound semantics, not refusal-of-the-file.
   - Gate stale-oracle note: headerless-with-readable-entries = BOUND, not a refusal.
   - `s3wp1-gate-all-entries-unreadable-silent-tofu` fold: content-present-nothing-
     readable declines every comparison; first contact requires no surviving-or-skipped
     content claims.
   - The three-way header classification (`s3wp1-sol-l1...` fold): type+kind =
     unclassifiable (skipped, named), never absorbed, never refuses the file.
4. **Family-vector shape**: your design point — decide whether the family's inputs are
   (known-state, presented-head) pairs only, or full journal fixtures exercised
   through `parse_journal_lines` (pure, raw lines in). The finding-fold behaviors
   above argue for at least SOME journal-fixture vectors; justify the split in the
   report.

## Review lenses (from this slice's own receipted observations — apply, don't cite)

- `observation:practice/two-valued-classifiers-lie-in-one-direction`: wherever your
  vector schema forces a binary answer, ask what the third honest answer is.
- The closed-set naming lesson (WP1 sol r3/r4): if a family or field name enumerates
  causes, ask whether the set can grow.

## Non-goals

No module changes (any behavior you believe wrong is a FINDING, not a fix). No seam
(WP3). No signed grammar. No new outcome strings.

## Oracle (the gate re-runs from scratch)

1. All vectors green through the consumer; `VECTOR_INVENTORY` exact both directions
   (drop one fixture → fails naming it; add a stray → fails unclassified).
2. Mutation demos at the module level, run through the VECTORS: (a) break the
   classifier's rollback arm → the rollback vectors fail; (b) break reset-inclusive
   epoch reading → the reset vectors fail; (c) weaken the incomplete-read decline
   (established_head returns despite skips) → those vectors fail. Restored clean each
   time.
3. Engine suite green; counts reconciled (baseline 2158+1s, +your consumer tests).
4. `git ls-files` shows every vector JSON committed (the gitignore trap).

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s3wp2 -b slice3/wp2-vectors 9ed893fe`
  (step 0: verify merge-base with slice3/arrival-witness = 9ed893fe).
- Report AS YOU GO: `docs/scratch/arrival-break/slice3-wp2-report.md`. Loops emissions
  from MAIN checkout cwd, payload `agent=s3wp2-impl slice=3 wp=2 role=implementer`
  (finding folds by name=). Facts only; never stage `.loops/`.
- Commits conventional, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip, files, counts, mutation results, design
  choices one line each, deviations.
