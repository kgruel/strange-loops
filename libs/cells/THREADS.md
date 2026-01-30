# THREADS — cells

## Feedback loop — implemented
RenderApp renamed to Surface. Emit protocol added: `Emit = Callable[[str, dict], None]`.
Surface accepts `on_emit` callback, provides `emit(kind, **data)` method.
Auto-emits `"ui.key"` after each keypress and `"ui.resize"` on terminal resize.
The callback is structurally compatible with `Fact.of(kind, **data)` — the
integration layer wires `on_emit` to `Fact.of()` + `Stream.emit()`.
No cross-lib imports; cells stays independent.

## ShapeLens extensions
Current shape_lens renders by convention: dict->table, list->list-view,
set->inline tags, scalar->formatted value. Discussed extensions:
- Tree lens (nested structures)
- Chart lens (numeric data)
- Other convention-based renderers

## Zoom propagation
In composed views with multiple Lenses, how does zoom propagate?
Options: global (all lenses zoom together), independent (each lens
has its own zoom), relative (child zoom is offset from parent).
Not yet decided.

## CLI -> TUI continuum
Fidelity as a spectrum from plain text (Level 0) through styled text
(Level 1), composed layout (Level 2), interactive TUI (Level 3), to
full application (Level 4). print_block() bridges Level 1-2. The
continuum pattern is documented in demos/FIDELITY.md.

## Block serialization — multi-format output
Cells' rendering pipeline is terminal-agnostic up to Block. The only
terminal-specific code is writer.py (ANSI output), keyboard.py (input
parsing), and app.py (Surface runtime). Nothing else in the lib knows
what ANSI is.

This means Block is a natural serialization boundary. A Block is a 2D
grid of styled characters — it can be converted to any grid-compatible
format:

    Block → ANSI    (Writer — exists today)
    Block → HTML    (<pre>/<span> with inline CSS or classes)
    Block → JSON    (structured cell grid with style metadata)
    Block → text    (strip styles, keep chars)
    Block → SVG     (rendered monospace grid)

Combined with Lens (zoom 0/1/2), this gives any shaped state a
multi-format export path:

    shaped state → Lens (filter/zoom) → Block → serializer

Use cases:
- TUI snapshot: capture current Buffer as HTML for sharing/debugging
- Webhook output: render shaped state at zoom 0 as compact JSON
- Report generation: same lens pipeline → HTML or text instead of ANSI
- Testing: assert on Block content without terminal

The grid primitives (Cell, Block, Buffer, Span, compose, Lens, Layer,
components) are already terminal-agnostic. The serializers would be
small functions: block_to_html(), block_to_json(), block_to_text().

Open question: where do serializers live? Options:
- In cells alongside writer.py (serializers are output adapters)
- In a separate cells/export.py or cells/serialize.py
- As standalone functions users write (cells just provides the Block)

Related: the internal split between grid primitives (terminal-agnostic)
and terminal adapter (writer, keyboard, app) is clean today. Making it
explicit in the module structure would make the serialization story
obvious. See "Grid surface vs terminal adapter" below.

## Grid surface vs terminal adapter
The cells dependency graph has a clean split:

    Layer 1-3: cell, buffer, block, span, compose, borders,
               region, lens, layer, focus, search, theme,
               components — all terminal-agnostic

    Layer 4:   writer, keyboard, app (Surface) — terminal-specific

Nothing in layers 1-3 imports from layer 4. The terminal adapter is
a leaf dependency.

Making this split explicit (subpackage, separate __init__ exports, or
just documented convention) would clarify that cells is a grid surface
library with a terminal adapter, not a terminal library. A future
HTML or API surface would consume the same grid primitives.

Where it falls down:
- No Surface protocol/ABC to program against (Surface IS the terminal)
- Layer.handle() takes `key: str` — keyboard-centric, not event-generic
- Components assume keyboard interaction (j/k navigation, char input)
- Emit wiring flows through keyboard → layer → handler → emit

The rendering side (shaped state → Lens → Block) is fully portable
today. The interaction side (events → layer → state changes → emit)
would need an event abstraction to generalize beyond keyboard input.
