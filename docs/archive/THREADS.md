# THREADS — monorepo

Cross-cutting concerns that span multiple libs or affect the monorepo
as a whole. Per-lib threads live in each lib's own THREADS.md.

## Naming — loops vs volta (under consideration)

Two candidates remain. The choice is between ontology and brand.

**loops** — the ontological argument:
- Everything IS loops, from Planck scale to Big Bang
- The atoms provide specificity; the container provides universality
- The "genericness" is the feature — loops is the medium, not a metaphor
- One-way time + entropy = loops occur naturally at every scale
- "The election loop" is immediately graspable; it reframes familiar concepts
- The system models reality; the name should describe reality
- CS collision (event loop, for-loop) is real but arguably irrelevant:
  event loops ARE loops. for-loops ARE loops. That's the point.
- Discoverability concern: "loops python" returns tutorials

**volta** — the brand argument:
- Italian for "turn." The volta in a sonnet is where accumulated meaning
  shifts. Alessandro Volta: circuits, stored potential.
- Carries semantic accuracy of "turn" with brand texture
- Literary/scientific depth, story worth telling at a conference
- Distinctive, searchable, low collision risk
- Doesn't carry the universality claim — it's about the individual turn,
  not the medium
- PyPI: taken but abandoned (7+ years). NVIDIA Volta: fading/different domain.

**prism** (current) stays on the table as neutral fallback — doesn't
mislead, doesn't teach, lets the atoms do the work.

Alternatives fully explored and retired: turn (verb-phrase clash),
coil, gyre, helix, reverb, ambit (see HANDOFF.md for full analysis).

Status: leaning loops. Thinking on it. No rename work started.

## The pivot — shaped state as universal contract

The volta (complete traversal) has two halves separated by shaped state:

    facts, ticks, peers, shapes        ← below the pivot (universal)
    ─────────────────────────────────
          shaped state (a dict)         ← the pivot
    ─────────────────────────────────
    surface (cells, html, api, ...)    ← above the pivot (paradigm-specific)

Below the pivot: domain logic. Facts enter, shapes fold them, peers
scope them. Universal — doesn't know or care how state renders.

The pivot itself: the output of shape.apply(). A plain dict. The
universal intermediate representation. Format-agnostic.

Above the pivot: rendering and feedback. A surface takes shaped state,
renders it outward, emits interactions inward. Cells is the first
surface (character-grid paradigm, terminal adapter). Future surfaces
would consume the same dict through different paradigms.

Four atoms are universal (tick, fact, peer, shape). Cell is a surface
specialization — the first, not the only. This reframes cells from
"the fifth atom" to "the first surface."

Shaped state as a contract needs investigation: what guarantees does
shape.apply() make about its output? Is it always a dict? Can surfaces
depend on structure, or only on the shape's facet declarations?

Related: cells THREADS.md "Block serialization" and "Grid surface vs
terminal adapter" threads explore the cells-specific side of this.

## Conceptual vocabulary

The volta framing introduces vocabulary for talking about the system:

    volta       one complete traversal: fact → shape → cell → new fact
    close       when a surface emits feedback, completing the volta
    turn        what happens during a volta (the sequence of events)
    feedback    facts emitted by surfaces, re-entering the next volta
    pivot       shaped state — the universal handoff between domain and surface
    open volta  observation without emission (surface watches, doesn't respond)
    prima volta   first pass through new facts (musical: first time)
    seconda volta re-pass after feedback arrives (musical: second time)

Not all of these may earn their keep. prima/seconda volta in particular
need to prove useful in practice before committing to them.

## Surface as a general concept

A surface is the bidirectional boundary where the volta touches reality.
It renders shaped state outward and emits interactions inward as new
facts. Cells is the terminal surface (character-grid paradigm + ANSI
adapter). Other surfaces would use different paradigms:

    Surface type     Paradigm              Atom
    ─────────────────────────────────────────────────
    cells            character grid         Cell (char + style)
    (future) docs    document structure     section/fragment
    (future) api     structured data        endpoint/payload
    (future) web     DOM                    element/component

Each paradigm has its own rendering atom. They share the same contract:
consume shaped state, render outward, emit feedback inward.

Open questions:
- Does the monorepo need a Surface protocol, or is this just a pattern?
- How does emit generalize across surfaces? cells uses keyboard events;
  web would use clicks/forms; api would use request payloads.
- Layer (modal stacking) currently assumes key: str input. Generalizing
  to event-based input is needed before a second interactive surface.

## Strata as temporal accumulator

strata (~/Code/strata) is a personal analytics engine for LLM coding
sessions. It ingests conversations from Claude Code, Gemini CLI, and
Codex CLI, stores them in SQLite, and provides full-text + semantic
search + SQL queries.

strata embodies the same philosophy as the volta model:
- Observation is first-class (everything is a recorded observation)
- Append-only (ingested conversations are immutable records)
- Meaning is derived, not stored (cost is query-time, tags are manual)
- Feedback exists (insights from queries change future sessions)

The domain model maps onto the atoms:

    volta atom    strata equivalent
    ──────────────────────────────────────────────────────────
    Fact          Prompt, Response, ToolCall — timestamped observations
    Peer          Harness + workspace — scoped identity (which tool, where)
    Shape         Adapters — fold raw logs into normalized domain model
    Tick          Conversation — temporal boundary, one session snapshotted
    Surface       CLI formatters — render query results for the observer

The key distinction: **volta is always real-time.** Not because the facts
are new, but because the observer is always in the present. Even when
replaying a stored session, your observation is happening now — you're
starting a new volta with historical facts as input. Your interpretation,
your tagging, your decision to apply an insight — those are new facts
created by the act of observation.

This makes the relationship between the two systems clear:

    volta   real-time feedback circuit. Always now.
    strata  temporal accumulator. Stores facts across voltas.

strata bridges voltas across time. It archives facts from past voltas
and makes them available for re-entry into new ones. Replay isn't
"watching a recording" — it's feeding historical facts into a new volta
where your observation creates new meaning.

strata is not currently built on volta's atoms. Its domain model
(Conversation → Prompt → Response → ToolCall) is richer than
Fact(kind, ts, payload) for its specific domain. But strata is part of
the flow — it's a participant that could emit facts and consume streams
without being rewritten. The relationship is: strata is a concrete
application of the pattern that volta generalizes, and the direction is
bringing it into the loop as a fact-emitting, stream-consuming
participant. See "Integration vision" below.

Origin conversations tagged in strata: `origin:prism-monorepo`
(01KFXBA6WMEM, 01KFXBA8CQQ3, 01KFXBA5B1B2).

## Integration vision — bringing external systems into the loop

The monorepo provides atoms and protocols. External systems participate
by emitting facts and consuming streams. The monorepo doesn't absorb
them — it gives them a way in.

### The concrete workflow

You sit down to work. A Tick starts.

    You open your workspace
      → fact: kind="workspace.open", payload={path, ...}
      → your ticks daemon receives it
      → preconfigured projections start folding

    You connect to relevant event streams
      → workspace events (file changes, git, builds)
      → strata events (session ingested, session indexed)
      → agent events (delegated, completed, failed)
      → any external stream (deploys, alerts, CI)

    You talk to Claude
      → your session is a volta (real-time, interactive)
      → Claude delegates a task
        → fact: kind="peer.delegated", payload={parent, child, scope}
        → child peer created (kyle/claude-session/worker-1)
        → child's Tick starts (delegation → session end)

    The delegated agent spins up
      → connects to the projection (reads current workspace state)
      → sees real-time feed: active sessions, recent ingests, etc.
      → does its work, producing facts along the way
      → session ends → its Tick closes

    Unrelated things happen in the background
      → a CI build completes: fact enters the stream
      → strata finishes indexing yesterday's sessions: fact
      → another agent finishes a parallel task: fact
      → all recorded, but NOT projected into YOUR current lens
      → your surface shows what your Tick is focused on

    Your surface is interactive
      → toggle streams on/off
      → view raw facts or shaped projections
      → switch lenses (zoom, filter, different shape)
      → every interaction emits facts back into the stream

    Everything feeds back to the beginning
      → your observations become facts
      → agent results become facts
      → strata ingests this session → emits ingestion facts
      → the loop continues

### What "bring X into your loop" means

The monorepo doesn't need to contain strata. It needs to provide:

1. **Fact emission protocol** — how external systems emit facts into a
   stream. strata emits "session.ingested". CI emits "build.completed".
   A deploy tool emits "deploy.started". Same protocol, any source.

2. **Stream connectivity** — how a new participant (agent, tool, surface)
   connects to an existing stream. The ticks daemon exposes something
   (socket, pipe, file, channel) that peers attach to.

3. **Peer registration** — how external systems identify themselves.
   strata is a peer (strata/indexer). CI is a peer (ci/github-actions).
   Each has a scope that determines what it can see and emit.

4. **Tick boundaries** — how external systems declare their temporal
   scope. An agent's tick spans delegation → completion. A build's tick
   spans trigger → result. strata's ingestion tick spans ingest-start →
   ingest-complete.

strata already does most of this implicitly. It ingests (consumes facts),
normalizes (shapes), stores (ticks), and presents (surfaces). Making it
explicit — emitting facts into a volta stream, registering as a peer —
is the integration step. Not a rewrite. A protocol adoption.

### The ticks daemon

The missing infrastructure: a long-running process that maintains
streams and projections. This is the runtime that makes the atoms
operational.

    ticks daemon
      ├── receives facts from any source
      ├── routes to configured streams
      ├── maintains projections (fold via shapes)
      ├── exposes connection points for new peers
      ├── manages tick boundaries (start, close, timeout)
      └── serves shaped state to surfaces

Without the daemon, the atoms are libraries that compose in scripts.
With it, they're a live system that external tools participate in.

### Stream selectivity and lens focus

Not everything projects into everything. The key UX insight: your
surface shows what YOUR Tick is focused on. Background events are
recorded (facts enter the stream) but not projected into your current
lens unless you choose to see them.

    Your Tick: "working on auth refactor"
      → projecting: workspace events, your Claude session, delegated agents
      → recording but not projecting: CI builds, strata indexing, other workspaces

    You toggle a stream on:
      → CI events start projecting into your lens
      → you see the build that just failed
      → your observation becomes a fact
      → you delegate an agent to fix it
      → toggle CI off, back to your focus

This is the surface being interactive — not just rendering state but
letting you control what you observe. The streams are always there.
The lens is your choice.

### Tick lifecycle

Everything closes its own tick — ideally. In practice, some ticks
just stop without formal closure (you close your laptop, an agent
crashes, a network drops). The system should handle both:

    Clean close:  agent completes → emits "tick.closed" → tick archived
    Dirty close:  agent crashes → no close event → tick times out or is
                  closed by a parent peer ("I noticed my worker stopped")
    Implicit:     you close your laptop → session JSONL stops → strata
                  ingests it later → the tick is effectively closed by
                  the archive, retroactively

The append-only model helps here: even a dirty close has all its facts
recorded up to the point of failure. The tick boundary is the only
thing missing, and that can be inferred or applied after the fact.

### The timescale spectrum

Same structure, different clock speed:

    milliseconds   TUI render volta (cells observe, user responds)
    seconds        interactive volta (you type, Claude responds)
    minutes        agent volta (delegated, works, completes)
    hours          session volta (start coding, session ends)
    days/weeks     practice volta (strata query, insight, new session)

The atoms don't change across timescales. Fact, Peer, Shape, Tick,
Surface — same at every level. What changes is the clock speed and
the surface through which you observe.

Open questions:
- What does the ticks daemon concretely look like? Process, socket,
  file-based, or something else?
- How does stream routing work? Does every fact go to every stream,
  or is there kind-based routing? Peer-scoped routing?
- What's the minimum viable "bring strata into the loop" integration?
  Probably: strata emits facts to a file/socket that the daemon reads.
- How do tick timeouts work? Who decides a tick has implicitly closed?
  Parent peer? Daemon? Configurable per-tick?
