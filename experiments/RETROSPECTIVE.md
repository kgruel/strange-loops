# Retrospective: Event-Sourced Reactive TUI Pattern

## What was built

Four examples over one reactive primitive set (Signal, Computed, Effect), progressively testing harder questions:

| Example | Domain | Key question answered |
|---------|--------|----------------------|
| dashboard | Independent events | Does reactive + Rich work at all? |
| http_logger | Correlated events | Can Computed handle derived state (latency from two events)? |
| http_logger_v2 | Same, more panes | Do new features compose without refactoring? |
| process_manager | State machines + user actions | Does the pattern hold when the user *causes* events, not just observes? |

## What was proven

**The core pattern works.** Append-only EventStore → Computed derivations → single Effect render. Three domains, zero framework changes for the third.

**Actions are just events.** The HANDOFF posed this as an open question: "How do user-triggered mutations interact with the reactive layer?" The answer turned out to be trivially simple — actions add events to the same store, Computed recomputes, Effect re-renders. No special action system needed.

**Per-entity state falls out naturally.** One shared EventStore with a `pid` field. Computed scans and groups. No per-entity Signals needed. The event-sourcing model gives you entity state machines for free.

**Composability via addition.** http_logger_v2 added histogram, breakdown, sliding window — all as new Computed values and pane renderers. No existing code modified. process_manager added CONFIRM mode, tick signal for live durations — same shape, just more Signals.

## What the extraction revealed

The `cli_framework/` is 214 lines. That's the reusable *code*. But the actual value is the *pattern knowledge*:

- EventStore is trivial (append + version bump)
- BaseApp is mostly wiring (Effect body reads Signals, calls render)
- The real work lives in domain-specific Computed functions and filter logic

This confirms the HANDOFF's verdict: "shared module, not framework." The pattern is the product, not the library.

## Pane type taxonomy (stabilized)

Four types emerged and held across all examples:

| Type | Updates when | Examples |
|------|-------------|----------|
| List | Event added | Requests, process list |
| Aggregate | Event added | Metrics, status counts |
| Live State | Every render tick | Pending age, uptime |
| Detail | Selection changes | Request detail, process detail |

## Design Tensions (deferred — UX/interaction, not architectural)

1. **Confirmation mode vs. inline.** CONFIRM as a separate Mode works but feels heavy for a single y/n. Inline prompt in status bar might feel more natural.

2. **Selection after action.** When you stop a process, should selection stay (showing "stopped") or move? Current: keeps selection. Might surprise users expecting "done = dismiss."

3. **Filter vs. live state.** Filtering by `state=running` is a snapshot. Process could crash between filter and view. Reactive update handles it correctly (process disappears from filtered list) but could be jarring.

## What wasn't tested

- **Persistence.** Events live in memory only. Event sourcing implies replay from disk — not explored.
- **Real data sources.** All simulators. Pattern should work with actual subprocess management or HTTP proxying, untested.
- **Scale.** Computed re-scans full event list on every change. Fine for hundreds/low thousands. Would need incremental computation for high-throughput.
- **Multi-user / networked.** Single-process, single-terminal only.

---

## Intellectual Genealogy

### Thread 1: Reactivity

VisiCalc (1979) is the ur-reactive system. Cells depend on cells; change propagates automatically. The user never manually recalculates.

Conal Elliott and Paul Hudak formalized this as **Functional Reactive Programming** (1997, "Functional Reactive Animation"). Key abstraction: *behaviors* (continuous time-varying values) and *events* (discrete occurrences). Pure functions transform them.

FRP remained academic until the web needed it. Erik Meijer's Reactive Extensions (2009-2012) brought observable streams to C#/Java/JS. RxJS became the industrial form — powerful but hard to reason about.

Then **Signals** (2022-2024): SolidJS, Preact Signals, Angular Signals, Vue's reactivity, TC39 proposal. FRP stripped to minimum: mutable cell (Signal), derived cell (Computed), side-effect trigger (Effect). No streams, no operators, no backpressure. Just dependency tracking and synchronous propagation. A return to the spreadsheet.

### Thread 2: Unidirectional data flow

Mid-2010s web drowning in two-way binding (Angular 1.x, Backbone). State everywhere; mutations trigger cascading updates unpredictably.

**Flux** (Facebook, 2014): Actions → Dispatcher → Store → View. One direction.

**Redux** (Dan Abramov, 2015): single store, pure reducer functions, dispatched actions. Conceptually event-sourced — actions are events, reducer derives state. But Redux abandoned the log: replaces state rather than accumulating events.

**Elm** (Evan Czaplicki, 2012): Model → update → View → Msg → Model. Entire app is a pure function from message history to UI.

Shared insight: **state derivation should be a pure function of inputs, not a side-effect of mutations.**

### Thread 3: Event sourcing

Greg Young and DDD community (2005-2010) formalized what accounting knew forever: the ledger (append-only log of facts) is the source of truth. Balances are derived views.

**CQRS** splits write model (accept commands, emit events) from read models (project events into queryable views). Read models are disposable — rebuild from the log.

Jay Kreps' "The Log" (2013, Kafka origin essay): the append-only log is the fundamental data structure for distributed systems. Everything else — databases, caches, indexes — is a materialized view.

Pat Helland's "Immutability Changes Everything" (2015): immutable facts compose; mutable state doesn't.

Pattern: **truth is accumulated facts; current state is a pure function over them.**

### Thread 4: Rendering paradigms

**Retained mode** (DOM, Qt, GTK): persistent object tree. Framework diffs and patches.

**Immediate mode** (Dear ImGui, 2014): every frame, emit full UI description. No persistent tree. Read state → produce output.

Rich's `Live.update(renderable)` is immediate mode for terminals. Each render produces a complete frame. No widget identity, no reconciliation.

### Thread 5: TUI renaissance (2020-present)

- **Rich** (Will McGuigan, 2020): declarative terminal rendering as composable renderables
- **Textual** (McGuigan, 2021): widget framework, message-passing, CSS-like styling
- **Bubbletea** (Charm, 2020): Elm architecture for Go terminals
- **Ratatui** (Rust, 2023): immediate-mode terminal rendering

Textual and Bubbletea chose **retained-mode thinking** — widgets with identity, message passing, component lifecycle. Imported the web's component model.

Ratatui chose immediate mode without a reactive state layer.

---

## The Convergence

| Thread | Our form |
|--------|----------|
| Reactivity | Version counters — poll-based, zero dependencies |
| Unidirectional flow | Stream → Projection → render loop |
| Event sourcing | Append-only EventStore, derived state via Projection |
| Rendering | Retained mode (Buffer diff, incremental updates) |
| Terminal UI | Custom render layer (cells, blocks, styled spans) |

What makes this distinctive: **the event log is both the persistence model AND the reactivity source.** The `version` Signal on EventStore bridges the two worlds. Event sourcing gives "what happened"; Signals give "when to recompute"; Computed gives pure derivation; Effect gives side-effect boundary.

---

## The Void

**1. Signals exist for browsers. Not terminals.** The Signals renaissance targets DOM rendering. We're using signals for dependency tracking + recomputation — a reason that doesn't care about rendering target.

**2. Event sourcing exists for backends. Not UIs.** CQRS/ES is a server pattern. Using append-only log as the *UI state model* is unusual. Redux gestured here but didn't commit. Our pattern commits: EventStore *is* the state. Computed functions *are* the read models.

**3. TUI frameworks chose components.** Textual has widgets/CSS/messages. Bubbletea has Models/Update. Ratatui has immediate-mode without reactivity. None combine event sourcing + signals + immediate-mode.

**4. No name for this combination.** "Event-sourced reactive TUI" is descriptive but not a meme. Not a framework anyone ships. Not a pattern anyone's written up. Ingredients well-known; recipe not established.

**5. The framework is almost nothing.** 214 lines. The value is pattern knowledge — how to structure an app so events, derivation, and rendering compose. Distribution problem: too small for a library, too specific for a blog post.

**6. The scale cliff is visible but unvisited.** Full recomputation works at our scale. Beyond that: incremental computation (differential dataflow, Materialize). Known solutions, not yet brought to TUI context.

**7. The real-data bridge is unbuilt.** Pattern *should* work for actual subprocess management, HTTP proxying, log tailing. Architecture supports it; proof doesn't exist yet.

### The shape of the void

- The **primitives** are mature (signals, event sourcing, Rich)
- The **pattern** is validated (three examples, framework extraction)
- The **community** doesn't exist (no name, no ecosystem, no adoption)
- The **ambition gap** is clear (simulated data → real tools)
- The **scale story** is hand-wavy (works for now, known solutions exist for later)

Closest analog: where Elm was circa 2013 — a pattern that works, demonstrated in toys, obvious path to real applications, without gravity to attract community. Our answer might be "a set of examples that real tools copy" — how React's ideas spread beyond React. Or: a design pattern that lives in your head, applied when building terminal tools. The 214-line framework is the reference; the pattern is the product.

---

## The Larger Architecture: Context Systems

### The workflow shift agents unlock

Agents don't just speed up the "fix" step. They collapse the cost of the *generalization step*. Previously: fix → done (because going further is A Project). Now: fix → "what's the general form of what you just did?" → script → schedule. The marginal cost of the second step dropped from "an evening of scaffolding" to "10 minutes of conversation."

This changes what's worth building. A corrupt video file used to be: notice → investigate → fix → forget. Now it's: notice → agent investigates → fix → "audit all files for the same issue" → cron job. The "works for me → works for everyone" collapse becomes viable when the agent handles the scaffolding cost.

### Two context systems

The broader system this project sits within has two orthogonal context capture mechanisms:

| System | Source | Captures | Answers |
|--------|--------|----------|---------|
| **Cognitive** | Agent conversations (across harnesses, providers, models) | Reasoning, decisions, discoveries, collaborative problem-solving | How, why, who |
| **Deterministic** | System events, logs, streams, file states | Observable state changes, errors, data flows | What, where |

**Cognitive context capture** is the sqlite normalization project — conversations like the one that produced this retrospective occur mid-task, across different tools and sessions, and all contain extractable knowledge. Previously this was a 90mb knowledge.txt of forum pastes and history dumps, ported between machines. Now it's structured, queryable, cross-referenceable across sessions.

**Deterministic context capture** is this project — the reactive TUI pattern. Not "a dashboard," but a context scoping and capture primitive:

| Pattern component | Context role |
|-------------------|--------------|
| EventStore | The raw stream (everything happening) |
| Filter | Context scoping (narrow to what's relevant now) |
| Tee | Context capture (persist the scoped chunk) |
| Computed | Derived views (make scoped context legible) |
| Replay | Append-only log enables re-deriving any past state |

The event-sourced architecture isn't an implementation choice — it's a requirement. You need replay. You need "show me what happened between 14:02 and 14:07 on that docker stack." Mutable state doesn't give you that. The log does.

The "lite" aspect — filter-then-tee — answers "not all context is worth keeping." You observe the full stream, scope to what's relevant, capture that slice, and the rest flows past. The tool is a lens, not a recorder. It becomes a recorder only when you choose to point it.

### The join: temporal correlation

Cognitive gives how/why/who. Deterministic gives what/where. The missing primitive is **when** — the temporal correlation between the two. "This agent conversation was happening *while* this system state was occurring."

Timestamps in both event logs are the join key. The sqlite normalization preserves them on the cognitive side. This project preserves them on the deterministic side. Cross-referencing is a query over both: "what was the system doing when the agent decided to restart that service?"

### The "works for everyone" path

The goal isn't to build bespoke dashboards per-system. It's to develop patterns and primitives that allow "works for me" to collapse directly into "works for everyone" via agentic assistant. The same pattern that monitors a homelab docker stack monitors a team's queue service. Other developers care about the events, not the event system — they shouldn't need Sumo Logic or Confluence for what a scoped, filtered, live view gives them directly.

---

## Reflections: Stepping Back

### What I see clearly

**The event log is undervalued as a UI primitive.** The industry treats event logs as backend infrastructure (Kafka, CloudWatch, Datadog) or developer tooling (structured logging, tracing). The idea that the append-only log is also the *right state model for interactive applications* — that current state is always a derived view, never a primary store — is well-understood theoretically (event sourcing literature) but almost never applied at the UI layer. We've shown it works. The implications are broader than terminals: any UI that shows "what's happening" and "what happened" benefits from this model.

**The pattern's simplicity is both its strength and its adoption barrier.** 214 lines of framework. Three primitives (Signal, Computed, Effect) plus an append-only list. There's nothing to sell, nothing to install, nothing to migrate to. This is powerful for the person who understands it — you just apply the pattern in whatever context you're in. But it means there's no artifact that accumulates community, no package to star on GitHub, no conference talk that demos a logo. Patterns spread through osmosis, not launches. The question is whether the examples are compelling enough to be copied, or whether this stays personal tooling knowledge.

**The "context scoping" reframe changes the value proposition.** A "reactive TUI framework" competes with Textual, Bubbletea, Ratatui — established tools with communities. A "context scoping and capture primitive" competes with... nothing, really. The closest things are log viewers (lnav, stern) and monitoring dashboards (Grafana), but those are either read-only or require infrastructure. A composable, in-terminal, filter-tee-replay tool that you stand up in 200 lines for any event stream — that's a different category.

### What concerns me

**The recomputation model has a real ceiling.** Every Computed re-scans the full event log on every change. This is fine for the examples (hundreds of events), plausible for real monitoring (thousands), and untenable for serious log analysis (millions). The fix is known — incremental computation, windowed projections, or hybrid approaches where you maintain running aggregates — but it's not trivial to retrofit. The pattern as-is works for "live monitoring with short memory." It doesn't work for "replay last week's logs." That's a different tool, or a significant extension.

**The cognitive/deterministic split might be premature.** You're drawing a clean line between "agent conversations" and "system events." But in practice, the most interesting context is the *boundary* — the agent running a command (cognitive decision) that produces output (deterministic event) that the agent interprets (cognitive) and acts on (deterministic). The join isn't just temporal correlation; it's causal. Timestamps get you proximity; they don't get you causality. The deeper integration might need the agent's actions to *be* events in the deterministic log, not a parallel stream joined by time.

**The "works for everyone" collapse depends on interface stability.** The pattern works because EventStore is generic over event type. But "works for everyone" means other people's event shapes, other people's filter needs, other people's pane layouts. The framework is 214 lines because it defers everything domain-specific to the user. That's architecturally clean but it means each new use case requires someone who understands the pattern to wire it up. The agentic assistant is the answer to that — "here's my event stream, give me a dashboard" — but that requires the agent to understand the pattern deeply enough to instantiate it correctly. You're betting that agents can be that bridge, which is a reasonable bet given what you've seen, but it's worth naming explicitly: the adoption path runs through AI, not documentation.

**There's a tension between "lens" and "tool."** You describe this as a lens — observe, scope, capture, move on. But the process_manager example is a tool — it takes actions, mutates state. These are different postures. A lens is passive and composable; you can point it at anything. A tool is active and domain-specific; it needs to understand what it's controlling. The pattern supports both, but the further you go toward "tool" the more domain logic leaks into the framework boundary. The pure "lens" use case (filter + tee on any event stream) might be the more powerful primitive to develop first — it's universally applicable, whereas "tool" is per-domain.

### What I find genuinely interesting

**The temporal join between cognitive and deterministic context is a novel data model.** I'm not aware of systems that explicitly maintain both "what the human/agent was thinking" and "what the system was doing" as correlated event logs, queryable together. Development tools have traces (what the code did) and maybe git blame (who wrote it), but not "what was the reasoning that led to this change, cross-referenced with the system state that motivated it." If you build this — even messily, even just for yourself — you'll have a dataset that doesn't exist elsewhere. The meta-patterns you extract from it could be genuinely novel.

**The "automated knowledge.txt" concept solves a real problem.** Every experienced engineer has institutional knowledge trapped in their head, in scattered notes, in chat history. The idea that agent conversations — which already capture the investigation process, the dead ends, the "oh, it was actually X" moments — can be structured into a queryable knowledge base is compelling. The key insight is that the *conversation itself* is the knowledge artifact, not a summary extracted from it. You don't need to write documentation; the collaborative investigation *is* the documentation.

**The reactive TUI as "agent's viewport" is unexplored territory.** Right now agents interact with systems via command execution and output parsing. The reactive TUI could be the intermediate representation — the agent doesn't need to parse raw logs if it can observe a structured, filtered, live view. This inverts the current model: instead of "agent reads raw output, builds mental model," it's "system provides structured observable state, agent reads the projection it needs." The TUI isn't just for human eyes — it's a structured interface that both human and agent can observe simultaneously. Whether that's practical depends on how agents evolve, but it's a direction nobody's building toward.

### Correction: lens vs. tool is a false tension

On reflection, the lens/tool distinction drawn above is artificial. A kill button on a process and a remove button on a queue subscription are the same gesture — "act on a selected entity in the observed stream." From the user's perspective there's no category boundary between "observe" and "act." The pattern already supports both; the concern about "domain logic leaking into the framework" is an architecture purity worry, not a user-facing problem.

The better frame: this is what Bubbletea did for Go TUIs, what Bootstrap did for front-ends. The question is what this project *collapses*:

- **Bootstrap** collapsed "design a decent page" into "apply these classes"
- **Bubbletea** collapsed "build an interactive Go TUI" into "implement Model/Update/View"
- **This** collapses "build a reactive terminal observer/actor for any event stream" into "define your event type, your filter logic, and your panes"

The gap between 214 lines and that is the ergonomics layer. The pattern is proven; the developer experience of instantiating it isn't. The current primitives: EventStore, Computed, Filter, Tee, Pane. Some may merge, split, or be replaced by something unnamed. More examples across more domains will apply the pressure that exposes the real primitive set.

This isn't going to stay a 214-line pattern. The next phase is pushing it — both as lens and as active tool — looking for what the context observability/filtering primitive actually is. Where it lands (framework, toolkit, or category-defining project) depends on what the examples reveal.
