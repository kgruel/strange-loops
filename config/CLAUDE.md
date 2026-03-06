# ~/.config/loops/

User-level loops configuration. Most work resolves here — declaring vertices, writing lenses, wiring hooks. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
vertices, lenses     emit/status/fold    Vertex, Store        Fact, Spec
```

Below: `apps/loops/` is the CLI that reads these declarations. `libs/engine/` runs vertex programs. `libs/atoms/` defines data primitives. `libs/painted/` renders everything.

---

## Level 0 — Use the system

**Trigger**: I need to query, emit, or check on something.

```bash
# What vertices exist?
loops vertices                           # all discovered vertices
loops vertices -v                        # with store paths and kinds

# Query a vertex
loops fold meta                          # current folded state
loops fold project --kind decision       # just decisions
loops stream meta --kind thread          # event history
loops fold comms --lens comms            # domain lens rendering

# Emit a fact
loops emit project decision topic="auth" "JWT over sessions"
loops emit meta thread name="store-ops" status="open"

# Session orientation
loops fold project --lens state          # tasks, threads, recent decisions
```

The 15 vertices here cover: identity, meta (cross-cutting decisions), project (per-repo architecture), comms (discord + native messaging), reading (RSS feeds), economy (FRED data), system (machine monitoring), homelab, ambient (browsing traces), session, and more.

**Don't reach for yet**: Lens authoring, vertex declarations, hooks.

---

## Level 1 — Customize rendering

**Trigger**: The default fold view doesn't show what I need, or I want a domain-specific lens.

**The contract** — a lens is a pure function:

```python
def fold_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render folded vertex state."""

def stream_view(data: dict, zoom: Zoom, width: int | None) -> Block:
    """Render event stream."""
```

No IO, no store access. Lens receives data, returns a Block.

**What you receive** (`FoldState` from atoms):

```python
data.sections      # tuple[FoldSection, ...] — one per kind
section.kind       # "decision", "thread", "message", etc.
section.items      # tuple[FoldItem, ...] — folded results
section.fold_type  # "by" (keyed upsert) or "collect" (bounded list)
section.key_field  # for "by" folds: the grouping key name

item.payload       # dict — domain content
item.ts            # float | None — epoch seconds
item.observer      # str — who emitted
item.id            # str | None — source fact ULID
```

**Zoom levels** — every lens renders at four levels:

| Zoom | Intent | Example |
|------|--------|---------|
| MINIMAL | One line, counts | `12 messages (discord, 5m)` |
| SUMMARY | Orient without drowning | Author + content snippet |
| DETAILED | Everything visible | + timestamps, secondary fields |
| FULL | All fields, no truncation | + observer, ULID, all metadata |

**Writing a lens** (place in `~/.config/loops/lenses/`):

```python
# ~/.config/loops/lenses/my_lens.py
from painted import Block, Style, Zoom, join_vertical

def fold_view(data, zoom, width):
    plain = Style()
    rows = []
    for section in data.sections:
        label = section.key_field or section.kind
        for item in section.items:
            key = item.payload.get(label, "?")
            rows.append(Block.text(f"  {key}", plain))
    return join_vertical(*rows) if rows else Block.text("(empty)", plain)
```

Usage: `loops fold meta --lens my_lens`

**Key patterns** from existing lenses:
- Drive from metadata (`section.key_field`, `section.fold_type`), not `if kind == "decision":`
- Progressive disclosure via `zoom`, not separate code paths
- `width=None` means piped — no truncation, no padding

**Resolution chain** (first match wins):
1. `--lens` CLI flag
2. Vertex `lens {}` declaration
3. Vertex-local: `<vertex_dir>/lenses/<name>.py`
4. Project-local: `<cwd>/lenses/<name>.py`
5. **User-global: `~/.config/loops/lenses/<name>.py`** — you are here
6. Built-in: `loops.lenses.<name>`

**Current user-global lenses:**
- `comms` — messaging vertices. Author/content extraction, self-scoping, delta rendering.
- `state` — session orientation. Tasks by priority, open threads, recent decisions.

**Don't reach for yet**: Vertex declarations, source wiring, hooks.

---

## Level 2 — Add a domain

**Trigger**: I want to track a new kind of data — a new attention surface.

A vertex is a KDL file that declares what data looks like and where it lives:

```kdl
// ~/.config/loops/mydomain/mydomain.vertex
name "mydomain"
store "./data/mydomain.db"

loops {
  // Each block declares a fact kind and how it folds
  item {
    fold {
      items "by" "name"        // keyed upsert — latest per name
    }
  }
  event {
    fold {
      items "collect" 50       // bounded list — keep last 50
      count "inc"              // running count
      updated "latest"         // timestamp of most recent
    }
  }
}
```

**Two vertex kinds:**

| Kind | Has | Purpose |
|------|-----|---------|
| Instance | `store`, `loops` | Holds data. Has a SQLite db. |
| Aggregation | `combine`, `discover` | Collects instances. No own store. |

**Instance vertex** — the common case:

```kdl
name "reading"
store "./data/reading.db"

loops {
  item { fold { items "by" "link" } }
}
```

**Aggregation vertex** — combines multiple stores:

```kdl
name "comms"
combine {
  vertex "./discord/discord.vertex"
  vertex "./native/native.vertex"
}
```

**Fold vocabulary** (declared in `fold {}` blocks):

| Declaration | Fold op | What it does |
|------------|---------|-------------|
| `items "by" "field"` | Upsert | Latest per key field |
| `items "collect" N` | Collect | Keep last N (0 = unbounded) |
| `count "inc"` | Count | Running counter |
| `updated "latest"` | Latest | Most recent timestamp |

**Sources** — external data ingestion:

```kdl
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"        // one instance per line
    loop {
      fold { items "by" "link" }
      boundary when="{{kind}}.complete"
    }
  }
}
```

Sources run shell commands, parse output, emit facts. See `libs/atoms/` Level 3 for the Source primitive. `.loop` files declare the command + parse pipeline.

**Discovery** — find nested vertices:

```kdl
discover "./**/*.vertex"    // glob for child vertices
```

The root `.vertex` here uses this to find all 15 domain vertices.

**Don't reach for yet**: Observer declarations, combine override semantics, hooks.

---

## Level 3 — Infrastructure

**Trigger**: I need to control observer access, wire session hooks, or understand combine semantics.

**Observer declarations:**

```kdl
observers {
  kyle { }
  loops-claude { }
  meta-claude { }
}
```

Observers declared on a vertex (or any vertex in its combine chain) can emit to it. `loops whoami` resolves the current observer from the workspace `.vertex` chain. `LOOPS_OBSERVER` is exported so emits are tagged automatically.

**Observer cascade**: Aggregation vertices inherit observers from their source vertices. If `discord.vertex` declares `alcove`, then `comms.vertex` (which combines discord) also accepts alcove's emits.

**Combine semantics**: When an aggregation vertex declares its own `loops {}` blocks, they override the source vertex's fold declarations for that kind. The aggregation controls how combined data folds.

**Hooks** (Claude Code `.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [{ "command": "..." }],
    "SessionEnd": [{ "command": "..." }]
  }
}
```

Hooks compose CLI commands — `loops fold`, `loops emit`. No new infrastructure. The pickup script (`pickup.zsh`) reads the full fold before session start and injects it as `--system-prompt`.

**Lens declarations** (vertex-level):

```kdl
lens {
  fold "prompt"    // use prompt lens for fold rendering
}
```

Vertex can declare which lens to use by default, overriding the resolution chain tiers 3-6.

---

## Structure

```
.vertex              Root — discovers all vertices, declares global observers
lenses/              Custom lenses (user-global tier in resolution chain)
  comms.py           Messaging lens — author/content, self-scoping
  state.py           Session orientation — tasks, threads, decisions
identity/            Observer self-knowledge (self, principles, observations)
comms/               Unified comms (combines discord + native)
discord/             Discord bridge (messages via webhook/bot)
meta/                Cross-cutting decisions (combines project metas)
project/             Per-repo architecture (combines project instances)
session/             Session state
reading/             RSS feeds + reaction traces
economy/             FRED economic indicators
system/              Local machine monitoring
homelab/             Per-VM agent pattern
ambient/             Passive attention traces (browsing, screen time)
messaging/           Direct messaging
dev/                 Development checks
realestate/          Real estate data
```

## Abstraction reference

This config layer consumes the loops monorepo libraries:

```
atoms    →  FoldState, FoldSection, FoldItem (data shapes lenses receive)
engine   →  vertex_fold, vertex_read (how data is computed before lenses see it)
painted  →  Block, Style, Zoom (how lenses produce output)
lang     →  .vertex declarations (fold specs, lens declarations, observer grants)
loops    →  CLI commands, built-in lenses, lens resolver (the app that wires it all)
```

See `~/Code/loops/CLAUDE.md` for the monorepo. Each lib has its own CLAUDE.md.
