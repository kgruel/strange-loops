# Declaration, Scaffolding and Target Discovery in Loops

The `libs/sdk` library provides headless operations to scaffold, inspect, mutate, and discover Loops vertices and targets.

Every declaration mutation is orchestrated through a two-phase atomic ceremony that generates deterministic AST diffs, persists intent logs, commits signed genesis/declaration facts, and updates generation fingerprints.

---

## 1. API Reference Overview

```python
from sdk import (
    init_vertex,
    inspect_declaration,
    discover_targets,
    add_kind,
    edit_kind,
    remove_kind,
    grant_observer,
    revoke_observer,
    recover_ceremony,
)
```

| Operation | Purpose | Return Model |
| :--- | :--- | :--- |
| **`init_vertex`** | Scaffolds a new `.vertex` declaration and initializes storage directories. | `InitVertexResult` |
| **`inspect_declaration`** | Deeply inspects and validates a `.vertex` file without side effects. | `DeclarationInspectionResult` |
| **`discover_targets`** | Traverses a directory to discover all `.vertex` files and bare stores. | `list[TargetInfo]` |
| **`add_kind`** | Declares a new loop-kind and executes a declaration ceremony. | `KindMutationResult` |
| **`edit_kind`** | Modifies an existing loop-kind fold definition via ceremony. | `KindMutationResult` |
| **`remove_kind`** | Removes an existing loop-kind definition via ceremony. | `KindMutationResult` |
| **`grant_observer`** | Adds or updates observer capability grants in the admission block. | `KindMutationResult` |
| **`revoke_observer`** | Removes an observer from the declared admission block. | `KindMutationResult` |
| **`recover_ceremony`** | Resumes or rolls back an interrupted `.vertex.intent` ceremony file. | `KindMutationResult \| None` |

---

## 2. Vertex Scaffolding (`init_vertex`)

Initialize a standalone vertex or an aggregate root discovery vertex:

```python
from sdk import init_vertex

# Scaffolding a standalone vertex with SQLite backing store
res = init_vertex("app.vertex", name="my_app", store_type="sqlite", observer="alice")
print(f"Created vertex: {res.target_path} (store: {res.store_path})")

# Scaffolding a root aggregate vertex that discovers all nested vertices
root_res = init_vertex("root.vertex", is_root=True)
print(f"Created root discovery vertex: {root_res.target_path}")
```

---

## 3. Declaration Inspection (`inspect_declaration`)

Examine declared stream kinds, admission rules, and observer permissions:

```python
from sdk import inspect_declaration

info = inspect_declaration("app.vertex")
print(f"Vertex: {info.name} (status: {info.status})")
print(f"Store: {info.store_mode} at {info.store_path}")
print(f"Declared kinds: {info.declared_kinds}")
print(f"Declared observers: {info.declared_observers}")
print(f"Strict mode: {info.strict}")
```

---

## 4. Workspace Target Discovery (`discover_targets`)

Find all Loops targets within a repository:

```python
from sdk import discover_targets

targets = discover_targets(".", recursive=True)
for t in targets:
    print(f"Found {t.target_type} at {t.target_path} (mode: {t.canonical_mode})")
```

---

## 5. Kind & Observer Mutation Ceremonies

All declaration mutations use atomic, signed ceremonies:

### Adding and Editing Kinds
```python
from sdk import add_kind, edit_kind, remove_kind
from lang.ast import LoopDef, FoldDecl, FoldCollect

# Add new kind with default 'collect 100'
add_kind("app.vertex", "task", observer="admin")

# Edit existing kind
edit_kind(
    "app.vertex",
    "task",
    LoopDef(folds=(FoldDecl("items", FoldCollect(500)),)),
    observer="admin",
)

# Remove kind
remove_kind("app.vertex", "task", observer="admin")
```

### Managing Observer Grants
```python
from sdk import grant_observer, revoke_observer

# Grant 'alice' permission to emit 'task' and 'note' kinds
grant_observer("app.vertex", "alice", grants=["task", "note"], observer="admin")

# Revoke observer permissions
revoke_observer("app.vertex", "alice", observer="admin")
```

---

## 6. Result Models

| Model | Schema | Key Fields |
| :--- | :--- | :--- |
| **`InitVertexResult`** | `loops.cli/init-vertex/v1` | `target_path`, `name`, `store_path`, `store_type`, `is_root`, `file_written` |
| **`DeclarationInspectionResult`** | `loops.cli/declaration-inspection/v1` | `target_path`, `name`, `status`, `store_mode`, `store_path`, `declared_kinds`, `declared_observers`, `cadence_ticks`, `strict`, `is_aggregate`, `syntax_valid`, `errors` |
| **`KindMutationResult`** | `loops.cli/kind-mutation/v1` | `status`, `reason`, `mode`, `vertex_path`, `generation_before`, `generation_after`, `changes`, `file_written` |
