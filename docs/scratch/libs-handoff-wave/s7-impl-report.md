# S7 impl report — probe_target + read_preflight

Branch: `slice/s7-probe-preflight` (off `libs-handoff-wave` @ a39028e8)
Worktree: `/Users/kaygee/Code/loops/.claude/worktrees/agent-a29c3a4966637d51a`
Commits: 57f2bf8f (impl), f3a15d64 (report), + missing-sqlite fix commit

## What was built

### A. `engine/probe.py` — `probe_target(path) -> TargetInfo`

- Composes `engine.residence` (extension-is-the-switch) — no re-spelled
  suffix logic. Suffix classifies (`vertex | jsonl_log | derived_index |
  sqlite_store | unknown`), content corroborates (sqlite magic header,
  first codec line decode), existence is orthogonal (`exists` field; a
  missing `foo.jsonl` still probes as `jsonl_log`).
- All nine contract fields present. `canonical_path` for a derived index
  is the sibling LOG; `writable=False` there by construction, with the
  out-of-band-insert rationale in `reason`.
- `index_current` is documented as OFFSET PARITY ONLY (scope-the-claim,
  same style as `Check.beyond_offset`): a tampered-but-parity-intact
  index still reads `index_current=True`; integrity is preflight/audit's
  claim. Composes `jsonl_store._index_is_current` (read-only meta read +
  stat).
- `declaration_status` for vertex targets via `load_declaration_status`
  (verified pure: it resolves through `resolve_store_path`, never
  `resolved_index`); parse failures land in `reason`, never raise.
- Purity traps avoided: no `JsonlStore` construction, no
  `ensure_index`/`resolved_index`, no bare `sqlite3.connect` (which
  creates missing files) — only `declaration._open_readonly` and raw
  `open('rb')`.

### B. `engine/preflight.py` — `read_preflight(target, mode)`

- `PreflightMode`: `AUDIT_ONLY` / `AUDIT_THEN_OPEN` / `RECOVER_THEN_OPEN`
  over `canonical_audit.audit_agreement`. Verification and repair never
  share a path: repair happens only in `RECOVER_THEN_OPEN`, always
  preceded by an evidentiary pre-audit (kept in `report`) and followed by
  a `post_report`.
- `AUDIT_THEN_OPEN` refuses on any failing audit — including a fresh
  clone's missing index (materializing IS repair; documented, with
  `RECOVER_THEN_OPEN` named as the sanctioned path).
- `RECOVER_THEN_OPEN` can still refuse: out-of-band index rows raise
  `JsonlCanonicalUnsupported` at open → `status="refused"`, typed
  distinctly from `recovered`.
- Exit-code mapping via the closed `PREFLIGHT_STATUSES` vocabulary
  (`ok | recovered | index-behind | diverged | refused | unreadable`);
  no integers baked in. `index_behind` keeps the audit's scope-limited
  wording (never an innocence claim).
- Accepts a canonical path, a derived-index path (re-routed through the
  probe to its canonical sibling — nobody audits "the index against
  itself"), or a `TargetInfo` (seats the P2 contract that maintenance
  APIs take `TargetInfo`). Sqlite-canonical: agreement is vacuous
  (`agreed=True`, `report=None`, reason says so), open modes open — but
  a MISSING sqlite db is `unreadable` in every mode: `SqliteStore.__init__`
  creates a missing file, and a read preflight never creates (advisor
  finding, fixed pre-merge; pinned by
  `test_preflight_never_creates_a_missing_sqlite_store`).
- Both exported from `engine` (`__all__` + lazy map).

## Oracle results

`libs/engine/tests/test_probe_preflight.py` — 23 tests, all passing:

- Probe matrix: vertex (jsonl store / missing / storeless / unparseable),
  jsonl log, derived index, sqlite-canonical, missing paths per suffix,
  stale index (behind AND absent → `index_current=False`, not
  materialized), out-of-band tampered store (parity-scoped, no verdict),
  content-corroboration lies, and a creates-nothing sweep over missing
  targets of every suffix.
- Every probe wrapped in a before/after byte-hash of the target dir.
  **Oracle scoping found during implementation**: any read-only (mode=ro
  URI) connection to a WAL-mode sqlite db may create `-wal`/`-shm`
  scaffolding — sqlite's shared-memory protocol, not a store mutation
  (it happens on `sl read` too). The oracle asserts: every artifact
  byte-identical, no new files beyond that scaffolding.
- Preflight matrix: audit-only clean/damaged (typed damage, dir-hash
  unchanged), audit-then-open refuses damage AND fresh clone (index not
  materialized), recover-then-open repairs fresh clone (both reports
  kept), still refuses out-of-band rows, never invents a log,
  clean-store no-op, sqlite vacuous, probe composition + derived-index
  re-route, index-behind status mapping.

Gates: `uv run --package engine pytest libs/engine/tests` → **1312
passed** (4 consecutive clean runs); root `./dev check` (architecture
ratchet) → 59 passed; ruff clean on the new files.

## Deviations / notes

- One full-suite run early on showed 4 `test_topology.py` cache failures;
  not reproducible in 4 subsequent full runs, in isolation, or paired
  with the new file — treated as a pre-existing flake, flagging for the
  gate re-run.
- `TargetInfo.declaration_status` is vertex-only (`None` elsewhere) — a
  probe never parses arbitrary files as declarations.
- `ruff format --check` would reformat the new modules, but the repo does
  not run format in its gate and existing engine modules are not
  format-clean either; matched house style instead.

## S1 seam (explicit)

Built against the CURRENT canonical-log record grammar
(`engine.jsonl_codec.deserialize_row`: `fact`/`tick` rows only). Two
touchpoints if S1 introduces a declaration-ceremony record type:

1. `probe._log_content_note` corroborates the first log line via
   `deserialize_row` — a new record type that the codec learns to decode
   needs nothing here; a type the codec rejects would mis-note a valid
   log.
2. Preflight inherits whatever `audit_agreement` learns — no grammar
   knowledge is duplicated in `preflight.py`.

Gate re-runs after S1 merges, per the wave plan.
