# The Composition Journey: From Profiling to Layer 3

How we discovered the missing layer in our render stack and arrived at Span/Line as frozen dataclasses.

## 1. The Problem Surfaced Through Profiling

FrameTimer revealed that `m.build` (StyledBlock creation in the logs app) consumed **90% of frame time**. The root cause was structural: we were building StyledBlocks for ALL filtered log lines, not just the visible ones.

The fix was straightforward — visible-window slicing:

```
Before: 139ms average frame time
After:  12.7ms average frame time
```

But this raised a deeper question. Even with only visible rows being built, each individual line was still surprisingly expensive. The windowing fix was a band-aid over a design issue.

## 2. Why Each Line Is Expensive

A single log line in our system requires:

```python
parts = []
parts.append(StyledBlock.text(f"{source:>12} ", Style(fg=color)))   # list[Cell] created
parts.append(StyledBlock.text("│ ", Style(dim=True)))                # list[Cell] created
parts.append(StyledBlock.text(msg, msg_style))                       # list[Cell] created
return join_horizontal(*parts, gap=0)                                 # merge into list[list[Cell]]
```

The cost breakdown per line:
- 3 `StyledBlock.text()` calls, each creating a `list[Cell]` (one Cell object per character)
- 1 `join_horizontal` call merging into a new `list[list[Cell]]`
- **~82 Cell objects**, **4 list allocations**, **1 merge pass**

StyledBlock is a 2D cell grid. It is the correct abstraction for borders, padding, and multi-line block composition. But for "3 styled segments on one row," it is overkill. We are paying per-character object costs just to describe what text should appear.

## 3. How Other Frameworks Handle This

### Ratatui (Rust)

Three-tier hierarchy: `Span` -> `Line` -> `Text`.

```rust
// A Span is content + style, nothing more
pub struct Span<'a> {
    pub content: Cow<'a, str>,  // zero-copy reference or owned
    pub style: Style,
}

// A Line is a vec of Spans + base style for inheritance
pub struct Line<'a> {
    pub spans: Vec<Span<'a>>,
    pub style: Style,
    pub alignment: Option<HorizontalAlignment>,
}
```

All three types implement `Widget` — they paint directly into a Buffer. The `Stylize` trait lets you write `"error".red().bold()` on bare `&str`. Style inheritance flows parent-to-child: Line's style patches onto each Span's style at render time.

Cells are created only when `Widget::render()` is called (the paint boundary). Composition (building `Vec<Span>`) is nearly free — just collecting references.

### Lip Gloss (Go)

No intermediate type at all. The composition unit is a rendered string with embedded ANSI codes:

```go
label := labelStyle.Render("Status:")
value := valueStyle.Render("Active")
line := label + " " + value
```

`JoinHorizontal` exists for multi-line block alignment, not for inline spans. For single lines, string concatenation is the composition operation.

The design is deliberately flat: Style is configuration, output is a flat string, there is no tree of styled nodes.

### Rich/Textual (Python)

`Text` holds a plain string internally plus a list of offset-based `Span` overlays:

```python
class Span(NamedTuple):
    start: int
    end: int
    style: Union[str, Style]
```

Composition via `Text.assemble()` takes `(str, style)` tuples:

```python
line = Text.assemble(
    ("ERROR", "bold red"),
    (": ", "white"),
    ("file not found", "yellow"),
)
```

Spans can overlap. Text is mutable in Rich; Textual's `Content` class is immutable. No 2D grid — Text is 1D, line breaks are characters in the string.

## 4. The Key Pattern Across All Three

Every framework separates two concerns:

1. **Description layer** — what to render (spans, strings, tuples). Composition here is cheap: collecting references, concatenating strings, appending to a vec.
2. **Output layer** — how to render (buffer cells, ANSI escape codes). Per-character cost happens here and only here.

The critical boundary is the paint/render call. Everything before it is description. Everything after it is output.

**Our system collapses both layers into StyledBlock.** Every composition operation immediately pays the per-character Cell creation cost. There is no cheap description layer.

## 5. The Missing Layer

Mapping our stack against this pattern reveals a gap:

| Layer | What | Primitive |
|-------|------|-----------|
| 0 | Terminal | Physical cells, ANSI |
| 1 | Writer | CellWrite -> ANSI adapter |
| 2 | Buffer | Frame buffer, flat Cell grid, diff |
| **3** | **??? THE GAP** | **Description of what to render, composes cheaply** |
| 4 | StyledBlock | Retained 2D cell grid (correct for borders/padding) |
| 5 | Components | State + render |
| 6 | App | Lifecycle |

Layer 3 is the description layer. It sits between "what state do I have" (components) and "write cells into a buffer" (StyledBlock/Buffer). Its job: describe styled text cheaply so composition doesn't pay cell-per-character costs.

## 6. Evaluating Python Primitives for Layer 3

Four options for representing a styled text segment:

### Bare tuples: `(str, Style)`

Zero overhead, no methods, no type safety. Works as an internal representation but offers no behavior (width calculation, truncation, paint).

### NamedTuple

Same memory as tuple, named field access. But awkward to add methods, and constructing with defaults requires class-level gymnastics.

### str subclass: `class Span(str)` with `__slots__ = ('style',)`

Appealing at first glance: a Span IS a string, so `len()` works, `in` works, slicing works. But:
- Copies the text on construction (str is immutable in Python, so the subclass stores a new copy)
- Slicing and string methods lose the style without overriding `__getitem__`, `split`, `strip`, etc.
- Requires ~4 method overrides to maintain style through operations
- Fights Python's grain — str subclasses with extra state are a known footgun

### Frozen dataclass with `__slots__`

48 bytes per instance. References (not copies) the source string. Named attributes, clear construction, extensible with methods and properties. Matches every other frozen state object in the project (LogLine, ListState, ProgressState, etc.).

### Memory comparison

All Layer 3 options are in the same ballpark:

```
Per frame (90 spans x 30 fps):  ~9-11 KB — negligible
Current StyledBlock approach:   ~350 KB — 30-40x more
```

The choice between tuple, NamedTuple, str subclass, and dataclass is about **ergonomics and consistency**, not performance. All of them are cheap compared to what we have now.

## 7. Why Line Needs a Base Style (Not Just a Tuple of Spans)

Consider selection highlighting. Without a base style on Line:

```python
# To highlight a line, you must rebuild every Span with a merged style
highlighted_spans = tuple(
    Span(s.text, s.style.merge(Style(bg=237)))
    for s in line.spans
)
```

With a base style field:

```python
# Just set the Line's base style — merge happens at paint time
Line(spans, style=Style(bg=237))
```

This is the Ratatui pattern: style inheritance flows from Line to Span at the paint boundary, not at construction time. The Line carries intent ("this row is selected"), and the paint method applies it.

This is also why Line needs to be a dataclass and not a bare tuple — it needs:
- A `style` field for inheritance
- A `width` property (sum of span widths)
- A `truncate(max_width)` method that walks spans and cuts
- A `paint(view, x, y)` method — the boundary where Cells get created

## 8. The Final Design

```python
@dataclass(frozen=True, slots=True)
class Span:
    text: str
    style: Style = Style()

    @property
    def width(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class Line:
    spans: tuple[Span, ...] = ()
    style: Style = Style()  # base style — inherits to all spans at paint time

    @property
    def width(self) -> int:
        return sum(s.width for s in self.spans)

    def truncate(self, max_width: int) -> 'Line':
        """Walk spans, cut at max_width, return new Line."""
        ...

    def paint(self, view: BufferView, x: int, y: int) -> None:
        """The boundary: create Cells here, write into view."""
        cx = x
        for span in self.spans:
            merged = self.style.merge(span.style)  # inheritance
            view.put_text(cx, y, span.text, merged)
            cx += span.width
```

## 9. What This Enables

**Log line rendering** drops from 82 Cell objects + 4 list allocations to: build 3 Spans (3 frozen dataclass instances referencing existing strings), wrap in a Line, call `.paint()`.

```python
line = Line(spans=(
    Span(f"{source:>12} ", Style(fg=color)),
    Span("| ", Style(dim=True)),
    Span(msg, msg_style),
))
line.paint(view, 0, row_y)
```

**Selection highlighting**: override the base style at paint time without rebuilding spans.

**Truncation**: `Line.truncate(available_width)` walks spans and cuts, returning a new Line. No Cell creation until paint.

**StyledBlock remains** for actual 2D composition — borders, padding, multi-line blocks. It is not replaced, just properly scoped to what it is good at.

**Components** can accept or return Lines for the common single-row case, avoiding StyledBlock overhead for simple content.

## 10. The Architectural Insight

StyledBlock is a **retained 2D canvas** — like a pre-rendered texture. Every time you create one, you pay the full per-character cost upfront. This is correct when you need a reusable 2D rectangle (bordered panels, padded blocks, table cells).

Span/Line is a **description** — like a draw call. It says what to paint, not how. The per-character cost is deferred to the paint boundary. This is correct when you are composing styled text that will be painted once into a known location.

You do not pre-render a texture just to draw one line of text.

## Ratatui Alignment

| Ours | Ratatui | Role |
|------|---------|------|
| `Span` | `ratatui::Span` | Content + style, no cells. Cheap to create and compose. |
| `Line` | `ratatui::Line` | Vec of spans + base style + alignment. The composition unit. |
| `Line.paint()` | `Widget::render()` | The boundary where cells get written into a buffer. |
| `StyledBlock` | Pre-rendered Widget output | A retained cell grid you can composite. Correct for 2D blocks. |

## Layer Stack (Updated)

| Layer | Primitive | Role |
|-------|-----------|------|
| R1 | Cell, Buffer, Writer | Physical output, diff, ANSI |
| R2 | StyledBlock, compose | 2D retained cell grids, borders, padding |
| **R2.5** | **Span, Line** | **Inline text description, cheap composition, paint boundary** |
| R3 | Components | Frozen state + transitions + render |
| R4 | RenderApp | Lifecycle, keyboard, frame loop |

Span/Line sits between Buffer and StyledBlock — it is the lightweight path for the common case (styled text on a single row) that avoids the heavyweight path (2D cell grid) when a 2D grid is not needed.
