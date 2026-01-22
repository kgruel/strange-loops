# EV Codebase: Code-Only Architecture Analysis

## Core Architecture

**ev** is a ~500 LOC contract library with three core modules:
- **types.py**: Event and Result frozen dataclasses with complete immutability
- **emitter.py**: Protocol-based interface with reference implementations
- **emitters/**: JsonEmitter and PlainEmitter rendering implementations

## Key Abstractions

### Event - Immutable streaming facts

- 5 kind discriminators (log, progress, artifact, metric, input)
- 4 severity levels (debug, info, warn, error)
- 6 factory methods (log, progress, artifact, metric, input, log_signal)
- Typed using `Literal` unions for exhaustive checking
- Auto-populated timestamps via `default_factory`
- Signal events as structured logs (machine-readable observables)
- Topic-based filtering (`event.topic`)

### Result - Immutable outcome summary

- 2 status values (ok, error)
- Invariant enforcement: ok→code=0, error→code≠0 (in `__post_init__`)
- 2 factory methods (ok, error)
- Both data and meta fields for structured output + metadata

### Emitter - Structural protocol (not ABC)

- `emit(event)` for streaming
- `finish(result)` for finalization
- Lifecycle invariants enforced by all implementations
- Context manager protocol support

## Design Patterns

1. **Immutability**: Frozen dataclasses + MappingProxyType wrapping
2. **Protocol-based**: Structural typing enables duck typing without inheritance
3. **Factory methods**: Encode conventions (e.g., artifact requires type)
4. **Lifecycle enforcement**: `_finished` flag prevents double-finish and post-finish emit
5. **Literal discriminators**: Type-safe kind/level/status checking
6. **Topic-based filtering**: Unifies signal name and artifact type into queryable surface
7. **Stdout/stderr discipline**: JsonEmitter separates result (stdout) from events (stderr)
8. **Round-trip serialization**: `to_dict()`/`from_dict()` with timestamp sentinel (0.0)

## Emitter Implementations

- **ListEmitter**: In-memory collection for testing
- **NullEmitter**: No-op but enforces invariants
- **JsonEmitter**: Result as JSON to stdout; optional JSONL events to stderr
- **PlainEmitter**: Human-readable text with kind-specific formatting (5 formatters for each event type)

## Type System

- `EventKind`, `EventLevel`, `ResultStatus` as Literal unions
- Full type hints with `typing.Protocol` for structural typing
- `Self` return type in factories (PEP 673)
- `Mapping[str, Any]` for read-only collections

## Error Handling

- Invariant violations raise `ValueError` at construction
- Lifecycle violations raise `RuntimeError` with clear messages
- No silent failures; context manager doesn't suppress exceptions

## Testing Characteristics

- 100% coverage requirement enforced
- Tests verify immutability (caller dict mutations don't affect instances)
- Round-trip serialization testing
- Protocol satisfaction verification
- Output format validation
- Context manager testing

## Architecture Constraints

- Zero external dependencies (stdlib only)
- Frozen + MappingProxyType throughout (complete immutability)
- No inheritance hierarchies (protocol-based)
- Full type hints
- Lifecycle invariants always checked

## Evolution

v0.6.0 simplified by removing TeeEmitter, FileEmitter, RichEmitter (moved to ev-toolkit), keeping core minimal and portable.
