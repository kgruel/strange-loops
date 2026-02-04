# dsl

KDL-based loader for `.loop` and `.vertex` files. Parses [KDL](https://kdl.dev/) documents into AST dataclasses, then validates and compiles to runtime types.

## Usage

```python
from dsl import parse_loop_file, parse_vertex_file

# Parse a .loop file
loop = parse_loop_file(Path("disk.loop"))

# Parse a .vertex file
vertex = parse_vertex_file(Path("system.vertex"))
```

## CLI

```bash
loop validate disk.loop          # syntax check
loop test disk.loop --input sample.txt  # run parse against sample
loop run disk.loop               # execute and print facts
loop compile system.vertex       # show generated structure
loop start system.vertex         # run the vertex
```

## File Formats

Both `.loop` and `.vertex` files use KDL syntax. See `CLAUDE.md` in the repo root for the node reference.
