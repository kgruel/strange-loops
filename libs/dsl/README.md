# dsl

Parser for `.loop` and `.vertex` DSL files.

## Usage

```python
from dsl import parse_loop, parse_vertex

# Parse a .loop file
loop = parse_loop("disk.loop")

# Parse a .vertex file
vertex = parse_vertex("system.vertex")
```

## CLI

```bash
loop validate disk.loop          # syntax check
loop test disk.loop --input sample.txt  # run parse against sample
loop run disk.loop               # execute and print facts
loop compile system.vertex       # show generated structure
loop start system.vertex         # run the vertex
```
