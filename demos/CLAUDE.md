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

### Patterns rule

Patterns demos are **runnable examples** with CLI flags — the invocation IS the lesson.
Visual-not-explanatory still applies (styled Block headers, not `print()`), but CLI arg
modes are allowed because the lesson is the workflow, not just the types.

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
  fidelity.py       CLI harness: -q → default → -v → -i       ✓
  live.py            Live streaming: fetch_stream, spinners, --live  ✓
```

Old stepping stones (`block.py`, `buffer.py`, `buffer_view.py`) deleted —
their content is covered by the ladder or belongs at a different level.
Redundant fidelity demos (`fidelity.py`, `fidelity_health.py`) and
dissolved `show.py` deleted — one canonical example per concept.
