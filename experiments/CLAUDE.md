# Project: experiments

Spec-driven data contracts for homelab monitoring. See `docs/SPEC_DRIVEN.md` for the conceptual foundation.

## Architecture

```
rill (primitives)     →  framework (specs + orchestration)  →  apps (dashboards)
Stream, Projection       KDL parsing, SSH, collectors          homelab.py
FileWriter, Tailer       SpecProjection, fold ops              cells rendering
```

**Core insight:** We're not doing config-driven UI. We're doing **spec-driven data contracts** where rendering is a convention layer on top of projected state.

## Spec-Driven Principles

1. **Spec is source of truth** — KDL specs declare event shapes, state shapes, fold ops. Code interprets specs.
2. **Projection is the primitive** — all derived state comes from folding events. No other state mutation.
3. **Rendering is convention** — state shape implies UI (dict→table, list→scrolling). No custom render code per projection.
4. **Validation at boundaries** — check events on ingest against EventSpec. Reject or log violations.
5. **Hot-reload by default** — specs are files, SpecWatcher enables edit-and-see.

## Package Boundaries

| Package | Imports from | Provides |
|---------|--------------|----------|
| `rill` | stdlib only | Stream, Projection, Tailer, FileWriter |
| `cells` | stdlib + wcwidth | RenderApp, Block, Style, components |
| `framework` | rill, kdl-py, asyncssh | SpecProjection, AppSpec, SSH, collectors |
| `apps` | rill, cells, framework | Runnable dashboards |

Apps import primitives from `rill`, spec layer from `framework`. No re-exports.

## Conventions

- Events flow through typed Streams (or Tailer for file-based)
- Projections fold events into derived state via declared fold ops
- Collectors emit to streams, persistence is a tap concern (FileWriter)
- Side effects only at boundaries (FileWriter, SSH)
- KDL for specs, Python for logic, cells for rendering
