# lang — the grammar

KDL parser for `.loop` and `.vertex` files. Pure grammar — no runtime types, no execution. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  lang (grammar)  →  apps (CLI)
Fact, Spec        Tick, Vertex         .loop/.vertex      loops validate/run
```

Below: `libs/engine/` compiles these AST types into runtime Vertices and Sources. `libs/atoms/` defines the data types that engine produces.
Above: `apps/loops/` calls `parse_vertex_file()` and `validate()` for its CLI commands.

Only external dependency: `ckdl` (KDL parser). No cross-lib imports — lang is portable.

---

## Level 0 — Parse a file

**Trigger**: I need to load a `.loop` or `.vertex` file.

```python
from lang import parse_loop_file, parse_vertex_file

loop_ast = parse_loop_file(Path("disk.loop"))
# LoopFile(command="df -h", format="lines", parse=[Split(), Pick(0, 4), ...])

vertex_ast = parse_vertex_file(Path("status.vertex"))
# VertexFile(name="status", loops=[...], sources=[...], store="./data/status.db")
```

These return frozen AST dataclasses — the complete structure of the file, ready for validation or compilation. No execution happens here.

```python
from lang import validate

validate(loop_ast)    # raises ValidationError on problems
validate(vertex_ast)  # checks routes reference defined loops, folds are valid, etc.
```

`validate()` also infers **shape** through parse pipelines (STRING → LIST → DICT), catching mismatches before runtime. Engine's compiler calls this automatically via `load_vertex_program()`.

**Don't reach for yet**: AST internals, population management, loader details.

---

## Level 1 — Understand the AST

**Trigger**: I need to inspect or manipulate the parsed structure.

**`.loop` file AST** — a source definition:

```python
LoopFile(
    command="df -h",           # shell command to run
    kind="disk",               # fact kind for output
    observer="monitor",        # who's observing
    format="lines",            # lines | json | ndjson | blob
    every=Duration(60),        # polling interval (None = one-shot)
    parse=[Split(), Pick(0, 4), Rename({0: "fs", 1: "use"})],  # shaping pipeline
    trigger=None,              # event-driven trigger kinds
)
```

**`.vertex` file AST** — the runtime configuration:

```python
VertexFile(
    name="project",
    store="./data/project.db",
    loops=[
        LoopDef(name="decision", folds=[FoldBy(target="items", key="topic")]),
        LoopDef(name="thread", folds=[FoldBy(target="items", key="name")]),
    ],
    sources=[Path("sources/disk.loop"), TemplateSource(...)],
    discover="./instances/**/*.vertex",  # glob for child vertices
    vertices=["child.vertex"],           # explicit child vertices
    routes={"disk.*": "disk"},           # pattern-based routing
)
```

The fold ops map 1:1 to atoms' fold vocabulary — `FoldBy` → `Upsert`, `FoldCollect` → `Collect`, `FoldCount` → `Count`, etc. Engine's compiler does the mapping (see `libs/engine/` compiler.py).

**Parse step types**: `Skip`, `Split`, `Pick`, `Transform` (Strip/Replace/Coerce), `Select`, `Explode`, `Project`, `Where`. These map to atoms' parse ops.

**Boundary types**: `BoundaryWhen(kind)`, `BoundaryAfter(count)`, `BoundaryEvery(count)`.

**Don't reach for yet**: Population management, KDL text manipulation.

---

## Level 2 — Manage populations

**Trigger**: I need to work with template parameter tables — the rows that instantiate template sources.

```python
from lang import resolve_vertex, resolve_template, read_population

# Find a vertex by name in LOOPS_HOME
vertex_path = resolve_vertex("reading", home)
# home/reading/reading.vertex

# Find the template source within it
template = resolve_template(vertex_ast)

# Read its population (parameter rows)
pop = read_population(vertex_ast, template, base_dir)
# PopulationInfo(header=["kind", "url"], rows=[...], storage="file")
```

**Storage modes**: `"file"` (external `.list` file), `"inline"` (KDL `with` rows), `"both"`.

Population management also includes KDL text manipulation — `kdl_insert_with_row()`, `kdl_remove_with_row()`, `export_to_file()`, `import_from_file()`. These edit the `.vertex` file text directly to add/remove parameter rows. The CLI (`loops ls/add/rm`) uses these.

**Name resolution**: `resolve_vertex("dev/project", home)` → `home/dev/project/project.vertex`. Slashed names use the leaf for the filename.

---

## Key invariants

- Pure grammar — no runtime types, no execution, no atoms/engine imports.
- AST types are frozen dataclasses. Parsing produces immutable structure.
- Validation infers shape (STRING → LIST → DICT) through parse pipelines.
- KDL is the surface syntax. `ckdl` handles lexing. Lang maps to domain AST.
- `.loop` = source definition. `.vertex` = vertex configuration. Different files, different ASTs.

## Build & test

```bash
uv run --package lang pytest libs/lang/tests
uv run --package lang pytest libs/lang/tests/test_loader.py  # single file
```
