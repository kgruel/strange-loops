# Composition and Layout

fidelis’s layout layer is intentionally small: it’s a set of pure functions that transform `Block` → `Block` (or join multiple blocks into one).

This lets you build complex UI surfaces without introducing mutable layout state.

See also:
- `docs/ARCHITECTURE.md`: stack + data flow (`../ARCHITECTURE.md`)

---

## Joins

Join blocks horizontally or vertically, optionally with alignment and gaps.

<!-- docgen:begin py:fidelis.compose:Align#definition -->
```python
class Align(Enum):
    START = "start"    # top or left
    CENTER = "center"
    END = "end"        # bottom or right
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.compose:join_horizontal#signature -->
```python
def join_horizontal(*blocks: Block, gap: int = 0,
                    align: Align = Align.START) -> Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.compose:join_vertical#signature -->
```python
def join_vertical(*blocks: Block, gap: int = 0,
                  align: Align = Align.START) -> Block:
```
<!-- docgen:end -->

## Padding and Borders

Padding adds empty space. Borders wrap content, optionally with a title.

<!-- docgen:begin py:fidelis.compose:pad#signature -->
```python
def pad(block: Block, *, left: int = 0, right: int = 0,
        top: int = 0, bottom: int = 0, style: Style = Style()) -> Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.compose:border#signature -->
```python
def border(block: Block, chars: BorderChars = ROUNDED,
           style: Style = Style(), title: str | None = None,
           title_style: Style | None = None) -> Block:
```
<!-- docgen:end -->

## Truncation and Slicing

Truncation is the simplest “responsive layout”: cap width, show an ellipsis, preserve the rest of the composition pipeline.

Slicing (`vslice`) is the bridge to scrollable UIs: build a full block, then window into it.

<!-- docgen:begin py:fidelis.compose:truncate#signature -->
```python
def truncate(block: Block, width: int, ellipsis: str = "…") -> Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.compose:vslice#signature -->
```python
def vslice(block: Block, offset: int, height: int) -> Block:
```
<!-- docgen:end -->

---

## Pattern: “compose, then paint”

The render loop usually looks like:

1. Construct blocks from state (text, tables, lists).
2. Compose them (join/pad/border/truncate).
3. Paint the result into a buffer view.

The key mental model: layout is pure and local — no retained layout objects, no incremental mutation.
