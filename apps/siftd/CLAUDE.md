# siftd — conversation search and analytics

Conversation exchanges as facts. Search, tag, and analyze CLI coding sessions. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  siftd (app)
Fact, Spec        Vertex, Store        search/status/tag
```

Below: `libs/engine/` provides vertex_read, vertex_search, vertex_facts. `libs/painted/` renders all display output.

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

Data arrives via adapter scripts (separate from this app) or `loops emit exchange ...`.

**Don't reach for yet**: Lens internals, feedback handler implementation, vertex declaration.

---

## Level 1 — Understand the architecture

**Trigger**: I need to modify a command or understand the data model.

siftd is NOT a standalone CLI. It registers with the loops CLI:
- **Vertex template**: `_TEMPLATES["siftd"]` in loops main.py — `loops init siftd` creates the vertex
- **PayloadLens**: `siftd_lens` knows how to render exchange/tag payloads
- **Feedback handlers**: `tag_handler` emits tag facts (action-on-the-loop)
- **App dispatch**: `_APPS["siftd"]` routes `loops siftd <cmd>` to `_run_app()`

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

---

## Build & test

```bash
./dev check                                                  # CI gate (when dev script exists)
uv run --package siftd-loops pytest apps/siftd/tests         # from monorepo root
```
