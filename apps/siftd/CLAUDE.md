# siftd — conversation search and analytics

Conversation exchanges as facts. Search, tag, and analyze CLI coding sessions. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
siftd.vertex         read/emit/search    vertex_search        Fact, FTS5
```

siftd is a pure-config vertex — no app dispatch, no custom CLI commands. All operations use standard loops verbs. Domain logic lives in the source parser, fold lens, and PayloadLens.

Below: `libs/engine/` provides `vertex_read`, `vertex_search`, `vertex_facts`. `libs/painted/` renders all display output.

---

## Level 0 — Use it

**Trigger**: I need to search or browse past coding sessions.

```bash
loops init --template siftd                   # create local siftd vertex
loops read siftd                              # fold state (conversations, tags)
loops read siftd --facts --since 7d           # recent exchanges chronologically
loops read siftd --facts "vertex templates"   # FTS5 search over exchanges
loops emit siftd tag name=architecture conversation_id=abc123  # tag a conversation
```

Common flags: `-q` (minimal), `-v` (detailed), `-vv` (full), `--json`, `--plain`.

Data arrives via adapter scripts (separate from this app) or `loops emit siftd exchange ...`.

**Don't reach for yet**: Lens internals, source adapters, vertex declaration.

---

## Level 1 — Configure, don't code

**Trigger**: I need to change how siftd data is indexed, searched, or displayed.

**siftd uses harness topology** — an aggregation vertex combining harness-specific children:
- `config/siftd/siftd.vertex` — aggregation (combine, no own store)
- `config/siftd/claude-code/claude-code.vertex` — instance (store, sources)

Both declare the same kinds:
- `exchange` kind — folded `by conversation_id`, FTS5 searchable on `prompt` + `response`
- `tag` kind — folded `by name`

Before modifying siftd source, check whether what you need is:
- **Different search fields** — change the `search` declaration in both vertex files
- **Different fold behavior** — change the `fold` block (aggregation overrides instance)
- **Different display** — the fold lens at `config/siftd/lenses/fold.py` renders fold state. The PayloadLens in `lens.py` renders individual facts in stream view.

**Don't reach for yet**: Source adapter implementation, feedback handler internals.

---

## Level 2 — Understand the architecture

**Trigger**: I need to modify siftd's behavior or understand how it plugs into loops.

**Configuration files** (in `config/siftd/`):

| File | What |
|------|------|
| `siftd.vertex` | Aggregation vertex — combines children, overrides folds |
| `claude-code/claude-code.vertex` | Instance vertex — store, sources, kind declarations |
| `claude-code/sources/claude-code.loop` | Source declaration — points to adapter script |
| `lenses/fold.py` | Custom fold lens — domain-aware rendering of FoldState |

**Domain logic** (in `apps/siftd/src/siftd_loops/`):

| File | What |
|------|------|
| `sources/claude_code.py` | Source adapter — discovers JSONL sessions, emits exchange facts |
| `lens.py` | PayloadLens for exchange/tag rendering + status/log/search views |
| `feedback.py` | Tag handler — emits tag facts (used by feedback system) |

**Two fact kinds:**
- `exchange` — one per prompt/response pair. Folded `by conversation_id`. FTS5 searchable on `prompt` + `response`.
- `tag` — labels on conversations. Folded `by name`.

**Key concept mapping:**

| Concept | Loops equivalent |
|---------|-----------------|
| Conversation | Group of exchange facts sharing `conversation_id` |
| Search | `loops read siftd --facts "query"` → `vertex_search()` with FTS5 |
| Status | `loops read siftd` → fold state via generic read |
| Log | `loops read siftd --facts --since 7d` → `vertex_facts()` time range |
| Tag | `loops emit siftd tag name=X conversation_id=Y` |

**Adapter sources** (in `src/siftd_loops/sources/`) ingest conversations from external tools. Each adapter parses a tool's conversation format into exchange facts. Adapters are independent — adding a new one doesn't change siftd's core.

---

## Level 3 — Data pipeline

**Trigger**: I need to understand how conversations flow from external tools to searchable facts.

**Ingestion flow:**
```
External tool (Claude Code, etc.)
  → Adapter script parses conversation format
  → Emits exchange facts with conversation_id, prompt, response
  → Vertex receives, FTS5 indexes prompt + response fields
  → Fold accumulates by conversation_id (latest exchange per conversation)
```

**Search flow:**
```
loops read siftd --facts "query"
  → fetch_stream → vertex_search(store, query) — FTS5 MATCH
  → Returns ranked facts with snippets
  → Stream lens renders at zoom level
```

**Tag flow:**
```
loops emit siftd tag name=architecture conversation_id=abc123
  → cmd_emit → vertex.receive(tag fact)
  → Fold accumulates by tag name
  → Tags are queryable alongside exchanges
```

---

## Key conventions

- siftd is a pure-config vertex. No app dispatch — all CLI surface is standard loops verbs.
- Exchange facts are append-only. Conversations grow by accumulation.
- FTS5 search is declared in the vertex, not coded in Python.
- Adapters are independent scripts — one per external tool.
- Source dedup is managed by the adapter via manifest files, not by the vertex.

## Build & test

```bash
./dev check                                                  # CI gate (when dev script exists)
uv run --package siftd-loops pytest apps/siftd/tests         # from monorepo root
```
