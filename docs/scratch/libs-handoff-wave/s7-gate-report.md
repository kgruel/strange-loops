# S7 GATE report — probe_target + read_preflight

Gate re-ran the oracle from scratch on `slice/s7-probe-preflight` @ 2b6e156e
(merge-base with `libs-handoff-wave` = a39028e8, confirmed). Independent
fixtures, independent byte-hash oracle (own script, not the slice's test
helpers). The impl report (f3a15d64) was treated as target, not authority.

## Verdict table

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Test suites | **PASS** | `uv run --package engine pytest libs/engine/tests` → **1313 passed** (impl report's 1312 predates the fix commit 2b6e156e, which added `test_preflight_never_creates_a_missing_sqlite_store` — reconciled, not a discrepancy). Root `./dev check` → **59 passed**. |
| 1a | test_topology "flake" | **PASS, framing corrected** | The 4 `TestTopologyCacheResolution` failures reproduce deterministically pre-`uv sync` on BOTH the slice and clean base a39028e8 (`ModuleNotFoundError: No module named 'loops'` under `--package engine`) and vanish after `uv sync`. Environment-dependent, not slice-caused — but not a "flake"; it is a workspace-sync state. |
| 2 | Probe matrix (independent fixtures) | **PASS** | All target classes checked with own fixtures + before/after sha256 of every file: vertex w/ jsonl store, missing vertex, storeless vertex, unparseable vertex, jsonl log, derived index (canonical = the LOG, writable=False), sqlite-canonical (index_current=None), missing paths per suffix, stale index (behind AND absent → False, never materialized), tampered store (index_current=True by documented parity scope, no verdict wording), content-corroboration lies. Zero non-scaffolding new files, all pre-existing artifacts byte-identical in every probe. |
| 3 | Purity adversarial | **PASS** | Grep of probe.py: no `JsonlStore`, no `ensure_index`/`resolved_index`, no bare `sqlite3.connect`, no mkdir/write-mode opens — only `open('rb')` and `_index_is_current` → `declaration._open_readonly` (URI `mode=ro`, declaration.py:203). Adversarial inputs: path in nonexistent directory, zero-byte .db ("file is empty" note), sqlite-magic-but-truncated .db, garbage first-line .jsonl — all classified, nothing raised, nothing created. `_open` in preflight.py exists only behind mode gates. |
| 4 | Preflight semantics | **PASS** | Independently: audit-only on damage → `diverged`, dir byte-identical; audit-then-open refuses damage AND fresh clone (index not materialized); recover-then-open repairs fresh clone with pre-report (not ok) + post-report (ok); RTO on out-of-band rows → `refused` (not `recovered`), and a post-refusal re-audit reports the IDENTICAL divergence summary ("index has 2, log accounts for 1") — refusal demonstrably did not repair at content level, not just byte level. Missing sqlite db → `unreadable` in all three modes, nothing created; missing .jsonl under RTO → `unreadable`, no log invented. Vocabulary closed (6 statuses, tuple matches) and exported (`PREFLIGHT_STATUSES`, `read_preflight`, `probe_target`, `PreflightMode`, `TargetInfo`, `PreflightResult` all reachable from `engine`); all six statuses observed live in the gate matrix. |
| 4a | WAL carve-out | **PASS with observed deviation, in-scope** | One byte-hash delta in the whole matrix: pf-rto-oob (RTO refusal) churned pre-existing `s.db-wal`/`s.db-shm` bytes. Within the slice's stated carve-out (sqlite shared-memory protocol), in the one mode where repair is permitted anyway, with `.jsonl` and `.db` byte-identical — and closed by the content-level re-audit above. All other probes/preflights: `-wal`/`-shm` were the only new files and everything pre-existing was byte-identical, verified independently. |
| 5 | AUDIT_THEN_OPEN vs fresh-clone auto-rebuild | **JUDGMENT: no conflict today; adoption hazard, located** | `grep -rn "read_preflight\|probe_target" apps libs` (excluding the new module/tests/exports) → zero callers. The existing read path (`resolved_index`/`ensure_index`, CLAUDE.md "Fresh-clone bootstrap": first read rebuilds automatically) is untouched. The divergence is deliberate and documented at preflight.py:17–23. Hazard: if a CLI later adopts AUDIT_THEN_OPEN as its default read gate, fresh clones start refusing where today they self-heal — the parity mode with documented CLI behavior is RECOVER_THEN_OPEN. Location claim only; nothing to fix in this slice. |
| 6 | LIBS_CHANGES contract | **PASS** | P1-probe: `probe_target(path) -> TargetInfo`, all nine suggested fields present with documented meanings; "never turning a read probe into store creation or repair" verified byte-level. Residual: classification is suffix-driven with content as corroboration in `reason` (content never overrides suffix) — a defensible reading of "use file content where appropriate", documented as the taxonomy at probe.py:27–41. P1-preflight: three modes exactly as named, typed agreement/recovery info, verification never conflated with repair, closed status vocabulary for exit-code mapping with no baked integers. No unsatisfied material property. Minor note: sqlite-canonical returns `report=None` (agreement vacuous) — documented, reasonable. |
| 7 | Pyright preflight.py:397 | **REAL PATH, TESTED — annotation nit, located** | The `hasattr(target, "target_type")` branch (preflight.py:394–398) handles a store-less `TargetInfo`; exercised by test_probe_preflight.py:388 (`pytest.raises(ValueError, match="no canonical_path")`) and by the gate matrix. Runtime-safe (hasattr-guarded). Pyright complains because the parameter is `Path | str | Any`; the tightening is `Path | str | TargetInfo` (import under TYPE_CHECKING). Location claim; not fixed by the gate. |

## Overall: **PASS**

Gate matrix script: 74 checks, sole deviation the in-carve-out WAL churn above.
Findings for the wave (non-blocking): item 5 adoption hazard, item 7 annotation
tightening, item 1a flake-framing correction.

---

## Seam re-check after S1b merge (libs-handoff-wave @ debb2e6e)

Deferred per the wave plan: S1b landed the `"t":"batch"` codec record
(multi-row ceremonies) with batch expansion in `_index_lines`/
`_prefix_intact`/`audit_deep`. Re-ran on ceremony-bearing fixtures built via
`absorb_genesis` + multi-change `absorb_edit` (one genesis fact line + one
batch line + a post-ceremony fact).

| Item | Verdict | Evidence |
|------|---------|----------|
| 1a. probe on log CONTAINING a batch line | **PASS** | `probe_target` on the ceremony log: `jsonl_log`, `index_current=True`, no corroboration mis-note (genesis fact line is first; `deserialize_row` decodes it fine). Byte-hash unchanged. |
| 1b. probe on log whose FIRST line is a batch | **FAIL — real seam defect, located** | Constructed a log whose first line is the ceremony batch line. `probe_target` reason gains "; content does not decode as loops log rows" — a mis-note on a valid log. Cause: `probe._log_content_note` (probe.py, `_log_content_note`) corroborates via `jsonl_codec.deserialize_row`, which S1b taught to REFUSE batch lines ("decode with deserialize_records"). This is exactly touchpoint 1 predicted in s7-impl-report's "S1 seam" section. One-line fix: corroborate via `deserialize_records`. Impact bounded: `reason` string only (no field is wrong, nothing raises), and genesis-is-always-first makes the shape unreachable in practice — but the probe claims to classify arbitrary locations, so the mis-note stands as a defect. Gate did not fix. |
| 2a. preflight, all 3 modes, clean ceremony store | **PASS** | audit-only `ok`; audit-then-open `ok`+opened; recover-then-open `ok`, no recovery. Fresh-clone shape (index deleted): RTO → `recovered`, post-report ok, and the rebuilt index has the SAME fact count as before deletion — batch expansion inherited correctly by rebuild (4 facts incl. the 2 inner batch rows). |
| 2b. damaged variant: index-side edit to one inner batch row | **PASS at the correct layer; expectation re-scoped** | `audit_deep` detects it (`ok=False`) — S1b's batch expansion in the deep walk works. `read_preflight` reports `ok` in every mode because it composes `audit_agreement` (the CHEAP gate: counts/offset/last-line), and an in-place UPDATE moves no counts. NOT a batch regression: the identical edit to a plain non-batch row also passes `audit_agreement` (verified side-by-side) — interior in-place edits have always been the deep audit / `store verify` layer's claim (CLAUDE.md's documented custody boundary). If the wave wants interior-edit detection in preflight, that is a design question (a `deep=` option on `read_preflight`), not S1b damage. Location claim only. |
| 3. byte-hash purity sweep on ceremony fixtures | **PASS** | Every probe and every audit-mode preflight on ceremony-bearing fixtures: all artifacts byte-identical, no new non-WAL files. |

Overall seam verdict: substrate inheritance is correct (rebuild, deep audit,
agreement all expand batches properly); one located cosmetic defect in probe
corroboration (1b) for the wave to fix (`_log_content_note` →
`deserialize_records`).
