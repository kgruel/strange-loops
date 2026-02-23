# fidelis Hierarchy

Reference for how primitives compose.

```
                           FIDELIS HIERARCHY
═══════════════════════════════════════════════════════════════════

ATOMIC LAYER
─────────────────────────────────────────────────────────────────
  Cell            one character + one Style
  Style           fg, bg, bold, dim, italic, underline, reverse


CONTENT LAYER
─────────────────────────────────────────────────────────────────
  Span            styled text fragment
  Line            sequence of Spans (horizontal)
  Block           2D rectangle of Cells, immutable, known dimensions


CANVAS LAYER
─────────────────────────────────────────────────────────────────
  Buffer          2D grid of Cells (mutable, the drawing surface)
  BufferView      clipped, translated region of Buffer


PROJECTION LAYER
─────────────────────────────────────────────────────────────────
  Lens            (State, zoom) -> Block, pure function
                  transforms arbitrary content into visual representation
                  zoom controls detail level (summary → structure → full)

  ShapeLens       convention-based: dict→table, list→list-view, set→tags
  CustomLens      app-defined rendering at zoom levels


COMPOSITION LAYER
─────────────────────────────────────────────────────────────────
  join_horizontal combine Blocks side-by-side
  join_vertical   combine Blocks stacked
  pad             add spacing around Block
  border          wrap Block with border characters
  truncate        clip Block to size


APPLICATION LAYER
─────────────────────────────────────────────────────────────────
  Writer          ANSI escape output, terminal detection
  print_block     inline output (no TUI)
  KeyboardInput   non-blocking key reader
  Surface       async main loop, alt screen, diff rendering


STATE/INTERACTION LAYER
─────────────────────────────────────────────────────────────────
  Focus           component focus management (plus ring navigation)
  Layer           modal stacking
  Search          filtered selection


COMPONENTS (stateful widgets)
─────────────────────────────────────────────────────────────────
  spinner         animated indicator
  progress_bar    percentage display
  list_view       scrollable selection
  text_input      editable text field
  table           columnar data
```

## The Full Pipeline (with vertex)

```
═══════════════════════════════════════════════════════════════════
                    DATA → VISUAL TRANSFORMATION
═══════════════════════════════════════════════════════════════════

  Events ──→ Projection ──→ State ──→ Lens ──→ Block
                 ↑                      ↑
             fold ops               zoom level
              (vertex)                (fidelis)

  vertex owns DATA transformation:
    Projection[S, E]: fold events into derived state
    Stateful, incremental, O(new events)

  fidelis owns VISUAL transformation:
    Lens[S]: render state at zoom level into Block
    Stateless, pure, convention-driven
```

## Vocabulary

| Layer | Primitive | Signature | Nature |
|-------|-----------|-----------|--------|
| vertex | Projection | `(State, Event) -> State` | Fold (stateful) |
| fidelis | Lens | `(State, zoom) -> Block` | Map (stateless) |

They're **peers across domains**. Projection is vertex vocabulary. Lens is fidelis vocabulary.

## Zoom Levels

Lens renders state at different detail levels:

```
zoom 0: summary    {"users": 3}
zoom 1: structure  {"users": ["alice", "bob", "charlie"]}
zoom 2: full       {"users": [{"id": 1, "name": "alice", ...}, ...]}
```

Same state, different visual projection. Fidelity flags (`-v`, `-vv`) map to zoom levels.
