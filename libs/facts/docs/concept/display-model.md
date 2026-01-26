# Display Models

*The missing layer between contract and presentation.*

## The Stack

```
┌─────────────────────────────────────────────────────┐
│ CONTRACT (ev)                                       │
│ Event, Result — what happened                       │
│ Frozen, minimal, serializable                       │
├─────────────────────────────────────────────────────┤
│ NORMALIZATION                                       │
│ Normalizers — source → display model                │
│ from_event(), from_docker(), from_systemd()         │
├─────────────────────────────────────────────────────┤
│ DISPLAY MODELS                                      │
│ LogLine, ProgressState, ArtifactRef                 │
│ Layout-aware, style-agnostic, frozen                │
├─────────────────────────────────────────────────────┤
│ RENDERING                                           │
│ render(model, theme, config, state) → Line          │
│ Semantic IR: Line[Segment] with roles               │
├─────────────────────────────────────────────────────┤
│ BACKENDS                                            │
│ rich.render(Line, theme) → Text                     │
│ json.render(Line) → dict                            │
│ plain.render(Line) → str                            │
├─────────────────────────────────────────────────────┤
│ PRESENTATION                                        │
│ Terminal, file, stream                              │
└─────────────────────────────────────────────────────┘
```

Each layer has one job. Data flows down, styling decisions flow up.

## The Gap ev Doesn't Fill

ev defines the contract: Event describes what happened, Result describes the outcome. But between receiving an Event and producing terminal output, there's a conceptual gap.

For trivial cases, emitters bridge this directly. For serious CLIs, intermediate layers emerge. This document defines those layers.

## Layer 1: Contract (ev)

What happened. Facts from domain logic.

```python
Event(kind="log", level="error", message="Connection failed", data={...})
```

ev stays here. Frozen, minimal, serializable.

## Layer 2a: Normalization

Sources converge to canonical display models.

```python
class Normalizer(Protocol):
    def accepts(self, item: object) -> bool: ...
    def normalize(self, item: object) -> DisplayModel: ...
```

Multiple sources produce similar content:

```python
# ev Events
class EventNormalizer:
    def normalize(self, event: Event) -> LogLine:
        return LogLine(
            message=event.message,
            source=event.signal_name,
            level=event.level,
            timestamp=datetime.fromtimestamp(event.ts),
        )

# Docker compose logs
class DockerComposeNormalizer:
    def normalize(self, line: str) -> LogLine:
        service, message = line.split(" | ", 1)
        return LogLine(message=message, source=service, level=detect_level(message))

# Systemd journal
class SystemdNormalizer:
    def normalize(self, entry: dict) -> LogLine:
        return LogLine(
            message=entry["MESSAGE"],
            source=entry.get("SYSLOG_IDENTIFIER"),
            level=priority_to_level(entry.get("PRIORITY")),
            timestamp=entry.get("__REALTIME_TIMESTAMP"),
        )
```

Normalizers are source-specific. They know format details. Display models don't.

## Layer 2b: Display Models

Canonical forms ready for rendering. The key properties:

**Layout-aware** — contains the fields renderers need (message, source, level, timestamp).

**Style-agnostic** — contains no styling decisions. If a display model contains `"red"` or `"✓"`, you've smuggled Theme into Data.

```python
# Good - semantic tokens
level = "error"

# Bad - styling decisions
color = "red"
icon = "✗"
```

**Frozen** — immutable data, no behavior.

```python
@dataclass(frozen=True)
class LogLine:
    """Display model for log-like content."""
    message: str
    source: str | None = None
    level: str | None = None           # semantic: "error", "warn", "info", "debug"
    timestamp: datetime | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ProgressState:
    """Display model for progress indication."""
    message: str
    step: int | None = None
    total: int | None = None
    percent: float | None = None
    phase: str | None = None

@dataclass(frozen=True)
class ArtifactRef:
    """Display model for produced artifacts."""
    type: str
    message: str
    path: str | None = None
    href: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
```

## Layer 3: Rendering → Semantic IR

Renderers transform display models into a **semantic intermediate representation** — structured output that's backend-neutral.

```python
@dataclass(frozen=True)
class Segment:
    """A piece of output with a semantic role."""
    role: str   # "timestamp", "source", "level:error", "message", "separator"
    text: str

@dataclass(frozen=True)
class Line:
    """A complete line of semantic output."""
    segments: tuple[Segment, ...]
```

The role identifies what kind of content this is. Theme maps roles to styles. The renderer doesn't know about colors — it knows about meaning.

```python
def render_log_line(
    model: LogLine,
    config: LogLineConfig,
    state: RenderState,
) -> Line:
    """Transform LogLine to semantic Line."""
    segments = []

    if config.show_source and model.source:
        color = state.get_source_color(model.source)
        segments.append(Segment(role=f"source:{color}", text=model.source.ljust(config.source_width)))
        segments.append(Segment(role="separator", text=config.separator))

    if model.level:
        segments.append(Segment(role=f"level:{model.level}", text=model.message))
    else:
        segments.append(Segment(role="message", text=model.message))

    return Line(segments=tuple(segments))
```

**Why semantic IR?**

1. **Backend-neutral** — same Line renders to Rich, JSON, or plain text
2. **Testable** — assert on roles and text, not terminal escape codes
3. **Inspectable** — can examine structure before rendering
4. **Transformable** — can filter, modify, aggregate Lines

## Layer 4: Backends

Backends convert semantic IR to specific output formats.

```python
# rich_backend.py
def render(line: Line, theme: Theme) -> Text:
    """Convert semantic Line to Rich Text."""
    result = Text()
    for segment in line.segments:
        style = theme.style_for_role(segment.role)
        result.append(segment.text, style=style)
    return result

# json_backend.py
def render(line: Line) -> dict:
    """Convert semantic Line to JSON-serializable dict."""
    return {
        "segments": [{"role": s.role, "text": s.text} for s in line.segments]
    }

# plain_backend.py
def render(line: Line) -> str:
    """Convert semantic Line to plain string."""
    return "".join(s.text for s in line.segments)
```

Theme lives in the backend layer. It maps roles to styles:

```python
@dataclass(frozen=True)
class Theme:
    styles: Mapping[str, str] = field(default_factory=dict)

    def style_for_role(self, role: str) -> str:
        # Exact match
        if role in self.styles:
            return self.styles[role]
        # Prefix match: "level:error" → "level"
        prefix = role.split(":")[0]
        return self.styles.get(prefix, "")

# Example theme
default_theme = Theme(styles={
    "level:error": "bold red",
    "level:warn": "yellow",
    "level:debug": "dim",
    "source": "cyan",
    "separator": "dim",
    "timestamp": "dim",
})
```

## Rendering Context

Rendering requires more than the display model:

| Component | What It Provides | Lifecycle | Mutability |
|-----------|------------------|-----------|------------|
| **Config** | Structural options | Per-component | Frozen |
| **State** | Accumulated context | Per-session | Mutable* |
| **Theme** | Role → style mapping | Global | Frozen |
| **Data** | Display model | Per-item | Frozen |

*State mutation can be explicit (reducer pattern) or implicit (mutable object).

### Config (Per-Component, Frozen)

Structural decisions. Layout, not style.

```python
@dataclass(frozen=True)
class LogLineConfig:
    show_source: bool = True
    source_width: int = 15
    separator: str = " │ "
    show_timestamp: bool = False
```

### State (Per-Session)

Accumulated context for consistency across items.

```python
@dataclass
class RenderState:
    source_colors: dict[str, str] = field(default_factory=dict)

    def get_source_color(self, source: str) -> str:
        if source not in self.source_colors:
            # Assign consistent color based on hash
            colors = ["blue", "green", "magenta", "cyan", "yellow"]
            self.source_colors[source] = colors[hash(source) % len(colors)]
        return self.source_colors[source]
```

**State mutation patterns:**

```python
# Mutable (simpler)
line = render(model, config, state)  # state.source_colors mutated

# Reducer (more functional, better for testing)
line, new_state = render(model, config, state)  # state unchanged
```

### Theme (Global, Frozen)

Visual vocabulary. Loaded once, used everywhere.

```python
theme = Theme(styles={
    "level:error": "bold red",
    "source:blue": "blue",
    ...
})
```

## Testing

Semantic IR makes testing trivial:

```python
def test_error_level_has_correct_role():
    model = LogLine(message="Connection failed", level="error")
    line = render_log_line(model, config, state)

    # Assert on semantic structure
    roles = [s.role for s in line.segments]
    assert "level:error" in roles

def test_source_included_when_configured():
    model = LogLine(message="OK", source="nginx")
    config = LogLineConfig(show_source=True)
    line = render_log_line(model, config, state)

    assert any(s.role.startswith("source:") for s in line.segments)
    assert any(s.text.strip() == "nginx" for s in line.segments)

def test_source_color_consistency():
    state = RenderState()

    line1 = render_log_line(LogLine(message="a", source="nginx"), config, state)
    line2 = render_log_line(LogLine(message="b", source="nginx"), config, state)

    # Same source gets same color role
    color1 = [s.role for s in line1.segments if s.role.startswith("source:")][0]
    color2 = [s.role for s in line2.segments if s.role.startswith("source:")][0]
    assert color1 == color2
```

No mocking Rich. No capturing terminal output. Just data in, data out.

## Library Boundaries

If this becomes a library (ev-display, ev-view, ev-present):

**In scope:**
- Frozen display models (LogLine, ProgressState, ArtifactRef)
- Normalizer protocol
- Semantic IR (Segment, Line)
- Renderers → Line (backend-neutral)
- Config/State patterns

**Out of scope:**
- Rich/blessed/textual integration (backends live in apps)
- Live UI, async, streaming (app layer)
- Domain logic (above contract layer)

This keeps the library backend-neutral and focused.

## Validation Test

The concept earns its existence if this pipeline is clean and testable:

**Inputs:**
- ev log events
- Docker compose raw lines
- (Future: systemd journal, JSON logs)

**Process:**
1. Normalizers → unified LogLine stream
2. Renderer → Line stream with consistent source coloring
3. Backend → terminal output

**Outputs:**
- Same source always gets same color
- Same layout regardless of input source
- Testable without terminal

If that feels clean, the abstraction is real.

## Summary

```
ev Event ──────────────┐
                       │
docker logs ───────────┼──► Normalizers ──► Display Models ──► Renderers ──► Line ──► Backends ──► Output
                       │         ↑                                  ↑              ↑
systemd journal ───────┘    source-specific              (config, state)      (theme)
                            format knowledge              layout decisions    style decisions
```

- **Contract** (ev): what happened
- **Normalization**: source → canonical model
- **Display Models**: layout-aware, style-agnostic, frozen
- **Rendering**: (model, config, state) → semantic IR
- **Backends**: semantic IR → styled output
- **Theme**: role → style mapping

The semantic IR (Segment/Line) is the key insight. It's the backend-neutral representation that makes everything testable and portable.
