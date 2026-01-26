---
status: completed
updated: 2026-01-04
---

# ev-display Library Handoff

Developing the display model layer as a standalone library.

## Vision

A tiny, backend-neutral library that bridges ev's contract layer to terminal presentation. Like ev, it's frozen and opinionated.

```
ev (contract) → ev-display (presentation models) → app (backends)
```

## Project Setup

```bash
# Create new repo
mkdir ev-display && cd ev-display
git init

# Python setup
uv init
uv add --dev pytest pytest-cov ruff

# Structure
src/ev_display/
├── __init__.py
├── models.py      # LogLine, ProgressState, ArtifactRef
├── ir.py          # Segment, Line
├── normalize.py   # Normalizer protocol, from_event()
├── render.py      # render_log_line() → Line
└── context.py     # Config, State base patterns

tests/
├── test_models.py
├── test_ir.py
├── test_normalize.py
└── test_render.py
```

## Core Types (Priority Order)

### Phase 1: Semantic IR

The foundation. Everything else builds on this.

```python
# ir.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Segment:
    """A piece of output with a semantic role."""
    role: str   # "timestamp", "source:blue", "level:error", "message"
    text: str

@dataclass(frozen=True)
class Line:
    """A complete line of semantic output."""
    segments: tuple[Segment, ...]

    def __iter__(self):
        return iter(self.segments)

    def text(self) -> str:
        """Plain text without roles."""
        return "".join(s.text for s in self.segments)

    def with_segments(self, *segments: Segment) -> "Line":
        """Return new Line with additional segments."""
        return Line(segments=self.segments + segments)
```

**Tests:**
- Segment is frozen
- Line is frozen
- Line.text() concatenates
- Line iteration works

### Phase 2: Display Models

Start with LogLine only. Add others when needed.

```python
# models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

@dataclass(frozen=True)
class LogLine:
    """Display model for log-like content.

    Layout-aware: contains fields renderers need.
    Style-agnostic: no colors, icons, or styling decisions.
    """
    message: str
    source: str | None = None
    level: str | None = None  # "error", "warn", "info", "debug", "trace"
    timestamp: datetime | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
```

**Tests:**
- LogLine is frozen
- Defaults work
- All fields accessible

### Phase 3: Normalizers

Protocol + ev adapter.

```python
# normalize.py
from typing import Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

@runtime_checkable
class Normalizer(Protocol[T]):
    """Converts source-specific data to display models."""

    def accepts(self, item: object) -> bool:
        """Return True if this normalizer handles the item."""
        ...

    def normalize(self, item: T) -> LogLine:
        """Convert item to LogLine."""
        ...


def from_event(event) -> LogLine:
    """Convert ev Event to LogLine.

    Note: Takes 'event' as Any to avoid ev dependency.
    Duck-types on event.message, event.level, etc.
    """
    from datetime import datetime

    return LogLine(
        message=getattr(event, "message", ""),
        source=getattr(event, "signal_name", None),
        level=getattr(event, "level", None),
        timestamp=datetime.fromtimestamp(getattr(event, "ts", 0)),
        data=dict(getattr(event, "data", {})),
    )
```

**Tests:**
- from_event() extracts fields correctly
- Handles missing attributes gracefully
- Protocol is runtime checkable

### Phase 4: Rendering Context

Config and State patterns.

```python
# context.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class LogLineConfig:
    """Structural options for LogLine rendering.

    Layout decisions, not styling.
    """
    show_source: bool = True
    source_width: int = 15
    separator: str = " │ "
    show_timestamp: bool = False
    timestamp_format: str = "%H:%M:%S"


@dataclass
class RenderState:
    """Accumulated context during rendering.

    Mutable. Caller owns lifecycle.
    """
    source_colors: dict[str, str] = field(default_factory=dict)
    _color_cycle: tuple[str, ...] = ("blue", "green", "magenta", "cyan", "yellow")

    def get_source_color(self, source: str) -> str:
        """Get consistent color for source. Assigns if new."""
        if source not in self.source_colors:
            idx = len(self.source_colors) % len(self._color_cycle)
            self.source_colors[source] = self._color_cycle[idx]
        return self.source_colors[source]
```

**Tests:**
- Config is frozen
- State is mutable
- get_source_color is consistent
- Different sources get different colors (until cycle repeats)

### Phase 5: Renderer

The core logic. Produces semantic IR.

```python
# render.py
from .ir import Segment, Line
from .models import LogLine
from .context import LogLineConfig, RenderState


def render_log_line(
    model: LogLine,
    config: LogLineConfig,
    state: RenderState,
) -> Line:
    """Render LogLine to semantic Line.

    Returns backend-neutral IR. Caller converts to rich.Text, str, etc.
    """
    segments: list[Segment] = []

    # Timestamp (optional)
    if config.show_timestamp and model.timestamp:
        ts_str = model.timestamp.strftime(config.timestamp_format)
        segments.append(Segment(role="timestamp", text=ts_str + " "))

    # Source (optional)
    if config.show_source and model.source:
        color = state.get_source_color(model.source)
        padded = model.source.ljust(config.source_width)
        segments.append(Segment(role=f"source:{color}", text=padded))
        segments.append(Segment(role="separator", text=config.separator))

    # Message with level role
    if model.level:
        segments.append(Segment(role=f"level:{model.level}", text=model.message))
    else:
        segments.append(Segment(role="message", text=model.message))

    return Line(segments=tuple(segments))
```

**Tests:**
- No source when show_source=False
- Source padded to source_width
- Level encoded in role
- Timestamp formatted correctly
- Color consistency across calls

## Package Exports

```python
# __init__.py
from ev_display.ir import Segment, Line
from ev_display.models import LogLine
from ev_display.normalize import Normalizer, from_event
from ev_display.context import LogLineConfig, RenderState
from ev_display.render import render_log_line

__all__ = [
    # IR
    "Segment",
    "Line",
    # Models
    "LogLine",
    # Normalization
    "Normalizer",
    "from_event",
    # Context
    "LogLineConfig",
    "RenderState",
    # Rendering
    "render_log_line",
]
```

## Validation Test

The library earns its existence if this works cleanly:

```python
# test_integration.py
from ev_display import (
    LogLine, LogLineConfig, RenderState,
    render_log_line, from_event, Line
)

def test_unified_pipeline():
    """ev events and docker logs render identically."""
    config = LogLineConfig(source_width=10)
    state = RenderState()

    # From ev Event (mock)
    class MockEvent:
        message = "Connected"
        level = "info"
        signal_name = "nginx"
        ts = 1704326400.0
        data = {}

    line1 = render_log_line(from_event(MockEvent()), config, state)

    # From docker compose format
    docker_line = LogLine(message="Connected", source="nginx", level="info")
    line2 = render_log_line(docker_line, config, state)

    # Same structure
    assert [s.role for s in line1] == [s.role for s in line2]

    # Same source color
    colors1 = [s.role for s in line1 if s.role.startswith("source:")]
    colors2 = [s.role for s in line2 if s.role.startswith("source:")]
    assert colors1 == colors2

def test_backend_neutral():
    """Line can be converted to any format."""
    model = LogLine(message="Error", level="error", source="app")
    config = LogLineConfig()
    state = RenderState()

    line = render_log_line(model, config, state)

    # Plain text
    plain = line.text()
    assert "Error" in plain
    assert "app" in plain

    # JSON-like
    as_dict = [{"role": s.role, "text": s.text} for s in line]
    assert any(s["role"] == "level:error" for s in as_dict)

    # Rich (in app, not library)
    # rich_text = rich_backend.render(line, theme)
```

## Out of Scope (For Now)

- **ProgressState, ArtifactRef** — add when needed
- **Theme** — lives in app/backend layer
- **Rich/blessed integration** — app provides backends
- **Async/streaming** — app layer
- **Level detection** — app layer (regex patterns vary)
- **Docker/systemd parsers** — app layer (source-specific)

## Dependencies

```toml
# pyproject.toml
[project]
name = "ev-display"
version = "0.1.0"
requires-python = ">=3.11"
# No runtime dependencies! Not even ev.
dependencies = []

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "ruff"]
```

**Zero runtime dependencies.** The from_event() function duck-types on ev.Event without importing it.

## Success Criteria

1. **All tests pass** with 100% coverage
2. **No Rich/ev imports** in library code
3. **Integration test** shows unified pipeline
4. **hlab can adopt** by replacing its LogLine with ev-display's

## Future Considerations

- **ProgressState** — when a CLI needs progress display models
- **ArtifactRef** — when artifact rendering needs convergence
- **Reducer-style state** — `render() -> (Line, State)` for pure functional style
- **Line transformers** — filter, map, aggregate Lines
- **Role registry** — validate roles, provide completions

## Notes

This follows ev's philosophy:
- Frozen, minimal, opinionated
- No dependencies
- Backend-neutral
- Easy to understand, hard to misuse

The semantic IR (Segment/Line) is the key insight. Everything else is sugar.
