# cells — Session Log

## 2026-01-29

### Session: Feature expansion + code review

**Added:**
- Mouse support (+1047 lines) — `MouseEvent`, SGR parsing, Surface integration, drawable canvas demo
- Big text rendering (+832 lines) — `render_big()` with sizes, formats, glyph sets
- Lens extensions (+869 lines) — `tree_lens`, `chart_lens` following shape_lens pattern
- Verbosity spectrum (+2392 lines) — CLI→TUI pattern, 3 domain demos (build, health, disk)

**Reviewed:**
- Deep code review of all additions
- Core additions follow cells conventions well
- Demos have mutable state patterns (acceptable for illustration, not production templates)
- High-priority fixes identified and in progress

**Open threads:**
- Architecture layering research started — what's core vs optional?
- Viewport dataclass still needed (now has mouse scroll to consume)

**Files touched:**
```
libs/cells/src/cells/mouse.py         (new)
libs/cells/src/cells/big_text.py      (new)
libs/cells/src/cells/lens.py          (extended)
libs/cells/src/cells/keyboard.py      (mouse integration)
libs/cells/src/cells/writer.py        (mouse enable/disable)
libs/cells/src/cells/app.py           (mouse callback)
demos/cells/demo_mouse.py             (new)
demos/cells/demo_big_text.py          (new)
demos/cells/demo_lenses.py            (new)
demos/cells/demo_verbosity*.py        (new, 3 files)
experiments/verbosity/                (new module)
docs/MOUSE.md                         (new)
```

---

## 2026-01-26

### Session: Surface + Emit feedback loop

- Renamed RenderApp to Surface
- Added Emit protocol for observations
- Three emission strata: raw input, UI structure, domain
- Python minimum bumped to 3.11
