# client — Apex Composition Library

The single composition point for loops substrate operations (`resolve_target`, `read_*`, `emit_fact`, `add_kind`, `edit_kind`, `remove_kind`, `recover_ceremony`).

## Owns

- High-level headless operations over targets:
  - `resolve_target`
  - `read_summary`, `read_facts`, `read_state`, `read_ticks`, `read_fact_by_id`
  - `emit_fact`
  - `add_kind`, `edit_kind`, `remove_kind`, `recover_ceremony`
- Typed result models and error taxonomy for client consumers (`ReadSummary`, `EmitReceipt`, `FactPageResult`, `FoldStateResult`, `KindMutationResult`).
- Composition of `engine.probe`, `engine.preflight`, `engine.ceremony`, `engine.store_reader`, `engine.admission`, `custody.CredentialProvider`, and `lang.vertex_mutation`.

## Boundaries

- **Upstream Dependencies**: `atoms`, `custody`, `engine`, `lang`, `sign`, `store`.
- **Downstream Consumers**: Presentation layers (`apps/loops`, TUI, external tools/agents) must consume `client` rather than composing substrate libraries directly.
- **Invariants**: Zero CLI flag parsing or terminal ANSI escape formatting owned here.

## Testing Pyramid

Run tests via `uv`:
```bash
uv run --package client pytest libs/client/tests
```

- **Unit & Contract Layer**: `test_target.py`, `test_types.py`
- **Integration & Composition Layer**: `test_read.py`, `test_emit.py`, `test_kind.py`, `test_smoke.py`
- **Property & Invariant Layer (Hypothesis)**: `test_properties_client.py`
