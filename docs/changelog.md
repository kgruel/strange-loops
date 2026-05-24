# Changelog

> Generated from `git log`; see `git log` for full history. The repo also keeps
> inline `changelog:` commits with dated notes (preserved below under
> Docs / Changelog). Newest-first within each group.

## Features

- `f2c65c4` emit: `--stdin FIELD` and `--file FIELD=PATH` flags
- `f459ff8` lang/population: generalize splice library for vertex mutation
- `c5c2cbc` loops: cardinality-driven auto-zoom for fold rendering (later reverted)
- `02ee436` loops: per-kind preview declaration + render rule
- `932bcd7` atoms+loops/read: WalkedItem + ref-graph walk (A2 of trace-dissolution)
- `38691aa` loops/read: `--refs [N]` unification (A1 of trace-dissolution)
- `1fe66d4` lens(deliberation): structural overfit detector for status-bearing kinds
- `803ba03` trace: top-level verb for kind/key lifecycle (`--refs`, `--diff`, `--depth`)
- `5846478` emit-receipt-on-write: in-moment feedback for every emit
- `f3492b2` read-path access primitives: `--key` prefix filter + lens-fetch kwargs passthrough
- `cb89a89` extract-structure-reveal: composable corpus → embed → kernel → readout harness
- `b6a31c5` salience-driven-display: `cite --message` + cite-count salience + open-window bridge
- `77101c1` session_landing lens + cite primitive + lens-declares-fetch
- `f06c320` TickWindow primitive: density + depth + delta at the window level

## Fixes

- `33937f6` fix/entity-ref-fold-key-skip: skip emitted kind's fold-key value during ref scan
- `0deb7ea` fix/cite-cluster: fix `sl cite` ref-stealing + implicit universal cite loop
- `51f8cc8` loops/trace: discoverable help + kind index + bare-name crash fix

## Refactors

- `2455548` loops/trace: replace `_DIFF_SKIP_FIELDS` with `_is_diff_skip` predicate
- `ca34312` loops/cli: complete helpargs ripout (fix store/validate/test/compile/whoami)
- `180e052` loops/cli: complete trace-lens dissolution and rename SOURCES section
- `e73e60e` loops/cli: replace helpargs with stock argparse `--help` across all verbs
- `8fdfaf8` loops/cli: declarative add/rm/ls surface; retire pop-fact machinery
- `2e35968` loops/commands: resolve multi-ref payloads per-address
- `4ff364b` loops/cli: drain remaining helpers from main.py (pass 3)
- `7af3774` loops/cli: migrate `_run_ticks` to commands/ticks.py (pass 2)
- `83358d9` loops/cli: migrate store + population ops to commands/ (pass 2)
- `397dd3b` loops/cli: migrate `_run_stream` to commands/stream.py (pass 2)
- `e5b49c3` loops/cli: migrate `_run_whoami` to commands/whoami.py (pass 2)
- `3083c18` loops/cli: delete dead code from main.py (pass 1 of body migrations)
- `035af59` loops/cli: dissolve main.py into cli/views/ (steps 1-6)
- `68500ba` loops/cli: Step 0 — Operation IR + Reporter + dispatch skeleton
- `52f2d0e` loops/read: delete trace verb (D of trace-dissolution)
- `aa8bd94` loops/read: `--diff` routing (C of trace-dissolution)
- `b05e126` loops/read: positional kind/key (B of trace-dissolution)
- `ba3cd2a` engine/loops: dissolve duplicate id generator (CLI emit was uuid4)
- `2a82065` store/engine: drop sqlite-ulid dep, align schemas to id-supplied-at-INSERT
- `0a0e64a` engine: restore ULID id generation via python-ulid
- `ec8c4a9` dispatch-consolidation-via-program: collapse 3 CLI sites into VertexProgram

## Docs / Changelog

- `2010e0a` changelog: 2026-05-19 — cite ref-stealing + implicit universal loop
- `336f39a` changelog: 2026-05-19 — preview_fields, `_is_diff_skip`, namespace degenerate fix
- `d952a2d` CLAUDE.md: track public-facing version; bilateral runbook moves to docs/dev
- `b204f6c` changelog: 2026-05-17 — trace dissolves into read `--diff [--refs N]`
- `c3a2424` changelog: 2026-05-16 — ULID restoration + deliberation lens + ARCS hooks
- `db5dc74` changelog: 2026-05-16 — `sl trace` verb (kind/key lifecycle)
- `a12fc8e` changelog: 2026-05-16 — emit receipt + fold merge
- `3b8757c` docs: vouch design refinements — IDENTITY/SCOPE-LATTICE/essay/ARCHITECTURE
- `fcfff10` Document defensive branch in `_tick_payload_stats`
- `7aa90fc` Add CHANGELOG.md — project history Feb 2026 through autoresearch campaign

## Other

- `ad23262` Revert auto-zoom and MINIMAL/`--facts` coupling (c5c2cbc + 7c3bca6)
- `7c3bca6` loops/fold: MINIMAL falls back to key list; `--facts` disables auto-zoom (reverted)
- `2621be9` loops/diff: strip refs from `--diff` (refs accumulate, not state)
- `d563728` loops/fold: degenerate namespace breakdown falls back to flat rendering
- `fe1dea1` loops/ls: surface `preview_fields` in `_summarize_kinds` and `_render_kind`
- `c5972fa` loops/cli: ls accepts `--kind/--observer/--combine/--row` flags
- `20814af` loops/cli: align refactor docstrings with paused-pilot reality
- `9562843` stop tracking personal state; remove stale autoresearch scaffolding
- `707c558` detach painted from monorepo; consume as PyPI dep
- `57c003c` tooling: pyrightconfig pointed at .venv for workspace import resolution
- `a3e6542` loops/read: drop duplicate `--facts` in `--help`
- `a042655` lens(deliberation): tighten SUSPICIOUS to `emit_count<=1`
- `68a3361` engine(combine): thread `retain_facts` through `_combined_read`
- `c690589` lens(session_landing): budget-tune to 2KB inline-preview cutoff
- `fe4602e` vertex: declare friction (local) + hypothesis (template) fold-by-name kinds
- `7c1b95e` repo: untrack CLAUDE.md (per-clone bilateral runbook)
- `d43fd79` release: 0.3.1 — read-path access primitives + lens-resolution-strict completion
- `65ea07b` read-path: autoresearch lens sentinel + lens-not-found exits-loudly test
- `57d547e` chore: bump libs/painted submodule to v0.1.8
- `ca22e70` chore: gitignore .mcp.json, move scratch txt to docs/scratch
- `22503e3` release: 0.3.0 — include libs/sign in published wheel
- `9f58e4c` engine.peer: docstring nudge — chain ancestry lives on Facts, not Peers
- `9657f69` Add typing_extensions to root deps — workaround python-ulid 3.1.0 metadata gap
- `ea517f1` Carve loops/libs/sign — JWT/JWKS/keys utility lib
- `3461911` read-path-author-side: mentions block + emit-discipline for painted/first-disclosure
- `e9b6a87` land-coupling-kernels-demonstrators: commit experiments + verification fixtures
- `234a91f` fold-lens-fidelity-wired: thread chars/lines budgets through fold render
- `67f6fb1` session_landing: WINDOW → LANDING — section names purpose, not temporal slice
- `724add3` session_landing PLAN section + stale-as-focus-filter + emission ergonomics design

## See also

- [deployment-guide.md](deployment-guide.md)
- [../README.md](../README.md)
