# Sol review brief — arrival-break slice 3 / WP1 (head-attestation module), round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-3 WP1 — the head-attestation module, the
custody-memory primitive slices 4 and 6 build against. Review the WP diff adversarially
for correctness against the design contract. You review and report — no fixes, no
commits. Run tests/scripts to verify claims empirically.

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice3/arrival-witness`, tip `fbdc5770` (10 commits over main `4c4bf148`).
- Diff spec: `git diff 4c4bf148...fbdc5770`. Four files: the module
  (`engine/arrival_head_attestation.py`), its test file (91 tests), the Rule 18
  enrollment, the WP report.
- Suites: engine per-package; `tests/architecture` SEPARATELY (running them in one
  pytest process yields cross-suite pollution failures even on clean main — verified
  by the gate on the base commit).

## 2. Design contract (what the code must honor)

From `design:arrival-break-slice3-witness-minimum` (ratified,
`01M17S26ZC1JFC51VEVSG4ZA67`), §B/§C of slice3-design-proposal.md, and the amended
rulings on the finding folds (grep .loops/data/project.jsonl for
`s3wp1-mid-file-journal-damage-unstated` and `s3wp1-gate-all-entries-unreadable-silent-tofu`
— read every entry; both rulings were amended mid-WP with receipts):

1. Module imports stdlib + `arrival_contract` ONLY. Lineage-keyed append-only JSONL
   journal at `$XDG_STATE_HOME/loops/heads/<lineage>.jsonl` (`~/.local/state`
   fallback; `LOOPS_HOME` deliberately ignored).
2. Observation record: full `Head` + kind(bootstrap/advance/audit/trust-reset) +
   level + observed_at; signed fields ABSENT; type string `arrival-head-observation`.
3. Read rules: max-ordinal within the RESET-INCLUSIVE trust epoch; tolerate-and-report
   damage ANYWHERE (no positional torn-tail distinction survives);
   `JournalRead.known` is a THREE-state union — `EstablishedHead` (complete read) /
   `HeadLowerBound(at_least)` (losses recorded; ROLLBACK-only) / `HeadUnreadable`
   (content present, nothing readable; NO ordinal field; answers nothing) —
   `established_head()` is the only path to a compare argument and RAISES
   `IndeterminateComparison` on both weakened states. First-contact TOFU requires no
   surviving-or-skipped content claims (empty and header-only journals qualify).
4. Pure seven-row classifier `compare(known, presented, at_known)`; string outcomes;
   `AttestationRefusal` family rooted OUTSIDE `ContractRefusal` (arbiter ruling);
   `HeadFork` distinct from `arrival_contract.SameHeightFork`.
5. Headers identified by their `type` string alone (later builds adding fields stay
   recognized; a different type string is skipped+reported); any other kindless dict
   is a recorded skip. Write path: O_APPEND everywhere including the exclusive
   create; line-boundary guard; a crashed creator cannot strand a headerless journal.
6. Transitional `bindings.jsonl` with DELETE IN SLICE 5 marker; "bindings" reserved
   lineage name.

## 3. Unverified fixes

None arbiter-applied. All fixes this WP were impl-made and gate-verified across two
gate rounds (report + gate report carry the full trail).

## 4. Prior review state (do not re-litigate; flag if unsound)

The WP's full review arc, all receipted: arbiter mid-file ruling → impl CONDITIONAL
STOP refuted the mechanism (journal writes do not ascend in file order; [90,92,91]
demonstration) → amended ruling (lower bound, unignorable by construction) → gate
round 1 FAIL, 2 BLOCKING (kindless-dict absorbed as header with no skip recorded;
all-entries-unreadable falling through to silent TOFU via pure version skew) → both
fixed at the level raised → gate round 2 PASS with the gate re-running its own
demonstrations and its adversarial shortcut attempt against all three states. Nine
mutation demos total, all gate-re-run. Known residual, correctly out of scope:
substituting a well-formed header for an entry ≡ line deletion, closeable only by the
deferred signed grammar (observation:design/signed-attestation-grammar-scope-seeds).

## 5. Seeded review targets

- The journal writer under concurrency you can construct: two processes appending to
  one journal (real flock-free racing) — does O_APPEND + the line-boundary guard
  actually hold on your filesystem, and can a lost race still produce interleaved
  bytes the reader then misclassifies?
- `observed_at` is caller-supplied everywhere (no clock reads) — is there any path
  where two entries with identical ordinals but different observed_at confuse the
  max-ordinal rule or the equivocation check?
- The equivocation check itself: same ordinal, different record_hash, both readable —
  construct it and verify the outcome is the typed refusal, not last-writer-wins.
- `unaccounted_heads(epoch, at_ordinal)` with the injected lookup: can a hostile
  lookup (returning wrong records) make it claim accounted-for heads that aren't?
- Serialization round-trip: an entry written by this build and re-read — field-exact?
  And unknown FIELDS on a known kind (choice 9: preserved by construction) — verify
  a rewrite path never materializes that would drop them (there should be no rewrite
  path at all — confirm append-only holds everywhere).

## 6. Verdict format

Per §2 item: PASS/FAIL + evidence. New findings: `S3WP1-L-<n>`, file:line, severity
(BLOCKING/NON-BLOCKING), concrete failure scenario, evidence. Then one line:
**CONVERGED** or **NOT CONVERGED** (with the blocking list).
