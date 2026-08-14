# Sol review brief — libs-handoff-wave, round 1

## 1. Anchor

- Repo: this checkout (strange-loops monorepo), branch `libs-handoff-wave`.
- Diff spec: `git diff main...HEAD` (56 commits: 8 implementation slices, 8 gate reports, merge commits, one arbiter fix).
- Review the FULL branch diff, not per-slice. Cross-slice seams and post-review fix commits are your highest-yield zones.

## 2. Design contracts (the code must honor these)

**Primary contract**: `docs/scratch/libs-handoff-wave/LIBS_CHANGES.md` (Sol's own
libs-handoff spec — P0 ceremonies/plan-apply/recovery, P1 query/attestation/
admission/strict/kdl-mutation/probe/preflight). Ratified as
`design:architecture/libs-handoff-scope` with these arbiter modifications:
- bounded-fact-query specs against the SHIPPED 0.8.0 temporal-cursor contract
  (WitnessPosition, rowid witness axis), NOT the FactCursor sketch. A3:
  fact ids are NEVER ordered (mixed uuid4/ULID eras).
- strict ruling (`decision:design/strict-enforcement-at-engine-receive`):
  enforced at engine receive, typed rejection, explicit bypass, non-strict
  behavior preserved VERBATIM (stored, raw-readable, folds when later declared).

**Encoding contract** (NON-NEGOTIABLE lines): `docs/scratch/libs-handoff-wave/s1a-encoding-proposal.md`, ratified as `design:architecture/jsonl-declaration-ceremony-encoding`:
- Genesis is one plain fact line, NO new grammar; all CAS checks before any log byte.
- Multi-row edit = ONE `"t":"batch"` line, rows ≥2, verbatim payload TEXT per row,
  no ticks/nesting/dup-id/extra keys. A 1-row batch must NEVER be written.
- D1: same-ts is a ceremony rule (audit_deep asserts for all-`_decl.*` batches),
  NOT a codec rule.
- Stale expected_head leaves the LOG byte-identical (index may lawfully converge pre-CAS).
- Open-time detection stays two cheap checks; batch expansion bounded by ceremony size.
- The sqlite index remains a pure derivation of the canonical log.
- Golden fixtures in `libs/engine/tests/fixtures/jsonl/` are the Go cross-language
  byte contract — changing their bytes is a contract change, flag it.

**Attestation contract**: receipt attestation populated from the COMMITTED ROW,
never configuration inference (write-receipt-vs-temporal-query).

## 3. Unverified fixes (re-verify these empirically where possible)

Every fix below was applied AFTER the slice's last independent internal review,
except where noted:

| Commit | What it answers | Verification status |
|---|---|---|
| arbiter fix `fix(engine): probe log corroboration decodes batch lines` (single commit on wave, post-S7-re-gate) | S7 re-gate finding 1b: probe used deserialize_row, false "does not decode" on batch-first logs | Mutation-verified by arbiter only — NO independent gate re-ran it. Highest-priority re-verify. |
| `b451761f` (S1b) | Gate blocker: gitignore-swallowed golden fixtures | Gate re-verified from clean bytes |
| `03f4d36f` (S5) | Gate 5d: allow-mode unpinned | Gate re-verified with own mutation |
| `3daaf563` (S4) | Gate 5c: CLI mark resurrected config inference | Gate re-verified incl. own mutant |

Known dispositions to NOT re-litigate (already ruled, receipts in gate reports):
- S5 aggregate RAISES `WitnessAggregateUnsupported` vs your "typed result" wording —
  deliberate, matches shipped 0.8.0 aggregate `at=` precedent. CLI must catch-and-render (open item, noted).
- S1b genesis crash-recovery deviates from the encoding proposal's matrix row:
  retry → AmbiguousGenesis → explicit adopt_lineage (proposal row was stale against
  the 71de5111 anti-hijack ratchet). Ruled JUSTIFIED.
- S2 report's "S3 CredentialProvider" cite is wrong (it's the VertexHandle arc's S3,
  d22f614d); mechanism verified byte-for-byte. Documentation error only.
- Pre-existing, out of scope: store merge/receive bypasses strict (transport ≠
  emission; thread:strict-does-not-gate-transport), receive_as stale-_ast F1
  (thread:receive-as-stale-ast), intent-gate TOCTOU (thread:intent-gate-toctou).

## 4. Focus zones (where slice review structurally cannot see)

- Cross-slice seams: S1b batch grammar × S7 probe/preflight; S3 receive_as ×
  S4 receipt threading; S2 ceremony orchestration × S1b store ceremonies × S3
  admission; S5 pagination × S1b ceremony receipt-groups (witness allow-mode).
- The arbiter's own fix (probe corroboration) — constructed evasions welcome.
- Anything the gates' independent oracles share as a blind spot with the
  implementations (both are Claude-family).

## 5. Verdict format

Per finding: id, file:line, severity (blocker/major/minor/note), claim,
empirical evidence (run it where possible), suggested fix direction.
End with an overall CONVERGED / NOT CONVERGED call: CONVERGED means zero
new findings at blocker/major severity and you judge the branch honors the
contracts above.
