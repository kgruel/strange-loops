# Lens Primitive: Discovery Retrospective

How we arrived at the Lens primitive for cells.

## Starting Point: Verbosity Flags

The question: how should `-q`, `-v`, `-vv` work in a CLI/TUI context?

Standard semantics:
- `-q` = less output (results only)
- (default) = balanced
- `-v` = more detail (what's happening)
- `-vv` = internals (how it works)

## First Implementation: Navigation Verbosity

For the demo bench, we expressed verbosity as **navigation position**:
- `-q`: print inline, exit
- default: start at main slides
- `-v`: start at detail slides
- `-vv`: start at source slides

Key insight: **verbosity = starting zoom level, not structure transformation**. The content graph stays the same; only the entry point changes.

This led to the principle: **Content is structure. View is position.**

## The CLI → TUI Continuum

Verbosity can move you along an output sophistication spectrum:

```
Level 0: Plain text (no styling)
Level 1: Styled text (ANSI, inline)
Level 2: Composed layout (boxes, borders, still inline)
Level 3: Interactive TUI (alternate screen)
Level 4: Rich TUI (layers, modals, complex state)
```

The same primitives (Block, Span) work across levels. `print_block()` for inline, `RenderApp` for TUI. Content is mode-agnostic.

## The LensView Concept Emerges

What if the same content could be rendered differently at different zoom levels?

```python
Lens[T] = Callable[[T, int], Block]  # (content, zoom) -> Block
```

Example: JSON at zoom levels
- zoom 0: `{"users": 3}` (count)
- zoom 1: `{"users": ["alice", "bob", "charlie"]}` (keys)
- zoom 2: full structure with all fields

This is **projection verbosity** - same content, different visual projections.

## Connection to rill

Looking at rill's Projection primitive:

```python
class Projection[S, T]:
    def apply(self, state: S, event: T) -> S  # fold
```

rill's Projection is a **fold** - stateful, accumulates events into derived state.

The cells Lens is a **map** - stateless, transforms state into Block at a zoom level.

## The Full Pipeline

```
Events → Projection → State → Lens → Block
              ↑                  ↑
          fold ops           zoom level
           (rill)             (cells)
```

**rill owns data transformation** (events → state)
**cells owns visual transformation** (state → Block)

They're peers across domains, not the same thing.

## Vocabulary Resolution

| Layer | Primitive | Signature | Nature |
|-------|-----------|-----------|--------|
| rill | Projection | `(State, Event) -> State` | Fold (stateful) |
| cells | Lens | `(State, zoom) -> Block` | Map (stateless) |

"Projection" stays with rill. "Lens" is the cells vocabulary for visual transformation.

## What experiments Already Had

The "convention-based rendering" in experiments is an implicit lens:
- dict → table
- list → list-view
- set → tags

State shape determines rendering. The Lens primitive makes this explicit and adds the zoom dimension.

## Design Decisions

1. **Lens is a pure function** - no internal state. Zoom is passed in, not owned.

2. **Zoom is an aspect of rendering** - may expand to other dimensions later (width, focus, etc.)

3. **ShapeLens for conventions** - dict→table, list→list-view. CustomLens for app-specific rendering.

4. **Components = Lens + state machine** - the render half of a component IS a lens.

## Implementation Path

1. Add `Lens` type to cells core
2. Implement `ShapeLens` for convention-based rendering
3. Demo: JSON inspector with zoom levels
4. Integrate with verbosity flags

## Open Questions

- How do lenses compose? (parallel rendering at same zoom vs. nested zoom)
- Zoom propagation policy: global, independent, or relative?
- Should Lens report preferred size per zoom level?

## Key Insight

The demo's "navigation verbosity" and the Lens concept are both expressions of the same underlying pattern: **same content, different views based on a zoom/detail parameter**.

Navigation verbosity changes *which content* you start at.
Lens/projection verbosity changes *how content renders*.

Both are valid. The right choice depends on whether your content is a graph (navigation) or a value (projection).
