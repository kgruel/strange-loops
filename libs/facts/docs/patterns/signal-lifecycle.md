# Signal Lifecycle Pattern

*Structured signaling for multi-stage operations.*

When an operation has distinct stages (deploy, build, migration), use a consistent signal lifecycle to communicate progress.

## The Pattern

For each stage, emit three signals:

```python
# Stage starting
Event.log_signal("deploy.stage_started", stage="rsync", stack="media")

# ... do work ...

# Stage completed (success)
Event.log_signal("deploy.stage_completed", stage="rsync", duration_ms=2340, stack="media")

# OR stage failed
Event.log_signal("deploy.stage_failed", stage="rsync", error="Connection refused", duration_ms=1200, stack="media")
```

## Signal Naming Convention

Use `domain.subject` format:

| Signal | Meaning |
|--------|---------|
| `deploy.stage_started` | Stage is beginning |
| `deploy.stage_completed` | Stage finished successfully |
| `deploy.stage_failed` | Stage failed with error |
| `deploy.connecting` | Ephemeral: attempting connection |
| `deploy.connected` | Ephemeral: connection established |

The domain prefix (`deploy.`) groups related signals for routing.

## Implementation

```python
import time
from ev import Event, Result, Emitter

STAGES = ["decrypt", "rsync", "compose_up", "health_check"]

async def deploy(stack: str, emitter: Emitter) -> Result:
    stages_completed: list[str] = []
    failed_stage: str | None = None
    error_message: str | None = None
    total_start = time.perf_counter()

    for stage in STAGES:
        start = time.perf_counter()

        # Signal: starting
        emitter.emit(Event.log_signal(
            "deploy.stage_started",
            stage=stage,
            stack=stack
        ))

        success, error = await execute_stage(stage)
        duration_ms = (time.perf_counter() - start) * 1000

        if success:
            # Signal: completed
            emitter.emit(Event.log_signal(
                "deploy.stage_completed",
                stage=stage,
                stack=stack,
                duration_ms=duration_ms
            ))
            stages_completed.append(stage)
        else:
            # Signal: failed
            emitter.emit(Event.log_signal(
                "deploy.stage_failed",
                stage=stage,
                stack=stack,
                error=error,
                duration_ms=duration_ms
            ))
            failed_stage = stage
            error_message = error
            break

    total_duration = (time.perf_counter() - total_start) * 1000

    if failed_stage:
        return Result.error(
            f"{stack} deploy failed at {failed_stage}",
            data={
                "stack": stack,
                "failed_stage": failed_stage,
                "error": error_message,
                "stages_completed": stages_completed,
                "duration_ms": total_duration,
            }
        )

    return Result.ok(
        f"{stack} deployed successfully",
        data={
            "stack": stack,
            "stages_completed": stages_completed,
            "duration_ms": total_duration,
        }
    )
```

## Ephemeral vs Durable Signals

Not all signals need the same treatment:

| Type | Examples | Batch Emitter | Live Emitter |
|------|----------|---------------|--------------|
| **Ephemeral** | `*.started`, `*.connecting` | Ignore | Show spinner |
| **Durable** | `*.completed`, `*.failed` | Render | Update final state |

Ephemeral signals communicate transient state. Durable signals are facts worth persisting.

```python
class BatchEmitter:
    def emit(self, event: Event) -> None:
        # Only collect durable signals
        if event.topic.endswith(".completed") or event.topic.endswith(".failed"):
            self._stages.append(event.data)
        # Ignore ephemeral signals like *.started

class LiveEmitter:
    def emit(self, event: Event) -> None:
        # Show all signals
        if event.topic.endswith(".started"):
            self._show_spinner(event.data["stage"])
        elif event.topic.endswith(".completed"):
            self._show_checkmark(event.data["stage"], event.data["duration_ms"])
        elif event.topic.endswith(".failed"):
            self._show_error(event.data["stage"], event.data["error"])
```

## Artifacts for Summary

After all stages complete, emit an artifact summarizing the operation:

```python
emitter.emit(Event.artifact(
    "deploy_result",
    stack=stack,
    success=not failed_stage,
    stages_completed=stages_completed,
    failed_stage=failed_stage,
    duration_ms=total_duration
))
```

Artifacts are durable records suitable for:
- JSON output aggregation
- Audit logs
- Dashboard metrics

## Timing

Always include `duration_ms` in completed/failed signals:

```python
start = time.perf_counter()
# ... work ...
duration_ms = (time.perf_counter() - start) * 1000

emitter.emit(Event.log_signal("deploy.stage_completed",
    stage="rsync",
    duration_ms=duration_ms  # Always include
))
```

Renderers can:
- Display timing: `rsync (2.3s)`
- Aggregate for metrics
- Hide in quiet mode

## Testing

Use `ListEmitter` to verify signal sequence:

```python
from ev import ListEmitter

def test_deploy_emits_lifecycle_signals():
    emitter = ListEmitter()

    result = await deploy("media", emitter)

    # Verify sequence
    topics = [e.topic for e in emitter.events]
    assert "signal:deploy.stage_started" in topics
    assert "signal:deploy.stage_completed" in topics

    # Verify timing included
    completed = [e for e in emitter.events if e.topic == "signal:deploy.stage_completed"]
    for event in completed:
        assert "duration_ms" in event.data
```

## When to Use

Use the lifecycle pattern when:
- Operation has 3+ distinct stages
- Each stage can succeed or fail independently
- You want progress visibility during long operations
- Different output modes need different detail levels

Skip for simple operations where a single Result captures everything.
