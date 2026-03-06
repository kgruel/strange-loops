# siftd — conversation search and analytics

Conversation exchanges as facts. Search, tag, and analyze CLI coding sessions. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
loops CLI (host)  →  siftd (plugin)  →  engine (runtime)  →  atoms (data)
loops siftd ...      lens, feedback     vertex_search        Fact, FTS5
```

siftd is NOT a standalone CLI — it registers into the loops CLI as a plugin. Vertex template, lens, and feedback handlers all wire through loops.

Below: `libs/engine/` provides `vertex_read`, `vertex_search`, `vertex_facts`. `libs/painted/` renders all display output.

---

## Level 0 — Use it

**Trigger**: I need to search or browse past coding sessions.

```bash
loops init siftd                              # create siftd vertex + data dir
loops siftd search "vertex template design"   # FTS5 search over exchanges
loops siftd status                            # kind counts, freshness, recent activity
loops siftd log --since 7d                    # recent exchanges chronologically
loops siftd tag architecture --conversation abc123  # tag a conversation
```

Common flags: `-q` (minimal), `-v` (detailed), `-vv` (full), `--json`, `--plain`.

Data arrives via adapter scripts (separate from this app) or `loops emit exchange ...`.

**Don't reach for yet**: Lens internals, feedback handlers, vertex declaration.

---

## Level 1 — Configure, don't code

**Trigger**: I need to change how siftd data is indexed, searched, or displayed.

**siftd's vertex declaration lives in the loops app** (`_TEMPLATES["siftd"]` in `apps/loops/main.py`). It defines:
- `exchange` kind — folded `by conversation_id`, FTS5 searchable on `prompt` + `response`
- `tag` kind — folded `by name`

Before modifying siftd source, check whether what you need is:
- **Different search fields** — change the `search` declaration in the vertex template
- **Different fold behavior** — change the `fold` block in the vertex template
- **Different display** — the `siftd_lens` in `lens.py` controls rendering. Same contract as all lenses: `(data, zoom, width) -> Block`

**Don't reach for yet**: Feedback handler implementation, adapter internals.

---

## Level 2 — Understand the architecture

**Trigger**: I need to modify siftd's behavior or understand how it plugs into loops.

**Four registration points** in the loops CLI:

| Registration | What | Where |
|-------------|------|-------|
| `_TEMPLATES["siftd"]` | Vertex template for `loops init siftd` | `apps/loops/main.py` |
| `_APPS["siftd"]` | App dispatch for `loops siftd <cmd>` | `apps/loops/main.py` |
| `siftd_lens` | PayloadLens for exchange/tag rendering | `apps/siftd/lens.py` |
| `tag_handler` | Feedback handler — emits tag facts | `apps/siftd/feedback.py` |

**Two fact kinds:**
- `exchange` — one per prompt/response pair. Folded `by conversation_id`. FTS5 searchable on `prompt` + `response`.
- `tag` — labels on conversations. Folded `by name`.

**Key concept mapping:**

| Concept | Loops equivalent |
|---------|-----------------|
| Conversation | Group of exchange facts sharing `conversation_id` |
| Search | `vertex_search()` with FTS5 index |
| Status | `vertex_read()` fold state |
| Log | `vertex_facts()` time range |
| Tag | Fact on the wire (action-on-the-loop) |

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
loops siftd search "query"
  → vertex_search(store, query) — FTS5 MATCH
  → Returns ranked facts with snippets
  → siftd_lens renders at zoom level
```

**Tag flow (feedback):**
```
loops siftd tag <name> --conversation <id>
  → tag_handler emits tag fact
  → Fold accumulates by tag name
  → Tags are queryable alongside exchanges
```

---

## Key conventions

- siftd is a plugin, not standalone. All CLI surface is via loops.
- Exchange facts are append-only. Conversations grow by accumulation.
- FTS5 search is declared in the vertex, not coded in Python.
- Adapters are independent scripts — one per external tool.

## Build & test

```bash
./dev check                                                  # CI gate (when dev script exists)
uv run --package siftd-loops pytest apps/siftd/tests         # from monorepo root
```
