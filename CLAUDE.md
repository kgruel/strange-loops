# Project: experiments

## Architecture

`framework/` — streaming event infrastructure:

- **Primitives**: Stream, EventStore, Projection, FileWriter, Forward
- **Specs**: KDL-driven projection and app specs
- **Orchestration**: SSH collectors, multi-host event gathering

See `framework/README.md` for the streaming topology.

## Conventions

- Events flow through typed Streams
- Projections fold events into derived state
- Collectors emit to streams, persistence is a tap concern
- Side effects only at boundaries (FileWriter, SSH)
