# EVToolkit Code Architecture Analysis

## Overview

ev-toolkit is a ~5,000 line Python library providing composable utilities for the ev event contract. It's organized into distinct layers: emitter wrappers, collectors, presentation/rendering, generation, and convenience APIs.

## Core Module Organization

**Top-level modules (public API):**
- `__init__.py` - Re-exports public API
- `emitter.py` - Emitter protocols
- `wrappers.py` - Emitter wrapper implementations
- `collector.py` - Event collection and aggregation
- `protocols.py` - Collector protocols
- `convenience.py` - One-liner helpers
- `mode.py` - Output mode detection
- `resolve.py` - Resource resolution with suggestions
- `runtime.py` - CLI harness integration
- `errors.py` - Base error classes
- `recipes.py` - Copy-paste patterns
- `rich_emitter.py` - Rich terminal output (optional)

**Subpackages:**
- `present/` - Terminal presentation layer (7 modules)
- `gen/` - CLI generation from specs (4 modules)

## Architectural Layers

### Layer 1: Emitter Protocol & Wrappers

**Pattern: Composition over inheritance**

`emitter.py` defines protocol interfaces:
- `EmitterLike` - Minimal emitter interface (duck-typed on ev.Emitter)
  - `emit(event)`
  - `finish(result)`
  - Context manager protocol (`__enter__`, `__exit__`)
- `EmitterFactory` - Protocol for creating mode-appropriate emitters

`wrappers.py` implements layerable wrappers:
- `RecordingEmitter` - Captures events+result for analysis
- `QuietEmitter` - Filters to errors/warnings only
- `VerbosityEmitter` - Level-based filtering (error:0, warn:0, info:1, debug:2)
- `TeeEmitter` - Broadcasts to multiple emitters
- `FilterEmitter` - Predicate-based filtering
- `TimingEmitter` - Auto-adds duration to result.meta
- `CountingEmitter` - Counts matching events
- `FileEmitter` - Writes JSONL for debugging/LLM

**Key insight:** Wrappers use `__slots__` for memory efficiency and always delegate context manager calls. All implement the EmitterLike protocol for composability.

### Layer 2: Collection & Aggregation

**Pattern: Query API + streaming handle() method**

`collector.py` provides hierarchical collection:
- `ResourceState` - Dataclass for tracked resources
- `Collector` - Base class with query API
  - `collect(event) -> bool` - Filter+store
  - `signals(name) -> list[Event]` - Query by signal name
  - `last_signal(name) -> Event | None` - Latest observation
  - `resources -> list[ResourceState]` - Extracted resources
  - `by_context() -> dict` - Group resources
  - `context_health(context) -> tuple[int, int]` - Health counting
  - `handle(event) -> Context | None` - Streaming aggregation hook
  - Override points: `_should_collect()`, `_extract_resource()`

- `SignalCollector` - Filters to signal_name events only
- `ContainerCollector` - Extracts container health signals

**Functional utilities:**
- `collect_signals(events, predicate) -> dict[str, list[Event]]`
- `build_context_from_signal(event) -> Context | None`

`protocols.py` provides duck-typed interfaces:
- `CollectorProtocol` - Minimal interface for collectors
- `AggregatingCollector` - Adds handle() for streaming

**Key insight:** Two-phase model: (1) post-hoc query via collector property accessors, (2) streaming via handle() returning render Context.

### Layer 3: Presentation & Rendering

**Pattern: Backend-neutral semantic IR**

**Core IR (`ir.py`):**
- `Segment` - Semantic piece of output
  - `role` (STABLE) - "source", "level", "message", "timestamp", "separator"
  - `tags` (STABLE) - Frozenset of "namespace:value" identifiers
  - `hint` (UNSTABLE) - Presentation suggestion ("blue", "bold", etc)
- `Line` - Immutable sequence of Segments with optional Context
  - `plain()` - Concatenate text
  - `with_segments(*segments)` - Append segments
  - `with_context(context)` - Attach semantic context

**Semantic model (`semantic.py`):**
- `Context` - Immutable semantic identity flowing through pipeline
  - Fields: kind, name, source, level, state, data, message
  - Methods: `with_updates(**kwargs)`, `merge_data(**kwargs)`

**Display models:**
- `Message` - Timestamped narrative (frozen dataclass)
- `Status` - Point-in-time state indicator (icon, label, detail, annotation)
- `Progress` - Progress indicator
- `Field` - Key-value datum
- `Notice` - Notification primitive

**Rendering pipeline:**
1. `render_message()` - Message → Line with source padding, separator, level tags
2. `render_status()` - Status → Line with state icon
3. `render_field()` - Field → Line with key/value alignment
4. `render_message_lines()` - Multi-line handling (first line decorated, continuation indented)
5. `render_event()` - Main dispatcher
   - Dispatches on event.kind (log, metric, artifact, progress)
   - Builds Context from event attributes
   - Returns Line or Iterator[Line]
   - Attaches Context to each Line

**Normalization (`normalize.py`):**
- `Normalizer` protocol - Converts domain objects to Message
- `from_event()` - Duck-typed event→Message adapter
- `supports()` - Checks if object has minimum event interface

**Key insight:** Separation of semantic IR (Segment/Line/Context) from rendering (role-based dispatch). Backends convert Lines to rich.Text/str/HTML using segment roles and context fields.

### Layer 4: Mode Detection

`mode.py` - Environment-aware output mode selection:
- `OutputMode` enum: RICH, PLAIN, JSON
- `detect_mode()` - Priority: json_flag > plain_flag > non-TTY > NO_COLOR > RICH
- `detect_verbosity()` - 0=quiet, 1=normal (default), 2+=verbose

### Layer 5: Convenience APIs

`convenience.py`:
- `get_emitter()` - Selects emitter by flags (quiet > json > rich)
- `tee(*emitters)` - Creates TeeEmitter
- `signal(emitter, signal_name, message_template)` - Factory for fixed-name signal emitters

### Layer 6: Runtime Harness

`runtime.py` - Argparse integration:
- `add_standard_args()` - Adds --json, --plain, -q, -v, --record flags
- `standard_emitter()` - Builds mode-appropriate emitter stack
- `run()` - Main CLI harness: parse args → call operation → finish emitter → return exit code
  - Async support (detects awaitable results)
  - Exception handling: CLIError → code 2, KeyboardInterrupt → 130, other → 1
  - Optional JSONL recording via --record

### Layer 7: Error Handling

`errors.py`:
- `CLIError` - Abstract base with `message` and `suggestion` properties
  - Subclasses provide user-friendly display

`resolve.py`:
- `Resolver` protocol - get(name) + list_names()
- `NotFoundError` - CLIError with resource_kind, name, available
  - Generates suggestions automatically

### Layer 8: Code Generation

`gen/` subpackage:
- `spec.py` - Declarative specs
  - `Arg`, `Flag` - Input definitions
  - `SignalField`, `SignalSpec` - Output signal schemas
  - `ToolSpec`, `CommandSpec` - Tool definitions (frozen dataclasses)
  - TYPE_MAP - Type mapping for code generation

- `scaffold.py` - Code generator
  - `generate()` - Dispatches on framework (standalone, argparse, cappa)
  - Generates Python code with argparse wiring, signal placeholders, result typing

- `kdl_parser.py` - KDL format parser for specs
- `cli.py` - CLI entry point (ev-gen command)

### Layer 9: Rich Output (Optional)

`rich_emitter.py`:
- `RichEmitter` - Uses ev-present pipeline
- HINT_STYLES - Maps hint strings to Rich styles
- CONTEXT_STYLES - Semantic styling based on (field, value) tuples
- `_to_rich_text()` - Converts Line to rich.Text
- Gracefully degrades to PlainEmitter if Rich unavailable

## Key Design Patterns

### 1. Protocol-Based Interfaces
- EmitterLike, CollectorProtocol, AggregatingCollector, Resolver, Normalizer
- Enable duck-typing without inheritance
- Used with @runtime_checkable for isinstance() checks

### 2. Wrapper Composition
- Emitters wrap emitters: `TeeEmitter(FilterEmitter(TimingEmitter(...)))`
- Each wrapper maintains `__slots__` for efficiency
- All delegate context manager calls
- Result always passes through (filtering only affects events)

### 3. Semantic Intermediate Representation
- Segment/Line separate semantic identity (role, tags, context) from presentation (hint)
- Roles are stable; hints are unstable (can change)
- Backend-neutral: any backend can convert Line to its format
- Context carries domain semantics without parsing content

### 4. Two-Phase Collection
- Post-hoc: query via collector properties (signals, resources, by_context)
- Streaming: handle() method for real-time aggregation decisions
- Default handle() collects and returns None (no render decision)

### 5. Frozen Dataclasses
- ToolSpec, CommandSpec, Context, Line, Segment, Message
- Immutability ensures safe sharing
- With_* methods create modified copies

### 6. Layered Configuration
- MessageConfig, StatusConfig, FieldConfig - Frozen structural options
- RenderState - Mutable accumulation (source_hints, line_count)
- Separation enables reuse across rendering passes

## Type System Usage

- Heavy use of `from __future__ import annotations` for deferred evaluation
- TYPE_CHECKING blocks for circular import avoidance
- TypeVar (R) for generic Resolver protocol
- @dataclass(frozen=True) for immutable models
- frozenset[str] for Segment.tags
- Protocol with @runtime_checkable for duck-typing validation

## Dependencies

**Core (internal):**
- ev >= 0.3.0 (the event contract)

**Optional:**
- rich >= 13.0 (for RichEmitter)
- kdl-py >= 1.0.0 (for KDL spec parsing)

**Dev:**
- pytest, pytest-cov, ruff

## Entry Points

- CLI: `ev-gen` - Scaffold generation tool (gen/cli.py:main)
- Module: Public API via __init__.py re-exports

## Code Quality Patterns

- Comprehensive docstrings with Examples sections
- Type hints throughout (python 3.13+)
- Ruff linting (line-length 88, target-version py313)
- 90% test coverage requirement
- Clear override points in base classes (_should_collect, _extract_resource)

## How It Relates to ev

ev-toolkit extends the ev contract (events + results) with:
1. **Emitter enhancements** - Wrappers that compose cleanly
2. **Collection layer** - Capture and query events post-hoc
3. **Presentation** - Bridge from events to terminal display
4. **Code generation** - Bootstrap CLI projects matching ev semantics
5. **Runtime integration** - Standard argparse wiring with mode detection

The toolkit never breaks ev's contract; it works with event-like objects via duck-typing.
