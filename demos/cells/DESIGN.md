# Tour Design

How prism teaches its concepts. This pattern originates here, in the cells
tour, but it generalizes to any library or system that builds up from
composable primitives.

## The Spatial Model

Three axes of navigation. Each core concept is a **column** — a vertical
slice with depth in both directions.

### Horizontal (Left/Right): The Dependency Chain

The main axis walks the build-up sequence. Each stop depends on the ones
before it:

    Cell → Style → Span → Line → Block → Buffer → Lens → Surface

The first six stops teach **construction** — how to build visual output
from primitives. The last two teach **orchestration** — how the output
comes alive in a running application. This is a natural difficulty curve,
not a genre shift.

### Down: Detail and Verbosity

Each stop expands downward into implementation detail, API surface, edge
cases, internals. The "tell me more" axis.

### Up: Visual, Fun, Concepts

Each stop expands upward into demonstrations, compositions, visual
payoffs, conceptual framing. The "show me" axis.

## Where Concepts Live

Not every concept is a horizontal stop. The horizontal axis is reserved
for the **dependency chain** — things that build on each other in sequence.

Operations and emergent behaviors attach to their parent concept on the
vertical axes:

- **Composition** (join, pad, border, truncate) — operations on Blocks.
  Lives "up" from Block. It's the visual payoff of understanding Block.
- **BufferView** — a clipped region of Buffer. Lives "down" from Buffer
  (implementation detail).
- **Writer** — ANSI output mechanism. Lives "down" from Surface
  (how output reaches the terminal).
- **Layer, FocusRing** — modal stacking and focus navigation. Live "up"
  from Surface (interactive concepts).

The test: does this concept **depend on all prior stops** and **enable
the next one**? If yes, it's a horizontal stop. If it's an operation on,
detail of, or demonstration of an existing stop, it belongs on the
vertical axis.

## The Self-Referential Payoff

By the Surface stop, the tour points at itself: you're inside a Surface
right now, with Lenses rendering each stop as a Block. The abstraction
becomes concrete because you've been experiencing it the whole time.

## Extensibility

New core concept → new column, slotted by dependency order. Each column
grows independently on the vertical axes. The tour gains a stop without
restructuring.

## Verbosity Mapping

The CLI flags map directly to this model:

    -q          Print all slides inline, exit (no TUI)
    (default)   Interactive horizontal navigation
    -v          Detail (down) slides included in main flow
    -vv         Source code view toggle

## The General Pattern

This spatial model isn't specific to cells. Any library with a composable
primitive hierarchy can use the same axes:

- **Horizontal**: the dependency chain of core concepts
- **Down**: depth into each concept
- **Up**: that concept in action

The tour is the first implementation. The pattern is the lasting artifact.
