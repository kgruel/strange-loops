# Primitives and Blocks

fidelis is built from a small set of immutable “render layer” value types:

- **Primitives**: `Style`, `Cell`, `Span`, `Line`
- **Rectangles**: `Block`

These are the *inputs* to every higher-level feature (composition, buffers, TUI, widgets).

See also:
- `docs/ARCHITECTURE.md`: stack + data flow (`../ARCHITECTURE.md`)
- `docs/PRIMITIVES.md`: quick reference (`../PRIMITIVES.md`)

---

## Style

`Style` is an immutable bundle of attributes (colors, bold/underline/etc). Styles combine via `merge()` (overlay wins).

<!-- docgen:begin py:fidelis.cell:Style#definition -->
```python
@dataclass(frozen=True)
class Style:
    """Immutable text style with color and attribute flags."""

    fg: Color = None
    bg: Color = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    dim: bool = False

    def merge(self, other: Style) -> Style:
        """Combine styles. `other` overrides non-None/non-False fields."""
        return Style(
            fg=other.fg if other.fg is not None else self.fg,
            bg=other.bg if other.bg is not None else self.bg,
            bold=other.bold or self.bold,
            italic=other.italic or self.italic,
            underline=other.underline or self.underline,
            reverse=other.reverse or self.reverse,
            dim=other.dim or self.dim,
        )
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.cell:Style.merge#signature -->
```python
    def merge(self, other: Style) -> Style:
```
<!-- docgen:end -->

## Cell

`Cell` is the atom: one character + one style. Most code manipulates `Block`s rather than individual cells.

<!-- docgen:begin py:fidelis.cell:Cell#definition -->
```python
@dataclass(frozen=True)
class Cell:
    """Atomic display unit: a single character with style."""

    char: str
    style: Style

    def __post_init__(self):
        if len(self.char) != 1:
            raise ValueError(f"Cell char must be a single character, got {self.char!r}")
```
<!-- docgen:end -->

## Span and Line

`Span` is “text + style” with **display width** (wide-char aware). `Line` is a tuple of spans that can paint into a `BufferView` or convert into a `Block`.

<!-- docgen:begin py:fidelis.span:Span#definition -->
```python
@dataclass(frozen=True, slots=True)
class Span:
    """A run of text with a single style."""

    text: str
    style: Style = Style()

    @property
    def width(self) -> int:
        """Display width, accounting for wide characters."""
        w = wcswidth(self.text)
        if w < 0:
            # Fallback for strings containing non-printable chars
            return len(self.text)
        return w
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.span:Line#definition -->
```python
@dataclass(frozen=True, slots=True)
class Line:
    """A sequence of spans forming a single line of styled text."""

    spans: tuple[Span, ...] = ()
    style: Style = Style()

    @classmethod
    def plain(cls, text: str, style: Style = Style()) -> Line:
        """Create a Line from a single unstyled (or uniformly styled) string."""
        return cls((Span(text, style),))

    @property
    def width(self) -> int:
        """Total display width across all spans."""
        return sum(s.width for s in self.spans)

    def paint(self, view: BufferView, x: int, y: int) -> None:
        """Render spans into a BufferView, merging base style onto each span."""
        col = x
        for span in self.spans:
            merged = self.style.merge(span.style)
            view.put_text(col, y, span.text, merged)
            col += span.width

    def truncate(self, max_width: int) -> Line:
        """Return a new Line truncated to max_width display columns."""
        remaining = max_width
        kept: list[Span] = []
        for span in self.spans:
            sw = span.width
            if sw <= remaining:
                kept.append(span)
                remaining -= sw
            else:
                # Cut this span character by character
                chars: list[str] = []
                used = 0
                for ch in span.text:
                    cw = wcswidth(ch)
                    if cw < 0:
                        cw = 1
                    if used + cw > remaining:
                        break
                    chars.append(ch)
                    used += cw
                if chars:
                    kept.append(Span("".join(chars), span.style))
                break
        return Line(spans=tuple(kept), style=self.style)

    def to_block(self, width: int) -> "Block":
        """Convert this Line to a Block of the given width.

        Builds cells directly from spans, merging Line style onto each span.
        Pads with empty cells if Line is shorter than width.
        Truncates if Line is longer than width.
        """
        from .block import Block

        cells: list[Cell] = []
        for span in self.spans:
            merged = self.style.merge(span.style)
            for ch in span.text:
                if len(cells) >= width:
                    break
                cells.append(Cell(ch, merged))
            if len(cells) >= width:
                break

        # Pad to width
        while len(cells) < width:
            cells.append(EMPTY_CELL)

        return Block([cells], width)
```
<!-- docgen:end -->

## Block

`Block` is an immutable rectangle of styled cells with known width/height. It’s the unit of composition.

Instead of embedding the full `Block` implementation here (it’s larger than the other primitives), the guide pins the public construction surface:

<!-- docgen:begin py:fidelis.block:Wrap#definition -->
```python
class Wrap(Enum):
    NONE = "none"        # single line, truncate at width
    CHAR = "char"        # break at any character
    WORD = "word"        # break at word boundaries
    ELLIPSIS = "ellipsis"  # truncate with "…"
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.block:Block#signature -->
```python
class Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.block:Block.text#signature -->
```python
    @staticmethod
    def text(content: str, style: Style, *, width: int | None = None,
             wrap: Wrap = Wrap.NONE) -> Block:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.block:Block.empty#signature -->
```python
    @staticmethod
    def empty(width: int, height: int, style: Style = Style()) -> Block:
```
<!-- docgen:end -->

---

## Why this matters

fidelis deliberately pushes complexity *up* the stack:

- These types are immutable values → safe to share and cache.
- Higher-level systems (buffers, layers, widgets) can treat rendering as pure transformation: state → blocks.
