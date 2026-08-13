# S3 GATE report — admission policy at the engine boundary

Gate branch: `slice/s3-admission-policy-gate` (pointer at slice tip `874af7f2`).
Merge-base verified: `9cb77675` is an ancestor of the slice tip.
Method: independent re-run — own driver (28 checks) against real `.vertex`
fixtures, own CLI drive, own bypass audit. The impl report was the target,
not the authority. Contracts read directly: LIBS_CHANGES.md P1 (observer
admission + strict) and `decision:design/strict-enforcement-at-engine-receive`.

## Verdict table

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Suites | **PASS** | engine 1359 passed; loops 2521 passed + 1 xfail; lang 557 passed + 3 skip; root 59 passed. Matches impl report exactly; no topology flake seen. |
| 2 | Five observer-grant cases | **PASS** | Own driver, real fixtures: no-observers → unrestricted; unknown observer → `UnknownObserver`, 0 rows stored; declared-no-grant → unrestricted; declared-with-potential → in-potential stored, out-of-potential `Receipt(stored=False)`; aggregate → `AggregateAdmissionUnsupported` from `program.receive_as`. Raw `receive` bypass confirmed both ways (unknown observer AND out-of-potential land; row counts exact). Aggregate bypass side also exercised: raw `receive` on the aggregate program never consults admission — no `AdmissionError`; it returns `Receipt(stored=False)` for the non-admission reason that an aggregate is not a write target. |
| 3 | Bypass audit / evasions | **PASS** (with one pre-existing structural note) | See below. |
| 4 | Strict ruling conformance | **PASS** | Typed `UndeclaredKind` raised before storage — store row count unchanged after rejection (1 vs 1). `receive_as` also strict-refuses. `admit_undeclared=True` stores. Non-strict preservation verbatim: undeclared stored, raw-readable via sqlite (`[('later', '{"message": "early bird"}')]`), folds after later declaration (verified in fold state). Enforcement fires only when declaration says strict (non-strict vertex admits identical fact). |
| 5 | CLI seam | **PASS** | Drove worktree CLI (`uv run --package loops loops emit`, path-target). Strict vertex + undeclared kind → single refusal rc=2, sane message + hint, no traceback, no double rejection, nothing stored. `--strict` on non-strict vertex → CLI refusal rc=2, nothing stored. Non-strict undeclared → WARN + stored. Narrower-or-equal claim verified by reading both derivations: CLI declared-set = `ast.loops` ∪ {cite} (resolve.py `classify_emit_status`) ⊆ engine `accepts()` = loops ∪ boundary ∪ routes ∪ child-accepted (vertex.py:319). Both resolve via `load_declaration`, and vertex-declared strict has no CLI/env override-off (`_resolve_strict`, emit.py:164) — the containment direction is the right one: every kind the engine would refuse is already refused by the CLI first, so engine `UndeclaredKind` is unreachable from `cmd_emit`. |
| 6 | Reported-not-fixed items | **PASS** (location claims confirmed) | (a) No engine-exception→exit-code mapper in `loops` main — confirmed; but admission errors are NOT reachable from current CLI paths (see item 5), so severity stays latent, no upgrade. (b) `emit.py:890` and `emit.py:1361` still raw `program.receive` — confirmed; deferral rationale is sound: migrating to `receive_as` would start hard-rejecting undeclared observers on observers-block vertices, where the CLI today deliberately forgives (WARN + store) under non-strict. Behavior change, correctly out of slice. |
| 7 | `receive_as` freshness | **PARTIAL — finding F1** | The claim "`_recompile` keeps `_ast` fresh" is true but overstated. Empirically: declare a new observer by editing the `.vertex` out-of-band, then `handle.receive_as` as that observer WITHOUT reopening → **first call still raises `UnknownObserver`** (stale `_ast`). After `refresh(force=True)`, admitted. |

**OVERALL: PASS**, with finding F1 (below) recommended as a follow-up, not a
block — the freshness gap is out-of-band-edit-shaped, one-catch-up wide, and
does not violate the P1 contract text or the strict ruling.

## Item 3 detail — bypass audit

Every `admit_undeclared=True` call site in the tree (non-test):

| Site | Classification |
|------|----------------|
| `libs/engine/src/engine/executor.py:235` (`_sync` in sync_async) | engine-internal-and-necessary (lifecycle fact; a strict vertex never declares `_sync`) |
| `libs/engine/src/engine/executor.py:293` (`_sync.{kind}` in `_run_source`) | engine-internal-and-necessary (same) |

No other production site passes the bypass. Threading-only sites
(handle/program/vertex parameter pass-through) default False.

Evasion attempts, all run empirically:

- **Source producing an undeclared kind on a strict vertex** (executor
  `sync_async`, real `Source` + `Cadence.always()`): fact NOT stored; raise
  captured by the source-error path — `SyncResult.errors` carries
  `_sync.rogue` with `status=error, error_type=UndeclaredKind`; the `_sync`
  lifecycle facts land via the explicit bypass. Store contents afterward:
  `['_sync', '_sync.rogue']` only. Their claim verified.
- **Fold-replay of a historical undeclared row on a now-strict vertex**:
  emitted undeclared while non-strict, flipped `strict true`, reloaded —
  replay does not raise (Vertex.replay bypasses `receive_receipt`; the
  `engine/replay.py` module-level `replay()` that WOULD go through receive
  has no production callers — checked). New undeclared ingress still refused
  post-replay.
- **Child-tick re-entry** (`_from_child` exemption): engine-internal — the
  exempted fact is the engine-minted child tick, not attacker ingress; an
  original fact routed toward a child is accepted by `accepts()` (which
  includes child-accepted kinds) before the exemption can matter. No evasion.
- **`store merge`/`receive` of a foreign fact with an undeclared kind into a
  strict sqlite-canonical store**: **LANDS** — `receive_store` →
  `merge_store` is ATTACH + `INSERT OR IGNORE`
  (`libs/store/src/store/merge.py:73`), never touches `Vertex.receive`, never
  consults admission. Verified: merged `rogue` into the strict store,
  `select kind from facts` shows it; subsequent CLI emit + replay still work
  (no crash, no detection on sqlite-canonical). **Location claim**: this is a
  store-layer structural bypass that PRE-DATES the slice and sits outside the
  ruling's scope ("enforcement at engine receive"; direct-db ops are the
  documented custody boundary — jsonl-canonical stores detect them on open,
  sqlite-canonical do not). Not a slice failure; worth a thread if strict is
  ever expected to gate transport.

## Finding F1 — receive_as grant resolution precedes catch-up

`VertexHandle.receive_as` (handle.py:1400) resolves
`grant_for_observer(self._ast, ...)` under the lock and only THEN calls
`receive()`, whose catch-up (`_advance_full` → `_recompile`) is what refreshes
`_ast`. Consequences, both empirically confirmed:

1. The first `receive_as` after an out-of-band `.vertex` edit resolves against
   the previous ontology epoch (newly declared observer refused once).
2. Because the refusal raises BEFORE `receive()` runs, no catch-up happens —
   pure-`receive_as` retries stay stale indefinitely until some other handle
   operation (e.g. `refresh()`) advances the epoch.

The mirror direction also holds in principle: an observer REMOVED by an edit
is admitted for one call under the stale grant. The impl report's "stays fresh
across ontology epochs (verified)" is true only from the second
post-catch-up call onward. Fix shape: resolve the grant inside `receive()`
after step-1 catch-up, or `refresh()` before resolution in `receive_as`.
Severity: minor (out-of-band edits only; single-writer CLI flows reopen per
command and never hit it).

## Oracle inventory

- Own driver: 28 checks, 27 pass, 1 fail (= F1) —
  scratchpad `gate_driver.py`, run via `uv run --package engine python`.
- CLI drive: 5 invocations against strict/loose path-target fixtures.
- Merge evasion: `store.receive.receive_store` cross-store merge + post-merge
  CLI emit.
- Suites: 4/4 green, exact counts in the table.
