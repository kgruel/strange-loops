# Collapsed Architecture: Embedded Orchestration

The dashboard IS the orchestrator. Live connection is default, recording is opt-in.

## Current State (Two Paths)

```
Path 1: Dashboard (live)
  SSHConnectionManager ──callback──▶ app._on_ssh_event() ──▶ projection.consume()
  (hardcoded collectors)

Path 2: Orchestrator CLI
  DataSourceSpec ──▶ get_collector() ──▶ Stream ──▶ FileWriter
  (spec-driven)
```

Problems:
- SSHConnectionManager doesn't use specs
- Orchestrator writes files, dashboard tails them (or uses its own SSH)
- Two implementations of the same thing

## Target State (Collapsed)

```
Dashboard (live)
  DataSourceSpec ──▶ Source ──▶ Stream ──┬──▶ Projection ──▶ Render
                                         │
                                         └──▶ FileWriter (opt-in)

Dashboard (replay)
  TailerSource ──▶ Stream ──▶ Projection ──▶ Render
```

One path. Spec-driven. Persistence is a tap.

## Core Abstractions

### Source Protocol

```python
# In ticks (stdlib only, no IO)
from typing import Protocol, TypeVar, AsyncIterator

T = TypeVar("T")

class Source(Protocol[T]):
    """Async iterator that produces events."""

    def __aiter__(self) -> AsyncIterator[T]: ...
    async def __anext__(self) -> T: ...

    async def close(self) -> None:
        """Clean shutdown."""
        ...
```

Sources are async iterators. That's it. ticks defines the shape, doesn't implement IO.

### Source Implementations (framework)

```python
# framework/sources/ssh.py
class SSHSource:
    """Source that runs a collector over SSH."""

    def __init__(
        self,
        session: SSHSession,
        collector: Callable[[SSHSession], AsyncIterator[dict]],
        event_type: str,
    ):
        self._session = session
        self._collector = collector
        self._event_type = event_type

    async def __anext__(self) -> dict:
        event = await self._collector(self._session).__anext__()
        event["type"] = self._event_type
        return event


# framework/sources/tailer.py
class TailerSource:
    """Source that reads from JSONL file."""

    def __init__(self, tailer: Tailer, event_type: str):
        self._tailer = tailer
        self._event_type = event_type

    async def __anext__(self) -> dict:
        events = self._tailer.poll()
        if not events:
            await asyncio.sleep(0.1)  # backoff
            raise StopAsyncIteration  # or continue polling
        event = events[0]
        event["type"] = self._event_type
        return event
```

### SourceRunner

```python
# framework/runner.py
async def run_source(source: Source[T], stream: Stream[T]) -> None:
    """Run a source, emitting events to stream until exhausted or cancelled."""
    try:
        async for event in source:
            await stream.emit(event)
    except asyncio.CancelledError:
        pass
    finally:
        await source.close()
```

### Wiring It Together

```python
# framework/orchestrate.py
@dataclass
class SourceBinding:
    """A source bound to its stream and projection."""
    source: Source[dict]
    stream: Stream[dict]
    projection: SpecProjection
    writer: FileWriter | None = None  # opt-in recording


def bind_data_source(
    spec: DataSourceSpec,
    projection_specs: dict[str, ProjectionSpec],
    session: SSHSession,
) -> SourceBinding:
    """Create source, stream, projection from spec."""

    # Get collector from registry
    mode, collector_fn = get_collector(spec.collector)

    # Create source
    if mode == "collect":
        source = PollSource(session, collector_fn, spec.event_type, spec.interval)
    else:
        source = StreamSource(session, collector_fn, spec.event_type)

    # Create stream and projection
    stream = Stream[dict]()
    proj_spec = projection_specs[spec.projection]
    projection = SpecProjection(proj_spec)

    # Wire up
    stream.tap(projection)

    return SourceBinding(source=source, stream=stream, projection=projection)


def enable_recording(binding: SourceBinding, path: Path) -> None:
    """Attach FileWriter tap for persistence."""
    writer = FileWriter(path, serialize=lambda e: e)
    binding.stream.tap(writer)
    binding.writer = writer


def disable_recording(binding: SourceBinding) -> None:
    """Detach FileWriter tap."""
    if binding.writer:
        binding.stream.detach(binding.writer)
        binding.writer.close()
        binding.writer = None
```

## Dashboard Integration

```python
# apps/homelab.py (collapsed)

class HomelabApp(Surface):
    def __init__(self, app_spec: AppSpec, source_dir: Path | None = None):
        super().__init__()
        self.app_spec = app_spec
        self._source_dir = source_dir
        self._bindings: dict[str, list[SourceBinding]] = {}  # vm_name -> bindings
        self._tasks: dict[str, list[asyncio.Task]] = {}

    async def _connect(self, vm: VMInfo) -> None:
        """Connect to VM: create bindings, start sources."""

        if self._source_dir:
            # Replay mode: tailer sources
            bindings = self._create_tailer_bindings(vm)
        else:
            # Live mode: SSH sources
            session = await SSHSession(vm.host, vm.user, vm.key_file).__aenter__()
            bindings = self._create_ssh_bindings(vm, session)

        self._bindings[vm.name] = bindings

        # Start source runners
        tasks = [
            asyncio.create_task(run_source(b.source, b.stream))
            for b in bindings
        ]
        self._tasks[vm.name] = tasks

    def _create_ssh_bindings(self, vm: VMInfo, session: SSHSession) -> list[SourceBinding]:
        """Create bindings for live SSH mode."""
        proj_specs = {p.name: p for p in self.app_spec.projections}
        return [
            bind_data_source(ds, proj_specs, session)
            for ds in self.app_spec.data_sources
        ]

    def _create_tailer_bindings(self, vm: VMInfo) -> list[SourceBinding]:
        """Create bindings for replay mode."""
        bindings = []
        for ds in self.app_spec.data_sources:
            path = self._source_dir / vm.name / f"{ds.projection}.jsonl"
            tailer = Tailer(path, deserialize=lambda d: d)
            source = TailerSource(tailer, ds.event_type)

            stream = Stream[dict]()
            proj_spec = next(p for p in self.app_spec.projections if p.name == ds.projection)
            projection = SpecProjection(proj_spec)
            stream.tap(projection)

            bindings.append(SourceBinding(source, stream, projection))
        return bindings

    # Recording controls (future)
    def start_recording(self, vm_name: str) -> None:
        """Enable recording for a VM's bindings."""
        for binding in self._bindings.get(vm_name, []):
            path = Path(f"/tmp/recordings/{vm_name}/{binding.projection.spec.name}.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            enable_recording(binding, path)

    def stop_recording(self, vm_name: str) -> None:
        """Disable recording for a VM's bindings."""
        for binding in self._bindings.get(vm_name, []):
            disable_recording(binding)
```

## What Changes

| Component | Before | After |
|-----------|--------|-------|
| `SSHConnectionManager` | Hardcoded collectors, callbacks | Deleted |
| `Orchestrator` | Standalone CLI | Pattern embedded in app |
| Dashboard live mode | Uses SSHConnectionManager | Uses spec-driven sources |
| Dashboard replay mode | Uses Tailer directly | Uses TailerSource |
| Recording | Not supported | Tap attach/detach from UI |

## Migration Path

1. **Add Source protocol to ticks** — just the type shape
2. **Add SSHSource, TailerSource to framework** — implements Source
3. **Add SourceBinding, bind_data_source to framework** — wiring helpers
4. **Update homelab.py** — use bindings instead of SSHConnectionManager
5. **Delete SSHConnectionManager** — no longer needed
6. **Add recording UI** — key binding to toggle FileWriter tap

## What Stays the Same

- `ticks` primitives (Stream, Projection, FileWriter, Tailer)
- `cells` rendering
- KDL spec parsing
- Collector registry and implementations
- SpecProjection fold logic

The change is wiring, not primitives.
