# Patterns Mined from hlab CLI

Deep analysis of `~/Code/gruel.network/cli/hlab` - a production CLI using ev v0.6.0.

## Architecture Overview

```
Domain Operations (ssh.py, deploy.py)
    ↓ Emits Event stream
CommandContext (context.py)
    ↓ Wires emitter based on output mode
Emitters (plain.py, json.py, live.py)
    ↓ Routes events by topic → render functions
Render functions (render.py) + View builders (views.py)
    ↓ dict → str (plain) or Text/Tree (rich)
Terminal Output
```

Operations emit **signals** (structured observations), not strings. Emitters decide presentation.

---

## Pattern 1: Signal Naming Convention

**Domain.Subject format:**

```python
Event.log_signal("status.stack", stack="media", healthy=True)
Event.log_signal("deploy.stage_started", stage="rsync", stack="media")
Event.log_signal("deploy.stage_completed", stage="rsync", duration_ms=2340)
Event.log_signal("deploy.stage_failed", stage="compose_up", error="Port in use")
```

Produces topics like `signal:status.stack`, `signal:deploy.stage_started`.

**Why it works:**
- Hierarchical namespace prevents collision
- Enables prefix routing (`deploy.*` handlers)
- Self-documenting

---

## Pattern 2: Signal Schemas (TypedDict)

hlab uses TypedDict to document expected signal shapes:

```python
# signals.py
class StackStatusSignal(TypedDict, total=False):
    stack: str
    status: Literal["healthy", "unhealthy", "error"]
    healthy_count: int
    total_count: int
    duration_ms: float
    error: str  # only when status="error"
    unhealthy_services: list[str]

class DeployStageSignal(TypedDict, total=False):
    stack: str
    stage: str
    duration_ms: float
    error: str  # only for failed
```

**Why it works:**
- Documentation as code
- IDE autocomplete
- Not enforced at runtime (fast)
- Renderers know what data to expect

---

## Pattern 3: KNOWN_TOPICS Registry

Single source of truth for signal routing:

```python
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

Emitters check against this set:
- Known topic → custom handler
- Unknown topic → generic fallback (if verbosity allows)

**Why it works:**
- Extensibility without modifying emitters
- Catches typos (unknown signals get generic treatment)
- Central documentation of all signal types

---

## Pattern 4: Ephemeral vs Durable Signals

**Ephemeral signals** (state transitions, not final outcomes):
- `deploy.stage_started` - operation is starting
- `deploy.connecting` - attempting connection

Renderers may:
- Live: show spinner, update display immediately
- Batch: ignore (only render final outcome)

**Durable signals** (facts worth persisting):
- `deploy.stage_completed` - stage finished successfully
- `deploy.stage_failed` - stage failed with error
- `status.stack` - final health check result

Renderers should:
- Render in all output modes
- Include in JSON output
- Suitable for audit logs

**Artifacts** (summary records):
- `artifact:deploy_result` - final deployment outcome

---

## Pattern 5: Stage Progression Model

For multi-step operations, use ordered stages:

```python
STAGES = ["decrypt", "rsync", "compose_up", "health_check"]

for stage in STAGES:
    emitter.emit(Event.log_signal("deploy.stage_started", stage=stage))

    success, error = await execute_stage(stage)

    if success:
        emitter.emit(Event.log_signal("deploy.stage_completed",
                                       stage=stage, duration_ms=elapsed))
    else:
        emitter.emit(Event.log_signal("deploy.stage_failed",
                                       stage=stage, error=error, duration_ms=elapsed))
        break
```

**Why it works:**
- Clear semantic lifecycle
- Renderers can show progress (2/4 stages)
- Easy to add stages without changing renderer code

---

## Pattern 6: View Functions (Pure State→Renderable)

Separate state accumulation from rendering:

```python
# views.py - pure functions, no side effects
def build_deploy_tree(stages: dict, connecting: bool, theme: Theme) -> Tree:
    """Build Rich Tree from current deploy state."""
    tree = Tree("Deploy")
    for name, data in stages.items():
        if data.get("signal") == "deploy.stage_completed":
            tree.add(f"[green]✓[/] {name} ({data['duration_ms']}ms)")
        elif data.get("signal") == "deploy.stage_started":
            tree.add(f"[yellow]⏳[/] {name}...")
    return tree
```

Emitter calls view functions on state change:

```python
# live.py
def _update_display(self):
    tree = build_deploy_tree(self._stages, self._connecting, self._theme)
    self.live.update(tree)
```

**Why it works:**
- Testable without mocking terminal
- Same state renders consistently
- Clear separation of concerns

---

## Pattern 7: Timing Integration

Duration measured at operation level, included in signals:

```python
start = time.perf_counter()
# ... do work ...
duration_ms = (time.perf_counter() - start) * 1000

emitter.emit(Event.log_signal("deploy.stage_completed",
                               stage="rsync",
                               duration_ms=duration_ms))
```

And in Result:

```python
return Result.ok(
    "Deployed successfully",
    data={"duration_ms": total_duration}
)
```

**Why it works:**
- Fine-grained timing per stage
- Renderers can show/hide based on verbosity
- JSON output includes timing for tooling

---

## Pattern 8: Batch vs Live Emitter Lifecycles

**Batch (Plain/JSON):**
```python
def emit(self, event: Event) -> None:
    # Buffer event data
    self._stacks.append(event.data)

def finish(self, result: Result) -> None:
    # Render all buffered data at once
    for stack in self._stacks:
        print(render_stack_status(stack))
```

**Live (Rich):**
```python
def emit(self, event: Event) -> None:
    # Update state and redraw immediately
    self._results[event.data["stack"]] = event.data
    self._update_display()

def finish(self, result: Result) -> None:
    # Final update, stop live context
    self._show_summary(result)
    self.live.stop()
```

Both implement same `Emitter` protocol. Operations don't know which they're using.

---

## Pattern 9: Binary Result with Signal Nuance

Results are binary (ok/error), but signals provide nuance:

```python
# 2/3 stacks healthy - success with nuance
for stack in ["media", "infra", "dev"]:
    status = "healthy" if stack != "dev" else "unhealthy"
    emitter.emit(Event.log_signal("status.stack", stack=stack, status=status))

# Binary result - automation can act on this alone
return Result.ok("2/3 stacks healthy", data={"healthy": 2, "total": 3})
```

Renderers show:
- [OK] media: healthy
- [OK] infra: healthy
- [FAIL] dev: unhealthy
- Summary: 2/3 stacks healthy

**Why it works:**
- Automation reads Result alone (simple contract)
- Humans see full signal stream (rich context)
- Partial success expressible via signals + data

---

## Pattern 10: CommandContext as Seam

`CommandContext` bridges CLI flags → operation execution:

```python
@dataclass
class CommandContext:
    output_mode: OutputMode  # RICH, PLAIN, JSON
    verbosity: int
    config: Config

    def emitter(self, stacks: list[str]) -> Emitter:
        """Create appropriate emitter based on output mode."""
        match self.output_mode:
            case OutputMode.JSON:
                return JsonEmitter()
            case OutputMode.PLAIN:
                return PlainEmitter(self.verbosity)
            case OutputMode.RICH:
                return LiveEmitter(stacks, self.verbosity)
```

Operations receive emitter, don't know about output modes:

```python
async def check_stacks(stacks, emitter: Emitter) -> Result:
    # Just emit events - don't care about format
    ...
```

---

## Key Files in hlab

| File | Purpose |
|------|---------|
| `src/hlab/signals.py` | KNOWN_TOPICS, TypedDict schemas |
| `src/hlab/context.py` | CommandContext, emitter factory |
| `src/hlab/deploy.py` | Stage progression, signal emission |
| `src/hlab/ssh.py` | Status checks, progress events |
| `src/hlab/emitters/plain.py` | Batch ASCII emitter |
| `src/hlab/emitters/json.py` | Batch JSON emitter |
| `src/hlab/emitters/live.py` | Streaming Rich emitter |
| `src/hlab/emitters/render.py` | Format-specific rendering |
| `src/hlab/emitters/views.py` | Pure tree builders |

---

## Potential ev Enhancements

Patterns hlab implements that ev could formalize:

1. **Signal schema documentation** - convention or helper for TypedDict schemas
2. **Topic registry pattern** - standard way to declare known topics
3. **Ephemeral/durable distinction** - maybe a flag on signals?
4. **Stage progression helpers** - common pattern for multi-step operations
5. **Timing convenience** - auto-capture duration in Result.meta?

All of these are implementable in userland today. The question is whether formalizing any would benefit multiple users of ev.

---

## ev-toolkit: The Convenience Layer

`~/Code/ev-toolkit` provides composable utilities for common emitter patterns.

**Philosophy:** Like `itertools` for emitters. Self-contained, copy-paste friendly.

### Emitter Wrappers

| Wrapper | Purpose | Lines |
|---------|---------|-------|
| `QuietEmitter` | Filter to errors/warnings only | ~12 |
| `FilterEmitter` | Predicate-based event filtering | ~12 |
| `TimingEmitter` | Auto-add duration to result.meta | ~20 |
| `CountingEmitter` | Count matching events while delegating | ~15 |

All wrappers:
- Take inner emitter
- Implement emit()/finish()
- Compose naturally: `TimingEmitter(FilterEmitter(inner))`

### Convenience Functions

**`get_emitter(json=False, quiet=False)`** — Auto-select emitter by flags:
- Priority: quiet > json > rich (if tty) > plain
- Handles the common CLI pattern in one call

### Recipes (copy-paste patterns)

| Recipe | Purpose |
|--------|---------|
| `ProgressTracker` | Track/emit progress for known-length iterations |
| `VerbosityFilter` | Filter by -v verbosity level |
| `BatchCollector` | Base for collect-then-render emitters |
| `ContextEmitter` | Auto-finish on context exit |
| Signal helpers | `find_signals()`, `assert_has_signal()` for tests |

### Design Split

| ev core | ev-toolkit |
|---------|------------|
| Frozen contract | Evolving convenience |
| Emitter protocol | Wrapper decorators |
| JSON/Plain/Rich/Tee | Quiet/Filter/Timing/Counting |
| Essential only | Opinionated helpers |

This split keeps ev core stable while toolkit can evolve with new patterns.
