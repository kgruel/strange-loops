# Learn Summary — strange-loops operational guides

**Date:** 2026-05-24 13:52 | **Mode:** init-guides (custom doc set) | **Scope:** everything | **Depth:** deep
**Validation:** 100% | **Fix iterations:** 0 | **Learn score:** 100 (Excellent)

## What was asked

Beyond the standard auto-doc set (generated earlier today, 100% at `learn/260524-1336-init-deep-fullrepo/`),
the user wanted **a rich set of operational docs that walk from basic library usage up to the
intricacies of the full loops CLI capabilities** — a learning ladder, not another reference.

## Baseline → final state

- **Before:** `docs/` held the 9 standard auto-docs + 12 hand-written deep-dives. No
  progressive/tutorial path — a reader had no obvious "start here and climb" route.
- **After:** new `docs/guides/` directory — a **README index + 10 numbered rungs** (2,800+ lines)
  walking bottom-up through the abstraction chain. No existing doc was touched; the guides
  *link into* the deep-dives and reference docs rather than duplicating them.

## The ladder (docs/guides/)

The rungs follow the system's abstraction chain, learned bottom-up. The pivot is Rung 04:
below it you build by hand in Python; above it you declare once and drive from the CLI.

| # | Rung | Lines | Layer |
|---|------|-------|-------|
| — | `README.md` (index + map) | — | — |
| 01 | Atoms: the data layer | 278 | atoms |
| 02 | Vertices & Loops: the runtime | 236 | engine |
| 03 | Persistence & Replay | 234 | engine |
| 04 | Declaring Vertices in KDL | 261 | config (pivot) |
| 05 | The loops CLI: emit, read, fold | 251 | CLI |
| 06 | The Fact Graph: refs & cites | 203 | CLI |
| 07 | Reading Deeply: zoom, keys & lenses | 312 | CLI |
| 08 | Sources & Cadence | 290 | CLI |
| 09 | Store Maintenance & Transport | 222 | CLI/ops |
| 10 | Identity & Federation | 292 | CLI/ops (apex) |

## Key decisions

- **New `docs/guides/` namespace, not loose files in `docs/`** — keeps the ladder grouped,
  `ls`-sortable, and visually distinct from the standard auto-docs and the conceptual deep-dives.
- **Three roles, no duplication** — guides are the *path* (how, in order); deep-dives are the
  *concepts* (what); api-reference/cheatsheet are the *lookup*. Guides link into the other two.
- **Bottom-up, not call-order** — the user learns from `Fact` upward, so Rung 01 is atoms and
  Rung 10 is federation, even though at runtime config drives the CLI drives the engine.
- **Shared author spine** — three parallel authors were given one brief (canonical verified
  wiring snippet, guide template, vocabulary lock, link conventions, full file list) so the
  rungs cohere despite parallel generation.
- **Anchored install caveat preserved** — Rung 05 carries the hard-won `uv tool install . -e`
  vs `uv run` staleness lesson (the uuid4-vs-ULID divergence) unsoftened, per project memory.

## Validation trajectory

Single pass at 100%: 11/11 files present, all ≤800 lines (largest 312), all 10 inter-rung
links + all deep-dive/reference links resolve, no anchored cross-file links, and the riskiest
API claims spot-verified against live source (`Vertex.register`/`register_loop`,
`loops test --input`, `Grant(horizon, potential)`, `compile_vertex -> dict[str, Spec]`).

## Findings surfaced during generation (pre-existing repo issues, NOT new-doc bugs)

The authoring agents, while grounding examples against source, caught three stale spots in
the *existing* deep-dives. The new guides use the correct form; the deep-dives still carry the
old one. Out of scope here (this run generated guides, didn't edit deep-dives):

1. `docs/IDENTITY.md` — `Grant(observer=...)`; real `Grant` is `horizon` + `potential` only.
2. `docs/LENSES.md` — `--minimal` flag; real flag is `-q` / `--quiet`.
3. `docs/CLI-CHEATSHEET.md` — lists retired `loops export <target>` as active.

## Recommended next steps

- `git add docs/guides/` to track the new ladder (currently untracked).
- Optional `--mode update --file IDENTITY.md` (and LENSES.md, CLI-CHEATSHEET.md) to clear the
  three staleness findings above.
- Link `docs/guides/README.md` from the top-level project README / CLAUDE.md "Where to start"
  so newcomers find the ladder.
