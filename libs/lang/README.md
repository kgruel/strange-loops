# lang

KDL-based loader for `.loop` and `.vertex` files. Parses [KDL](https://kdl.dev/) documents into AST dataclasses, then validates them.

## Usage

```python
from pathlib import Path

from lang import parse_loop_file, parse_vertex_file

# Parse a .loop file
loop = parse_loop_file(Path("disk.loop"))

# Parse a .vertex file
vertex = parse_vertex_file(Path("system.vertex"))
```

## CLI

```bash
uv run loops validate disk.loop                # syntax check
uv run loops test disk.loop --input sample.txt # run parse against sample
uv run loops run disk.loop                     # execute and print facts
uv run loops compile system.vertex             # show generated structure
uv run loops run system.vertex                 # run the vertex
```

## File Formats

Both `.loop` and `.vertex` files use KDL syntax. See `CLAUDE.md` in the repo root for the node reference.
