# Topic Registry Pattern

*Central registry of known signal topics for routing and validation.*

When your CLI has many signal types, a topic registry provides:
- Single source of truth for all signals
- Routing table for emitters
- Fallback handling for unknown signals
- Documentation of expected data shapes

## The Pattern

Define a frozen set of known topics:

```python
# signals.py - Single source of truth
KNOWN_TOPICS = frozenset({
    "signal:status.stack",
    "signal:restart.status",
    "signal:deploy.connecting",
    "signal:deploy.connected",
    "signal:deploy.stage_started",
    "signal:deploy.stage_completed",
    "signal:deploy.stage_failed",
    "artifact:deploy_result",
})
```

Emitters check against this registry:

```python
class PlainEmitter:
    def emit(self, event: Event) -> None:
        topic = event.topic

        if topic in KNOWN_TOPICS:
            # Known topic - use custom handler
            handler = self._get_handler(topic)
            handler(event)
        elif topic.startswith("signal:") or topic.startswith("artifact:"):
            # Unknown but structured - generic fallback
            self._generic_signal(event)
        # else: narrative log, progress, etc. - default handling
```

## Topic Handlers

Map topics to handler methods:

```python
class PlainEmitter:
    HANDLERS = {
        "signal:status.stack": "_handle_status_stack",
        "signal:deploy.stage_completed": "_handle_stage_completed",
        "signal:deploy.stage_failed": "_handle_stage_failed",
        "artifact:deploy_result": "_handle_deploy_result",
    }

    def emit(self, event: Event) -> None:
        handler_name = self.HANDLERS.get(event.topic)
        if handler_name:
            handler = getattr(self, handler_name)
            handler(event)
        else:
            self._fallback(event)

    def _handle_status_stack(self, event: Event) -> None:
        data = event.data
        status = "[OK]" if data.get("status") == "healthy" else "[FAIL]"
        print(f"{status} {data.get('stack')}: {data.get('healthy_count')}/{data.get('total_count')}")

    def _handle_stage_completed(self, event: Event) -> None:
        data = event.data
        print(f"  ✓ {data.get('stage')} ({data.get('duration_ms'):.0f}ms)")
```

## Signal Schemas

Document expected data shapes with TypedDict:

```python
from typing import TypedDict, Literal

class StackStatusSignal(TypedDict, total=False):
    """Data shape for signal:status.stack"""
    stack: str
    status: Literal["healthy", "unhealthy", "error"]
    healthy_count: int
    total_count: int
    duration_ms: float
    error: str  # only when status="error"

class StageCompletedSignal(TypedDict, total=False):
    """Data shape for signal:deploy.stage_completed"""
    stack: str
    stage: str
    duration_ms: float

class StageFailedSignal(TypedDict, total=False):
    """Data shape for signal:deploy.stage_failed"""
    stack: str
    stage: str
    duration_ms: float
    error: str
```

These are documentation, not runtime enforcement. They:
- Provide IDE autocomplete
- Document expected fields
- Guide emitter implementation

## Prefix Routing

For related signals, route by prefix:

```python
def emit(self, event: Event) -> None:
    topic = event.topic

    # Exact match first
    if topic in self.HANDLERS:
        self._handle_exact(topic, event)
        return

    # Prefix match for signal groups
    if topic.startswith("signal:deploy."):
        self._handle_deploy_signal(event)
    elif topic.startswith("signal:status."):
        self._handle_status_signal(event)
    elif topic.startswith("artifact:"):
        self._handle_artifact(event)
```

## Fallback for Unknown Signals

Unknown signals should render gracefully:

```python
def _fallback(self, event: Event) -> None:
    if self.verbosity < 1:
        return  # Quiet mode - skip unknown signals

    # Generic rendering for unknown signals
    if event.is_signal:
        name = event.signal_name
        data = {k: v for k, v in event.data.items() if k != "signal"}
        print(f"  {name}: {data}")
    elif event.kind == "artifact":
        type_ = event.data.get("type", "unknown")
        print(f"  [artifact:{type_}] {event.data}")
```

This enables extensibility: new signals render (generically) without modifying emitter code.

## Validation

Optionally warn about unknown signals in development:

```python
import warnings

def emit(self, event: Event) -> None:
    topic = event.topic

    if topic.startswith("signal:") and topic not in KNOWN_TOPICS:
        warnings.warn(f"Unknown signal topic: {topic}", stacklevel=2)

    # ... normal handling
```

Or fail loudly in tests:

```python
def test_all_signals_are_known():
    emitter = ListEmitter()
    run_all_operations(emitter)

    for event in emitter.events:
        if event.topic.startswith("signal:"):
            assert event.topic in KNOWN_TOPICS, f"Unknown signal: {event.topic}"
```

## Example: Full Registry Module

```python
# signals.py
from typing import TypedDict, Literal

# Topic registry - single source of truth
KNOWN_TOPICS = frozenset({
    # Status signals
    "signal:status.stack",
    "signal:status.service",

    # Deploy signals
    "signal:deploy.connecting",
    "signal:deploy.connected",
    "signal:deploy.stage_started",
    "signal:deploy.stage_completed",
    "signal:deploy.stage_failed",

    # Restart signals
    "signal:restart.status",

    # Artifacts
    "artifact:deploy_result",
    "artifact:status_report",
})


# Signal schemas (documentation only)
class StackStatusSignal(TypedDict, total=False):
    stack: str
    status: Literal["healthy", "unhealthy", "error"]
    healthy_count: int
    total_count: int
    duration_ms: float
    error: str


class DeployStageSignal(TypedDict, total=False):
    stack: str
    stage: str
    duration_ms: float
    error: str  # only for failed


class DeployResultArtifact(TypedDict, total=False):
    stack: str
    success: bool
    stages_completed: list[str]
    failed_stage: str | None
    duration_ms: float


# Helper for checking known topics
def is_known_topic(topic: str) -> bool:
    return topic in KNOWN_TOPICS
```

## When to Use

Use a topic registry when:
- Your CLI has 5+ distinct signal types
- Multiple emitters need consistent routing
- You want to catch typos in signal names
- You need to document signal data shapes

Skip for simple CLIs with 1-2 signals.

## Related

- [signal.md](../concept/signal.md) — Signal concept and naming conventions
- [signal-lifecycle.md](signal-lifecycle.md) — Stage progression pattern
