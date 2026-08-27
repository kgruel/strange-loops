# WP-1 pass check — codex sol LOW — slice D, D0 (the projected arrival coordinate)

## 1. Anchor

Repo: this checkout (loops monorepo). Branch under review: `slice/D-wp1`.
Diff spec: `git diff 560710b8...slice/D-wp1` (exclude `WP1A-REPORT.md`,
`WP1A-FIX-REPORT.md`, `WP1B-REPORT.md`, `WP1B-FIX-REPORT.md` — implementer
receipts, not product). Commits: 6 (WP-1a impl, gate-fix, WP-1b impl + report,
G-1 fix + report).

## 2. Design contract

Ratified: `plan:arrival-libs-slice-D` (status ratified 2026-08-22) +
`decision:design/arrival-sliceD-design-ratified`; full text
`docs/scratch/arrival-sliceD/design-proposal.md` §D0. Invariants the code must
honor:

- `facts` and `ticks` each carry `arrival_ordinal INTEGER NOT NULL`,
  `arrival_seq INTEGER NOT NULL`, table-level `UNIQUE (arrival_ordinal,
  arrival_seq)` — the invariant lives in the TABLE, binding foreign SQL.
- Migration is a one-transaction-per-table rebuild, ROWID-PRESERVING (rowid
  named in both column lists; FTS + fts_state watermark depend on it),
  with dependency-CLOSED trigger/index/view inventory replayed in dependency
  order; `coordinate_axis` marker commits inside the second table's
  transaction; idempotent; no observable half-state.
- Mode-aware: mirrored (legacy) backfills `(rowid, 0)`; arrival re-derives
  from the log via a provider yielding composite `(table, row_id, ord, seq)`;
  mismatch refuses toward `rederive_projections`.
- NON-NEGOTIABLE: the rederive route itself must NOT validate (ratified D0
  text: the provider is "only consulted if the index predates the columns and
  is not being rederived") — the G-1 fix implements this as `validate=False`.
- Legacy allocator: `COALESCE(MAX(arrival_ordinal), 0) + 1`, seq 0, in the
  insert's transaction, per table.
- Read paths are NOT re-keyed in WP-1 (that is WP-2/WP-3); rowid reads remain.
- Signed bytes untouched: `_tick_envelope` unchanged.

## 3. Unverified-fixes enumeration

Every commit on the branch has been through an independent Claude-opus gate
(4 rounds, report on `slice/D-wp1-gate`: `GATE-WP1A-REPORT.md`):

| Commit | What | Gate status |
|---|---|---|
| 6b2297d8 | WP-1a impl | r1 BLOCKING (F-1 apps regression, F-2 report omission, F-3..F-7 minor) |
| e81de220 | F-1,F-3..F-7 fix | r2 PASS (anti-weakening grep clean, byte-level restores verified) |
| ac7ac6a0 + b07d5a03 | WP-1b impl | r3 BLOCKING (G-1 circular refusal in rederive route) |
| 8a5fbe35 + 1aa1f7af | G-1 fix | r4 PASS (G-1 cleared; batch-discriminating log-faithfulness proof; machinery shared not duplicated) |

ARBITER-APPLIED FIX — verify this one first, it has no independent gate:

| Commit | What |
|---|---|
| aaf44142 | R5-1: parametrized the marker-present refusal test over the deep defect matrix (nullable ordinal/seq, missing seq, missing UNIQUE) with unmodified-store proof. TEST-ONLY. Arbiter mutation-verified: shallow-verifier mutation fails all 4, restore => 30 green. |

Also since your last review: ac8b61fa (SOL-WP1-01 fix — structural verifier both
paths, marker+incomplete => loud refusal no auto-rebuild, marker-absent+partial
=> rebuild; gate round 5 PASS with SHA-256-level unmodified-store verification).

RE-VERDICT SCOPE: the delta 3f9fa7fb^^..HEAD plus your SOL-WP1-01 claim —
is it closed as you meant it? Full re-review NOT needed.

Your job at LOW effort: an independent last pass over the diff for anything the
gate's protocol would structurally miss — cross-file semantic drift, a claim in
code comments/docstrings the diff falsifies, an insert path outside the closure
(grep for INSERT INTO facts|ticks and executemany repo-wide), a consumer of the
new columns making an assumption D0 forbids. Do NOT re-run the suites (gate did,
four times); spot-verify at most.

## 4. Do-not-re-report (ratified rulings, not findings)

- O(store) lazy rebuild at first writable open — Kyle accepted (Q8).
- Full column names `arrival_ordinal`/`arrival_seq` (D0-Q2).
- Placeholder `(rowid, 0)` coords in the non-validating rederive path — sound
  because rederivation deletes and reinserts immediately (ratified fix shape).
- apps/loops TEST fixture coordinate-supply edits — ruled a forced schema
  consequence, receipted.
- Read paths still on rowid — deliberate WP-1 scope, re-keyed in WP-2/3.
- Staging temp-table cleanup asymmetry — known, non-blocking, carried.

## 5. Verdict format

Per-finding: id (SOL-WP1-NN), severity, file:line, claim, evidence. Overall:
PASS (WP-1 merges) or FAIL (with the blocking subset named). One response.
