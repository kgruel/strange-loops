# Composition Ergonomics Research

How do similar TUI frameworks handle inline styled text composition?

## Ratatui (Rust)

### Hierarchy

```
Text  (multi-line container)
  └── Line  (single line, vec of spans, optional alignment)
        └── Span  (styled text segment: content + style)
```

Style inherits downward: Text style patches onto Line style, Line style patches onto Span style.

### Span — styled text segment

```rust
pub struct Span<'a> {
    pub content: Cow<'a, str>,
    pub style: Style,
}
```

Construction:

```rust
// Unstyled
Span::raw("hello")

// Explicit style
Span::styled("hello", Style::new().fg(Color::Green).add_modifier(Modifier::BOLD))

// Stylize trait (ergonomic shorthand) — works on &str, String, Span
"hello".green().bold()
"hello".red().on_yellow().italic()
```

A Span implements Widget — you can render it directly into a Buffer/Rect.

### Line — single line of Spans

```rust
pub struct Line<'a> {
    pub spans: Vec<Span<'a>>,
    pub style: Style,
    pub alignment: Option<HorizontalAlignment>,
}
```

Construction:

```rust
// From vec of spans (the core pattern)
Line::from(vec![
    Span::styled("Hello", Style::new().blue()),
    Span::raw(" world!"),
])

// With Stylize trait
Line::from(vec!["Hello".blue(), " world!".green()])

// Styled entire line (inherits to all spans)
Line::styled("all green", Style::new().green())
```

Line implements Widget — renders directly to Buffer.

### Text — multi-line container

```rust
Text::from(vec![
    Line::from("first line"),
    Line::from(vec!["styled ".yellow(), "second".red()]),
])
```

### Rendering into Buffer

All three types implement Widget:

```rust
let line = Line::from(vec!["key: ".bold(), "value".cyan()]);
line.render(area, buf);  // writes styled cells left-to-right, truncates at area boundary
```

For wrapping/borders, wrap in Paragraph:

```rust
Paragraph::new(text)
    .block(Block::bordered().title("Title"))
    .wrap(Wrap { trim: true })
```

### Ergonomics — 3 differently-styled segments

```rust
// Verbose
Line::from(vec![
    Span::styled("error", Style::new().fg(Color::Red).add_modifier(Modifier::BOLD)),
    Span::styled(": ", Style::new().fg(Color::White)),
    Span::styled("file not found", Style::new().fg(Color::Yellow)),
])

// Ergonomic (Stylize trait)
Line::from(vec![
    "error".red().bold(),
    ": ".white(),
    "file not found".yellow(),
])
```

### Key Design Observations

| Property | Detail |
|----------|--------|
| Ownership | `Cow<'a, str>` — zero-copy for &str, owned for String |
| Style inheritance | Parent patches onto child; child can override |
| All are Widgets | Span, Line, Text can all render directly to Buffer |
| No layout logic | These types don't wrap or align — that's Paragraph's job |
| Composition | Always explicit: build `Vec<Span>` then wrap in `Line` |

---

## Bubble Tea / Lip Gloss (Go)

### Style Type: Immutable Value with Builder Pattern

Style is a value type (struct). All setter methods return a new Style:

```go
var style = lipgloss.NewStyle().
    Bold(true).
    Foreground(lipgloss.Color("#FAFAFA")).
    Background(lipgloss.Color("#7D56F4")).
    PaddingLeft(4)
```

Each method call produces a new Style. Assignment copies.

### Composing a Line with Multiple Styled Segments

There is no first-class "styled span" type. The composition model: render each segment to a string (with embedded ANSI), then concatenate:

```go
label := labelStyle.Render("Status:")
value := valueStyle.Render("Active")
badge := badgeStyle.Render("NEW")

line := label + " " + value + " " + badge
```

The unit of composition is already-rendered strings, not style objects.

### JoinHorizontal: Multi-line Block Alignment

```go
func JoinHorizontal(pos Position, strs ...string) string
```

Designed for joining multi-line blocks, not inline spans:
1. Splits each input into lines
2. Pads shorter blocks with blank lines
3. Pads each line to the block's max width
4. Concatenates horizontally

For single-line segments, simple string concatenation does the same thing.

### Style-to-Render Relationship

```go
style := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("212"))
output := style.Render("hello")  // returns string with ANSI codes
```

`Render` applies: text transform, tab expansion, word wrap, alignment, ANSI codes, padding, border, margin, max width/height.

### Ergonomics: 3-Segment Line

```go
var (
    keyStyle   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("205"))
    sepStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
    valueStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("86"))
)

line := keyStyle.Render("name") + sepStyle.Render(": ") + valueStyle.Render("experiments")
```

Three Render calls, string concatenation. No intermediate type.

### Key Design Observations

| Aspect | Lip Gloss Approach |
|--------|-------------------|
| Style mutability | Immutable value type, builder returns copies |
| Composition unit | `string` (with embedded ANSI) |
| Inline composition | String concatenation |
| Block composition | `JoinHorizontal` / `JoinVertical` |
| Abstraction level | Style is config, output is flat string, no tree |

The design is deliberately flat — no AST of styled nodes, no layout engine for inline content. Render eagerly to strings, compose those strings.

---

## Rich / Textual (Python)

### Rich `Text` — The Core Type

Mutable. Holds a plain string internally plus a list of Span namedtuples marking styled regions by character offset:

```python
class Span(NamedTuple):
    start: int
    end: int
    style: Union[str, Style]
```

Plain text and style spans stored separately. Spans can overlap.

### Three Ways to Build Multi-Styled Lines

**a) Text.assemble() — tuple-based (preferred for multi-segment)**

```python
from rich.text import Text

line = Text.assemble(
    ("ERROR", "bold red"),
    " in ",
    ("main.py", "cyan underline"),
    ": ",
    ("division by zero", "yellow"),
)
```

Each element is either `str` or `(str, style)` tuple. Returns one `Text`.

**b) append() — imperative builder**

```python
text = Text()
text.append("ERROR", style="bold red")
text.append(" in ")
text.append("main.py", style="cyan underline")
```

**c) Console markup**

```python
console.print("[bold red]ERROR[/] in [cyan]main.py[/]: [yellow]division by zero[/]")
text = Text.from_markup("[bold red]ERROR[/] in [cyan]main.py[/]")
```

### Textual Widget Rendering

```python
class StatusBar(Widget):
    def render(self) -> Text:
        return Text.assemble(
            ("ERROR", "bold red"),
            " | ",
            ("main.py:42", "cyan"),
        )
```

Textual also has its own `Content` class (immutable, unlike Rich's `Text`):

```python
from textual.content import Content
content = Content("Hello, World!")
content = content.stylize(7, 12, "bold")  # returns new instance
```

### Ergonomics: 3-Segment Line

```python
line = Text.assemble(
    ("error", "bold red"),
    (": ", "white"),
    ("file not found", "yellow"),
)
```

### Key Design Observations

| Property | Detail |
|----------|--------|
| Model | "Attributed string" — plain text + offset-based style spans |
| Mutability | Rich Text is mutable; Textual Content is immutable |
| Composition | Concatenation via assemble/append, no layout algebra |
| Styles | Compose additively: "bold red on blue" parsed as independent attrs |
| No 2D grid | Text is 1D; line breaks are characters in the string |

---

## Our Current Approach

### StyledBlock — 2D cell grid

```python
class StyledBlock:
    __slots__ = ("width", "height", "_rows")
    # _rows: list[list[Cell]]  — 2D grid of styled cells
```

### Building a styled line

```python
parts: list[StyledBlock] = []
parts.append(StyledBlock.text(f"{source:>12} ", Style(fg=color)))
parts.append(StyledBlock.text("│ ", Style(dim=True)))
parts.append(StyledBlock.text(msg, msg_style))
return join_horizontal(*parts, gap=0)
```

### What this costs (see call stack analysis below)

Each `StyledBlock.text()` creates a `list[Cell]` (one Cell per character). Then `join_horizontal` creates a new merged `list[list[Cell]]`. For 3 segments of ~80 chars total: 4 list allocations, ~240 Cell objects, 1 merge pass.

---

## Comparison Table

| | Ratatui | Lip Gloss | Rich/Textual | Ours |
|---|---------|-----------|-------------|------|
| Line unit | `Span` (Cow str + Style) | rendered string | `(str, style)` tuple | `StyledBlock` (2D Cell grid) |
| Composition | `Line::from(vec![...])` | string concat | `Text.assemble(...)` | `join_horizontal(*blocks)` |
| Allocations per line | 1 Vec + n Cow refs | n string renders | 1 str + n Span tuples | n list[Cell] + 1 merge |
| Rendering | write cells left-to-right | print string | Console.print | paint into BufferView |
| Overkill factor | minimal | minimal | minimal | significant for 1-row case |
