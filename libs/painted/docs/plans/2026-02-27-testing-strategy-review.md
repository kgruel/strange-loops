# Testing Strategy Review — painted

**Date:** 2026-02-27
**Scope:** 1078 tests, 93% line+branch coverage, 0.96s runtime

## Executive Summary

The test suite is strong: fast, well-structured, and already at 93% coverage. The golden test infrastructure is a real asset. Three priorities emerge:

1. **Close the `app.py` gap (75% coverage)** — the largest uncovered module is the real async run loop and scroll optimization. The `TestSurface` harness already solves this for most paths but the low-level `_try_flush_scroll_optimized` and `_detect_vertical_scroll` internals account for most of the 46 missed lines.

2. **Extract shared test helpers** — `_block_to_text` is copy-pasted across 7 files; `_text_block`, `_row_text` are duplicated across 4 files. A `tests/helpers.py` module would remove ~80 lines of duplication and make new tests faster to write.

3. **Add property-based tests for primitives** — `Cell`, `Style`, `Span`, `Line`, `Block` all follow algebraic laws (merge idempotence, truncate monotonicity, width conservation) that are ideal for Hypothesis. This catches edge cases static tests miss.

---

## 1. Coverage Analysis

### Coverage by module (sorted by gap size)

| Module | Stmts | Miss | Branch Miss | Cover | Missing Lines |
|--------|-------|------|-------------|-------|---------------|
| `app.py` | 215 | 46 | 25 | 75% | run loop, mouse input, scroll optim |
| `_components/data_explorer.py` | 144 | 24 | 6 | 81% | page_up/down, home/end, render prefix clamp |
| `keyboard.py` | 129 | 20 | 3 | 86% | `__enter__`/`__exit__`, `_read_byte` real I/O, `get_input` UTF-8 |
| `_mouse.py` | 81 | 6 | 2 | 88% | scroll left/right, unknown scroll value |
| `inplace.py` | 47 | 3 | 4 | 89% | `clear()` outside context (line 86→exit), finalize paths |
| `fidelity.py` | 233 | 23 | 4 | 90% | `_run_live` streaming path (lines 380-399), `_render_error_block` |
| `block.py` | 206 | 14 | 11 | 92% | word wrap edge cases, cell_id fallback |
| `cell.py` | 23 | 1 | 1 | 92% | `Cell.__post_init__` validation for multi-char (line 59) |
| `region.py` | 11 | 1 | 0 | 91% | `Region.view()` (line 21) |
| `_components/sparkline.py` | 33 | 4 | 4 | 80% | `sparkline_with_range` empty values, width<=0 |
| `span.py` | 67 | 2 | 3 | 95% | `Span.width` negative-wcwidth fallback (line 30) |
| `_components/text_input.py` | 98 | 5 | 5 | 93% | `move_word_left`, `move_word_right`, `delete_word_back` |
| `_lens.py` | 404 | 14 | 16 | 95% | dead-code `not rows` guard (line 206), chart bars edge cases |
| `tui/testing.py` | 73 | 3 | 3 | 93% | `_render_and_capture` not-dirty early return, `write_ansi` path |
| `cursor.py` | 41 | 1 | 0 | 98% | `Cursor.with_count` edge (line 46) |

### Gap-by-gap recommendations

**`app.py` (75%, 46 lines missing)** — The real `Surface.run()` loop (lines 59-128) requires async execution with a real terminal, SIGWINCH signals, and keyboard context manager. The `TestSurface` harness deliberately bypasses this. Most of these lines are inherently hard to unit-test without mocking at the system level.

- *Worth covering:* `_try_flush_scroll_optimized` (lines 213-303) — already partially tested in `test_scroll_optimization.py` but branches at lines 230, 237, 251, 279, 291 are missed. These are the "bail out if region too small" and "too many repaints" guards. Add 4-5 targeted tests with small buffers and high-repaint scenarios.
- *Worth covering:* `_on_resize` (lines 199-206) — can be called directly on a Surface with mocked writer.
- *Not worth covering:* Lines 59-128 (the actual `async run()` body) — this is the integration point with the real terminal. The `TestSurface` harness exists precisely to test the same logic without real I/O. Covering these lines would require mocking `asyncio.get_running_loop()`, `signal.SIGWINCH`, `termios`, etc. The ROI is low.
- **Estimated effort:** 2-3 hours for scroll optimization edge cases and `_on_resize`.

**`_components/data_explorer.py` (81%, 24 lines missing)** — `page_up`, `page_down`, `home`, `end`, `with_visible`, and `_format_leaf_value` edge cases (lines 202-265). The existing tests in `test_data_explorer.py` cover `move_up`, `move_down`, `toggle_expand`, `home`, and `end` at the state level but miss `page_up`/`page_down` and some `_format_leaf_value` branches (bool, None, long strings).

- *Worth covering:* All of it. These are simple state transitions.
- **Estimated effort:** 1 hour. Add parameterized tests for `page_up`/`page_down` and `_format_leaf_value` with various types.

**`keyboard.py` (86%, 20 lines missing)** — The real I/O paths: `__enter__`/`__exit__` with `termios`/`tty` (lines 73-86), `_read_byte` with `select`/`os.read` (lines 90-95). The escape sequence parsing is well-tested via `test_keyboard_sequences.py` using mock byte streams.

- *Not worth covering most of it:* Lines 73-86 are terminal setup/teardown that only runs on a real TTY. The existing mock-based approach in `test_keyboard.py` and `test_keyboard_sequences.py` is the right strategy.
- *Worth covering:* Line 151 (`_read_sgr_mouse` returning "escape" on None) — add one test with a partial SGR mouse sequence.
- **Estimated effort:** 30 minutes for the one additional edge case.

**`fidelity.py` (90%, 23 lines missing)** — The `_run_live` streaming path (lines 380-399) using `InPlaceRenderer` with `fetch_stream`. This is the async streaming mode that requires an `AsyncIterator`.

- *Worth covering:* Yes. Create a simple `async def` generator that yields 2-3 states, run through `_run_live`. Also test the error paths within streaming.
- **Estimated effort:** 1.5 hours. Requires async test fixtures.

**`_components/sparkline.py` (80%, 4 lines missing)** — `sparkline_with_range` empty values (line 117) and zero width (line 106).

- *Worth covering:* Yes, trivial.
- **Estimated effort:** 15 minutes. Two test cases.

**`region.py` (91%, 1 line missing)** — `Region.view()` (line 21) is never called in tests.

- *Worth covering:* Yes, trivial. One test.
- **Estimated effort:** 5 minutes.

---

## 2. Test Quality Findings

### Files reviewed

1. `test_span.py` — Span/Line primitives
2. `test_compose.py` — vslice, join_vertical, join_responsive
3. `test_compose_extended.py` — id propagation through compose operations
4. `test_keyboard.py` — KeyboardInput byte handling
5. `test_keyboard_sequences.py` — VT escape sequences
6. `test_lens.py` — shape_lens, tree_lens, chart_lens
7. `test_lens_extended.py` — edge cases for uncovered _lens.py lines
8. `test_surface_harness.py` — TestSurface integration
9. `test_fidelity.py` — CLI harness parsing
10. `test_fidelity_extended.py` — CliRunner error paths
11. `test_text_input_render.py` — TextInputState + render
12. `test_data_explorer.py` — DataExplorerState + render
13. `test_architecture_invariants.py` — structural invariants
14. `test_len_guardrail.py` — AST-based len() usage guard

### Positive patterns

**Parameterization is used well.** `test_keyboard_sequences.py` is a standout: escape sequence mappings are parameterized with clear `(input_bytes, expected_key)` tuples. `test_fidelity.py` tests CLI arg parsing with systematic coverage of all flag combinations.

**Class-based grouping by concept.** Most files group tests by semantic concern (`TestSpanWidth`, `TestLineTruncate`, `TestLinePaint`). This makes it easy to find related tests.

**Assertion quality is generally good.** Tests assert specific values rather than just "no exception." The golden tests assert exact output text. The buffer tests check individual cells.

**Test isolation.** The golden `conftest.py` has an `autouse` fixture to reset `ContextVar`s (palette, icons). This prevents cross-test contamination.

**Architecture tests are creative.** The `test_len_guardrail.py` uses AST parsing to prevent `len()` on text variables in display modules, with an explicit allowlist. The frozen dataclass test scans all source files. These are high-value, low-maintenance guards.

### Issues found

**1. `_block_to_text` is duplicated 7 times.**

Files: `test_lens.py:300`, `test_lens_extended.py:8`, `test_flame_lens.py:6`, `test_data_explorer.py:184`, `test_demo_testing.py:33`, `test_demo_fidelity.py:36`, `test_demo_live.py:33`.

Two slightly different implementations exist: the unit tests extract chars directly from `block.row()`, while the golden tests use `print_block(block, buf, use_ansi=False)`. The golden version is more accurate (it goes through the real render pipeline), but the unit version is simpler.

**2. `_text_block` helper duplicated across compose tests.**

`test_compose.py:14` and `test_compose_extended.py:19` both define `_text_block`. The extended version adds an `id` parameter. `_row_text` is duplicated in 4 files (`test_compose.py`, `test_compose_extended.py`, `test_table_render.py`, `test_list_render.py`).

**3. Some tests are overly verbose where parameterization would help.**

In `test_text_input_render.py`, the tests for `move_left_at_start_is_noop`, `move_right_at_end_is_noop`, `delete_forward_at_end_is_noop`, `backspace_at_start_is_noop` all follow the same pattern: create state, call operation, assert `result is s`. These could be a single parameterized test:

```python
@pytest.mark.parametrize("method", ["move_left", "move_right", "delete_back", "delete_forward"])
def test_noop_at_boundary(method):
    ...
```

However, the current form is still readable and the naming is clear. This is a minor style issue, not a defect.

**4. Golden test demo imports use `importlib.util` boilerplate.**

Each golden test file repeats 7 lines of `importlib.util.spec_from_file_location` setup. This could be extracted to a helper in `tests/golden/conftest.py`:

```python
def import_demo(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod
```

**5. `test_lifecycle.py` uses `MagicMock` for internal Surface plumbing.**

The `_make_surface()` helper in `test_lifecycle.py` manually mocks `_writer`, `_keyboard`, and `_keyboard.get_input`. This is fragile — if the internal API of Surface changes (e.g., `_keyboard` renamed), these tests break silently. The `TestSurface` harness was built to solve exactly this problem. Consider migrating lifecycle tests to use `TestSurface` instead.

**6. No negative tests for Block.text() with invalid inputs.**

`Block.text()` and `Block()` have validation (row width mismatch, ids height mismatch), but edge cases like `Block.text("", Style(), width=-1)` or `Block.text(None, Style())` are untested. The `test_block_extended.py` covers some but misses the `width <= 0` early return path (line 73 in block.py).

### Naming conventions

Test naming is consistent within files but varies between files:

- `test_compose.py`: `TestVslice.test_basic_slice` (class + method)
- `test_text_input_render.py`: `test_insert_char_at_start` (bare functions)
- `test_keyboard_sequences.py`: `test_csi_final_mappings` (parameterized bare functions)

All three patterns are idiomatic pytest. The mix is acceptable given that class-based tests group related concerns while parameterized tests work better as bare functions.

---

## 3. Architecture Test Analysis

### Current state

Two architecture test files enforce structural invariants:

**`test_architecture_invariants.py`** (4 tests):
1. `test_block_defensively_freezes_rows` — verifies Block deep-copies and freezes row data on construction.
2. `test_state_dataclasses_declared_frozen` — AST scan ensures all `*State` classes and named types (Cell, Style, Span, etc.) use `@dataclass(frozen=True)`.
3. `test_block_rows_private_not_accessed_outside_block` — string scan ensures `._rows` is not accessed outside `block.py`.
4. `test_runtime_state_dataclasses_are_frozen` — runtime check that `__dataclass_params__.frozen` is `True` for all state types.

**`test_len_guardrail.py`** (1 test):
1. `test_no_new_len_on_text_variables_in_display_modules` — AST scan prevents `len()` on text-like variables in display-critical modules. Uses an explicit allowlist for intentional collection-size checks.

### What's enforced

- Frozen dataclass invariant (both static AST and runtime)
- Block internal encapsulation (`_rows` privacy)
- Display-width correctness (no accidental `len()` for display width)
- Block immutability (defensive copy + freeze)

### What should be enforced but isn't

**1. Import boundary enforcement.**

The package has a layered architecture: `painted` (CLI core) -> `painted.tui` (interactive) -> `painted.views` (data rendering). Nothing enforces that:
- `painted.cell`, `painted.span`, `painted.block` don't import from `painted.tui`
- `painted.tui` doesn't import from `painted.views`
- `painted.fidelity` doesn't import from `painted.tui` (except through handlers)

A test like:
```python
def test_core_does_not_import_tui():
    """CLI core modules must not depend on TUI subsystem."""
    for module in CORE_MODULES:
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                assert "painted.tui" not in (node.module or "")
```

**Estimated effort:** 1 hour.

**2. Public API surface stability.**

The `__init__.py` exports are the public contract. No test verifies that the set of names exported from `painted`, `painted.tui`, `painted.views`, etc. matches an expected list. Adding a test would catch accidental export additions or removals:

```python
def test_public_api_surface():
    import painted
    expected = {"Cell", "Style", "Span", "Line", "Block", "print_block", ...}
    actual = {name for name in dir(painted) if not name.startswith("_")}
    assert actual == expected
```

**Estimated effort:** 30 minutes per subpackage.

**3. `Emit` callback signature enforcement.**

All emission kinds (`ui.key`, `ui.mouse`, `ui.action`, `ui.resize`, `ui.scroll_optim`) should have documented schemas. Currently nothing verifies that emission data dictionaries have consistent keys. A test could scan all `self.emit(...)` call sites and verify the schemas.

**Estimated effort:** 2 hours (AST scan + schema definition).

**4. Component pattern enforcement.**

All components follow `State + render_fn(state, ...) -> Block`. A test could verify that every `*State` class in `_components/` has a corresponding top-level function that accepts it and returns `Block`.

**Estimated effort:** 1 hour.

---

## 4. New Testing Strategies

### 4.1. Property-based testing with Hypothesis

**What:** Use `hypothesis` to generate random inputs for primitive operations and verify algebraic laws.

**Why:** The primitives have clear mathematical properties that are ideal for property-based testing:

- **Style.merge is idempotent:** `s.merge(s) == s`
- **Style.merge with default is identity:** `Style().merge(s) == s`
- **Span.width is non-negative:** `Span(text).width >= 0`
- **Line.truncate is monotone:** `line.truncate(w).width <= w`
- **Line.truncate preserves content:** `line.truncate(line.width) == line`
- **Block.text respects width:** `Block.text(s, style, width=w).width == w`
- **join_vertical preserves total height:** `join_vertical(a, b).height == a.height + b.height`
- **join_horizontal preserves max height:** `join_horizontal(a, b).height == max(a.height, b.height)`
- **Buffer.diff is correct:** `apply(prev, prev.diff(cur)) == cur`

**Estimated effort:** 3-4 hours for first batch (Style, Span, Line, Block).

**Dependencies:** Add `hypothesis` to dev dependencies.

### 4.2. Snapshot/golden tests for more components

**What:** Extend the golden test pattern to component render functions (list_view, table, text_input, data_explorer, sparkline, progress_bar).

**Why:** The existing golden infrastructure (`--update-goldens`, `Golden.assert_match`) is already proven for demos. Applying it to individual component renders would catch visual regressions that cell-level assertions miss. A rendered table or list view has layout properties (alignment, padding, truncation) that are easier to verify visually in a golden file than through individual cell assertions.

**Estimated effort:** 2-3 hours. Create `tests/golden/test_component_goldens.py` with parameterized renders of each component at multiple sizes.

### 4.3. Fuzzing for keyboard/mouse parsing

**What:** Feed random byte sequences to `KeyboardInput.get_input()` via the existing mock-byte-stream pattern, and verify it never crashes.

**Why:** Terminal escape sequence parsing is inherently a protocol parser operating on untrusted input. Malformed sequences from SSH connections, tmux, or unusual terminal emulators could trigger unexpected behavior. The existing tests cover known sequences but not adversarial input.

**Implementation:**
```python
@given(st.binary(min_size=1, max_size=20))
def test_get_input_never_crashes(raw_bytes):
    stream = [bytes([b]) for b in raw_bytes]
    result = _get_input_from_stream(stream)
    assert result is None or isinstance(result, (str, MouseEvent))
```

**Estimated effort:** 1 hour (reuses existing `_get_input_from_stream` helper).

### 4.4. Full pipeline integration tests

**What:** Test the complete render pipeline: `data -> lens_fn -> Block -> Buffer.paint -> Buffer.diff -> CellWrite[] -> Writer.write_frame -> ANSI string`. Parse the ANSI output back and verify it matches the expected visual.

**Why:** The current tests exercise each stage independently. An end-to-end test would catch interface mismatches between stages (e.g., Block producing cells that Writer doesn't handle correctly).

**Estimated effort:** 3-4 hours. The `TestSurface` harness already captures frames after the full render+diff+flush cycle. What's missing is a test that actually verifies the ANSI output round-trips correctly by using the `write_ansi=True` option and parsing the result.

### 4.5. Performance regression tests

**What:** Add `pytest-benchmark` tests for critical paths: `Buffer.diff()` on large buffers, `Block.text()` with long strings, `Writer.write_frame()` with many CellWrites, `shape_lens` with large data.

**Why:** At 0.96s for 1078 tests, the suite is fast. But the framework is used for real-time terminal rendering where frame latency matters. A benchmark test would catch O(n^2) regressions in diff or write_frame.

**Estimated effort:** 2 hours. Add `pytest-benchmark` to dev dependencies.

**Priority:** Low. Only worth doing if performance becomes a concern.

---

## 5. Simplification Opportunities

### 5.1. Extract `tests/helpers.py`

**Impact:** Removes ~80 lines of duplicated code across 7+ files.

Create `tests/helpers.py` with:
```python
def block_to_text(block: Block) -> str:
    """Extract text from a block (character content only)."""
    return "\n".join(
        "".join(cell.char for cell in block.row(y))
        for y in range(block.height)
    )

def text_block(lines: list[str], style: Style = Style(), *, id: str | None = None) -> Block:
    """Build a Block from lines of text."""
    ...

def row_text(block: Block, row_idx: int) -> str:
    """Extract character text from a single row."""
    return "".join(c.char for c in block.row(row_idx))
```

Files that would use it: `test_lens.py`, `test_lens_extended.py`, `test_flame_lens.py`, `test_data_explorer.py`, `test_compose.py`, `test_compose_extended.py`, `test_table_render.py`, `test_list_render.py`.

The golden tests should keep their own `_block_to_text` that uses `print_block(block, buf, use_ansi=False)` since that exercises the real render path.

### 5.2. Extract golden test demo import helper

**Impact:** Removes ~28 lines (7 lines x 4 golden test files).

In `tests/golden/conftest.py`:
```python
def load_demo(name: str) -> types.ModuleType:
    path = Path(__file__).resolve().parent.parent.parent / "demos" / "patterns" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_demo_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod
```

### 5.3. Migrate `test_lifecycle.py` to `TestSurface`

The lifecycle tests use `MagicMock` to stub `_writer` and `_keyboard`, duplicating what `TestSurface` already provides. Since `TestSurface` was built later, these tests predate it. Migrating would:
- Remove the fragile `_make_surface()` helper
- Make the tests more resilient to Surface internal changes
- Demonstrate that `TestSurface` handles lifecycle hooks

**Caveat:** The lifecycle tests specifically test `async def run()`, which `TestSurface.run_to_completion()` does not use (it's synchronous). This migration would require either adding an async mode to `TestSurface` or keeping the mock approach for the async-specific tests.

### 5.4. No redundant multi-level testing found

I looked for tests that test the same behavior at multiple levels (e.g., testing `join_vertical` both directly and through a higher-level function that calls it). The layering is clean: unit tests test individual functions, golden tests test the full pipeline. There's no significant redundancy.

---

## 6. Prioritized Action Items

### Priority 1 (High value, low effort)

1. **Extract `tests/helpers.py`** — Remove `_block_to_text`, `_text_block`, `_row_text` duplication. ~1 hour.

2. **Add `sparkline_with_range` tests** — Cover the 4 missing lines in `sparkline.py` (empty values, zero width). ~15 minutes.

3. **Add `Region.view()` test** — 1 line uncovered, 1 test. ~5 minutes.

4. **Add `data_explorer` page_up/page_down/format_leaf tests** — 24 missing lines, all simple state transitions. ~1 hour.

### Priority 2 (High value, moderate effort)

5. **Add import boundary architecture test** — Enforce the layered dependency graph. ~1 hour.

6. **Add public API surface test** — Prevent accidental export changes. ~30 minutes per subpackage (3 subpackages = 1.5 hours).

7. **Add keyboard/mouse fuzz test** — `@given(st.binary())` over `get_input()`. Requires adding `hypothesis` dependency. ~1 hour.

8. **Cover `fidelity.py` streaming path** — Test `_run_live` with `fetch_stream` (async generator). ~1.5 hours.

### Priority 3 (Moderate value, moderate effort)

9. **Property-based tests for primitives** — Style merge laws, Span/Line width invariants, Block dimension laws. ~3-4 hours.

10. **Cover `app.py` scroll optimization edge cases** — Small buffers, high-repaint bail-out, `_on_resize` direct call. ~2-3 hours.

11. **Extract golden test demo import helper** — DRY improvement for golden tests. ~30 minutes.

12. **Golden snapshot tests for components** — Extend golden infrastructure to individual component renders. ~2-3 hours.

### Priority 4 (Lower priority, future consideration)

13. **Full pipeline round-trip test** — ANSI output -> parse -> verify. ~3-4 hours.

14. **Performance benchmarks** — `pytest-benchmark` for Buffer.diff, Block.text, Writer.write_frame. ~2 hours. Defer until performance becomes a concern.

15. **Emission schema enforcement** — Verify `self.emit()` call sites have consistent key schemas. ~2 hours. Defer until emission surface stabilizes.

---

## Appendix: Coverage Command Reference

```bash
# Full coverage report with missing lines
uv run --package painted pytest tests/ --cov=painted --cov-report=term-missing -q

# Coverage for a single module
uv run --package painted pytest tests/ --cov=painted.app --cov-report=term-missing -q

# Run only architecture tests
uv run --package painted pytest tests/unit/test_architecture_invariants.py tests/unit/test_len_guardrail.py -q

# Run only golden tests
uv run --package painted pytest tests/golden/ -q

# Regenerate golden files
uv run --package painted pytest tests/golden/ --update-goldens -q
```
