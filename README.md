# loops

Observation-feedback systems. Facts flow in, ticks come out.

## The Model

Three atoms:

| Atom | Structure | Question |
|------|-----------|----------|
| **Fact** | kind + ts + payload + observer | What happened? |
| **Spec** | fields + folds + boundary | How does state accumulate? |
| **Tick** | name + ts + payload + origin | What did a cycle become? |

See [LOOPS.md](LOOPS.md) for the fundamental model.

## Libraries

| Library | Purpose |
|---------|---------|
| **atoms** | Observation + Contract + Ingress: Fact, Spec, Source, Parse, Fold |
| **vertex** | Runtime + Identity: Tick, Vertex, Loop, Store, Grant |
| **lang** | DSL parser: `.loop`/`.vertex` files → runtime types |
| **cells** | Terminal surface: Cell, Block, Buffer, Lens, Surface |

## Setup

```bash
uv sync
```

## Test

```bash
uv run --package atoms pytest libs/atoms/tests
uv run --package vertex pytest libs/vertex/tests
uv run --package lang pytest libs/lang/tests
uv run --package cells pytest libs/cells/tests
```

## Documentation

| Doc | Focus |
|-----|-------|
| [LOOPS.md](LOOPS.md) | Fundamental model — truths, atoms, data flow |
| [VOCABULARY.md](VOCABULARY.md) | Canonical definitions |
| [docs/VERTEX.md](docs/VERTEX.md) | Routing, folding, branching |
| [docs/TEMPORAL.md](docs/TEMPORAL.md) | Boundaries and nesting |
| [docs/PERSISTENCE.md](docs/PERSISTENCE.md) | Durable state, replay |
| [docs/IDENTITY.md](docs/IDENTITY.md) | Observer and gating |

## Structure

```
libs/
  atoms/      Fact, Spec, Source, Parse ops, Fold ops
  vertex/     Tick, Vertex, Store, Grant
  lang/       .loop/.vertex parser and CLI
  cells/      Terminal UI framework

experiments/ Integration layer — wires libs together
docs/        Deep-dive documentation
```
