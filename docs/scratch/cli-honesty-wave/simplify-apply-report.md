# cli-honesty-wave — simplify-apply report

Agent: simplify-apply. Base: `90082250` (wave tip, after reset from a stale
`17ffde6c` merge-base). Suite baseline confirmed on the tip before any edit:
**2509 passed / 1 xfailed**.

## Per-item disposition

| # | Item | Status | Commit |
|---|------|--------|--------|
| 1 | Refusal-message unification (helper + table-driven router guards) | APPLIED | `9c8d4482` |
| 2 | cite.py single Invocation construction | APPLIED | `072edbd8` |
| 3 | missing_root_message single source (5 sites) | APPLIED | `2f36ac93` |
| 4 | ls.py `_validate_kind` helper | APPLIED | `11c529f1` |
| 5 | emit cite gate: partition loop, dead getattrs, unclamped subtraction | APPLIED | `31d45a91` |
| 6 | orient hot-path: one thread-fold pass | APPLIED | `8bfb84b9` |
| 7 | census key_or default removal + short-circuit walk | APPLIED | `1ba794e7` |
| 8 | completers first-slot factory | APPLIED | `bb219b71` |
| 9 | key-predicate parity ratchet test | APPLIED | `13209f7e` |
| 10 | test dedup (parametrize / shared `_emit` / `vpath` fixture) | APPLIED | `ed4a16c5` |
| 11 | read vertex miss did-you-mean (behavior change, ruled in-wave) | APPLIED | `193c418b` |

No item skipped; none required a behavior change beyond its description
(item 11's message improvement is the one sanctioned change).

## Item notes

**1.** `cli/refusals.py` (new, one function `status_inert_refusal(context,
drop_flag)`). The three in-view sites (fold `--why/--diff`, fold
live/interactive, dispatch custom-lens) were already byte-identical in shape
and their output is byte-unchanged; only the read-router copy had drifted
and now speaks the same sentence. The router's three fold-route-only guards
(`--at/--diff`, `--review`, `--status`) collapsed into one table-driven
loop with shared per-route reasons; guard order (and the `--at/--diff` wins
over `--review --diff` collision) preserved. The pinned substrings
(`fold route only`, `read --status`, `does not apply the status filter`)
survive; no test expectation needed updating. dispatch's statusless-kinds
refusal deliberately untouched (different genus). f-string/concat mix at
fold.py:717 gone.

**3.** `resolve.missing_root_message(root)` returns exactly
`{root} not found. Run 'loops init' first.`; resolve.py's own site keeps
its `Error: ` prefix outside the helper. Text byte-unchanged at all five
sites (the two pinning tests pass unmodified).

**5.** Verified first: `UnresolvedRef`/`ResolvedRef` declare `field`/`addr`
as required dataclass attrs (resolve.py:46–62) and all three
`_build_receipt_lines` call sites pass real ref objects (the strict-refuse
path already used `u.addr` bare); no test calls it directly. The
`getattr(status, …)` block stays — that looseness is a deliberate
circular-import dodge, out of scope.

**6.** `build_orient_summary` now does ONE `fetch_fold(kind="thread")`
(via `_fold_items`) serving open-count, adopted-count and the newest
`reconcile-*` ts, plus one friction fold — replacing two thread-fold
fetches and a full raw `vertex_facts(kind="thread")` scan.
`_reconcile_age_days` absorbed its one-caller wrapper; `.strip().lower()`
status comparison and the `_fact_epoch` coercion (None-safe) kept. Render
byte-identical on the live store (headline lines diffed by eye: identical).
Rough timing (`loops orient project`, warm, worktree code, main-checkout
cwd, read-only): **before ~0.15s / 0.11s user CPU → after ~0.11s / 0.09s
user CPU** (~25–30% off the warm wall time; the win is structural — one
fold pass instead of two folds + a raw scan — and grows with thread-fact
count). Orient tests pass unchanged (assertions and mechanism).

**7.** The short-circuit walk preserves the empty-is-not-evidence rule: a
kind whose rows are all key_or-filtered out is neither lacking nor bearing
(the generator's has_row/has_status pair, not a materialized list).

**9.** New `tests/test_key_predicate_parity.py`: 15 row shapes × 20
patterns, cell-by-cell agreement between `fetch._item_matches_key` and
`surface._row_matches_key`, with the Row built through the production
`_row_key` derivation. One genuinely divergent corner found and documented
as deliberately out-of-matrix (falsy non-string fold-key under a non-label
key_field — unreachable through the declared-fold pipeline; widening there
means first ruling which predicate is right).

**10.** (a) the four same-shape refusal tests are one parametrized test
(same 4 cases, ids kept meaningful); (b) one module-level
`_emit(vpath, parts, *, kind="cite", **extra)` replaces both class copies
and `_seed_thread`'s third; (c) a `vpath` fixture (sandbox sibling)
deleted 21 identical `vpath = _write_vertex(sandbox, "t")` lines (the
`.loops/`-dir variants are a different shape and stay inline).

**11.** `loops read <typo>` → exit 1, stderr carries
`_unknown_vertex_message` (miss + did-you-mean + known list); the bare
`No vertex resolved — run loops init first.` stays for the genuinely-bare
case. **Formats differ** from ls's miss: same helper (content parity by
shared source) but read's Reporter paints the message as one collapsed
line while ls prints the three lines raw — the test matches
whitespace-normalized content and says so. Friction
`read-vertex-not-found-lacks-suggestion` re-emitted `status=resolved`
`commit=193c418b`.

## Verification

- Full suite, worktree cwd: **2513 passed / 1 xfailed** (baseline 2509 + 4
  new: 1 ratchet + 3 read-miss; the parametrization kept the refusal
  quartet at 4 cases — minus nothing).
- Full suite from a `.loops`-bearing scratch cwd (project.vertex declaring
  design+thread+decision+cite): **2513 passed / 1 xfailed**.
- `./dev check` (repo root): exit 0.
- Live smokes (worktree code, main-checkout cwd, read-only):
  - `loops read projct` → exit 1, `vertex not found: projct  Did you mean:
    project, projects? Known vertices: …`
  - `loops orient project` → identical output pre/post item 6.
  - One `--status` refusal per unified site (all exit 2, one sentence
    family):
    - router/window: `read --status: `--facts` with a temporal
      window/anchor routes to the event-history view, not the fold read and
      does not apply the status filter — drop --status, or drop the window.`
    - router/ticks: `read --status: `--ticks` reads tick windows, not
      folded state and does not apply the status filter — drop --status, or
      drop --ticks.`
    - `--why`: `read --status: --why owns its own fetch and does not apply
      the status filter — drop --status, or drop --why.`
    - interactive: `read --status: interactive mode renders the raw fold
      and does not apply the status filter — drop --status, or drop -i.`
    - custom lens: `read --status: a custom lens renders its own shape and
      does not apply the status filter — drop --status, or drop --lens
      autoresearch.`
