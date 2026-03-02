# HANDOFF

Cold-start orientation for the loops monorepo. State lives in the stores; this document tells you where to look.

## Start here

```bash
loops status project          # project decisions, threads, tasks
loops status meta             # cross-cutting decisions (ways of working)
loops log project --since 7d  # recent project activity
```

Read `CLAUDE.md` for build commands and structure. Read `LOOPS.md` for the fundamental model.

## Current focus

**Progressive CLAUDE.md system** — applying the painted library's progressive discovery pattern to the monorepo. Each lib and app gets a CLAUDE.md with escalation levels, triggers, and "don't reach for yet" barriers. The document is the lens; the vertex store is the state.

Completed:
- Root `CLAUDE.md` — rewritten as monorepo orientation (pointer to LOOPS.md, build, structure, both stores)
- `libs/atoms/CLAUDE.md` — 4 levels: Observe (Fact), Accumulate (Spec+Fold), Shape (Parse), Ingest (Source+Runner). Semantic-first examples.
- `project.vertex` — established as project-specific knowledge store (renamed from session.vertex). Symlinked at `~/.config/loops/project` for global access.
- Vertex template system merged — slashed name resolution, `loops init` with config registration, aggregation vertices with discover pattern.

Next:
- `libs/engine/CLAUDE.md` — Tick, Vertex, Store, Projection, Peer, Grant. Deep dives (VERTEX.md, TEMPORAL.md, PERSISTENCE.md, IDENTITY.md) become reference layer.
- `libs/lang/CLAUDE.md` — KDL grammar, .loop/.vertex files, validation.
- `libs/painted/` — already has progressive CLAUDE.md, may need alignment pass.
- `libs/store/CLAUDE.md` — slice, merge, search, transport.

## Active apps

| App | What it does | Status |
|-----|-------------|--------|
| `apps/loops` | CLI for the loops system — emit, log, status, store, validate, run | 191 tests, full painted rendering |
| `apps/hlab` | Homelab monitoring — DSL-driven status, alerts, media | Working, 3 DSL commands |
| `apps/strange-loops` | Task orchestration — tasks as loops, workers in worktrees | 56 tests, full lifecycle working |
| `apps/reader` | Feed reader — RSS/Atom ingestion | Working |
| `apps/discord` | Discord transport | Scaffold |
| `apps/telegram` | Telegram transport | Working |

## Key architectural threads

Query open threads: `loops log meta --kind thread`

Active design threads from meta store:
- **vertex-template-init** — template instantiation, local+global registration, distributed stores
- **scaffold-as-ticks** — scaffold elements as derived ticks
- **attention-filter** — decision-tree scoring over fact streams
- **transport-protocols** — push/pull/sync between stores

## Stores

| Store | Location | What it holds |
|-------|----------|--------------|
| Project | `./project.vertex` → `data/project.db` | Loops-specific decisions, threads, tasks |
| Meta | `~/Documents/meta-discussion` | Cross-cutting patterns, ways of working (65 decisions, 19 threads) |
| Tasks | `./data/tasks.db` | Strange-loops task orchestration data |

## Session log

This handoff is a snapshot. For full session history, query the stores:

```bash
loops log project --kind decision        # what was decided
loops log meta --kind decision --since 7d  # recent cross-cutting decisions
```
