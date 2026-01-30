# Flowable Layouts for Cells

## Problem

Theme Carnival overlaps when terminal is too small. Current layout primitives (`join_horizontal`, `join_vertical`) compose blocks at fixed positions without regard for available space.

```
# Current: fixed composition
join_horizontal(a, b, c)  # always side-by-side, overlaps if terminal narrow
```

## Current State

**Existing primitives:**
| Primitive | Behavior |
|-----------|----------|
| `join_horizontal` | Side-by-side, total width = sum of widths |
| `join_vertical` | Stacked, max width taken |
| `truncate` | Clip to width with ellipsis |
| `vslice` | Extract vertical slice (for scrolling) |
| `pad`, `border` | Add spacing/decoration |
| `Viewport` | Scroll state for vertical overflow |
| `BufferView` | Clips writes to bounds (doesn't reflow) |

**Gap:** No size-aware layout. Composition produces fixed-size blocks; rendering clips but doesn't adapt.

---

## Prior Art Survey

### Textual (Python)
- **Model:** CSS-like with `Vertical`, `Horizontal`, `Grid` containers
- **Sizing:** Fractional units (`1fr`, `2fr`), percentages, `auto`
- **Overflow:** Automatic scrollbars via `overflow-y: auto`
- **Responsive:** No breakpoints; nesting + percentages for adaptation
- **Complexity:** Full CSS box model, significant runtime

### Ratatui (Rust)
- **Model:** Constraint solver (Cassowary algorithm)
- **Sizing:** `Min`, `Max`, `Length`, `Percentage`, `Ratio`, `Fill`
- **Overflow:** Solver produces "arbitrary solution close to constraints"
- **Responsive:** `Flex` enum for space distribution (Start, Center, SpaceBetween, etc.)
- **Complexity:** Constraint solver requires priority reasoning

### Brick (Haskell)
- **Model:** Fixed vs Greedy growth policy
- **Sizing:** `hLimit`/`vLimit` for caps, `Pad Max` for greedy fill
- **Overflow:** Directional cropping (`cropLeftBy`, `cropTopBy`)
- **Responsive:** Greedy elements share remaining space equally
- **Complexity:** Simple two-category model, predictable

---

## Options

### Option 1: Responsive Breakpoints
Add `join_responsive` that switches between horizontal/vertical based on width.

```python
def join_responsive(
    *blocks: Block,
    breakpoint: int,
    available_width: int,
    gap: int = 0
) -> Block:
    """Horizontal if fits, vertical if not."""
    total = sum(b.width for b in blocks) + gap * (len(blocks) - 1)
    if total <= available_width:
        return join_horizontal(*blocks, gap=gap)
    else:
        return join_vertical(*blocks, gap=gap)
```

**Pros:** Minimal change, solves overlap, easy to understand
**Cons:** Binary choice (no partial wrapping), caller must pass available_width

### Option 2: Flexbox-Style Flow (Wrapping)
Add `flow` that wraps items to next row when width exceeded.

```python
def flow(
    *blocks: Block,
    width: int,
    gap: int = 0,
    row_gap: int = 0
) -> Block:
    """Wrap blocks into rows that fit within width."""
    rows: list[list[Block]] = [[]]
    row_width = 0

    for block in blocks:
        if row_width + block.width + (gap if rows[-1] else 0) > width:
            rows.append([])
            row_width = 0
        rows[-1].append(block)
        row_width += block.width + (gap if len(rows[-1]) > 1 else 0)

    return join_vertical(
        *[join_horizontal(*row, gap=gap) for row in rows if row],
        gap=row_gap
    )
```

**Pros:** Graceful degradation, works for any number of items
**Cons:** More complex, row heights may vary, doesn't handle single-item overflow

### Option 3: Priority-Based Truncation
Add priority metadata; lower-priority items truncate/hide first.

```python
@dataclass(frozen=True)
class Constraint:
    min_width: int = 0
    priority: int = 0  # higher = more important

def constrained_horizontal(
    items: list[tuple[Block, Constraint]],
    width: int,
    gap: int = 0
) -> Block:
    """Fit items in width; truncate/hide low-priority items first."""
```

**Pros:** Fine control, preserves most important content
**Cons:** Requires constraint annotations, more complex API

### Option 4: Constraint Solver (Ratatui-style)
Full constraint system with Min/Max/Fill semantics.

**Pros:** Most flexible, handles complex layouts
**Cons:** Significant complexity, may be overkill for cells

### Option 5: Fixed + Greedy (Brick-style)
Two-category model: fixed blocks take their size, greedy blocks share remainder.

```python
class Size(Enum):
    FIXED = "fixed"    # block.width is authoritative
    GREEDY = "greedy"  # expand to fill available space

def distribute_horizontal(
    items: list[tuple[Block, Size]],
    width: int,
    gap: int = 0
) -> Block:
    """Allocate: fixed items first, greedy items share remainder."""
```

**Pros:** Simple model, predictable, matches Brick's proven approach
**Cons:** Only two categories (no min/max), greedy items need render callback

---

## Analysis

The overlap problem has a specific shape: Theme Carnival puts content side-by-side that should stack when narrow. This is a **breakpoint problem**, not a constraint-solving problem.

### What Theme Carnival Actually Needs

Looking at the demo:
1. Status indicators row (Connected, Error, Warning, Spinner) — should wrap or stack
2. Log levels list — already vertical, just needs width capping
3. Progress bar — should truncate to available width
4. Buttons row — should wrap or stack
5. Theme selector (2 columns) — should become 1 column when narrow

**Pattern:** Most issues are "horizontal row that should become vertical when narrow."

### Simplest Solution

Option 1 (responsive breakpoints) solves the specific problem with minimal API change:

```python
# Before: overlaps
row = join_horizontal(status, error, warning, spinner)

# After: adapts
row = join_responsive(status, error, warning, spinner,
                      breakpoint=40, available_width=w)
```

The demo can pass `available_width=w` from render context. No constraint annotations needed.

---

## Recommendation

**Implement Option 1 (Responsive Breakpoints) first**, with Option 2 (Flow) as enhancement.

### Phase 1: `join_responsive`
```python
def join_responsive(
    *blocks: Block,
    breakpoint: int | None = None,
    available_width: int,
    gap: int = 0,
    align: Align = Align.START
) -> Block:
    """Join horizontal if fits, vertical if not.

    Args:
        blocks: Blocks to compose
        breakpoint: Width threshold for switch (default: sum of block widths)
        available_width: Current container width
        gap: Space between blocks
        align: Alignment for both orientations
    """
```

### Phase 2 (optional): `flow`
If wrapping behavior needed for many items:
```python
def flow(
    *blocks: Block,
    width: int,
    gap: int = 0,
    row_gap: int = 0,
    align: Align = Align.START
) -> Block:
    """Wrap blocks into rows that fit within width."""
```

### Phase 3 (deferred): Constraints
If pattern emerges for min/max sizing, consider Brick-style fixed/greedy model.

---

## Migration Path for Theme Carnival

```python
# render() receives (w, h) from buffer

# Status row
status_row = join_responsive(
    connected_indicator,
    error_indicator,
    warning_indicator,
    spinner_block,
    available_width=panel_width,
    gap=2
)

# Buttons
buttons = join_responsive(
    save_btn, cancel_btn, delete_btn,
    available_width=panel_width,
    gap=2
)

# Theme columns (explicit breakpoint)
theme_list = join_responsive(
    col1, col2,
    breakpoint=40,  # switch to vertical below 40 chars
    available_width=w - 8
)
```

---

## Open Questions

1. **Should breakpoint be explicit or derived?**
   - Explicit: caller controls when to switch
   - Derived: sum of block widths + gaps (auto-calculate)
   - Recommendation: default to derived, allow override

2. **Alignment in vertical mode?**
   - Horizontal alignment of stacked blocks
   - Recommendation: use same `Align` parameter for both modes

3. **Nested responsive layouts?**
   - Inner responsive depends on outer's decision
   - Recommendation: compose naturally; inner gets width from outer's result

---

## Sources

- [Ratatui Layout Concepts](https://ratatui.rs/concepts/layout/)
- [Ratatui Constraint Documentation](https://docs.rs/ratatui/latest/ratatui/layout/enum.Constraint.html)
- [Textual Layout Guide](https://textual.textualize.io/guide/layout/)
- [Brick Widgets Core](https://hackage.haskell.org/package/brick-2.10/docs/Brick-Widgets-Core.html)
