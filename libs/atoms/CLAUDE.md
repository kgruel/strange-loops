# atoms — the data layer

Observations, contracts, and ingress.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  lang (grammar)  →  apps (CLI)
Fact, Spec        Tick, Vertex         .loop/.vertex      loops emit/status
```

Above: `libs/engine/` runs facts through vertices. `apps/loops/` provides the CLI. When you `loops emit project decision topic=auth ...`, it creates a Fact, resolves a Vertex, calls `vertex.receive()`.

## Current reference

```bash
loops fold docs --kind contract --plain    # API contracts (Fact, Spec, Parse, Source, Boundary)
loops fold docs --kind convention --plain  # invariants (frozen types, pure apply, zero deps)
loops fold docs --kind guide --plain       # progressive workflow (observe → accumulate → shape → ingest)
loops fold docs --kind vocab --plain       # fold/parse/boundary vocabulary (30 primitives)
loops fold docs -v --plain                 # everything at detailed zoom
```

The docs vertex holds living documentation — contracts, conventions, guides, and vocabulary accumulate as facts. See `~/.config/loops/docs/` for the vertex, `~/.config/loops/lenses/docs.py` for the lens.

## Build & test

```bash
uv run --package atoms pytest libs/atoms/tests
uv run --package atoms pytest libs/atoms/tests/test_fold_typed.py  # single file
```

## Decisions

Query project-specific atoms decisions:
```bash
loops stream project --kind decision --plain | grep atoms/
```
