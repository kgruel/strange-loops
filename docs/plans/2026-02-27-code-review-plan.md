# Code Review Plan -- painted

**Date:** 2026-02-27
**Scope:** Full codebase review of `painted`, a terminal UI framework built on cell buffers.
**Total source LOC:** ~6,878 (38 Python files under `src/painted/`)
**Total test LOC:** ~10,954 (57 test files)

## How to use this document

This plan breaks the codebase into 8 independent review domains. Each domain can be handed to a separate review agent with:

1. The domain section from this document (files, criteria, invariants)
2. The agent review template at the bottom
3. Access to the source files listed

Domains are ordered by dependency: review lower-numbered domains first, as higher domains depend on them. Domains 1-3 have no cross-dependencies and can be reviewed in parallel.

---

## Codebase Map

### Module inventory (sorted by LOC, descending)

| File | LOC | Role |
|------|-----|------|
| `_lens.py` | 1019 | Lens functions: shape, tree, chart, flame |
| `fidelity.py` | 492 | CLI harness: zoom, mode, format, CliRunner |
| `writer.py` | 410 | ANSI output, color conversion, print_block |
| `app.py` | 382 | Surface base class, render loop, scroll optimization |
| `big_text.py` | 378 | Block-character text rendering (glyph tables) |
| `compose.py` | 354 | Block composition: join, pad, border, truncate |
| `_components/data_explorer.py` | 330 | Interactive tree navigation |
| `block.py` | 318 | Block: immutable cell rectangle, wrapping |
| `buffer.py` | 268 | Buffer/BufferView: 2D cell grid, diff, scroll |
| `keyboard.py` | 243 | Cbreak input, escape sequence parsing |
| `__init__.py` | 217 | Package exports, `show()` function |
| `_components/table.py` | 174 | Table component |
| `_mouse.py` | 160 | Mouse event types, SGR parsing |
| `_components/text_input.py` | 151 | Text input component |
| `tui/testing.py` | 148 | TestSurface harness |
| `_components/sparkline.py` | 134 | Sparkline component |
| `_components/list_view.py` | 126 | Scrollable list component |
| `layer.py` | 110 | Layer stack: modal input/render |
| `span.py` | 108 | Span/Line: styled text |
| `_timer.py` | 107 | Frame timer for profiling |
| `inplace.py` | 106 | In-place terminal animation |
| `_text_width.py` | 99 | Display width utilities (wcwidth wrappers) |
| `search.py` | 94 | Search state, filter functions |
| `viewport.py` | 92 | Scroll state primitive |
| `icon_set.py` | 90 | Glyph vocabulary, ContextVar |
| `_sparkline_core.py` | 85 | Sparkline text generation |
| `focus.py` | 85 | Focus state, navigation helpers |
| `palette.py` | 79 | Semantic style roles, ContextVar |
| `_components/spinner.py` | 74 | Spinner component |
| `cursor.py` | 71 | Bounded index cursor |
| `_components/progress.py` | 70 | Progress bar component |
| `cell.py` | 62 | Cell, Style, EMPTY_CELL |
| `tui/__init__.py` | 56 | TUI subpackage re-exports |
| `_components/__init__.py` | 33 | Components re-exports |
| `region.py` | 21 | Named buffer region |
| `borders.py` | 20 | Border character presets |
| `mouse/__init__.py` | 12 | Mouse subpackage re-exports |
| `views/__init__.py` | 100 | Views subpackage re-exports |

### Dependency graph (who imports whom)

```
Layer 0 -- Zero internal dependencies
  cell.py

Layer 1 -- Depends only on cell
  buffer.py        -> cell
  palette.py       -> cell
  borders.py       (standalone dataclass)
  cursor.py        (standalone dataclass)
  _text_width.py   (standalone, wcwidth)

Layer 2 -- Depends on Layer 0-1
  _mouse.py        (standalone)
  viewport.py      (standalone dataclass)
  focus.py         (standalone dataclass)
  search.py        -> cursor
  span.py          -> cell, buffer
  block.py         -> cell, buffer, _text_width
  _sparkline_core.py (standalone)
  icon_set.py      (standalone)

Layer 3 -- Depends on Layer 0-2
  compose.py       -> block, borders, cell, _text_width
  writer.py        -> cell, buffer
  layer.py         -> buffer
  region.py        -> buffer
  keyboard.py      -> _mouse

Layer 4 -- Depends on Layer 0-3
  inplace.py       -> writer, block
  big_text.py      -> block, cell, compose
  app.py           -> _mouse, buffer, keyboard, layer, writer
  fidelity.py      -> block, icon_set, writer, inplace, cell, palette

Layer 5 -- Components (depend on Layers 0-3)
  _components/spinner.py       -> block, cell, cursor, icon_set
  _components/progress.py      -> block, cell, icon_set, palette
  _components/list_view.py     -> block, buffer, cell, cursor, span, viewport
  _components/text_input.py    -> block, cell, _text_width
  _components/table.py         -> block, buffer, cell, compose, cursor, span, viewport
  _components/sparkline.py     -> block, cell, _sparkline_core, icon_set, palette
  _components/data_explorer.py -> block, cell, compose, cursor, viewport, _text_width

Layer 6 -- Lenses (depend on Layers 0-3)
  _lens.py         -> block, cell, compose, _text_width, _sparkline_core, icon_set

Layer 7 -- Public subpackages (re-export assemblies)
  __init__.py      -> (most Layer 0-4 modules)
  tui/__init__.py  -> app, buffer, cursor, focus, keyboard, layer, region, search, testing
  views/__init__.py-> _components, _lens, big_text, icon_set, palette
  mouse/__init__.py-> _mouse
  tui/testing.py   -> app, buffer, writer, _mouse
```

---

## Review Domains

### Domain 1: Primitives (Cell, Style, Span, Line)

**Files:**
- `/Users/kaygee/Code/painted/src/painted/cell.py` (62 LOC)
- `/Users/kaygee/Code/painted/src/painted/span.py` (108 LOC)
- `/Users/kaygee/Code/painted/src/painted/_text_width.py` (99 LOC)

**Total LOC:** 269

**What to look for:**
- **Correctness:** Cell char validation (single character only). Style.merge semantics (does "other overrides non-None/non-False" work correctly for all combinations?). Span.width fallback when wcswidth returns -1.
- **Immutability:** Both Cell and Style are `frozen=True`. Span and Line are `frozen=True, slots=True`. Verify no mutation escapes.
- **Wide character handling:** Line.truncate cuts character-by-character. Does it handle wide chars (wcwidth=2) correctly at boundaries? Does Line.to_block handle wide chars?
- **API design:** `Color = str | int | None` type alias -- is this validated anywhere when constructing Style? Named color lookup happens in Writer, not in Style. Is this the right boundary?
- **Performance:** Span.width calls wcswidth on every access (no caching). Is this a concern for hot paths?
- **_text_width.py:** `display_width`, `char_width`, `truncate`, `truncate_ellipsis`, `index_for_col`, `take_prefix` -- these are used everywhere. Are edge cases handled (empty string, zero width, negative width, combining characters)?

**Key invariants:**
- Cell char is exactly 1 character (validated in `__post_init__`)
- Style.merge: `other` wins for non-None/non-False fields, boolean fields OR together
- All types are frozen dataclasses

**Cross-cutting concerns:**
- Span imports from buffer (for BufferView type in Line.paint) -- is this a layering concern?
- _text_width is used by block.py, compose.py, _lens.py, text_input.py, data_explorer.py

**Relevant tests:**
- `test_span.py` (208 LOC)
- `test_wide_char.py` (103 LOC)
- `test_text_width_extended.py` (190 LOC)

**Estimated effort:** Small (1-2 hours)

---

### Domain 2: Block and Composition

**Files:**
- `/Users/kaygee/Code/painted/src/painted/block.py` (318 LOC)
- `/Users/kaygee/Code/painted/src/painted/compose.py` (354 LOC)
- `/Users/kaygee/Code/painted/src/painted/borders.py` (20 LOC)

**Total LOC:** 692

**What to look for:**
- **Immutability enforcement:** Block uses manual `object.__setattr__` and a `_frozen` flag. Is this robust? Can it be circumvented? Why not use `__slots__` + `frozen` dataclass instead?
- **Width invariant:** Every row in a Block must have exactly `width` cells. This is checked in `__debug__` only -- what happens in optimized mode (`-O`)?
- **Block.text wrapping:** NONE, CHAR, WORD, ELLIPSIS modes. Edge cases: width=0, width=1, empty string, very long words, wide characters in wrapped text.
- **Composition correctness:** `join_horizontal` alignment, `join_vertical` alignment, `pad`, `border` with title. Do widths always add up correctly? Are ids propagated correctly through all composition operations?
- **id system:** Block has `id` (uniform) and `_ids` (per-cell). Composition functions must propagate these correctly through join/pad/border/truncate/vslice. This is complex -- verify each function handles both cases.
- **Border title rendering:** The title painting logic in `compose.border()` is complex with wide-char handling. Is it correct when title contains wide characters?
- **Performance:** `_cells_from_text` and `_char_wrap` iterate character-by-character. Block.paint iterates cell-by-cell. Are there O(n^2) risks with large blocks?
- **`_pad_row` function:** Creates new list cells each time. Could this be a hot path in wrapping?

**Key invariants:**
- `Block._rows[i]` has exactly `Block.width` cells for all i
- `Block._ids` (if present) has same dimensions as `_rows`
- Block is immutable after construction
- `join_horizontal` output width = sum of widths + gaps
- `join_vertical` output width = max of widths

**Cross-cutting concerns:**
- Block._ids accessed directly (private attribute) by compose.py functions via `block._ids` -- this breaks encapsulation
- Block imports from buffer (for paint method)

**Relevant tests:**
- `test_block_extended.py` (336 LOC)
- `test_compose.py` (222 LOC)
- `test_compose_extended.py` (564 LOC)

**Estimated effort:** Medium (2-3 hours)

---

### Domain 3: State Primitives (Cursor, Viewport, Focus, Search)

**Files:**
- `/Users/kaygee/Code/painted/src/painted/cursor.py` (71 LOC)
- `/Users/kaygee/Code/painted/src/painted/viewport.py` (92 LOC)
- `/Users/kaygee/Code/painted/src/painted/focus.py` (85 LOC)
- `/Users/kaygee/Code/painted/src/painted/search.py` (94 LOC)

**Total LOC:** 342

**What to look for:**
- **Immutability:** All four are `frozen=True, slots=True`. Verify `__post_init__` in Cursor uses `object.__setattr__` correctly for normalization of frozen fields.
- **Cursor normalization:** CLAMP vs WRAP semantics. Does `__post_init__` always produce valid state? What about `count=0` with `index=5`?
- **Viewport clamping:** `_clamp` ensures offset is in `[0, max_offset]`. Does `scroll_into_view` handle edge cases (index=0, index=content-1, content < visible)?
- **Focus navigation:** `ring_next`/`ring_prev` and `linear_next`/`linear_prev` use `list(items).index(current)` which is O(n). Is this acceptable? What if `current` is not in `items`?
- **Search state:** `select_next`/`select_prev` delegate to Cursor with WRAP mode. `filter_fuzzy` is O(n*m) where m is query length. Is the fuzzy matching algorithm correct?
- **API consistency:** Do all state types follow the same patterns? (frozen, return new instance, no mutation)

**Key invariants:**
- Cursor.index is always in [0, count-1] (CLAMP) or [0, count-1] mod count (WRAP), or 0 when count=0
- Viewport.offset is always in [0, max_offset]
- Focus.captured is boolean; focus/capture/release always return new Focus
- Search.selected resets to 0 on type/backspace/clear

**Cross-cutting concerns:**
- Cursor is used by spinner, list_view, table, data_explorer, search
- Viewport is used by list_view, table, data_explorer

**Relevant tests:**
- `test_cursor.py` (51 LOC)
- `test_viewport.py` (203 LOC)
- `test_focus.py` (126 LOC)
- `test_search.py` (178 LOC)

**Estimated effort:** Small (1-2 hours)

---

### Domain 4: Buffer, Writer, and Terminal Output

**Files:**
- `/Users/kaygee/Code/painted/src/painted/buffer.py` (268 LOC)
- `/Users/kaygee/Code/painted/src/painted/writer.py` (410 LOC)
- `/Users/kaygee/Code/painted/src/painted/inplace.py` (106 LOC)

**Total LOC:** 784

**What to look for:**
- **Buffer correctness:** `_index` bounds checking. `diff` compares cell-by-cell -- does it handle different-sized buffers? `line_hashes` uses a custom hash function -- is it collision-resistant enough for scroll detection? `scroll_region_in_place` -- are the index calculations correct for both positive and negative n?
- **BufferView clipping:** `_clip` returns `None` for out-of-bounds. `put` checks `if pos:` -- this works because `(0, 0)` is truthy (non-empty tuple), but `if pos is not None:` would be clearer intent. Verify all call sites use the same pattern consistently.
- **Writer color conversion:** `_rgb_to_256` does linear search over 240 colors -- is this acceptable for hot paths? Color downgrade chain: truecolor -> 256 -> 16. Are there edge cases in hex parsing (3-char hex, invalid hex)?
- **Writer.write_ops:** Synchronized output (mode 2026). Handles ScrollOp and CellWrite in mixed stream. Wide character tracking via `covered` set. Is the cursor position tracking correct after scroll ops?
- **Writer.write_frame type ignore:** `write_frame` calls `write_ops` with a `list[CellWrite]` but `write_ops` expects `list[RenderOp]`. The `# type: ignore` comment suggests this is known.
- **InPlaceRenderer:** Context manager safety. `render()` outside context raises RuntimeError. `finalize()` shows cursor. Clear logic: move up, clear lines, move back. Is the line count tracking correct when block height changes between frames?
- **print_block:** Plain text path just writes characters -- does it handle wide characters correctly? (Wide char occupies 2 columns but the char itself is 1 code point.)

**Key invariants:**
- Buffer._cells always has width * height elements
- Buffer._ids is None or has width * height elements
- Writer applies synchronized output brackets around write_ops
- InPlaceRenderer._height tracks previous frame height for correct cursor movement

**Cross-cutting concerns:**
- Buffer.diff is the hot path for Surface rendering
- Writer is used by Surface, InPlaceRenderer, TestSurface, print_block
- `_write_block_ansi` shared between print_block and InPlaceRenderer

**Relevant tests:**
- `test_buffer_extended.py` (435 LOC)
- `test_writer_extended.py` (403 LOC)
- `test_writer_coalescing.py` (113 LOC)
- `test_color_downconversion.py` (197 LOC)
- `test_inplace_renderer.py` (118 LOC)

**Estimated effort:** Medium-Large (3-4 hours)

---

### Domain 5: Surface, Layer, Keyboard, and Mouse

**Files:**
- `/Users/kaygee/Code/painted/src/painted/app.py` (382 LOC)
- `/Users/kaygee/Code/painted/src/painted/layer.py` (110 LOC)
- `/Users/kaygee/Code/painted/src/painted/keyboard.py` (243 LOC)
- `/Users/kaygee/Code/painted/src/painted/_mouse.py` (160 LOC)
- `/Users/kaygee/Code/painted/src/painted/tui/testing.py` (148 LOC)

**Total LOC:** 1,043

**What to look for:**
- **Surface run loop:** Async main loop with SIGWINCH handling. Does the adaptive sleep (0.001s active, 1/fps_cap idle) prevent busy-waiting? Is the `_dirty` flag race-safe (single-threaded async, but signal handler sets it)?
- **Scroll optimization:** `_detect_vertical_scroll` is O(height^2 * max_n) with nested loops. Is this acceptable for 60fps at reasonable terminal sizes? The `min_match_ratio` and `distinct` check -- are these heuristics robust? Could false positives cause visual glitches?
- **Layer stack:** `process_key` modifies only the top layer. Pop never removes the base layer. Push adds on top. Are there edge cases with empty stacks? Does `replace(top, state=new_layer_state)` work correctly with generic Layer[S]?
- **Keyboard parsing:** Escape sequence timeout (50ms). Does this cause problems on slow SSH connections? CSI parsing accumulates params until final byte -- is there a max length guard? UTF-8 multi-byte handling -- does it handle malformed sequences?
- **Mouse SGR parsing:** Bit manipulation for button, modifiers, motion detection. Are scroll button values (64-67) correctly extracted from `high_bits + button_bits`? Is coordinate conversion (1-indexed to 0-indexed) correct?
- **TestSurface:** Deterministic runner. Accesses `surface._running`, `surface._dirty`, `surface._buf`, `surface._prev`, `surface._writer`, `surface._on_emit` -- all private attributes. Is this fragile?
- **Signal safety:** SIGWINCH handler calls `self._on_resize()` which allocates new Buffers. Is this safe from within a signal handler in async context?
- **Terminal cleanup:** Is the finally block in `Surface.run()` robust enough? What if `exit_alt_screen` or `show_cursor` fails?

**Key invariants:**
- Layer stack: base layer never pops (enforced by `len(layers) > 1` check)
- Surface: alt screen entered on run, exited in finally
- Keyboard: complete escape sequences are always drained (no partial sequences left in buffer)
- Mouse: coordinates are 0-indexed in MouseEvent

**Cross-cutting concerns:**
- Surface.emit is the feedback boundary for the whole framework
- TestSurface breaks encapsulation of Surface internals
- KeyboardInput requires Unix (termios, tty) -- no Windows support

**Relevant tests:**
- `test_surface.py` (190 LOC)
- `test_surface_harness.py` (173 LOC)
- `test_layer.py` (475 LOC)
- `test_keyboard.py` (50 LOC)
- `test_keyboard_sequences.py` (194 LOC)
- `test_mouse.py` (160 LOC)
- `test_mouse_sgr.py` (136 LOC)
- `test_scroll_optimization.py` (149 LOC)
- `test_hit_testing.py` (99 LOC)
- `test_lifecycle.py` (175 LOC)
- `test_discord_chat.py` (125 LOC)

**Estimated effort:** Large (4-5 hours)

---

### Domain 6: Components (Spinner, Progress, List, Table, TextInput, Sparkline, DataExplorer)

**Files:**
- `/Users/kaygee/Code/painted/src/painted/_components/spinner.py` (74 LOC)
- `/Users/kaygee/Code/painted/src/painted/_components/progress.py` (70 LOC)
- `/Users/kaygee/Code/painted/src/painted/_components/list_view.py` (126 LOC)
- `/Users/kaygee/Code/painted/src/painted/_components/table.py` (174 LOC)
- `/Users/kaygee/Code/painted/src/painted/_components/text_input.py` (151 LOC)
- `/Users/kaygee/Code/painted/src/painted/_components/sparkline.py` (134 LOC)
- `/Users/kaygee/Code/painted/src/painted/_components/data_explorer.py` (330 LOC)
- `/Users/kaygee/Code/painted/src/painted/_sparkline_core.py` (85 LOC)

**Total LOC:** 1,144

**What to look for:**
- **State + render pattern compliance:** Each component should follow `FrozenState + pure_render_fn(state, ...) -> Block`. Verify no mutation in render functions.
- **Spinner:** Does `ic != IconSet()` comparison work correctly for detecting non-default icons? This creates a new IconSet on every call for comparison.
- **Progress bar:** `round(state.value * width)` -- is this the right rounding for visual accuracy? Could `filled_count + empty_count != width` due to rounding?
- **List view:** Buffer-based rendering. `max_width` calculation includes all visible items -- could this be expensive for large lists? The temporary Buffer allocation per render -- is this wasteful?
- **Table:** Similar buffer-based approach. Column width management. Separator rendering (`|` and `+`). Does `_pad_line` handle the Align.CENTER case correctly (left = padding // 2, right = padding - left)?
- **Text input:** Scroll offset tracking per character index. `_ensure_visible` does display_width calculations that could be O(n) for long text. Wide character cursor positioning -- does it work correctly?
- **Sparkline:** Two APIs (`sparkline` and `sparkline_with_range`). Both delegate to `_sparkline_core.sparkline_text`. Sampling strategies (tail, uniform). Edge cases: empty values, single value, width=1.
- **Data explorer:** `flatten()` is called on every property access (`self.nodes`). This is O(n) where n is expanded tree size. Multiple operations call `self.nodes` multiple times -- is this a performance concern?
- **_sparkline_core:** `_map_to_chars` index calculation: `int(ratio * (num_levels - 1))`. Is this correct at boundaries (ratio=0.0, ratio=1.0)?

**Key invariants:**
- All state types are frozen
- Render functions are pure (no side effects, no state mutation)
- Components respect Palette/IconSet ambient context
- ListState and TableState compose Cursor + Viewport

**Cross-cutting concerns:**
- Components import from parent package using `..` relative imports
- Palette and IconSet accessed via ContextVar in render functions (not state)
- DataExplorerState.nodes recomputes on every access

**Relevant tests:**
- `test_spinner_state.py` (15 LOC)
- `test_progress_bar.py` (63 LOC)
- `test_list_state.py` (34 LOC), `test_list_render.py` (211 LOC)
- `test_table_state.py` (34 LOC), `test_table_render.py` (307 LOC)
- `test_text_input_render.py` (317 LOC)
- `test_sparkline_themed.py` (59 LOC), `test_sparkline_core.py` (147 LOC)
- `test_data_explorer.py` (191 LOC)

**Estimated effort:** Medium-Large (3-4 hours)

---

### Domain 7: Lenses and Big Text

**Files:**
- `/Users/kaygee/Code/painted/src/painted/_lens.py` (1,019 LOC)
- `/Users/kaygee/Code/painted/src/painted/big_text.py` (378 LOC)

**Total LOC:** 1,397

**What to look for:**
- **shape_lens dispatch:** Auto-dispatches by data shape. Is the priority order correct? (bool before int, numeric before hierarchical, etc.) What happens with edge cases: empty dict, empty list, single-element dict with numeric value?
- **Recursive zoom reduction:** Nested rendering reduces zoom by 1 each level. At zoom=0, shows type/count only. Does recursion terminate correctly? Could deeply nested data cause stack overflow?
- **tree_lens:** Handles dicts, tuples, and objects with `.children`. Branch character rendering. Does `_tree_render_children_themed` handle empty children lists? Are tree prefix widths calculated correctly for deeply nested trees?
- **chart_lens:** Sparkline at zoom=1, bars at zoom>=3. Bar rendering: proportional fill based on min/max range. Is the percentage detection heuristic (`lo >= 0 and hi <= 100`) too broad?
- **flame_lens:** Proportional width allocation with two-pass algorithm. Width stealing from large segments to fit labels. Is the stealing algorithm stable? Could it loop? Does `_flame_render_levels` recursion handle all termination cases?
- **Duplicate helper:** `_truncate_ellipsis` in _lens.py is a thin wrapper around `truncate_ellipsis` from _text_width.py. Should it be eliminated?
- **Big text:** Glyph tables for 4 variants (3-row filled, 3-row outline, 5-row filled, 5-row outline). Are all glyphs the correct width (3 or 5 chars per row)? Is the fallback character (`\x00`) consistently used? Does `render_big` handle mixed-case correctly (it lowercases)?

**Key invariants:**
- All lens functions share signature: `(data, zoom, width) -> Block`
- shape_lens dispatches are mutually exclusive and exhaustive
- tree_lens recursion depth bounded by zoom level
- flame_lens segment widths sum to available width

**Cross-cutting concerns:**
- _lens.py is the largest single file (1,019 LOC) -- should it be split?
- Lens functions use ambient IconSet for themed characters
- big_text.py glyph tables are large static data -- 250+ LOC of constants

**Relevant tests:**
- `test_lens.py` (658 LOC)
- `test_lens_extended.py` (547 LOC)
- `test_flame_lens.py` (104 LOC)
- `test_big_text.py` (210 LOC)

**Estimated effort:** Large (4-5 hours)

---

### Domain 8: CLI Harness, Aesthetic System, and Package API

**Files:**
- `/Users/kaygee/Code/painted/src/painted/fidelity.py` (492 LOC)
- `/Users/kaygee/Code/painted/src/painted/palette.py` (79 LOC)
- `/Users/kaygee/Code/painted/src/painted/icon_set.py` (90 LOC)
- `/Users/kaygee/Code/painted/src/painted/__init__.py` (217 LOC)
- `/Users/kaygee/Code/painted/src/painted/tui/__init__.py` (56 LOC)
- `/Users/kaygee/Code/painted/src/painted/views/__init__.py` (100 LOC)
- `/Users/kaygee/Code/painted/src/painted/mouse/__init__.py` (12 LOC)
- `/Users/kaygee/Code/painted/src/painted/_components/__init__.py` (33 LOC)
- `/Users/kaygee/Code/painted/src/painted/_timer.py` (107 LOC)
- `/Users/kaygee/Code/painted/src/painted/region.py` (21 LOC)

**Total LOC:** 1,207

**What to look for:**
- **Mode resolution:** `resolve_mode` and `resolve_format` -- are the AUTO collapse rules correct? Does `_setup_defaults` correctly set icons for PLAIN format? Is it correct that palette is never auto-set?
- **CliRunner dispatch:** JSON serialization uses `asdict()` with fallback to raw state. `_run_live` with `fetch_stream` uses `asyncio.run` inside a sync method -- is this safe if already in an async context?
- **Error handling in CliRunner:** `_fetch_error_block` catches palette lookup failure. `_render_error_block` does not use palette. Return codes: 0=ok, 1=fetch error, 2=render error. Are these consistently used?
- **show() function:** Four paths (no args, Block, JSON, lens). The lens path does `_setup_defaults(ctx)` -- does this have side effects (setting ambient icons) that callers might not expect?
- **ContextVar thread safety:** Palette and IconSet use `ContextVar`. Are these safe in async contexts? `use_palette`/`use_icons` have no `reset` token -- changes are permanent for the context.
- **__all__ completeness:** Does `__all__` in each `__init__.py` match the actual imports? Are there symbols imported but not in `__all__`? Are there `__all__` entries that are not imported?
- **Import hygiene:** `views/__init__.py` uses absolute imports (`from painted._components...`) while other `__init__.py` files use relative imports. Is this inconsistent?
- **FrameTimer:** `dump_jsonl` writes profiling data. Is the JSON format documented? Are `phase_names()` order-stable?
- **Region:** Simple wrapper around Buffer.region. Is it used anywhere? (Check if it's only in the tui __init__ re-export.)

**Key invariants:**
- CliContext.mode and CliContext.format are never AUTO after resolution
- Palette has exactly 5 roles: success, warning, error, accent, muted
- IconSet has exactly the glyph slots documented
- __all__ matches actual public API

**Cross-cutting concerns:**
- ContextVar ambient state (palette, icons) affects all lens and component rendering
- fidelity.py imports from many modules (block, cell, palette, icon_set, writer, inplace)
- Package __init__.py is the primary public API surface

**Relevant tests:**
- `test_fidelity.py` (457 LOC)
- `test_fidelity_extended.py` (345 LOC)
- `test_fidelity_defaults.py` (48 LOC)
- `test_palette.py` (70 LOC)
- `test_icon_set.py` (66 LOC)
- `test_icon_set_views.py` (47 LOC)
- `test_show.py` (279 LOC)
- `test_architecture_invariants.py` (143 LOC)
- `test_timer.py` (367 LOC)

**Estimated effort:** Medium (2-3 hours)

---

## Cross-Cutting Review Themes

These themes span multiple domains. Each domain reviewer should flag findings related to these themes for aggregation.

### T1: Frozen / Immutable Data Pattern Compliance

**Pattern:** All state types should be `@dataclass(frozen=True)`. Components follow `State + render_fn(state, ...) -> Block`. No mutation in render functions.

**Check in every domain:**
- Are all state classes frozen?
- Do render functions have side effects?
- Are there mutable collections stored in frozen dataclasses (e.g., list fields)?
- Is `object.__setattr__` used correctly in `__post_init__` for frozen classes?

**Known occurrences to verify:**
- Block uses manual immutability via `_frozen` flag (Domain 2)
- Buffer is mutable by design (Domain 4)
- Cursor normalizes in `__post_init__` using `object.__setattr__` (Domain 3)

### T2: Public API Surface Consistency

**Check across all domains:**
- Parameter naming conventions (is it `style` or `styles`? `width` or `w`?)
- Return type consistency (all lens functions return Block, all state methods return new state)
- Optional parameter patterns (keyword-only after `*`, defaults)
- Type annotation completeness
- Docstring presence and accuracy

### T3: Error Handling Patterns

**Check across all domains:**
- What happens with invalid inputs? (negative width, empty collections, None where not expected)
- Are errors raised early (fail-fast) or silently ignored?
- `__debug__` guards in Block -- validation only in debug mode
- BufferView silently clips out-of-bounds writes
- CliRunner catches broad `Exception` in fetch/render

### T4: Performance Considerations

**Hot paths to examine:**
- Buffer.diff (called every frame in Surface)
- Block.paint (transfers cells to buffer)
- Writer.write_ops (generates ANSI output)
- _detect_vertical_scroll (O(height^2 * max_n) per frame)
- DataExplorerState.nodes (recomputes flatten on every access)
- _rgb_to_256 (linear search over 240 colors)

**Look for:**
- Unnecessary allocations in loops
- Repeated computations that could be cached
- O(n^2) algorithms that should be O(n)
- wcwidth calls that could be batched

### T5: Import Hygiene and Layering

**Check across all domains:**
- Are internal modules (`_lens.py`, `_mouse.py`, `_text_width.py`, `_sparkline_core.py`) only imported by the public API boundary?
- Are there circular import risks? (span.py imports from buffer.py; block.py imports from buffer.py)
- TYPE_CHECKING guards used correctly for forward references?
- Relative vs absolute import consistency (views/__init__.py uses absolute, others use relative)

### T6: Documentation Accuracy

**Check across all domains:**
- Do docstrings match actual behavior?
- Are parameter descriptions accurate?
- CLAUDE.md source layout vs actual file structure (CLAUDE.md mentions `effects/`, `widgets/`, `components/spinner.py` etc. but actual layout uses `_components/`)
- Is the documented API in `__all__` complete and accurate?

---

## Agent Review Template

Copy this section and customize the `[DOMAIN]` placeholder for each review agent.

---

### Review Assignment: [DOMAIN NAME]

**Scope:** You are reviewing the [DOMAIN NAME] domain of the `painted` terminal UI framework.

**Files to review:**
[List of absolute file paths]

**Context:** `painted` is a terminal UI framework (~6,878 LOC) built on cell buffers. All state types are frozen dataclasses. Components follow a `State + render_fn(state) -> Block` pattern. The framework renders by diffing cell buffers and writing only changed cells to the terminal via ANSI escape sequences.

**Review criteria:**
[Domain-specific criteria from this plan]

**Invariants to verify:**
[Domain-specific invariants from this plan]

**Cross-cutting themes to flag:**
- T1: Frozen/immutable compliance
- T2: API surface consistency
- T3: Error handling patterns
- T4: Performance on hot paths
- T5: Import hygiene and layering
- T6: Documentation accuracy

**How to structure findings:**

Use these severity levels:
- **BUG**: Incorrect behavior, will produce wrong output or crash
- **SAFETY**: Missing validation, potential for undefined behavior
- **PERF**: Performance concern on a known hot path
- **DESIGN**: API inconsistency, encapsulation violation, or architectural concern
- **NIT**: Style, naming, or minor improvement suggestion

For each finding, provide:
```
### [SEVERITY] Short title

**File:** /absolute/path/to/file.py
**Line(s):** N-M
**Description:** What the issue is and why it matters.
**Evidence:** Code snippet or reasoning showing the problem.
**Suggestion:** How to fix or improve it (if applicable).
```

**What constitutes a "finding" vs a "nit":**
- A finding is anything that could cause incorrect behavior, has a performance impact on a hot path, or represents a meaningful design concern.
- A nit is a style preference, minor naming suggestion, or improvement that does not affect correctness or performance.

**Cross-domain observations:**
If you notice something that affects a module outside your domain, note it under a "Cross-Domain Observations" section at the end of your review. Include the affected file path and a brief description so it can be routed to the appropriate domain reviewer.

**Expected output format:**
1. **Summary** (2-3 sentences: overall assessment of the domain)
2. **Findings** (ordered by severity, then by file)
3. **Cross-domain observations** (if any)
4. **Statistics** (finding count by severity)

---

## Suggested Review Order

```
Phase 1 (parallel, no dependencies):
  Domain 1: Primitives
  Domain 3: State Primitives

Phase 2 (depends on Phase 1):
  Domain 2: Block and Composition
  Domain 4: Buffer, Writer, Terminal Output

Phase 3 (depends on Phase 2):
  Domain 5: Surface, Layer, Keyboard, Mouse
  Domain 6: Components

Phase 4 (depends on all):
  Domain 7: Lenses and Big Text
  Domain 8: CLI Harness, Aesthetic, Package API
```

## Estimated Total Effort

| Domain | LOC | Estimated Hours |
|--------|-----|-----------------|
| 1. Primitives | 269 | 1-2 |
| 2. Block + Composition | 692 | 2-3 |
| 3. State Primitives | 342 | 1-2 |
| 4. Buffer + Writer | 784 | 3-4 |
| 5. Surface + Layer + Input | 1,043 | 4-5 |
| 6. Components | 1,144 | 3-4 |
| 7. Lenses + Big Text | 1,397 | 4-5 |
| 8. CLI Harness + Package API | 1,207 | 2-3 |
| **Total** | **6,878** | **20-28** |

With 4 parallel reviewers following the phased order, wall-clock time is approximately 8-12 hours.
