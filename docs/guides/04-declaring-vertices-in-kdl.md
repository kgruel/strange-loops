# Rung 04 — Declaring Vertices in KDL

> **What you'll learn:** How to move from constructing vertices in Python to declaring them in `.vertex` KDL files, and how the declaration compiles back into the same runtime you used in rungs 02–03.
> **Prerequisites:** [Rung 03 — Persistence & Replay](03-persistence-and-replay.md)
> **Time:** ~20 min

The abstraction chain runs left to right. Rungs 01–03 lived on the right side — atoms, runtime, persistence. This rung is the pivot to the left:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
.vertex / .loop      emit/read/sync      Vertex, Store        Fact, Spec
```

**Most work lives in config.** You declare what to accumulate; the runtime runs it. You almost never write the `Vertex(...)` / `v.register(...)` code from rung 02 directly — you declare the equivalent in KDL and let the compiler do the wiring.

---

## Why declaration over construction

The Python form from rung 02 is expressive but manual:

```python
from engine import Vertex
v = Vertex("project")
v.register("decision", {}, lambda state, p: {**state, p["topic"]: p})
v.register("thread", {}, lambda state, p: {**state, p["name"]: p})
```

This conflates *what to accumulate* with *how to instantiate it*. The KDL form separates them:

```kdl
name "project"
store "./data/project.db"

loops {
  decision {
    fold {
      items "by" "topic"
    }
  }

  thread {
    fold {
      items "by" "name"
    }
  }
}
```

The declaration is data. The compiler reads it, infers the fold semantics, and produces the same runtime `Vertex` and `Loop` objects you'd have written by hand — but now the structure is inspectable, version-controllable, and usable by the CLI without any Python glue.

---

## The `.vertex` file

A `.vertex` file is a [KDL](https://kdl.dev/) document. The full directive set is documented in [configuration guide](../configuration-guide.md) — this rung covers the shape you'll write most often:

```kdl
name "meter"
store "./data/meter.db"

loops {
  metric {
    fold {
      by_service "by" "service"    // dict keyed by "service" field
      total     "inc"              // running count
    }
    boundary every=100             // fire a Tick every 100 facts
  }

  event {
    fold {
      recent "collect" 50          // keep last 50 items
    }
  }
}
```

The fold-op vocabulary in KDL maps directly to the builder helpers (and to the runtime Spec folds):

| KDL inside `fold {}` | Meaning |
|----------------------|---------|
| `target "by" "field"` | Dict keyed by `field`; upsert per fact |
| `target "inc"` | Increment a counter |
| `target "latest"` | Most recent timestamp |
| `target "sum" "field"` | Running sum of a numeric field |
| `target "max" "field"` | Maximum value seen |
| `target "min" "field"` | Minimum value seen |
| `target "avg" "field"` | Running average |
| `target "collect" N` | Keep the last N items |
| `target "window" N "field"` | Sliding window of N values |

Cross-reference [configuration guide §4](../configuration-guide.md) for the full boundary and directive tables.

---

## The `.loop` file

A `.loop` file defines a *source*: a shell command that produces output, the kind of fact it emits, and an optional parse pipeline:

```kdl
// disk.loop
source "df -h"
every "60s"
kind "disk"
observer "monitor"

parse {
  skip "^Filesystem"
  split
  pick 0 4 5 {
    names "fs" "pct" "mount"
  }
  transform "pct" {
    strip "%"
    coerce "int"
  }
}
```

The `.vertex` file references `.loop` files via its `sources {}` block. Loop files and the parse pipeline vocabulary are covered fully in [configuration guide §2–3](../configuration-guide.md).

---

## `VertexBuilder`: the Python bridge

When you need to build a `.vertex` declaration programmatically — in tests, in tooling, or when scaffolding — `engine.builder` provides a fluent API that produces the same KDL AST the loader parses:

```python
from engine.builder import vertex, fold_by, fold_count, fold_collect

ast = (
    vertex("project")
    .store("./data/project.db")
    .loop("decision", fold_by("topic"))
    .loop("thread", fold_by("name"))
    .loop("event", fold_collect("items", max_items=100))
    .build()
)
# ast is a VertexFile — the same frozen AST parse_vertex_file() would return
```

The available fold helpers mirror the KDL op table:

| Helper | KDL equivalent |
|--------|---------------|
| `fold_count(target="count")` | `target "inc"` |
| `fold_by(key_field, target="")` | `target "by" "key_field"` |
| `fold_collect(target="items", max_items=100)` | `target "collect" N` |
| `fold_latest(target="latest")` | `target "latest"` |
| `fold_sum(field, target="")` | `target "sum" "field"` |
| `fold_max(field, target="")` | `target "max" "field"` |
| `fold_min(field, target="")` | `target "min" "field"` |
| `fold_avg(field, target="")` | `target "avg" "field"` |
| `fold_window(field, size, target="")` | `target "window" N "field"` |

### Writing to disk

`VertexBuilder.write(path)` serializes the AST as KDL to a file, then returns the `VertexFile`. This is how tests and scaffolding tools produce `.vertex` files:

```python
from pathlib import Path
from engine.builder import vertex, fold_by, fold_collect

ast = (
    vertex("project")
    .store("./data/project.db")
    .loop("decision", fold_by("topic"))
    .loop("event", fold_collect("items", max_items=50))
    .write(Path("project.vertex"))   # writes KDL, returns VertexFile AST
)
```

The resulting `project.vertex` file is valid KDL that `parse_vertex_file()` reads back unchanged.

---

## From AST to runtime

The compiler turns a `VertexFile` AST into runtime objects. There are two paths:

### Direct compilation (returns Specs, not a live Vertex)

```python
from lang import parse_vertex_file
from engine.compiler import compile_vertex

ast = parse_vertex_file(Path("project.vertex"))
specs = compile_vertex(ast)   # dict[str, Spec] — one Spec per loop
```

`compile_vertex` returns a `dict[str, Spec]`. A `Spec` is a blueprint: fold declarations, state fields, optional boundary — but not a live runtime object yet.

### Full materialization (returns the runtime Vertex from rung 02)

To get a live `Vertex` you can call `receive()` on:

```python
from lang import parse_vertex_file
from engine.compiler import compile_vertex_recursive, materialize_vertex

ast = parse_vertex_file(Path("project.vertex"))
compiled = compile_vertex_recursive(ast)    # CompiledVertex (handles child vertices)
runtime_vertex = materialize_vertex(compiled)  # the Vertex from rung 02

from atoms import Fact
runtime_vertex.receive(Fact.of("decision", "me", topic="auth/jwt", message="Use JWT"))
runtime_vertex.state("decision")  # {"auth/jwt": {...}}
```

The `compile_vertex_recursive` step handles nested child vertices (the `vertices` and `discover` directives). The `materialize_vertex` step wires everything into the `Vertex` you know from rung 02.

### Production path (used by the CLI)

In production, `load_vertex_program` is the single entry point — it parses, validates, compiles, and materializes in one call:

```python
from engine import load_vertex_program

program = load_vertex_program(Path("project.vertex"))
# program.vertex is the live Vertex
# program.collect() / program.run() drive sources
```

This is what `loops emit`, `loops read`, and `loops sync` call internally.

---

## Validating a file

The `lang` library provides `parse_vertex_file` and `validate`:

```python
from lang import parse_vertex_file
from lang.validator import validate

ast = parse_vertex_file(Path("project.vertex"))
validate(ast)   # raises ValidationError if routes reference undefined loops, etc.
```

From the CLI (after [rung 05](05-the-loops-cli-basics.md)):

```
loops validate project.vertex
loops compile project.vertex    # show the compiled structure
```

---

## What you've learned

- The abstraction chain: config declares, CLI uses, engine runs, atoms store.
- A `.vertex` file is data — KDL that describes what to accumulate, not how.
- `VertexBuilder` is the Python bridge for programmatic construction and testing.
- `compile_vertex` returns Specs; `materialize_vertex(compile_vertex_recursive(ast))` returns the live runtime Vertex; `load_vertex_program` is the production shortcut.
- Validate with `lang.validate` or `loops validate`.

---

**Next:** [Rung 05 — The loops CLI: emit, read, fold](05-the-loops-cli-basics.md)
**See also:** [deep dive: VERTEX](../VERTEX.md) · [configuration guide](../configuration-guide.md) · [guide index](README.md)
