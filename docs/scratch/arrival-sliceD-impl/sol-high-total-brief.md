# TOTAL COMPLETION CHECK — codex sol HIGH — slice D, entire arc

## 1. Anchor
Repo: loops monorepo, branch feat/arrival-libs. Diff under review:
git diff 560710b8...b92c40f3 — the COMPLETE slice D arc, 72 commits (five work
packages + gate reports + fix rounds + simplify pass). Receipts:
docs/scratch/arrival-sliceD-impl/ (briefs, stdout logs, site inventories),
GATE-WP*-REPORT.md files on the merged gate branches, per-WP *-REPORT.md files.

## 2. Design contract — what the code must honor
Ratified: plan:arrival-libs-slice-D (2026-08-22) + decision:design/
arrival-sliceD-design-ratified; full text docs/scratch/arrival-sliceD/
design-proposal.md (r6, review-CONVERGED). The five decisions:
- D0: arrival_ordinal/arrival_seq NOT NULL + table-level UNIQUE on facts/ticks;
  mode-aware one-transaction table-rebuild migration (rowid-preserving,
  dependency-closed view/trigger replay); structural verifier on both marker
  paths; marked+incomplete refuses, never auto-rebuilds; rederive route is
  non-validating (validate=False).
- D1: WitnessPosition re-keyed (arrival_lineage | None, ordinal with -1 empty
  prefix, record-granular cutoff); WitnessAxisMismatch same-path refusal;
  NON-NEGOTIABLE: WitnessAggregateUnsupported + A10 raise sites and message
  strings byte-identical; durable_handle output unchanged.
- D2: seals re-based on (ordinal, seq); NON-NEGOTIABLE: signed bytes untouched
  (_tick_envelope, _fact_row_hash, commitment hashes byte-identical;
  window_start/fact_cursor remain fact ids); rowid only as row address;
  cursors are (ordinal, seq) PAIRS (W2-1 ruling — naive ordinal cursors drop
  mid-batch rows).
- D3: L1 audit answers from arrival agreement with EXACT bounded work
  (healthy=1 verified record, K-behind=1+K, anchor-failed=1 with NO walk,
  deep=N); every Check a location claim, no verdict words, no invented
  magnitudes; beyond_offset fully dissolved (absence-pinned).
- D4: key_registry selective walk (registry-forming envelopes verified,
  ordinary NEVER); merge verifies post-dedup admitted fact rows against
  fact_commitment_hash under source key validity; default path byte-identical;
  legacy source = explicit no-claim.
- Scope law: diff outside libs/engine+libs/store confined to the receipted
  exceptions: fold.py baseline consumer, commands/store.py (audit dispatch arm
  + the second narrow rowid-ordering exception), probe.py beyond_offset
  consumer sweep, apps tests fixture conformance, four conformance call-site
  renames. preflight.py: exactly one docstring sentence.

## 3. Verification history — what to re-verify vs trust
Every WP went through: opus gate (fresh oracle re-derivation, 2-5 rounds each,
independent break/restore) + codex sol-low pass check (1-3 rounds each) to
PASS. The simplify pass had its own sol re-review (PASS, zero findings).
Cross-family held throughout (Gemini flash implemented WP-1/3/4 + fixes; opus
implemented WP-2-completion/WP-5 during a quota outage; opus gated; codex
reviewed).
ARBITER-APPLIED COMMITS (weakest independent coverage — re-verify these
first): R5-1 test parametrization; SOL-WP1-02 origin-'u' tightening
(12ae9042); W5-1 index derivation (f435328a, one pre-commit near-miss
disclosed and sol-verified).
Fix-round commits are the second-richest hunting ground: rounds 2+ of every
review in this arc were dominated by holes in round-1 fixes (G-1 circular
refusal, SOL-WP1-02 evasion of SOL-WP1-01's fix, W4-1's false magnitude).

## 4. Your job at HIGH effort
The full-branch adversarial pass that per-package review structurally cannot
do: cross-package seams (witness x seals x audit x admission all keying the
same coordinate — are their sentinel/boundary conventions actually identical,
e.g. -1 vs (-1,0) vs ordinal-0-genesis across D1/D2/D3?); the ruled-deviation
paper trail (does any code contradict a ratified ruling?); post-review fix
commits; the arc's own oracles (permuted harness, quantity seams) — can you
construct an evasion the gates missed? Empirically verify where possible —
you have workspace-write; build stores, run probes, run targeted tests.

## 5. Verdict format
Per-finding: SOL-HIGH-NN, severity, file:line, claim, evidence (pasted
command output where empirical). Then a verdict table over sections 2's five
decisions (PASS/FAIL each) and an overall CONVERGED / NOT_CONVERGED call.
One response.
