# Autoresearch Ideas

## Final State (experiment #200)
- **loops**: 98.0% (4741/4755 covered, 14 miss)
- Efficiency: 3.57 best (timing-variance adjusted; 5.39 at last run due to 2.82s vs 1.87s)
- 200 experiments total, 178 kept

## Confirmed dead code — do not pursue with tests

These 14 remaining miss lines are real error handlers and defensive guards confirmed
by source inspection. They cannot be triggered without source changes. Logged here per
the ceiling rule in autoresearch.md.

| File | Lines | Why unreachable |
|------|-------|-----------------|
| `emit.py` | L140, L144 | store-less writable vertex — `_resolve_writable_vertex` always returns a vertex that has a store configured; the `store_path is None` branch cannot fire |
| `fetch.py` | L82 | kind-filter `continue` — `vertex_fold` pre-filters by kind before calling this; the inner guard is redundant |
| `fetch.py` | L246 | tick payload `items` parsing — `fold_collect` always stores items as a list, never a non-list |
| `fetch.py` | L324 | tick `since=None` fast path — callers always set `since`; `None` path structurally unreachable |
| `fetch.py` | L401 | cross-tick fact dedup — fact IDs are unique within a vertex; the dedup set never fires |
| `resolve.py` | L339 | topology key with `None` key_field — topology cache stores kind→key_field, which is always a string if the kind is present |
| `resolve.py` | L343 | already-searched store dedup — local store and topology store are always distinct paths |
| `resolve.py` | L526–528 | config-level combine fallback — both branches call the same `resolve_vertex`; only one path is ever taken |
| `devtools.py` | L84 | `run_cli` error propagation — `run_cli` never returns a non-zero exit without raising |
| `stream.py` | L192 | payload field extraction — the outer loop already handles all `_LABEL_FIELDS` keys; second loop is dead |
| `main.py` | L1342 | fast-read vertex fallback — `_resolve_vertex_for_dispatch` and `_resolve_named_vertex` agree; the fallback path is never taken |

## Source changes that would unlock further coverage

None of the above are worth testing around. If coverage needs to go higher:

1. **emit.py L140/144** — remove the `store_path is None` branch entirely (writable always
   has store). Saves ~5 source lines, eliminates 2 miss lines without any test.
2. **fetch.py L82** — remove the kind guard (caller already filters). 1 line.
3. **fetch.py L324** — remove the `since=None` branch or assert it's never None. 1 line.
4. **fetch.py L401** — remove the cross-tick dedup set if fact IDs are globally unique. ~3 lines.
5. **resolve.py L526–528** — collapse the two `config_parent` branches into one. ~3 lines.

Each is a small, safe deletion — not a refactor. Total: ~13 source lines removed,
14→0 miss (98.0%→100%). Worth doing as a separate source cleanup pass, not as test work.
