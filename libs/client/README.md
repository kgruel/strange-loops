# client — Loops Apex Composition Library

`client` is the headless composition layer uniting `engine`, `custody`, `lang`, `store`, `atoms`, and `sign` into unified, typed operations.

## Capabilities

- **`read_target(target, ...)`**: Non-destructive target probing, preflight verification, inventory statistics, bounded fact queries, and folded state extraction.
- **`emit_fact(target, kind, payload, ...)`**: Validated fact emission with declared observer admission checks and committed-row signature attestation.
- **`add_kind(vertex_path, ...)`**: AST-verified declarative KDL mutations with transactional declaration update ceremonies (plan, apply, recover).

## Guarantees

- **No presentation logic:** Returns pure typed dataclasses; does not render terminal styling or parse CLI flags.
- **Transport agnostic:** Used equally by `cli/`, `apps/tui/`, `apps/tasks/`, and external Python scripts/services.
