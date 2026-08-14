# client — Apex Composition Library

The single composition point for loops substrate operations (`read`, `emit`, `kind_add`).

## Owns

- High-level headless operations over targets:
  - `read_summary`, `read_facts`, `read_state`, `read_ticks`, `read_fact_by_id`
  - `emit_fact`
  - `add_kind`
- Typed result models and error taxonomy for client consumers (`ReadSummary`, `EmitReceipt`, `FactPageResult`, `KindMutationResult`).
- Composition of `engine.probe`, `engine.preflight`, `engine.ceremony`, `engine.store_reader`, `engine.admission`, `custody.CredentialProvider`, and `lang.vertex_mutation`.

## Boundaries

- Depends on all substrate libs: `atoms`, `custody`, `engine`, `lang`, `sign`, `store`.
- Shipped presentation layers (`cli/`, `apps/*`) consume `client` rather than composing `libs/*` by hand.
- Zero CLI flag parsing or terminal formatting owned here.

## Tests

- Direct unit and integration tests under `libs/client/tests/`.
