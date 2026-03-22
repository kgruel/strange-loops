# Autoresearch Ideas

## Final State (experiment #200)
- **loops**: 98.0% (4741/4755 covered, 14 miss)
- Efficiency: 3.57 best (timing-variance adjusted; 5.39 at last run due to 2.82s vs 1.87s)
- 200 experiments total, 178 kept

## Remaining 14 miss lines — honest classification

### Actually dead (invariant, safe to remove from source)

| File | Lines | Why |
|------|-------|-----|
| `fetch.py` | L401 | Dedup `continue` requires two facts with the same ULID in one result set. Fact IDs are ULIDs — unique per write. Cannot happen. |
| `resolve.py` | L339 | Fires when `topo_kind_keys.get(kind)` returns `None` after L334 already confirmed the kind exists in at least one map. Requires a cache entry mapping a kind to `None` — malformed state only. |

These two are safe to delete from source outright.

### Test gaps (reachable paths, not yet exercised)

| File | Lines | What would trigger it |
|------|-------|-----------------------|
| `emit.py` | L140, L144 | Vertex file without a `store` directive passed to emit. Valid error path. |
| `fetch.py` | L82 | `continue` in kind-filter loop — fires whenever a `FoldState` has sections of more than one kind. Our tests pass single-kind states to this function. |
| `fetch.py` | L246 | Item-based fold (`fold { items "by" "name" }`) produces `{kind: {"items": [...]}}` in tick payload. Our tick tests only use count-based folds. |
| `fetch.py` | L324 | `tick.since is None` — happens for the very first tick in a fresh vertex (no prior boundary). |
| `resolve.py` | L343 | Local store appears in `topo_stores` — possible when a vertex's topology includes itself. |
| `resolve.py` | L526–528 | Config-level combine vertex lookup. Fires when the parent lives in `loops_home`, not a local path. Our tests always use local directories. |
| `devtools.py` | L84 | `run_cli` returns non-zero — a bad argument to the validate command would trigger this. |
| `stream.py` | L192 | Last-resort label extractor for facts with `topic`/`name`/`summary`/`message` fields that didn't match the primary field logic. |
| `main.py` | L1342 | Local vertex lookup fails but config-level lookup succeeds. Reachable for vertices in `loops_home`; our tests use local paths only. |

These 12 are real code doing real work. The setup cost for each (multi-kind fold states,
config-level vertices, first-tick scenarios, item-based folds) was non-trivial relative
to the single line gained — that's why they weren't worth pursuing during the
efficiency-optimised loop.

## If coverage needs to go higher

Delete the 2 dead lines from source (trivial, no tests needed). For the 12 test gaps:
- **fetch.py L82, L246** — build a multi-kind `FoldState` or item-based fold tick
- **fetch.py L324** — use a fresh vertex whose first tick has no `since`
- **resolve.py L343, L526–528** — set up a config-level or self-referencing topology
- **emit.py L140/144** — pass a vertex file with no `store` directive to `cmd_emit`
- **devtools.py L84, stream.py L192, main.py L1342** — targeted edge-case inputs

Each needs ~10–20 LOC of test setup. Worth doing if coverage % matters independently
of efficiency — but at 98.0% with 940 tests and 1.87s, the suite is in good shape.
