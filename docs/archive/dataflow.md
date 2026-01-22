# Reactive CLI Dataflow

## Current Architecture

```mermaid
flowchart TB
    subgraph Input["Input Layer"]
        Stream["Log Stream<br/>(mock or real)"]
    end

    subgraph State["State Layer (Signals)"]
        lines["lines: Signal[list[LogLine]]"]
        source_colors["source_colors: Signal[dict]"]
        status["status: Signal[str]"]
    end

    subgraph Derived["Derived Layer (Computed)"]
        visible["visible_lines<br/>lines()[-MAX:]"]
        line_count["line_count<br/>len(lines())"]
    end

    subgraph UI["UI Layer"]
        LogsUI["LogsUI.render()"]
        RichLive["Rich Live Display"]
    end

    subgraph Events["Event Layer"]
        subgraph Bridges["Reactive Bridges"]
            lifecycle["watch_lifecycle"]
            notable["watch_notable"]
            on_line["on_line callback"]
        end

        subgraph EmitterChain["Emitter Chain"]
            FilteredEmitter
            TeeEmitter
            ListEmitter["ListEmitter<br/>(inspection)"]
            FileEmitter["FileEmitter<br/>(recording)"]
        end
    end

    Stream -->|"parse + update"| lines
    Stream -->|"assign_color"| source_colors

    lines --> visible
    lines --> line_count

    visible --> LogsUI
    source_colors --> LogsUI
    line_count --> LogsUI
    LogsUI --> RichLive

    status --> lifecycle
    lines --> notable
    lines --> on_line

    lifecycle --> FilteredEmitter
    notable --> FilteredEmitter
    on_line --> FilteredEmitter

    FilteredEmitter --> TeeEmitter
    TeeEmitter --> ListEmitter
    TeeEmitter --> FileEmitter
```

## Unified Filtering (Current Implementation)

UI and filtered events both derive from the same filter:

```mermaid
flowchart TB
    subgraph State["State Layer"]
        lines["lines: Signal[list[LogLine]]"]
        filter_levels["filter_levels: Signal[set[str] | None]"]
    end

    subgraph Derived["Derived Layer"]
        filtered["filtered_lines<br/>Computed: apply filter to lines"]
        visible["visible_lines<br/>Computed: filtered[-MAX:]"]
        total["total_count"]
        vis_count["visible_count"]
    end

    subgraph UI["UI Layer"]
        LogsUI["LogsUI.render()<br/>Shows: visible_count/total_count"]
    end

    subgraph Events["Event Layer"]
        on_line["on_line callback<br/>(respects filter)"]
        unfiltered["Unfiltered emitter<br/>(ignores filter)"]
    end

    lines --> filtered
    filter_levels --> filtered
    filtered --> visible --> LogsUI
    lines --> total --> LogsUI
    filtered --> vis_count --> LogsUI

    lines --> on_line
    lines --> unfiltered
    filter_levels --> on_line
```

Key properties:
- `filtered_lines = Computed(lambda: [l for l in lines() if passes_filter(l)])`
- UI shows `visible_count/total_count` when filtered (e.g., "13/30 lines")
- Events respect filter by default, but `--record-unfiltered` bypasses it

## Output Mode Matrix

| Flag | UI Shows | Events Contain | Use Case |
|------|----------|----------------|----------|
| (none) | All lines | Lifecycle + notables | Interactive monitoring |
| `--record FILE` | All lines | All lines + lifecycle | Full audit trail |
| `--level X` | Only level X | Lifecycle + notables | Filtered monitoring |
| `--level X --record FILE` | Only level X | Only level X lines | Filtered audit |
| `--record-unfiltered FILE` | (any) | ALL lines (ignores filter) | Complete audit alongside filtered |
| `--no-ui` | Nothing | All lines | Headless/LLM consumption |
| `--no-ui --level X` | Nothing | Only level X | Filtered headless |

**Unified filtering**: `--level` now affects both UI and events consistently.

## Simultaneous Outputs

One command can produce multiple outputs:

```mermaid
flowchart TB
    subgraph Input
        stream["Log Stream"]
    end

    subgraph State
        lines["lines Signal"]
        filter["filter_levels Signal"]
    end

    subgraph Outputs["Simultaneous Outputs"]
        UI["Rich Live UI<br/>(filtered view)"]
        filtered_file["--record<br/>/tmp/errors.jsonl<br/>(filtered)"]
        all_file["--record-unfiltered<br/>/tmp/all.jsonl<br/>(complete)"]
        list["ListEmitter<br/>(inspection)"]
    end

    stream --> lines
    lines --> UI
    filter --> UI
    lines --> filtered_file
    filter --> filtered_file
    lines --> all_file
    lines --> list
```

Example command:
```bash
uv run logs_reactive.py \
    --level error,warn \
    --record /tmp/errors.jsonl \
    --record-unfiltered /tmp/all.jsonl
```

This produces:
- **UI**: Shows only errors/warnings (13/30 lines filtered)
- **/tmp/errors.jsonl**: Only error/warn events
- **/tmp/all.jsonl**: Complete record of all 30 lines

## Event Types

```mermaid
flowchart LR
    subgraph "Signal Events"
        started["logs.started"]
        completed["logs.completed"]
        errors["logs.recent_errors"]
    end

    subgraph "Log Events"
        log["kind: log<br/>Each log line"]
    end

    subgraph "Result"
        result["Final Result<br/>ok/error + data"]
    end

    started --> log
    log --> errors
    log --> completed
    completed --> result
```

All events flow through the same emitter chain. Filtering can be applied at any point.

---

## Alternative: Events-Primary Architecture

Instead of Signals as the source of truth with events as a parallel output,
events become the primary output and all state is derived from them.

```mermaid
flowchart TB
    subgraph Input
        source["Log Source<br/>(SSH, subprocess, etc)"]
    end

    subgraph EventBus["Event Bus (the spine)"]
        events["Event Stream<br/>StreamStarted → LogLine* → StreamEnded"]
    end

    subgraph Subscribers["Subscribers (derive their own state)"]
        ui["UISubscriber<br/>- lines deque<br/>- source_colors<br/>- counts"]
        file["FileSubscriber<br/>- writes JSONL"]
        filtered["FilteredFileSubscriber<br/>- errors only"]
        alerts["AlertSubscriber<br/>- error threshold"]
        stats["StatsSubscriber<br/>- aggregates"]
    end

    source -->|"emit()"| events
    events --> ui
    events --> file
    events --> filtered
    events --> alerts
    events --> stats
```

### Event Types

| Event | Purpose | Data |
|-------|---------|------|
| `StreamStarted` | Lifecycle | source, max_lines |
| `LogLine` | Each line | index, source, message, level, raw |
| `SourceDiscovered` | New source seen | source, color |
| `ErrorDetected` | Alerting | index, source, message |
| `StreamEnded` | Lifecycle | reason, total_lines, duration_s |

### Subscriber Pattern

Each subscriber maintains its own derived state:

```python
class UISubscriber:
    def __init__(self):
        self._lines = deque(maxlen=20)  # Bounded view
        self._source_colors = {}
        self._total_lines = 0

    def on_event(self, event):
        match event:
            case LogLine() as line:
                self._lines.append(line)  # O(1) append
                self._total_lines += 1
            case SourceDiscovered(source=s, color=c):
                self._source_colors[s] = c

    def render(self):
        # Render from derived state
        ...
```

### Why Events-Primary is Faster

| Operation | Signals (immutable) | Events-Primary |
|-----------|---------------------|----------------|
| Add line | `[*lines, new]` O(n) copy | `deque.append()` O(1) |
| 10k lines | ~50M items copied | 10k appends |
| Overhead | ~11μs/line at 10k | ~0.8μs/line |

The Signal pattern's immutable updates create O(n²) total work for append-heavy workloads.

### Benefits

1. **Single source of truth**: Events are the history
2. **Replay**: Record events → replay exact UI state
3. **Decoupled subscribers**: Add/remove without changing core
4. **Natural filtering**: Each subscriber chooses what to process
5. **Testable**: Assert on events, mock subscribers

### Trade-offs

1. **Event design matters**: Must capture all state-relevant changes
2. **No automatic reactivity**: Manual `match event` dispatch
3. **Memory**: Event history grows (can bound with maxlen)

### When to Use

- **Events-Primary**: Append-heavy, needs replay, multiple independent views
- **Signals**: Small state, complex derivations, automatic dependency tracking
