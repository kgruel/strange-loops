# Slice D run plan — mixed-family pipeline (gemini modification)

Date: 2026-08-20. Arbiter: Claude (Fable session). Ruled by Kyle: slice D
returns to `feat/arrival-libs` (same branch, pre-merge), executed through the
impl-pipeline with cross-vendor role routing.

## Role routing (this run)

The Gemini legs run through the Antigravity CLI (`agy`), per
`~/Code/skills/delegating-to-antigravity` + `antigravity-impl-pipeline`
(the raw gemini CLI's oauth tier is EOL'd — receipted in explorer-stderr.log).
Contract smoke test passed 2026-08-20 21:3x (worktree + tip echoed back).

| Role | Engine | Invocation |
|------|--------|-----------|
| Explorer | `agy gemini-3.7-flash-low` | `--sandbox --dangerously-skip-permissions --add-dir=<explore-wt>`, locatable questions only, JSON findings via exploration schema |
| Design synth / planning | Claude Opus subagent | `Agent` with `model: opus` |
| Implementer | `agy gemini-3.7-flash-high` | own worktree + branch, scope fence, break/restore proofs against committed fixes |
| Gate | Claude Opus subagent | independent; re-runs oracle from scratch; `git ls-files`; pointer branch `slice/D-gate` |
| Per-round review | codex `gpt-5.6-sol`, LOW effort | `codex exec -m gpt-5.6-sol -c model_reasoning_effort=low` — cross-family holds (gemini implements, codex reviews) |
| Remediation / apply | Claude Opus subagent | judgment fences; arbiter holds dispositions |
| Final PR review | codex `gpt-5.6-sol`, HIGH effort | whole-branch brief, verdict table, CONVERGED call (replaces the skill's gemini-3.1-pro readiness round — keeps final review cross-family from the build fleet) |
| Arbiter | this session | all seams, rulings, convergence |

Gate and remediation default to Opus (unassigned by Kyle; gate independence
from the implementer's family is the point, and the subagent-routing rule
already says opus for gate/apply). agy and codex are Bash-spawned; Claude
launches carry explicit `model:` every time.

agy mechanics (from the two skills, non-negotiable): flags precede `-p`;
`--add-dir` + `cd`-prefix instruction in every prompt; `--sandbox` always
(blast radius, NOT read-only — sweep `git status --short` after every run);
explorers share the throwaway detached worktree `~/Code/loops-wt/sliceD-explore`;
scratch at `~/Code/loops-wt/sliceD-scratch`; every stdout tees into this
directory as a receipt; prompts carry EXECUTE-YOURSELF, scope fence with
escape valve, one-shot clause, and the vocabulary ratchet verbatim (agy has
zero ambient loops context).

## Scope (plan:arrival-libs-slice-D @ 01M090RAN7Z9FMZX0S5KSEZ322)

1. **Audit** (CX-DC-01): `canonical_audit.py` offset/prefix custody model →
   arrival, including default L1 (`_check_offset`, `_suffix_unindexed`,
   `_check_last_line`); jsonl comparison becomes set membership.
2. **Witness** (CX-DC-02): `WitnessPosition` re-keys rowid →
   `(arrival_lineage, ordinal)`.
3. **Seals** (CX-DC-03): seal windows re-base on arrival coordinates.
4. **CX-BR-02 rider**: admission signature verification is new code in D —
   lands here or the proposal carves it explicitly with a fresh receipt.
   It has rolled once already; it does not roll silently again.

Done-criteria (verbatim from Plan §3D): `preflight.py` untouched;
`WitnessAggregateUnsupported` and the A10 cross-store lineage refusal stay
verbatim; federated-read vs admission distinction protected in the store API.

Gate item: audit vectors over a deliberately rebuilt AND shuffled index —
L1 must answer from arrival, not byte offsets.

## Sequencing

Stage 0 first, hard: the seal re-base (commitment-format change) and the
witness re-key (public coordinate) are ratify-gate-one-level-down decisions.
Explorer survey → Opus design proposal → **Kyle ratifies** → implementation.
Gemini writes no code before ratification.

Convergence precondition (process fix from the r3 conformance round): the
final sol-HIGH brief carries the slice roster explicitly — this run models
the roster check that would have caught D's silent drop.
