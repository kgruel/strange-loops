# THREADS — cells

## Feedback loop
Cells emitting facts back into ticks — UI observability. When you
interact with a TUI (keypress, selection, navigation), those actions
could become Events on the stream. Discussed in prior sessions, not
implemented. This closes the pipeline loop: you see state through
cells, your actions become facts, facts flow through ticks.

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
