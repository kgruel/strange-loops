# Display Models

*The missing layer between contract and presentation.*

## The Gap

ev defines the contract layer: Event describes what happened, Result describes the outcome. But between receiving an Event and producing styled terminal output, there's a conceptual gap.

```
Domain Logic
    ↓
ev Contract (Event, Result)
    ↓
??? ← What goes here?
    ↓
Styled Terminal Output (Rich Text)
```

For trivial cases, emitters bridge this directly. For complex cases, an intermediate layer emerges.

## The Display Model Layer

A **display model** is the canonical form for a category of content, ready for rendering but not yet styled.

```
ev Event (log kind) ────┐
                        ├──► LogLine ──► render() ──► Text
external logs ──────────┘

ev Event (progress) ────────► ProgressState ──► render() ──► Text

ev Event (artifact) ────────► ArtifactRef ──► render() ──► Text
```

Display models are:
- **Source-agnostic** — ev events and external sources converge
- **Renderer-aware** — shaped for rendering needs
- **Frozen** — immutable data, no behavior

## Why Not Render Events Directly?

Three reasons display models exist:

### 1. Source Convergence

Log-like content comes from multiple sources:
- ev log events (your CLI's output)
- Docker compose logs (external process)
- Systemd journal (system logs)
- JSON log files (structured logs)

All should render consistently. A display model provides the convergence point.

### 2. Rendering Needs Differ from Contract Needs

ev Events are optimized for **emission** — what the domain wants to say.
Display models are optimized for **rendering** — what the presenter needs to show.

| ev Event | Display Model (LogLine) |
|----------|------------------------|
| `ts: float` (epoch) | `timestamp: datetime` (parsed) |
| `data: Mapping` (arbitrary) | `source: str` (extracted) |
| `level: str` | `level: str` (same) |
| `message: str` | `message: str` (same) |
| `signal_name` (derived) | `source` (first-class) |

The shapes overlap but aren't identical. Display models reshape for rendering convenience.

### 3. Accumulated Context

Rendering often needs context beyond the single item:
- Consistent colors for the same source across lines
- Column widths based on seen content
- Counts, aggregations, groupings

This context accumulates across items. Display models are the natural attachment point.

## The Rendering Stack

Four layers, each with distinct responsibility:

```
┌─────────────────────────────────────────────────────┐
│ 1. CONTRACT LAYER (ev)                              │
│    Event, Result — what happened                    │
│    Frozen, minimal, serializable                    │
│    Lives in: ev core                                │
├─────────────────────────────────────────────────────┤
│ 2. DISPLAY MODEL LAYER                              │
│    LogLine, ProgressState, etc. — ready to render   │
│    Source-agnostic, renderer-aware, frozen          │
│    Lives in: ev-toolkit or application              │
├─────────────────────────────────────────────────────┤
│ 3. RENDERING LAYER                                  │
│    render_log_line(), etc. — styling logic          │
│    Pure functions: (model, context) → styled output │
│    Lives in: application                            │
├─────────────────────────────────────────────────────┤
│ 4. PRESENTATION LAYER (Rich, terminal)              │
│    Text, Tree, Live — actual output                 │
│    Library code, not ours                           │
│    Lives in: rich, blessed, etc.                    │
└─────────────────────────────────────────────────────┘
```

## Rendering Context

Rendering requires more than the display model. The full context:

| Component | What It Provides | Lifecycle | Mutability |
|-----------|------------------|-----------|------------|
| **Theme** | Visual tokens (colors, icons) | Global | Frozen |
| **Config** | Structural options (widths, separators) | Per-component | Frozen |
| **State** | Accumulated context (color assignments) | Per-session | Mutable |
| **Data** | The display model (LogLine) | Per-item | Frozen |

### Theme (Global)

Visual vocabulary shared across all rendering:

```python
@dataclass(frozen=True)
class Theme:
    error_color: str = "red"
    warn_color: str = "yellow"
    success_icon: str = "✓"
    error_icon: str = "✗"
    # ...
```

Loaded once, used everywhere. May come from config file or environment.

### Config (Per-Component, Frozen)

Structural decisions for a specific renderer:

```python
@dataclass(frozen=True)
class LogLineConfig:
    show_source: bool = True
    source_width: int = 15
    separator: str = " │ "
    show_timestamp: bool = False
    truncate_at: int | None = None
```

Created when component initializes, immutable thereafter. Describes "how to format" without visual details.

### State (Per-Session, Mutable)

Context accumulated during rendering:

```python
@dataclass
class RenderState:
    source_colors: dict[str, str] = field(default_factory=dict)
    line_count: int = 0
    seen_levels: set[str] = field(default_factory=set)
```

Mutated by render functions. Enables consistency across items (same source → same color).

### Data (Per-Item, Frozen)

The display model itself:

```python
@dataclass(frozen=True)
class LogLine:
    raw: str
    message: str
    source: str | None = None
    level: str | None = None
    timestamp: datetime | None = None
```

One per item being rendered. Immutable.

## The Render Function Pattern

Render functions are pure (modulo state mutation) transformations:

```python
def render_log_line(
    line: LogLine,          # Data (per-item)
    theme: Theme,           # Visual tokens (global)
    config: LogLineConfig,  # Structural options (per-component)
    state: RenderState,     # Accumulated context (per-session)
) -> Text:
    """Transform LogLine to styled Rich Text."""
    ...
```

The signature makes dependencies explicit:
- What are we rendering? (`line`)
- What colors/icons? (`theme`)
- What structure? (`config`)
- What context? (`state`)

## State Lifecycle

State must be managed by the caller:

```python
# Caller creates state
state = RenderState()

# Same state passed to all render calls
for line in log_lines:
    text = render_log_line(line, theme, config, state)
    console.print(text)

# State accumulated (source_colors populated, line_count incremented)
```

**Why caller-managed?**
- Explicit lifecycle (no hidden singletons)
- Testable (inject state, verify mutations)
- Flexible (reset state, share across components, serialize)

## MVVM Analogy

The pattern mirrors Model-View-ViewModel:

| MVVM | ev Rendering Stack |
|------|-------------------|
| Model | ev Event (facts from domain) |
| ViewModel | LogLine (display-ready form) |
| View | Rich Text (styled output) |

ev Events are the Model — raw facts.
Display models are the ViewModel — shaped for presentation.
Render output is the View — final styled form.

## When to Create Display Models

Create a display model when:
- Multiple sources produce similar content (convergence)
- Rendering needs differ from emission needs (reshaping)
- Context accumulates across items (state attachment)

Skip display models when:
- Single source, simple rendering
- Direct Event → output is clear
- No accumulated context needed

## Example: LogLine

```python
# Display model
@dataclass(frozen=True)
class LogLine:
    raw: str
    message: str
    source: str | None = None
    level: Literal["debug", "info", "warn", "error"] | None = None
    timestamp: datetime | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

# Converters (source-specific)
def from_event(event: Event) -> LogLine:
    """ev log Event → LogLine"""
    return LogLine(
        raw=event.message,
        message=event.message,
        source=event.signal_name,
        level=event.level,
        timestamp=datetime.fromtimestamp(event.ts),
        data=dict(event.data),
    )

def from_docker_compose(line: str) -> LogLine:
    """Docker compose log line → LogLine"""
    # Parse "service | message" format
    ...

# Renderer (source-agnostic)
def render_log_line(
    line: LogLine,
    theme: Theme,
    config: LogLineConfig,
    state: RenderState,
) -> Text:
    """LogLine → Rich Text"""
    ...
```

## Relationship to ev

ev stays at the contract layer. Display models are explicitly **not part of ev core**.

| Layer | Package | Stability |
|-------|---------|-----------|
| Contract | ev | Frozen |
| Display Model | ev-toolkit or app | Evolving |
| Rendering | Application | Application-specific |

This separation means:
- ev remains minimal and stable
- Display models can evolve with rendering needs
- Applications own their presentation logic

## Summary

Display models fill the gap between contract and presentation:

1. **Contract layer** (ev) — what happened
2. **Display model layer** — ready to render, source-agnostic
3. **Rendering layer** — pure functions with theme/config/state
4. **Presentation layer** — actual terminal output

The rendering context pattern (Theme + Config + State + Data) makes dependencies explicit and enables accumulated context across items.

Display models are not part of ev. They're the bridge each application builds between ev's facts and their presentation needs.
