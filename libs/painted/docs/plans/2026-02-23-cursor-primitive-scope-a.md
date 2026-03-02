# Cursor primitive + Viewport consistency (Scope A) — Design Plan

Goal: introduce a `Cursor` primitive and adopt it + `Viewport` consistently across navigable widgets, explicitly treating Cursor as a *stored* state primitive (not just a computation helper).

This plan is grounded in current implementations of:

- `Viewport` (`src/painted/viewport.py`)
- `ListState` (`src/painted/_components/list_view.py`)
- `TableState` (`src/painted/_components/table.py`)
- `SpinnerState` (`src/painted/_components/spinner.py`)
- `DataExplorerState` (`src/painted/_components/data_explorer.py`)
- `Search` (`src/painted/search.py`)

Constraints (enforced/observed today):

- All `*State` dataclasses (and primitives like `Search`, `Viewport`) are frozen; enforced by `tests/test_architecture_invariants.py`.
- No new dependencies.
- No module moves / import-path changes.

## 1) Cursor type design

### Location

- New module: `src/painted/cursor.py` (peer to `src/painted/viewport.py`)
- Export from `src/painted/__init__.py` (similar to `Viewport`)
- Consider exporting from `src/painted/tui/__init__.py` if we want Cursor available alongside `Search`/`Focus`

### Dataclass + semantics

- `@dataclass(frozen=True, slots=True)`
- Fields:
  - `index: int = 0`
  - `count: int = 0`
  - `mode: CursorMode = CursorMode.CLAMP` where `CursorMode` is a stdlib `Enum` with `CLAMP` and `WRAP`

Normalization invariants:

- `count <= 0` normalizes to empty (`count = 0`, `index = 0`)
- Clamp mode: `index` is clamped into `[0, count - 1]` (or `0` when empty)
- Wrap mode: `index` wraps with modulo when `count > 0` (or `0` when empty)

Methods (all pure, return new Cursor):

- `with_count(count)`, `move(delta)`, `move_to(index)`
- convenience: `next()`, `prev()`, `home()`, `end()`

## 2) Widget refactor plan (Cursor adoption)

### Cursor-as-helper vs Cursor-as-state

`Viewport` already shows the compositional advantage of “stored primitive”: `DataExplorerState` stores `viewport: Viewport` and therefore has consistent, shared scroll semantics, while `ListState`/`TableState` currently re-implement scroll offset math.

For Scope A, use the same pattern for cursor-bearing widgets:

- `ListState = Cursor(clamp) + Viewport`
- `TableState = Cursor(clamp) + Viewport`
- `DataExplorerState = Cursor(clamp) + Viewport`

Per-type exceptions/justifications:

- `Search`: keep `selected: int` because the domain size (`match_count`) is external by API design (`select_next/prev(match_count)`); a stored `Cursor(count=...)` would be stale unless Search owned the match set.
- `SpinnerState`: spinner is not user-navigated; storing `Cursor(count=len(frames))` duplicates data and requires syncing if `frames` changes. Cursor-as-helper inside `tick()` is sufficient.

Future-scenario divergence (why stored Cursor matters for list/table/data explorer):

- Keyboard shortcut maps: stored Cursor enables a shared “key → cursor op” layer reused across widgets; helper-only keeps each widget duplicating clamp/wrap and count handling.
- Multi-select + range selection: cursor stays “focus row” while selection becomes a separate primitive (`frozenset[int]` or `Selection`); composing primitives keeps invariants isolated and testable.
- Paging/home/end: become cursor ops + viewport.ensure-visible, matching `DataExplorerState`’s existing style.

## 3) Viewport adoption plan (ListState + TableState)

With `viewport: Viewport` stored in list/table state, replace the ad-hoc `scroll_offset` logic with primitive delegation everywhere:

- `scroll_into_view(visible_height)` updates `viewport = viewport.with_visible(visible_height).with_content(cursor.count)` and then `viewport = viewport.scroll_into_view(cursor.index)`.
- Render functions (`list_view`, `table`) compute an effective viewport via `state.viewport.with_visible(...).with_content(len(items|rows))` (same pattern used in `data_explorer()`), then use `vp.offset` for the window start.

## 4) Public API strategy

Primary objective is structural clarity: primitives are the source of truth.

- Keep imports stable (no module reorg).
- Preserve common attribute reads via properties for ergonomics:
  - `ListState.selected/item_count/scroll_offset` (derived)
  - `TableState.selected_row/row_count/scroll_offset` (derived)
- Construction: clean break. Construct with primitives (`cursor=...`, `viewport=...`) and update in-repo call sites (`demos/apps/widgets.py`, fidelity demos, `demos/tour.py`).

## DataExplorer migration note (cursor type change)

If `DataExplorerState.cursor` changes from `int` to `Cursor`, this is a type change on an existing field name. Update all int-uses accordingly:

- `state.cursor` as an index becomes `state.cursor.index` (or a `cursor_index` property).
- Render comparisons like `i == state.cursor` become `i == state.cursor.index`.
- Tests asserting `state.cursor == N` become `state.cursor.index == N`.

## 5) Test strategy

- Add `tests/test_cursor.py` for clamp/wrap + empty-count behavior.
- Update `tests/test_architecture_invariants.py`:
  - include `Cursor` in the AST “must be frozen” set
  - include `Cursor` in runtime “is frozen dataclass” list
- Add targeted widget tests (currently missing):
  - list/table: movement + `scroll_into_view()` delegation correctness
  - spinner: `tick()` wraps
- Keep existing `tests/test_search.py` and `tests/test_data_explorer.py` green.

## 6) Ordering

1. Add `Cursor` primitive + exports + invariant tests.
2. Refactor `Search` selection (Cursor wrap) + run `tests/test_search.py`.
3. Refactor `SpinnerState.tick()` + add spinner tests.
4. Refactor `ListState`/`TableState` selection (Cursor clamp) + add list/table tests.
5. Refactor list/table scrolling to use `Viewport` in state + render paths.
6. Refactor `DataExplorerState` movement math to Cursor(clamp) (fields unchanged).
7. Run full suite (`uv run --package painted pytest tests/ -q`).
