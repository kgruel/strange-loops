# demos/ — CLAUDE.md

## What We're Doing

Walking back through what we've built to create a progressive set of
educational demos. Many existing demos were stepping stones during API
development — they reference deleted helpers, reach up the stack, or
demonstrate intermediate APIs that no longer exist. We're replacing them
with demos that teach the final API cleanly.

Drop demos that no longer make sense. Don't preserve something just
because it exists.

## Demo Rules

1. **PEP 723** — `# /// script` metadata, runnable via `uv run demos/primitives/foo.py`
2. **Visual, not explanatory** — no `print()` commentary. The output is the lesson. Use styled Block headers (dim) for section labels.
3. **Own layer only** — use exactly the API you're demonstrating. Don't reach up the stack. Output primitives (`print_block`, `join_vertical`, `Block.text()` for headers) are the baseline display mechanism.
4. **`to_X` bridges are fair game** — each demo can use its type's bridge to the next layer (e.g. `Line.to_block()`). The ladder shows the manual version of what the next step automates.
5. **Sections as `join_vertical` groups** — dim header, spacer, content. Consistent visual rhythm.
6. **Real-ish sample text** — terminal output, deploy messages, status lines. Not "Hello world".

## Demo Tiers

Three tiers, distinguished by where state lives and how you test them.

| Tier | Lesson | State | Test shape |
|------|--------|-------|------------|
| **Primitive** | Type API | None | `function() → stdout capture` |
| **Pattern** | Workflow | Data only | `_render(ctx, data) → Block` |
| **App** | Interaction | Mutable (Surface) | `TestSurface(keys) → frames` |
| **Example** | Real app | Mutable (Surface) | `TestSurface(keys) → frames` |

**Primitives** teach a single type or composition. No `main()`, no CLI flags.
Output via `print_block` / `show`. The output is the lesson.

**Patterns** are runnable examples with CLI flags — the invocation IS the lesson.
They expose `_fetch()` and `_render(ctx, data) → Block` for golden testing.
A pattern may offer `-i` interactive mode **only** when it's a live frame around
the same `_render` function (e.g. responsive.py). If `-i` introduces new state
or its own render pipeline, it's an app.

**Apps** have their own state machines: selection, navigation, modal layers.
`surface.render()` owns the layout. Tested via `TestSurface` replay: send keys,
assert on captured frames and emissions.

**Examples** are miniature applications that show what you can build, not teach
individual concepts. They use the full API freely — the experience is the lesson,
the code is reference material. Same test shape as apps (TestSurface).

The test shape *is* the boundary. If you can test the full lesson by calling
`_render(ctx, data)`, it's a pattern. If you need to send keys and inspect
frames, it's an app.

## Demo Ladder

Each demo uses the API at its level. The code *is* the lesson.

```
primitives/
  cell.py           Style + print_block                        ✓
  span_line.py      Span, Line, to_block()                     ✓
  compose.py        join, border, pad, truncate, Wrap, Align   ✓
  show.py           show() auto-dispatch                       ✓

patterns/
  rendering.py      Rendering patterns: --explicit, --custom, --palette   ✓
  palette_icons.py  Ambient config: Palette + IconSet switching           ✓
  hit_testing.py    Hit testing: Block.id -> composition -> Buffer.hit()   ✓
  fidelity.py       CLI harness: -q → default → -v → -vv      ✓
  responsive.py     Responsive layout: join_responsive + breakpoints (-i) ✓
  live.py           Live streaming: fetch_stream, spinners, --live        ✓
  focus.py          Focus + Cursor + Search: navigation vs capture        ✓
  testing.py        Replay testing: emit capture, observation traces      ✓
  profiler.py       Self-profiling: frame cost, emission timeline, flame  ✓
  help.py           Zoom-aware help: HelpData rendered at each zoom level ✓

apps/
  (not yet graduated to golden tests — needs TestSurface integration)

examples/
  disk.py           Real filesystem disk usage visualization    ✓
  big_text.py       Block character rendering (multiple sizes)
  lenses.py         Tree and chart data visualization
  theme_carnival.py Interactive palette explorer
```

Old stepping stones (`block.py`, `buffer.py`, `buffer_view.py`) deleted —
their content is covered by the ladder or belongs at a different level.
Redundant fidelity demos (`fidelity.py`, `fidelity_health.py`) and
dissolved `show.py` deleted — one canonical example per concept.
