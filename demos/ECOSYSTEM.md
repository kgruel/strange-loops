# The Unified Semantic Ecosystem

Five libraries. Five atoms. Five questions. One composable ecosystem.

## The Five Dimensions

```
┌─────────────────────────────────────────────────────────────────┐
│                     peers (who + scope)                         │
│           identity and boundaries that cascade through          │
└─────────────────────────────────────────────────────────────────┘
          ↓ scopes everything below
┌─────────────────────────────────────────────────────────────────┐
│  facts         ticks         forms         cells                │
│  (what)        (when)        (how)         (where)              │
│                                                                 │
│  Fact          Tick          Field         Cell                 │
│  kind+ts+data  ts+payload    name+type     char+style           │
│                                                                 │
│  Verdict       Store         Form          Block                │
│  status+code   Stream        Fold          Buffer               │
│                Projection                  Lens                 │
└─────────────────────────────────────────────────────────────────┘
```

| Dimension | Library | Atom | Question |
|-----------|---------|------|----------|
| **Who** | peers | Peer (name + scope) | Who is acting? What can they see/do? |
| **What** | facts | Fact (kind + ts + data) | What semantic meaning? |
| **When** | ticks | Tick (ts + payload) | When did it happen? How does it flow? |
| **How** | forms | Field (name + type) | What shape? How does it transform? |
| **Where** | cells | Cell (char + style) | Where does it appear? How does it look? |

## Vocabulary Summary

| Library | Atom | Composed | Transform | Purpose |
|---------|------|----------|-----------|---------|
| **peers** | Peer | Scope | Grant/Restrict | Identity + boundaries |
| **facts** | Fact | - | Verdict | Semantic meaning |
| **ticks** | Tick | Store, Stream | Projection | Temporal flow |
| **forms** | Field | Form | Fold | Shape contracts |
| **cells** | Cell | Block, Buffer | Lens | Spatial display |

## The Flow

```
Peer (scoped identity)
  │
  ├─ emits ──→ Fact (semantic meaning)
  │              │
  │              ├─ stored in ──→ Tick (timestamped)
  │              │                  │
  │              │                  ├─ shaped by ──→ Form (field + fold)
  │              │                  │                  │
  │              │                  │                  ├─ rendered via ──→ Lens (zoom)
  │              │                  │                  │                     │
  │              │                  │                  │                     └─→ Cell/Block
  │              │                  │                  │
  │              │                  └─ projected ──→ State
  │              │
  │              └─ returns ──→ Verdict (final outcome)
  │
  └─ delegates to ──→ Peer (narrower scope)
```

## The Interlinks

```
peers ←──────────────────────────────────────────────────┐
  │                                                       │
  │ Peer emits Fact (scoped)                             │
  ↓                                                       │
facts ←─────────────────────────────────────────────┐    │
  │                                                  │    │
  │ Fact stored as Tick                             │    │
  ↓                                                  │    │
ticks ←────────────────────────────────────┐        │    │
  │                                         │        │    │
  │ Ticks projected via Form → State       │        │    │
  ↓                                         │        │    │
forms ←───────────────────────────┐        │        │    │
  │                                │        │        │    │
  │ State rendered via Lens       │        │        │    │
  ↓                                │        │        │    │
cells ─────────────────────────────┴────────┴────────┴────┘
  │                                ↑        ↑        ↑
  │ User sees Cells               │        │        │
  │ User acts                     │        │        │
  └─ interaction ─→ Fact ─────────┴─ scoped by Peer ┘
```

The feedback loop: Cells render for Peer → Peer sees/acts → Fact emitted → flows through ticks/forms → renders in cells

## Composition Patterns

**Standalone usage** - each library works alone:

```python
# Just facts - semantic events
from facts import Fact, Verdict
fact = Fact.log("Starting")
verdict = Verdict.ok(data={"count": 42})

# Just cells - visual rendering
from cells import Block, Lens, shape_lens
block = Block.text("Hello")

# Just ticks - temporal storage
from ticks import Store, Stream
store = Store(path="events.jsonl")

# Just forms - shape contracts
from forms import Form, Field, Fold
form = Form(name="status", fields=[Field("healthy", bool)])

# Just peers - identity/scope
from peers import Peer, Scope
me = Peer("kaygee", scope=Scope(see={"*"}))
```

**Composed usage** - full pipeline:

```python
# Peer-scoped facts through ticks, shaped by forms, rendered in cells
from peers import Peer, Scope
from facts import Fact
from ticks import Store, Projection
from forms import Form, Field, Fold
from cells import shape_lens

# Identity with scope
me = Peer("kaygee", scope=Scope(see={"*"}, do={"~/Code/*"}))

# Shape contract
status_form = Form(
    name="service-status",
    input_fields=[Field("service", str), Field("healthy", bool)],
    state_fields=[Field("services", dict)],
    folds=[Fold("upsert", "services", key="service")]
)

# Emit scoped fact → store → project → render
fact = Fact.log_signal("status", service="web", healthy=True, _peer=me.name)
store.add(fact)
state = projection.advance(store).state
block = shape_lens(state, zoom=1, width=80)
```

## Design Principles

| Principle | Expression |
|-----------|------------|
| **Explicit over implicit** | Types, shapes, contracts visible |
| **Simple by default** | Minimal primitives, extend only when proven |
| **Patterns over point solutions** | General forms you can specialize |
| **Convention over primitive** | Reserved keys before new types |
| **Vocabulary IS API** | Naming choices define the mental model |

## Library Vocabularies

### peers (who + scope)

| Primitive | Purpose |
|-----------|---------|
| Peer | name + scope (atomic identity) |
| Scope | see + do + ask (boundaries) |
| Grant | expand scope |
| Restrict | narrow scope (delegation) |

Scope cascades through everything - defines what a peer can see, do, and ask across all layers.

### facts (semantic meaning)

| Primitive | Purpose |
|-----------|---------|
| Fact | kind + ts + data (atomic semantic unit) |
| Verdict | status + code (final authoritative outcome) |
| FactKind | log, progress, metric, artifact, input |

### ticks (temporal flow)

| Primitive | Purpose |
|-----------|---------|
| Tick | timestamp + payload (atomic moment) |
| Store | append-only log |
| Stream | fan-out to consumers |
| Projection | `(State, Tick) → State` fold |
| Tailer | offset-tracking reader |

### forms (shape contracts)

| Primitive | Purpose |
|-----------|---------|
| Field | name + type (atomic slot) |
| Form | collection of fields + folds |
| Fold | upsert, latest, collect, count, sum |

### cells (spatial display)

| Primitive | Purpose |
|-----------|---------|
| Cell | char + style (atomic position) |
| Block | 2D rectangle of cells |
| Buffer | mutable grid |
| Lens | (state, zoom) → Block |

## What This Enables

1. **Standalone or composed** - each library works alone or together
2. **Scoped by identity** - peers cascade boundaries through everything
3. **No custom projection code** - forms fold ops cover 90% of cases
4. **No custom render code** - cells shape conventions handle it
5. **Replay** - ticks Store gives you time travel
6. **Hot reload** - change form, see result immediately
7. **Agent-friendly** - simple enough for agents to wire up

## Repository Locations

| Library | Repository | Status |
|---------|------------|--------|
| peers | TBD | Conceptual |
| facts | ~/Code/ev | Aliases added |
| ticks | ~/Code/rill | Renamed |
| forms | ~/Code/experiments/forms | Extracted |
| cells | ~/Code/cells | Active |
