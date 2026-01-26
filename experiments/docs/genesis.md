# Genesis: The Arc of a Personal Event Bus

## The Inciting Problem

It started with a frozen movie. A daughter tried to watch *The Wild Robot* and it stopped fifteen minutes in. A familiar kind of homelab annoyance — the kind that in a previous life would have been: notice, investigate, fix, forget. The corrupt file was 1.5GB instead of the expected 30GB for a Remux-1080p. Truncated download, metadata lying about runtime.

But this time the fix didn't stop at the fix. The conversation went further: "Come up with a script/cmd/pattern for quickly removing a 'dud' movie like this and requeueing a request to quickly replace it" and "Determine how we can scan for other video mismatches like this." What followed was `media-audit.py` with `--deep` flag for FFmpeg decode testing, `media-fix.py` with `--auto` mode, integration with Radarr quality definitions via Recyclarr, and eventually a full KDL spec-to-scaffold pipeline in `gruel_gen.py`.

This is the pattern that would repeat across every project in this ecosystem: a concrete problem surfaces, it gets solved, and then — because the marginal cost of generalization collapsed — it gets generalized into a tool, a pattern, a primitive. The gap between "works for me" and "works for everyone" narrowed to the length of a conversation.

## Thread 1: The ev Vocabulary

The first thread began in `ev` — a CLI event contract library. The core insight, articulated early: **"Events are facts, not instructions."** An event describes what occurred, not how to display it. Five frozen kinds emerged: `log` (narrative for humans), `progress` (work advancement), `artifact` (durable outputs), `metric` (quantitative facts), and `input` (decisions that occurred). Later, a sixth — `signal` — would be carved out of `log` to distinguish structured transient observations from narrative:

> "something happened" is what log is for, but log is doing too much and too little... the real gap is distinguishing structured transient observations from narrative logs.

The design principle held: Event kinds describe *what something is*, not what any consumer should do with it. A `metric` event doesn't instruct a progress bar to update — it reports that a measurement exists. The consumer decides presentation.

This led to the Emitter Protocol (`emit(Event)`, `finish(Result)`), with reference implementations: `JsonEmitter` for structured output, `PlainEmitter` for text, `RichEmitter` for styled terminal. The stdout/stderr policy emerged naturally: events flow to stderr (transient observations), Result flows to stdout (the authoritative verdict). Events are the stream; Result is the answer.

`ev-toolkit` followed as the script harness — `run()`, signal helpers, `detect_mode()`. This was the scaffolding that turned any CLI operation into a structured event stream with `--json`, `--plain`, `--quiet`, `--verbose`, and `--record PATH` for free. The JSONL output was the real payoff:

```json
{"kind": "log", "data": {"signal": "audit.started", "total_movies": 665}, "ts": 1768976475.83}
{"kind": "log", "data": {"signal": "audit.movie", "title": "21 Grams", "status": "ok"}, "ts": 1768976475.83}
```

Every signal captured with timestamps. Replay, audit, integration hooks — for free.

## Thread 2: The Streaming Resource Rewrite

In `hlab-streaming`, the architecture underwent a fundamental inversion. The original pattern was: operations gather all container data, compute health counts, emit a single aggregate `status.stack` signal. Emitters passively render what they receive.

The problem manifested as bridge code — a `_CapturingEmitter` that wrapped emitters to intercept and transform signals. A translation layer indicating the contract wasn't right. Operations knew too much about presentation; emitters were too passive.

The new architecture: operations emit one `container.state` event per container as they're discovered. `ResourceTracker` mixin tracks resources, errors, and insertion order. Emitters aggregate in `finish()` or when building trees. No bridge code.

**The seam moved.** Aggregation responsibility shifted from operations to emitters. Operations have a simpler job — emit what you observe. Emitters decide how to present it. This was the first concrete encounter with what would become the Stream topology: sources emit facts, consumers derive views.

## Thread 3: reaktiv and the Dashboard Experiments

The reactive thread emerged when reaktiv — a Python Signals library inspired by Angular/SolidJS — appeared. The recognition was immediate: "I'm basically trying to cram JS FE concepts into a CLI/TUI pattern here." The instinct was right — FRP stripped to minimum (Signal, Computed, Effect) mapped cleanly onto the interactive terminal problem.

The first dashboard proved the concept. EventStore as an append-only fact log with a `version: Signal` that bridges mutable-list performance with reactive dependency tracking. UI state (focus, mode, filter, input buffer) as Signals. One Effect triggers render when any dependency changes. No manual refresh calls.

> "Out of all of these examples this is by far the cleanest I think we've seen yet. This seems to be pretty powerful."

What followed was systematic stress-testing. Four examples, progressively harder:

- **Dashboard**: Independent events. Does reactive + Rich work at all?
- **HTTP Logger**: Correlated events. Can Computed handle derived state (latency from request/response pairs)?
- **HTTP Logger v2**: Same domain, more features. Do new features compose without refactoring?
- **Process Manager**: State machines + user actions. Does the pattern hold when the user *causes* events, not just observes?

Each answered its question cleanly. The pattern held. The extraction revealed the reusable surface was 214 lines of framework. A pane type taxonomy stabilized: List (event added), Aggregate (event added), Live State (every render tick), Detail (selection changes).

But then came the pivot.

## The Events-Primary Pivot

The observation that triggered the shift: "It seems... off that our UI is handled off to the side, separate from the event system." In the reaktiv model, UI and events were parallel side effects of the same Signal state — siblings, not parent-child. You couldn't replay the UI. Recording was a parallel concern, not an intrinsic one.

The events-primary architecture inverted this:

```
Input → EventBus → Subscribers
              ├─→ UISubscriber (renders)
              ├─→ FileSubscriber (records all)
              ├─→ FilteredFileSubscriber (errors only)
              └─→ StatsSubscriber (aggregates)
```

The EventBus became the spine. Everything flows through it. Subscribers derive their own state. The replay story became trivial — feed the JSONL back to a UISubscriber and you get the exact same renders.

The performance comparison was decisive: Signals caused O(n²) for appends (Computed re-scans full event list). Events-primary was O(n). This sealed the direction.

## The Render Layer Discovery

The render layer emerged as its own thing — not planned, but discovered through pressure. Rich was great for output but weak for interactivity (Live is a polling hack). Textual was a full widget framework (CSS, DOM, messages) — too heavy. The gap between them was unfilled in Python.

The answer was a buffer-diff engine: Cell grid, diff, ANSI output. Only changed cells get written to terminal. This was the architectural piece Rich was missing. The Python equivalent of Ratatui.

Three-level composition vocabulary emerged:
- **Span**: styled text run (atom)
- **Line**: sequence of Spans (workhorse, ~90% of cases)
- **Block**: 2D cell grid (escape hatch for borders, padding, joins)

Components became frozen value objects: state + transitions + render function. State flows down, styled output flows up. No mutation, no side effects. The paint boundary (Line.paint / Block.paint → BufferView) is where Cells get created — exactly once, in their final location.

Performance validated the approach: 7.3ms average frame at 2800+ items via the Line path.

## The Stream Topology

The final architectural piece came from a deeper realization: **EventStore is just one consumer, not the center. The Stream is the center.**

```python
stream: Stream[HealthCheck] = Stream()
stream.tap(store)          # persist
stream.tap(projection)     # fold → state
stream.tap(FileWriter(...))  # record
stream.tap(webhook, filter=lambda e: "unhealthy" in e.stacks.values())
```

The topology primitives crystallized: `Stream[T]` (typed async broadcast), `Consumer[T]` (protocol — anything that eats events), `Tap[T]` (handle for detach), plus battery consumers: `Projection[S,T]` (incremental fold), `EventStore[T]` (append-only log), `FileWriter[T]` (JSONL), `Forward[T,U]` (bridge between typed streams).

Design constraints were deliberate negations: no operator chains (not Rx), no backpressure (async/await naturally bounds), no main loop ownership, sources are NOT a type (just async functions that call `stream.emit()`), no external reactivity library — version counters, not Signals. The push topology handles invalidation.

This was the moment reaktiv was stripped from the architecture entirely. Version counters replaced Signals. Poll-based change detection, zero dependencies. The reactive model served its purpose — it proved the pattern — but the streaming topology subsumed its role.

## The gruel.network Scaffold System

Meanwhile, in `gruel.network`, a different pattern was compounding. The KDL spec-to-script generator (`gruel_gen.py`) emerged from the observation that every homelab script had the same shape: parse args, emit events during execution, produce a Result. The KDL spec captures the script's interface:

```kdl
arg "title" required=true
flag "deep" type="bool" default=false
signal "audit.started" { total_movies "int" }
signal "audit.movie" { title "str"; status "str" }
result { status "str"; issues "int" }
```

Generate the scaffold, drop in the operation logic. What you get for free: `--json`, `--plain`, `--quiet`, `--verbose`, `--record PATH`. The ev-toolkit harness handles the ceremony.

This connected back to the experiments project through `hlab scaffold service`, `hlab scaffold vm` (with YAML-based VM config replacing fragile HCL regex manipulation), `hlab scaffold adr`, `hlab scaffold changelog`, and the decommission commands. Each scaffold was an instance of the same pattern: structured intent in, working infrastructure out.

## The Cognitive/Deterministic Split

The retrospective crystallized a broader framing: two orthogonal context capture systems.

**Cognitive context** (tbd) captures reasoning, decisions, discoveries, collaborative problem-solving from agent conversations. The "90mb knowledge.txt" of forum pastes and history dumps, now structured and queryable. Conversations as knowledge artifacts — the investigation process *is* the documentation.

**Deterministic context** (this project) captures observable state changes, errors, data flows. The reactive TUI pattern isn't "a dashboard" — it's a context scoping and capture primitive:

- EventStore: the raw stream (everything happening)
- Filter: context scoping (narrow to what's relevant now)
- Tee: context capture (persist the scoped chunk)
- Computed/Projection: derived views (make scoped context legible)
- Replay: append-only log enables re-deriving any past state

The join between them is temporal: timestamps in both event logs as the correlation key. "What was the system doing when the agent decided to restart that service?" A query over both systems.

The concern noted honestly: this boundary might be premature. Agent actions *are* system events. The causal chain crosses constantly. Temporal proximity isn't causality. But "good enough join on timestamps" might be the pragmatic answer that works until the richer model emerges from actual data.

## The "Works for Everyone" Collapse

The deeper pattern threading through everything: agents collapse the cost of the generalization step. Previously: fix → done (because going further is A Project). Now: fix → "what's the general form?" → script → schedule.

> "The agentic capture is a specific frame, it captures this conversation along with the work that was done. The work that was done is free form. The capturing allows the collapse into something deterministic, which saves cognition (tokens/tools for you, formalization of concept for me) and time (less tool turns for you, less waiting for me) and reduces the loop."

A corrupt video file used to be: notice → investigate → fix → forget. Now it's: notice → agent investigates → fix → "audit all files for the same issue" → cron job. The marginal cost of the second step dropped from "an evening of scaffolding" to "10 minutes of conversation."

This changes what's worth building. Not dashboards per-system, but patterns and primitives that allow "works for me" to collapse into "works for everyone" via the agentic assistant. Other developers care about the events, not the event system.

## The Bootstrap/Bubbletea Frame

> "This thing isn't going to stay a 214 line pattern. We're going to keep pushing it, both as a lens and an active tool, looking for what the context observability/filtering primitive is here. Bubbletea did for Go TUIs what Bootstrap did for front-ends."

Bootstrap collapsed "design a decent page" into "apply these classes." Bubbletea collapsed "build an interactive Go TUI" into "implement Model/Update/View." This project collapses "build a reactive terminal observer/actor for any event stream" into "define your event type, your filter logic, and your panes."

The lens/tool distinction dissolved: a kill button on a process and a remove button on a queue subscription are the same gesture — "act on a selected entity in the observed stream." No category boundary from the user's side.

## The Provenance Layer

Obsidian captures the third kind of context: provenance. Web clippings with auto-generated tags via a taxonomy-aware pipeline. Research triggers from `~/.config/zsh/scripts`. The tagging skill that classifies incoming clippings against existing vault patterns.

The connection: ev feeds into gruel.network (scripts emit structured events), experiments captures the deterministic side (stream topology renders and records), tbd captures the cognitive side (conversations as queryable knowledge), and Obsidian captures external provenance (what was read, when, what it connected to).

## The Current Synthesis

Two independent layers exist:

**`render/`** — Cell-buffer terminal rendering engine. Diff-capable, composition-oriented, interactive components. Zero external dependencies beyond wcwidth.

**`framework/`** — Typed event multiplexer. Stream → Consumer topology with fan-in/fan-out. Projections as incremental folds. Version counters for change detection.

They're fully decoupled. render has zero framework imports. framework has zero render imports. Apps compose both: sources emit into Streams, Projections derive state, RenderApp paints the current view.

The conceptual model across the ecosystem:
- **ev** defines what things *are* (Event, Result, Emitter)
- **framework** routes where things *go* (Stream, Consumer, Tap)
- **render** determines how things *look* (Buffer, Line, Block)
- **ev-toolkit** is the script harness for fire-once CLI operations
- **tbd** is the cognitive context capture layer
- **Obsidian** is the provenance capture layer

## What's Missing

The primitives are mature. The pattern is validated. The community doesn't exist.

The scale cliff is visible but unvisited — full recomputation works at current scale, known solutions (incremental computation, differential dataflow) exist for later. The real-data bridge is partially built — `apps/logs.py` streams SSH log output through the topology — but more real-world forcing functions are needed.

The adoption path runs through AI, not documentation. The framework is too small to package, too specific for a blog post. But an agent that understands the pattern can instantiate it for any domain. The question isn't "how do we teach people the pattern" — it's "how do we teach agents to apply it."

The event log is undervalued as a UI primitive. The industry treats it as backend infrastructure (Kafka, CloudWatch) or developer tooling (structured logging). Using the append-only log as the *UI state model* — current state always a derived view, never a primary store — is well-understood theoretically but almost never applied at the UI layer. This project proved it works. The implications extend beyond terminals: any UI that shows "what's happening" and "what happened" benefits from this model.

## The Shape of the Void

The closest analog: where Elm was circa 2013. A pattern that works, demonstrated in increasingly real applications, with an obvious path to broader use but without the gravity to attract community. The 214-line framework became a topology of streaming primitives. The dashboard became a render layer. The script harness became a typed event vocabulary. The conversations became a queryable knowledge base.

Whether this converges into a named thing — a framework, a toolkit, a category — or remains personal infrastructure that others discover through its outputs is an open question. But the pattern is clear: typed facts → append-only log → derived views. Stream → Consumer → Projection → Render. What happened → what it means → what to show.

The personal event bus isn't one project. It's the connective tissue between all of them.
