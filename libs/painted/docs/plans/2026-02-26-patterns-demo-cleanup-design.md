# Patterns Demo Cleanup Design

Date: 2026-02-26

## Context

The primitives demo ladder is complete — four demos, each at its API layer,
following strict rules (PEP 723, visual-not-explanatory, own-layer-only).
The patterns demos are the next rung: five files with overlap, duplication,
and missing PEP 723 metadata.

## Decisions

### Two styles of demo

Primitives demos are **visual catalogs** (static, no args). Patterns demos
are **runnable examples** with CLI flags — the invocation IS the lesson.
Both follow visual-not-explanatory (styled Block headers, not `print()`).
The distinction is principled: primitives show what the types are, patterns
show how the types compose in real workflows.

### Deletions (4 files, zero unique content lost)

| File | Reason |
|------|--------|
| `demo_utils.py` | Dead code, nothing imports `render_buffer` |
| `patterns/show.py` | Dissolves: basics in `primitives/show.py`, lens override in `auto_dispatch.py`, Format.JSON in fidelity demo |
| `patterns/fidelity.py` | Redundant — same 4-level pattern as disk, no unique features |
| `patterns/fidelity_health.py` | Redundant — same 4-level pattern as disk, `--live` mode not needed for the concept |

### `auto_dispatch.py` — lens selection strategy

Teaches: auto → explicit → custom.

Changes:
- Add PEP 723 metadata
- Replace `print()` section headers with styled Block headers (dim)
- Keep three CLI modes (`--explicit`, `--custom`, default=auto)
- Keep data (CONFIG, METRICS, TRAFFIC, SERVICE) — good shape variety
- Drop `--all` mode (noisy, nobody runs it)
- Clean up `main()` dispatcher (remove `print("=" * 60)` banners)

### `fidelity_disk.py` → `fidelity.py` — CLI harness spectrum

Teaches: same data, different presentations via flags.

Rename to `fidelity.py` — it's the only fidelity demo now.

Changes:
- Add PEP 723 metadata
- `render_standard()` returns Block directly (not str → `_text_block`)
- Delete `_text_block` helper
- Consolidate duplicate `_human_size()` / `DirEntry.size_human`
- Replace `=====` comment banners with clean separators
- Keep interactive TUI tree browser (capstone)
- Keep `run_cli` integration (that's the lesson)

Disk data chosen because hierarchical data maps naturally to zoom depth —
one number → top dirs → styled bars → full tree → interactive browser.

### `demos/CLAUDE.md` update

Extend ladder and add patterns rule.

## Resulting Ladder

```
primitives/
  cell.py           Style + print_block                        ✓
  span_line.py      Span, Line, to_block()                     ✓
  compose.py        join, border, pad, truncate, Wrap, Align   ✓
  show.py           show() auto-dispatch                       ✓

patterns/
  auto_dispatch.py  Lens selection: auto → explicit → custom
  fidelity.py       CLI harness: -q → default → -v → -i
```
