# Grounding

How to get oriented in this project and re-establish context.

## Genesis

```
hlab (exploration)
  ↓ patterns emerged
experiments (proving ground)
  ↓ extracted what stabilized
ticks (libs/ticks) — streaming primitives, stdlib only
cells (libs/cells) — TUI rendering, composition-first
```

**The question that started this:** How do I monitor my homelab without adopting heavyweight infrastructure?

**The answer that emerged:** File-based event streams + declarative projections + convention-based rendering.

## The Three Packages

| Package | What | Where |
|---------|------|-------|
| **ticks** | Stream, Projection, Tailer, FileWriter | `libs/ticks` |
| **cells** | RenderApp, Block, Style, components | `libs/cells` |
| **experiments** | Spec layer, orchestration, homelab app | `experiments/` |

**ticks** and **cells** are general-purpose. **experiments** is the integration point where domain-specific work happens (homelab monitoring, KDL specs, SSH collection).

## The Thesis

**Spec-driven data contracts**, not config-driven UI.

- Specs declare event shapes, state shapes, fold ops
- Rendering derives from state shapes via conventions
- The spec is the source of truth

See `docs/SPEC_DRIVEN.md` for the full conceptual foundation.

## Key Files to Read

To re-ground quickly:

1. **`CLAUDE.md`** — principles and package boundaries
2. **`docs/SPEC_DRIVEN.md`** — the conceptual model
3. **`apps/README.md`** — what the homelab app does
4. **`specs/vm-health.projection.kdl`** — example spec (event + state + fold)

To understand the code:

1. **`framework/spec.py`** — KDL parsing, SpecProjection, validation
2. **`framework/ssh.py`** — SSHConnectionManager (the actual collection)
3. **`apps/homelab.py`** — the dashboard app

## Running Things

```bash
# Generate test events
uv run python apps/simulate_homelab.py

# Run dashboard against test events
uv run python apps/homelab.py --source /tmp/homelab

# Run dashboard against real VMs (needs SSH access)
uv run python apps/homelab.py

# Run tests
uv run pytest tests/ -v
```

## Current State (as of last session)

**Working:**
- KDL spec parsing (event, state, fold)
- Event validation + type coercion
- Fold ops: upsert, collect, latest, count
- Tailer-based consumption (JSONL files)
- Hot-reload via SpecWatcher
- 41 tests passing

**Known gaps:**
- SSHConnectionManager has hardcoded collectors (doesn't use collector registry)
- Single event type per projection (first iteration)
- No state persistence (memory only)
- SSH spawns subprocess per command (not multiplexed)

**Deferred:**
- Collector registry wiring
- State snapshots / replay
- SSH connection pooling

## Parallel Work

**cells** is being developed in parallel, iterating on TUI primitives. The two projects inform each other:
- cells provides rendering primitives
- experiments provides the spec-driven consumption model
- Both are testing what a "middle ground" TUI toolkit looks like

## Using tbd for Re-grounding

`tbd` aggregates and queries prior agent conversations. Use it to recover context, find decision rationale, and trace how things evolved.

### Quick Reference

```bash
# Semantic search (embeddings + FTS5 hybrid)
tbd ask "query"

# Filter to this workspace
tbd ask -w experiments "query"

# List recent conversations in this workspace
tbd query -w experiments

# View a specific conversation
tbd query <conversation_id>

# Search with full exchange context
tbd ask --full "query"

# Rank whole conversations, not chunks
tbd ask --conversations "query"
```

### Grounding Workflow

**Step 1: Find relevant conversations**
```bash
# What conversations touched this project recently?
tbd query -w experiments -n 10

# Semantic search for key concepts
tbd ask -w experiments "spec-driven projections"
tbd ask -w experiments "validation coercion"
tbd ask -w experiments "ticks extraction"
```

**Step 2: Recover decision context**
```bash
# Why did we choose KDL?
tbd ask -w experiments --full "why KDL format"

# How did validation get designed?
tbd ask -w experiments --context 3 "event validation strategy"

# Rank conversations by relevance to a topic
tbd ask -w experiments --conversations "fold ops design"
```

**Step 3: Trace evolution**
```bash
# Sort by time to see how thinking evolved
tbd ask -w experiments --chrono "projection primitive"

# Find the earliest discussion of a concept
tbd ask -w experiments --first "spec-driven"
```

### Useful Queries for This Project

| Query | What it finds |
|-------|---------------|
| `tbd ask -w experiments "spec-driven data contracts"` | The thesis and conceptual model |
| `tbd ask -w experiments "ticks cells extraction"` | Package boundary decisions |
| `tbd ask -w experiments "fold ops upsert collect"` | Fold operation design |
| `tbd ask -w experiments "SSHConnectionManager collectors"` | Collection architecture |
| `tbd ask -w experiments "KDL validation coercion"` | Event validation decisions |
| `tbd ask -w experiments "hot reload watcher"` | Edit-and-see pattern |

### Output Modes

- `tbd ask "query"` — snippet with score, good for scanning
- `tbd ask -v "query"` — full chunk text
- `tbd ask --full "query"` — complete prompt+response exchange
- `tbd ask --context 3 "query"` — ±3 exchanges around match
- `tbd ask --thread "query"` — narrative view: top conversations expanded
- `tbd ask --conversations "query"` — rank whole conversations, not chunks

### Pattern

**tbd recovers the *why*** — decision rationale, design discussions, rejected alternatives.

**Docs/code show the *what*** — current state, implemented behavior, working examples.

Start with tbd when you need context. Move to code when you need specifics.

## Re-grounding Checklist

When picking this up after a break:

1. [ ] Query tbd for recent conversations about this project
2. [ ] Read `CLAUDE.md` for principles
3. [ ] Read `docs/SPEC_DRIVEN.md` for the thesis
4. [ ] Run `uv run pytest tests/ -v` to verify things work
5. [ ] Run the simulator + dashboard to see it in action
6. [ ] Check `apps/README.md` for current state

## Asking Good Questions

When exploring or extending:

- "What does the spec declare vs what does code do?" — spec is source of truth
- "Where does this data come from?" — trace from collector → event → projection → state
- "Why isn't X in the spec?" — probably because it's derived or convention-based
- "What breaks if I change this spec?" — hot-reload means you can just try it

## Conventions

- **Events** are dicts with declared fields (extra fields allowed)
- **State** is derived, never directly mutated outside fold ops
- **Projections** are the unit of composition (one per concern)
- **Rendering** infers UI from state shapes (no custom render code per projection)
- **Validation** happens at boundaries (on ingest, not deep in fold)
