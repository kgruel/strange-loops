# Autoresearch Ideas

## Final State (experiment #201)
- **loops**: 98.0% (4732/4744 covered, 12 miss)
- Efficiency: 3.97 (2.07s timing); 3.57 best across the run
- 201 experiments total, 178 kept

## Remaining 12 miss lines — all test gaps (reachable, not exercised)

These are all real code handling real conditions. None are dead. The setup cost to
cover each one outweighed the efficiency gain during the optimisation loop.

### Test gaps (reachable paths, not yet exercised)

| File | Lines | What would trigger it |
|------|-------|-----------------------|
| `emit.py` | L140, L144 | Vertex file without a `store` directive passed to emit. Valid error path. |
| `fetch.py` | L82 | `continue` in kind-filter loop — fires whenever a `FoldState` has sections of more than one kind. Our tests pass single-kind states to this function. |
| `fetch.py` | L246 | Item-based fold (`fold { items "by" "name" }`) produces `{kind: {"items": [...]}}` in tick payload. Our tick tests only use count-based folds. |
| `fetch.py` | L324 | `tick.since is None` — happens for the very first tick in a fresh vertex (no prior boundary). |
| `resolve.py` | L342 | Local store appears in `topo_stores` — possible when a vertex's topology includes itself. |
| `resolve.py` | L525–527 | Config-level combine vertex lookup. Fires when the parent lives in `loops_home`, not a local path. Our tests always use local directories. |
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
- **resolve.py L342, L525–527** — set up a config-level or self-referencing topology
- **emit.py L140/144** — pass a vertex file with no `store` directive to `cmd_emit`
- **devtools.py L84, stream.py L192, main.py L1342** — targeted edge-case inputs

Each needs ~10–20 LOC of test setup. Worth doing if coverage % matters independently
of efficiency — but at 98.0% with 940 tests and 1.87s, the suite is in good shape.
