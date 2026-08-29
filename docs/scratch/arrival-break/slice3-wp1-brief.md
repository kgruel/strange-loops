# Slice 3 / WP1 impl brief — the head-attestation module

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice3-witness-minimum` @ `01M17S26ZC1JFC51VEVSG4ZA67` (ratified) —
the full design is `docs/scratch/arrival-break/slice3-design-proposal.md` (commit
1a29f200). **Your sections: §B (types, journal, serialization), §C (classifier +
refusal family), the §B/§C parts of §E's WP1 row.** Read them completely; they are the
contract. Deviations are reportable (finding fact + report), never silent.

## Scope

1. **`engine/arrival_head_attestation.py`** — imports stdlib + `arrival_contract`
   ONLY. The `arrival*` name auto-enrolls in Rule 18's glob ratchet; confirm
   architecture stays green with the module registered in `_SCAN_TARGETS`.
2. **The observation record** per §B: the full ratified `Head`, `kind` ∈
   bootstrap/advance/audit/trust-reset, `level` ∈ mint/first-contact/commit/
   descendant/full, `observed_at` — nothing else. Signed fields ABSENT, not empty.
   Serialization type string `arrival-head-observation` (never bare "attestation" —
   that vocabulary means signed row receipts in this codebase). JSONL journal, NOT the
   wire codec (the journal must stay readable when the store it witnesses cannot open).
3. **The journal** at `$XDG_STATE_HOME/loops/heads/<lineage>.jsonl` (lineage-keyed —
   the ruled home; honor `$XDG_STATE_HOME` with the standard `~/.local/state`
   fallback): append-only; read rules per §B — max-ordinal entry IS the cached head,
   first entry IS the bootstrap receipt, **trust-epoch scoping** (K, the equivocation
   check, and audit scope to the CURRENT epoch; pre-reset entries are evidence, not
   claims — the deadlock the proposal's own review caught).
4. **The pure classifier** `compare(known, presented, at_known) -> Outcome` per §C:
   seven rows — unchanged / advanced (proceed), rollback / same-height fork / rewrite /
   replacement (refuse), first-contact (proceed, permanently labeled TOFU). Outcomes
   are STRINGS the vectors will pin; exceptions are the module's own family.
5. **`AttestationRefusal` family, rooted OUTSIDE `ContractRefusal`** (arbiter ruling 1
   — applies the narrow-form ruling; do not join the contract root). The fork
   exception is `HeadFork` (the outcome string stays `same-height-fork`;
   `arrival_contract.SameHeightFork` is the adjacent replicate case, not yours).
6. **The transitional `bindings.jsonl`** (location→lineage binding closing
   wholesale-replacement detection) with its `DELETE IN SLICE 5` marker in a comment
   at the site (registry transitional-arm precedent).
7. Unit tests for all of the above, including the §D.4 store-absent split (no log +
   no journal → pre-genesis; no log + remembered head → refuse, never silent re-mint)
   at the classifier/journal level.

## Non-goals

No seam (WP3: BackendRegistry.open/AttestedLedger, bootstrap producer, audit producer,
staleness, trust-reset producer, the §0.4 lazy-reader fix). No conformance vectors
(WP2). Nothing signed — no sig/issuer/key_id/previous/attestation_id fields, no domain
strings. No scheduler. No journal compaction/retention. No `.vertex` grammar change.
No witnessing of jsonl/sqlite stores.

## Oracle (the gate re-runs from scratch)

1. Engine + architecture suites green; counts reconciled (baseline engine 2063+1s,
   architecture 99 — yours grow; account for every delta).
2. Import-closure test: a clean subprocess importing the module pulls neither sqlite3
   nor `engine.arrival` (the §B stdlib+contract-only claim, pinned the WP1-slice-2 way).
3. Mutation demos: (a) classifier — break the rollback arm (return proceed) → its
   test fails naming the outcome; (b) trust-epoch scoping — drop the epoch filter from
   the K read → the reset-deadlock test fails; (c) journal read rule — return the LAST
   entry instead of max-ordinal → its test fails. Each restored, diff clean.
4. `git ls-files` shows every new file committed.

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s3wp1 -b slice3/arrival-witness main`
  (you create the slice-3 wave branch `slice3/arrival-witness`; WP2/WP3 branch from
  your landed tip). Step 0: verify base includes 1a29f200; if behind, reset onto
  current main.
- Tests must not touch the real `$XDG_STATE_HOME` — isolate via env/monkeypatch tmp.
- Report AS YOU GO: `docs/scratch/arrival-break/slice3-wp1-report.md` on the branch.
  Loops emissions from MAIN checkout cwd, payload
  `agent=s3wp1-impl slice=3 wp=1 role=implementer` — NOTE: `finding` folds by
  `name=`, not `topic=`. Facts only; never stage `.loops/`.
- Commits conventional, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip, files, counts with deltas, mutation results,
  design choices one line each, deviations.
