# THREADS — cells

## Feedback loop — implemented
RenderApp renamed to Surface. Emit protocol added: `Emit = Callable[[str, dict], None]`.
Surface accepts `on_emit` callback, provides `emit(kind, **data)` method.
Auto-emits `"key"` after each keypress and `"resize"` on terminal resize.
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
Verbosity as a spectrum from plain text (Level 0) through styled text
(Level 1), composed layout (Level 2), interactive TUI (Level 3), to
full application (Level 4). print_block() bridges Level 1-2. The
continuum pattern is documented in demos/VERBOSITY.md.
