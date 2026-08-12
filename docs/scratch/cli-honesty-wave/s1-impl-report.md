# S1 implementation report — `read --status`

Slice: S1, cli-honesty-wave. Contract: `design:implementation/cli-honesty-wave` (ratified).
Driving friction: `friction:read-status-filter-missing`.
Branch: `worktree-agent-a9ae889ad9ced450c` (off `cli-honesty-wave`).
Commit: `7b2cb76` (implementation + tests; this report is a follow-up commit).

## What changed

`sl read <vertex> --status VALUE` filters fold rows by payload-field equality
on `status` (comma-OR: `--status open,in_progress`), composable with
`--kind`/`--key` and bare `--facts`. The r2 gate invocation
`--kind finding --status open` is now real (verified live: 1 open finding in
the project store; 30 open threads via `--kind thread --status open` — the
exact reconcile question the friction records).

### Design: dissolution into the predicate grammar

`--status` is sugar over the existing `status=VALUE` bareword predicate. The
fold view merges it into `SurfaceSpec.where`, so three behaviors ride the
existing machinery with zero new code:

- the filter itself (`surface.filter` → `_predicate_match`, missing field = no match)
- the per-kind lifecycle-hide defeat (`--status resolved` shows resolved
  threads — a `status` where-field auto-disables the S5 hide for
  lifecycle-declaring kinds)
- the gate-fail inert note on custom-lens vertices (where-predicates are
  already listed; the note text now names `--status` explicitly)

What the bare predicate never had is the honesty layer, carried as
`SurfaceSpec.status` (a marker, not a second filter path).

### The honesty layer (dispatch, gate-pass only)

Payload equality on a row with no `status` field can never match, so a kind
whose rows all lack the field would return a plausible-empty —
indistinguishable from "none open", the exact silent loss in the friction.
`_status_field_census` walks the fetched FoldState (nested sections included):

| Fetched state | Behavior | Exit |
|---|---|---|
| every rowful kind lacks `status` | refuse, stderr `read --status: kind 'log' has no status field — …`, nothing on stdout | 2 |
| mixed (some kinds carry it) | filter normally; stderr `note: kind 'X' has no status field — --status cannot match it` per lacking kind | 0 |
| kind carries status, no row matches value | silent honest empty (the r2 gate's load-bearing case) | 0 |
| zero rows anywhere | honest empty — no field claim without rows to witness it | 0 |

Ground truth is the data (does any folded row carry the field), not the
declaration — kind declarations don't enumerate payload fields, so a
declaration-based check would be either vacuous or a guess.

### Honor-or-refuse everywhere the filter cannot apply

All exit 2, error on stderr (contract non-negotiable):

- windowed `--facts --since/--as-of/--id` and `--ticks` routes (read router —
  those views never apply the SurfaceSpec); bare `--facts --status` falls
  through to the fold route and is honored
- `--why` / `--diff` (own fetch/render, never apply the spec)
- live / interactive modes (render the raw fold through the lens front door;
  the spec transforms are inert there)
- empty value (`--status ,`)
- `--status` + bare `status=` predicate together (same filter, give one)
- under `--review`: auto-refused by the existing `_REVIEW_COMPOSE`
  refuse-by-default whitelist — no code needed, the ratchet worked as designed

## Files touched

- `apps/loops/src/loops/cli/read_args.py` — `--status` declared in the
  single-source parser (runtime + `-h` reflection + completion walk all pick
  it up; no value completer, same deferral as `--edge`)
- `apps/loops/src/loops/cli/operation.py` — `SurfaceSpec.status` marker field
- `apps/loops/src/loops/cli/views/read.py` — router pre-parse; refusal on
  stream/ticks routes; re-injection on the fold route
- `apps/loops/src/loops/cli/views/fold.py` — where-merge, empty-value /
  predicate-conflict / `--why`/`--diff` / live/interactive refusals,
  spec assembly
- `apps/loops/src/loops/cli/dispatch.py` — `_status_field_census` +
  `_refuse_or_note_statusless_kinds`, wired on the gate-pass path before
  either encoder; inert-note text names `--status`
- `apps/loops/tests/test_read_status.py` — 13 tests (new)

## Test evidence

- `uv run --package loops pytest apps/loops/tests/test_read_status.py` — 13 passed
- `uv run --package loops pytest apps/loops/tests` — **2455 passed, 1 xfailed**
- `uv run pytest tests` (repo-level architecture ratchets) — 59 passed
- Live exercise via `uv run --package loops loops read …` (the `loops` entry
  point — the `sl` entry point resolves to the globally-installed build, per
  the arbiter correction mid-slice): basic filter, r2 gate read, refusal on a
  truly statusless kind (`--kind log`), mixed-fetch notes on an unscoped read,
  windowed-facts refusal, `-h` reflection — all as specified above.

Note from live exercise: `--kind observation --status open` returns an honest
empty (exit 0, no note) because some observation rows in the real store DO
carry a status field — the census keys off data, and it behaved exactly per
the mixed/bearing rules.

## Deviations from the contract

1. **Refusal (exit 2) instead of note-only when the filter is provably
   unmatchable.** The contract says "explicit note, not a silent
   plausible-empty". When *no* fetched rowful kind carries a status field, a
   stderr note + exit 0 + empty stdout is still misreadable by scripts (the
   r2 gate reads stdout/exit code) — the exact defect class the friction
   describes. So that case strengthens to a refusal; the mixed case keeps the
   note-and-continue shape. Strengthening, not weakening — reported per
   contract discipline. Emitted as `finding:chw-s1-deviation-refuse-over-note`.
2. **Windowed `--facts` (stream route) refuses rather than filters.** The
   contract allows fold-view minimum ("--facts view if natural"); bare
   `--facts` IS honored (fold route). The stream view is a legacy shim that
   never applies the SurfaceSpec — filtering there would mean new machinery
   in `commands/stream.py` plus a duplicated honesty layer. Refusal with a
   teaching message matches the wave's honor-or-refuse posture. Not emitted
   as a deviation-finding: it is inside the contract's stated minimum.
3. **Honesty layer is static-path-only by construction** — live/interactive
   never reach it, and `--status` refuses on those modes anyway (see above),
   so no path accepts the flag without either applying it or refusing.
