# atoms — the data layer

Observations, contracts, and ingress.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  lang (grammar)  →  apps (CLI)
Fact, Spec        Tick, Vertex         .loop/.vertex      SDK-backed JSON CLI
```

Above: `libs/engine/` runs facts through vertices. The agent-facing CLI is `apps/loops-min`, composed through the SDK. The old `apps/loops` frontend is retired.

## Current reference

See [the SDK reference](../sdk/README.md) and [JSON CLI](../../apps/loops-min/README.md).
Historical contracts and decisions remain data in their original stores;
reading them does not require restoring the retired CLI or its lenses.

## Build & test

```bash
uv run --package atoms pytest libs/atoms/tests
uv run --package atoms pytest libs/atoms/tests/test_fold_typed.py  # single file
```

## Decisions

Use SDK/JSON-client fact reads with an explicit target. Do not infer a live
store path or migrate it merely to inspect library code.
