# GENESIS: The Origin and Evolution of Prism

## A document reconstructed from archived conversations via strata

---

## Prologue: A Frozen Movie

It started with a corrupt file. A daughter tried to watch *The Wild Robot* — it froze fifteen minutes in. A truncated 1.5GB file with metadata lying about its runtime. A familiar homelab annoyance.

But the fix didn't stop at the fix. "Come up with a script for quickly removing a dud movie and requeueing." Then: "Determine how we can scan for other video mismatches." What followed was `media-audit.py`, Radarr/Recyclarr integration, a KDL spec-to-scaffold pipeline. The founding pattern was established: **a concrete problem surfaces, gets solved, then gets generalized.** Agents collapsed the cost of generalization. The question shifted from "can I afford to generalize?" to "why wouldn't I?"

The homelab — `gruel.network`, Proxmox VMs, 50+ Docker containers, SSH deploys via `hlab` — would serve as the forcing function for everything that followed. Every abstraction had to serve real infrastructure. When it didn't, it got archived.

---

## Act I: The Contract That Started Everything

### ev: Events as Facts, Not Instructions

The first library was `ev` — a CLI event contract. Five frozen event kinds: `log`, `progress`, `artifact`, `metric`, `input`. The core philosophical claim, stated early: **"Events are facts, not instructions."** An event describes what occurred, not how to display it.

`ev` established the Emitter Protocol, reference implementations (JsonEmitter, PlainEmitter, RichEmitter), and the stdout/stderr policy: events flow to stderr (transient observations), Result flows to stdout (the authoritative verdict). `ev-toolkit` gave any CLI structured event streaming for free.

But `ev` had a constraint it couldn't see yet: it defined canonical kinds as a **closed taxonomy**. It was prescriptive about what an event *is*. That constraint would eventually crack open the entire project.

### The Gap Nobody Filled

Managing 50+ containers emitting 100+ events/sec, Kyle reached for Rich. Beautiful output — but it polls and repaints the entire screen every frame. Too slow. Textual was a full widget framework with CSS and DOM. Too heavy. Ratatui and Bubbletea had diff-based rendering, but in Rust and Go.

Python had no diff-based terminal renderer. Kyle built one. That became **cells**: Cell (char + style) as the spatial atom, with Block, Buffer, Span, Line, Layer, Lens, Surface. The "Python Ratatui."

---

## Act II: The Reactive Detour

### The O(n²) Wall

Before cells found its footing, the project reached for reactive primitives. A Python Signals library (`reaktiv`, inspired by Angular/SolidJS) provided Signal, Computed, and Effect. Four dashboard examples proved the pattern worked.

Then the wall: `lines.update(lambda ls: [*ls, new_line])` creates an O(n) copy every append. Signals optimize for fine-grained interconnected state — the wrong shape for append-only streams. The system's fundamental data pattern is a growing log, not a web of mutable values.

### The Pivot: Events Are Primary, State Is Derived

The pivotal observation: **"It seems... off that our UI is handled off to the side, separate from the event system."** The events-primary architecture inverted the model: EventBus became the spine. Everything flows through it. Subscribers derive their own state. Replay became trivial.

The recognition: *"We've effectively gotten rid of the ev concept. ev in retrospect was an attempt to set up a signals interface, except it was being coupled with events which was limiting."*

This was the moment the project stopped being a CLI framework and started becoming something else.

---

## Act III: The Stream and Its Dissolution

### rill: Kafka at Personal Scale

The deeper realization: EventStore is just one consumer, not the center. **The Stream is the center.** `Stream[T]` as typed async broadcast, with Consumer, Tap, Projection, FileWriter, Tailer. Kafka concepts at personal scale, using files instead of brokers. Extracted as `rill` (~440 lines, zero dependencies) — named because "a rill is a small stream."

### Stream to Vertex: Plumbing Pretending to Be Architecture

But "Stream" described plumbing, not architecture. The reframe: **it's not a stream you tap into — it's an intersection of loops.** `Vertex` replaced Stream as the conceptual center. Graph theory vocabulary won: loops are cycles, vertices are where cycles meet. An intersection is a *place*, not a pipe.

"Stream as a concept disappears. It was plumbing pretending to be architecture." The `Stream` class still exists as runtime infrastructure. But the architecture speaks in vertices now.

---

## Act IV: Crystallization — Five Atoms, Five Questions

### The Unification Moment

Working on cells forced the question: if cells answers *where*, what answers *what*, *when*, *how*, *who*? The five-W framing emerged during the cells development arc:

| Package | Atom | Question | Metaphor Family |
|---------|------|----------|-----------------|
| **peers** | Peer = name + horizon + potential | *who* | social |
| **facts** | Fact = kind + ts + payload | *what* | narrative |
| **ticks** | Tick = name + ts + payload | *when* | temporal |
| **shapes** | Shape = facets + folds + boundary + apply | *how* | geometric |
| **cells** | Cell = char + style | *where* | spatial |

*"Having this atomic concept helps keep my thinking in line."*

Each library independently answers one question. The question IS the library boundary. They compose in the experiments layer. No atom imports another. The boundary discipline is absolute.

### The Data Flow: A Loop, Not a Pipeline

```
Peer observes a Fact
  -> Fact arrives at Vertex (routes by kind)
  -> Shape.apply folds state (pure dict->dict)
  -> Lens renders state as Cells
  -> You see it. Your choice becomes a new Fact.
  -> The loop closes.

At a temporal boundary:
  -> Folded state becomes a Tick
  -> Tick enters the next Vertex
  -> Same primitive, next level. Loops nest.
```

---

## Act V: The Vocabulary Wars

### The Great Deletion: Event to Fact

The most dramatic rename. 6,081 lines deleted. `Event(kind, level, message, data, ts)` with its entire Emitter hierarchy became `Fact(kind, ts, payload)` with one factory method.

The vocabulary shift: from "events you emit" (output-oriented, CLI-framework thinking) to "facts you observe" (input-oriented, observation-loop thinking). `Event` implies something happening *to* the system. `Fact` implies something the system *noticed*. The rename carried a conceptual reorientation.

### The Shapes Vocabulary Crisis

Three types from three metaphor families: `Shape` (geometry), `Field` (databases/agriculture), `Fold` (origami/FP). Kyle flagged it: *"It sits on my brain like three different concepts."*

The principle crystallized: **each library owns one metaphor family.** Mixing domains within a library is a vocabulary bug.

- `Field` became `Facet` ("a shape has facets" — gem-cutting, geometric)
- `Form` became `Shape` (primary type matches package name)
- `Fold` stayed (folding paper into shapes IS geometry)

The sentence test: "A shape has facets" works. "A shape has fields" mixes metaphors.

### The Fold Ownership Dialectic

Three-step dialectic:

1. **Folds in shapes.** Original home.
2. **Folds move to ticks.** Reasoning: "Shape describes structure, fold describes transformation. Different concerns." Shape becomes pure schema.
3. **But schema-only shapes is just TypedDicts with a fancy name.** Too thin. Then the resolution: a `Fold(op="upsert", target="services")` isn't *doing* anything — it's a **declaration**. Frozen, immutable, structural. Shape owns the complete contract.

The recurring move: reframe verbs as nouns. Fold is a declaration masquerading as a procedure.

### Scope to Horizon + Potential

Peer's `Scope(see, do, ask)` — three frozenset dimensions with undefined semantics — collapsed to two: `horizon` (what you can observe) and `potential` (what you can do/emit). Physical metaphors: one spatial (how far you can see), one energetic (what actions are available). The ill-defined `ask` dimension dissolved.

Stance (direct, guided, delegated, automated, observing) became emergent, not enumerated. *"The identity is the stance."*

---

## Act VI: The Questions That Dissolved

### Should Tick Collapse Into Fact?

The most sustained open question. Tick is structurally similar to Fact — both carry a timestamp and payload. The proposal: merge them. What's left in ticks is pure plumbing.

The external validation: a comparative analysis surveyed prism against event sourcing, stream processing, discrete event simulation, FRP, actor model, and control systems. Every comparison identified Tick as the key differentiator. *"A tick is a loop's exhale."*

The resolution: **Facts go in, Ticks come out.** They encode *direction*. Collapsing them erases the most distinctive concept. The question didn't get answered — it dissolved. Proven concretely in `experiments/fleet.py` with a three-level vertex hierarchy.

### Should Loop Be a Sixth Atom?

Explored: `Loop(name, receives, emits, boundary)`. But boundary already lived in Shape. Receives/emits is wiring, not data. Loop was neither data type nor infrastructure — a concept without a clean home. It dissolved into topology.

### Do We Need Lifecycle Primitives?

Lifecycle (start, stop, pause) dissolved into facts. Starting a loop is just an observation: "this loop started." Nesting dissolved into topology: inner loop's Tick enters outer loop's Vertex.

The pattern across all dissolutions: **the question is based on a false distinction.** The move is to show the distinction doesn't exist, not to resolve it.

---

## Act VII: The Monorepo Name

| Candidate | Metaphor | Fate |
|-----------|----------|------|
| **loops** | Engineering/systems | Rich vocabulary. Rejected: collides fatally with `asyncio.get_event_loop()`. |
| **turns** | Sequential flow | "A turn is the full record, observe, act flow." Rejected: `turns/facts` reads as a verb phrase. |
| **volta** | Italian for "turn"; electrical circuits; the sonnet's pivot | Strongest candidate. "Each pass through the system is a volta." Kyle: "I'm going to think on volta for a bit." |
| **prism** | Optics / light refraction | Current name. More brand than teach. Still open. |

The naming debate surfaced a deeper insight: the four atoms below cells (facts, ticks, peers, shapes) are *universal* — format-agnostic. Cells is the first *surface*, but shaped state could render to anything. The name should capture the universal part, not the terminal-specific part.

---

## Act VIII: The Feedback Loop Closes

### Surface + Emit: The Loop Becomes Real

`RenderApp` (one-directional rendering) became `Surface` with `Emit = Callable[[str, dict], None]`. Surface is bidirectional: renders state outward, emits interactions inward.

Every interaction — keypress, resize, domain action — becomes a Fact that re-enters the same Vertex as external observations. **The system doesn't distinguish between "a deploy happened" and "you pressed a key."** Both are Fact. Both arrive at the same Vertex. The loop went from aspirational diagram to implemented reality.

Three strata of Surface emissions:

| Stratum | Auto? | Kind | Example |
|---------|-------|------|---------|
| Raw input | yes | `ui.key` | `{key: "j"}` |
| UI structure | yes | `ui.action` | `{action: "pop", layer: "confirm"}` |
| Domain | no | (any) | `{item: "deploy-prod"}` |

### Observation Is Always Present-Tense

The deepest philosophical moment: "Even if you're replaying a stored session, is it still real-time?"

Yes. Observation is always in the present. Replaying historical facts creates a *new* loop, because the observer is always now. The system's philosophical core: **observation is participation. Seeing the system changes the system.**

---

## Act IX: The Mirror — AI Collaboration as Loop

### The Delegation Hierarchy Is the Collaboration Pattern

```
kyle                              -> you, direct participant
kyle/claude-session-123           -> your current Claude session
kyle/claude-session-123/worker-1  -> delegated subtask agent
kyle/claude-session-123/worker-2  -> another delegated agent
```

The Peer delegation hierarchy directly models human-to-AI-to-sub-agent chains. Stance is emergent: which peer observed the fact tells you the participation level. The architecture was designed from the observation that **human-AI collaboration IS a feedback loop**: observe, interpret, act, observe again.

### The Timescale Spectrum

Same atoms, same structure, different clock speed:

| Timescale | Loop Instance |
|-----------|--------------|
| milliseconds | TUI render cycle (cells observe, user responds) |
| seconds | Interactive session (you type, Claude responds) |
| minutes | Agent task (delegated, works, completes) |
| hours | Coding session (start work, session ends, strata ingests) |
| days/weeks | Practice loop (strata query, insight, apply to new work) |

This is why the system's structural truth is *loops*. The topology is the same whether it's a TUI redraw or a week-long research arc.

### Strata's Place in the Loop

Strata is not outside the loop. It is the archive participant that closes the longest timescale:

- **Consumes** facts (ingests sessions)
- **Produces** facts (emits ingestion/indexing events)
- **Serves** as a query surface (search results feed back as observations)

The vision: you code with Claude, sessions produce facts, strata ingests them, normalization emits new facts, those facts enter your workspace stream, preconfigured projections fold them, other agents connect with their own context. **The tools you build with prism are the tools you use to build prism.**

---

## The Principles (Distilled)

1. **Observation is the primitive.** Not instruction, not command. The system records what was noticed.
2. **Immutable by default, append-only truth.** All atoms frozen. State = fold(facts). Never mutate.
3. **The system is loops.** Not pipelines. The end connects to the beginning.
4. **Same primitive at every level.** Ticks nest. No conversion needed between levels.
5. **No atom imports another.** Composition lives at the integration point.
6. **Declarations over procedures.** Fold is a noun. Boundary is declarative. Stance is emergent.
7. **Vocabulary enables thinking.** Each library owns one metaphor family. If the name doesn't fit, the concept might be wrong.
8. **Defer until patterns emerge.** No premature abstraction. Convention before mechanism.
9. **Event-sourced everything.** Even authorization is just facts folded through a shape.
10. **Dissolution over resolution.** Many questions don't get answered — they reveal false distinctions.

---

## The Dead and the Archived

| What Died | Why | What Replaced It |
|-----------|-----|-----------------|
| 6,081-line Emitter framework | Solving a different problem (CLI output) | `Fact(kind, ts, payload)` |
| Spec-driven framework (binding, spec, collectors) | Too much infrastructure before concepts were clear | Direct Docker polling + thin integration |
| `reaktiv` signals | O(n^2) on append-only data | Events-primary architecture |
| `Scope(see, do, ask)` | Three undefined dimensions | `horizon` + `potential` |
| `FormProjection` bridge class | Unnecessary ceremony | `Projection(initial, fold=shape.apply)` |
| Loop-as-atom | Neither data type nor infrastructure | Topology (emergent) |
| `datetime` for timestamps | Too much ceremony | `float` (epoch seconds) |

The pattern: the project repeatedly resists premature structure. Things that looked like they needed dedicated types kept dissolving into simpler compositions.

---

## Epilogue: Still in the Loop

The project is at a threshold. Five atoms, all green (358+ tests), no cross-lib imports. The architecture document is crisp. The vocabulary is hard-won and specific. The experiments layer wires real things. The naming question remains open. And the builder is still in the loop — observing, folding, ticking at the boundary.

*"Not a framework for TUIs. A framework for observation-feedback systems."*
