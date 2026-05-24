# Validation Report — guides ladder

**Run:** 2026-05-24 13:52 | **Mode:** init-guides (custom doc set) | **Depth:** deep | **Scope:** everything

## Score: 100% (11/11 docs pass)

| Check | Result |
|-------|--------|
| All planned rungs present | 11/11 ✓ (README + 10 rungs) |
| Size compliance (≤800 lines) | 11/11 ✓ (largest: 07 @ 312) |
| Cross-rung links resolve | ✓ all 10 inter-rung links valid |
| Deep-dive links resolve (`../*.md`) | ✓ VERTEX, TEMPORAL, PERSISTENCE, IDENTITY, SCOPE-LATTICE, CADENCE, LENSES, api-reference, CLI-CHEATSHEET, configuration-guide |
| README index links resolve | ✓ |
| Anchored cross-file links | none used (no anchor risk) |
| Code/API references spot-verified | ✓ see below |

## Code-reference spot checks (against live source)

| Claim | Source | Verdict |
|-------|--------|---------|
| `Vertex.register(kind, init, fold, *, boundary=, reset=)` + `register_loop` | `engine/vertex.py:239,265` | ✓ |
| `loops test --input/-i` | `commands/devtools.py:113,125` | ✓ |
| `Grant(horizon, potential)` — **no** `observer` field | `engine/peer.py:14,25` | ✓ |
| `compile_vertex(vf) -> dict[str, Spec]` (not a live Vertex) | `engine/compiler.py:798` | ✓ |
| Canonical wiring (`register`+`receive`+`Tick`) | `tests/test_integration.py` | ✓ |

Validator script `~/.claude/scripts/validate-docs.cjs` not installed — manual validation performed.

## Pre-existing staleness in linked docs (NOT new-guide bugs)

Surfaced by the authoring agents while grounding examples. The new guides use the
**correct** form; the older deep-dives still carry the stale form. Out of scope for
this run (which generated guides, did not edit deep-dives) — logged for a future
`--mode update`:

1. `docs/IDENTITY.md` — shows `Grant(observer=...)`; real `Grant` has only `horizon` + `potential`.
2. `docs/LENSES.md` — references a `--minimal` flag; the real flag is `-q` / `--quiet`.
3. `docs/CLI-CHEATSHEET.md` — lists `loops export <target>` as active; it was retired in Phase 3.

No fix loop required — first-pass validation reached 100%.
