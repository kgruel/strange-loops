# ~/.config/loops/

User-level loops configuration. Vertices, lenses, and observer declarations that apply across all projects.

## Structure

```
.vertex              Root — discovers all vertices, declares global observers
lenses/              Custom lenses (user-global tier in the resolution chain)
identity/            Observer self-knowledge (self, principles, observations)
discord/             Discord bridge vertex (messages, comms lens)
meta/                Cross-cutting decisions (combines project-level metas)
project/             Aggregation vertex (combines project instances)
session/             Session state
```

## Custom Lenses

Lenses render vertex data at a given zoom level. The contract:

```python
def fold_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render folded vertex state."""

def stream_view(data: dict, zoom: Zoom, width: int | None) -> Block:
    """Render event stream."""
```

**Resolution chain** (first match wins):
1. `--lens` CLI flag
2. Vertex `lens {}` declaration
3. Vertex-local: `<vertex_dir>/lenses/<name>.py`
4. Project-local: `<cwd>/lenses/<name>.py`
5. **User-global: `~/.config/loops/lenses/<name>.py`** ← you are here
6. Built-in: `loops.lenses.<name>`

**Imports available** (via `uv run loops`):
- `from painted import Block, Style, Zoom, join_vertical` — rendering primitives
- `from atoms import FoldState, FoldSection, FoldItem` — typed fold data (TYPE_CHECKING)

**Current user-global lenses:**
- `comms` — messaging vertices (discord, telegram). Author/content/timestamp extraction.
- `state` — session orientation. Compact project summary for quick context.

**Writing a new lens:**
```python
# ~/.config/loops/lenses/my_lens.py
from painted import Block, Style, Zoom, join_vertical

def fold_view(data, zoom, width):
    # data is FoldState with .sections (tuple of FoldSection)
    # each section has .kind, .items (tuple of FoldItem), .key_field
    # each item has .payload (dict), .ts, .observer
    plain = Style()
    lines = []
    for section in data.sections:
        lines.append(f"## {section.kind.upper()}")
        for item in section.items:
            lines.append(f"  {item.payload}")
    rows = [Block.text(line, plain) for line in lines]
    return join_vertical(*rows) if rows else Block.text("(empty)", plain)
```

Usage: `loops fold <vertex> --lens my_lens --plain`

## Hooks

Hooks in `.claude/settings.json` compose vertex folds for session lifecycle:

- **SessionStart**: fold project state + identity + comms summary
- **SessionEnd**: emit session close marker

The observer resolves from `loops whoami` (workspace `.vertex` chain). Same hooks work for any observer — loops-claude, meta-claude, future observers.

## Abstraction Reference

This config layer consumes the loops monorepo libraries:

```
atoms    →  FoldState, FoldSection, FoldItem (data shapes lenses receive)
engine   →  vertex_fold, vertex_read (how data is computed before lenses see it)
painted  →  Block, Style, Zoom (how lenses produce output)
lang     →  .vertex declarations (fold specs, lens declarations, observer grants)
loops    →  CLI commands, built-in lenses, lens resolver (the app that wires it all)
```

See `~/Code/loops/CLAUDE.md` for the monorepo. Each lib has its own CLAUDE.md.
