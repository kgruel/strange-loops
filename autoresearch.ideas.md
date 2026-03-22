# Autoresearch Ideas

## Current State (experiment #196)
- **loops**: 97.7% (4740/4762 covered, 22 miss)
- Efficiency: 4.40 (below 4.53 baseline — new best!)
- Key wins: emit.py at 98% (5 miss), resolve.py 98% (5 miss)

## Remaining 22 miss lines

### Confirmed dead code / structurally unreachable:
- `fetch.py L82, L246-247, L325, L402` (5 lines) — confirmed dead
- `store.py L91` (1 line) — Fact.payload always a dict
- `stream.py L192` (1 line) — redundant search loop
- `main.py L1342` (1 line) — _try_fast_read dead fallback
- `devtools.py L84` (1 line) — validate run_cli never errors
- `resolve.py L339` (1 line) — key_field=None after kind in topo (malformed cache)
- `resolve.py L343` (1 line) — already-searched store (loop-level dedup, need topology widening test)
- `resolve.py L526-528` (3 lines) — config_parent path: both functions call same resolve_vertex

### Still reachable (11 lines):
- `emit.py L140-144` (5 lines) — writable vertex found but store_path=None; POSSIBLY dead (writable→has store)
- `emit.py L236` (1 line) — absolute path in `from file` clause (unusual but valid KDL)
- `emit.py L548-549` (2 lines) — validate_emit error in _run_close (observer restrictions)
- `pop.py L155` (1 line) — legacy header read from file when store header missing
- `pop.py L222, L289` (2 lines) — multi-template template assignment in cmd_add/cmd_rm

## Quick wins

### emit.py L236 (absolute from-file path)
- Set `from file "/absolute/path/feeds.list"` in vertex config
- Then call cmd_emit with pop.add — L236 fires during the `else: list_path = Path(list_path)` branch
- ~8 LOC test

### pop.py L222, L289 (multi-template add/rm)
- Call `cmd_add`/`cmd_rm` on a multi-template vertex with qualifier
- `payload["template"] = template.template.stem` when is_multi=True and qualifier resolves
- ~15 LOC, covers 2 lines

### emit.py L548-549 (validate_emit error)
- Create vertex with observer restrictions (observers { ... })
- Call `_run_close` with wrong observer kind → validate_emit returns error → L548-549
- ~15 LOC

## Step-down opportunities
- test_loc=8954 is high (97.8% over baseline). With 2.33s timing and 4740 covered:
  - Removing 600 LOC would hit ~4.0 efficiency (8354 * 2.33 / 4740 ≈ 4.1)
  - Focus: merge TestEmitPopFieldErrors + TestEmitPopSeedAndTemplate into one class with shared fixture
  - Can save ~30-40 LOC by extracting _setup_list_vertex as a shared helper

## Practical ceiling
- Likely ceiling: 4751-4757 covered (22 - 5 confirmed dead = ~17 more achievable)
- Would push to 97.9-98.0% coverage
- At 2.33s and 8954 LOC, adding 17 more lines gives: 4757 covered, 
  efficiency ≈ (8954+50)*2.33/4757 ≈ 4.40 — roughly same
