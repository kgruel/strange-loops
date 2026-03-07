# lenses — rendering layer

Pure functions that turn vertex data into terminal output. The top of the abstraction chain — lenses consume what every layer below produces.

```
atoms (data)  →  engine (runtime)  →  loops (CLI)  →  lenses (rendering)
FoldState          vertex_fold()       fetch/resolve     (data, zoom, width) -> Block
```

## The Contract

```python
def fold_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render folded vertex state."""

def stream_view(data: dict, zoom: Zoom, width: int | None) -> Block:
    """Render event stream."""
```

Pure. No IO, no store access, no state. Lens receives data, returns a Block.

## What You Receive

**Fold lenses** get `FoldState` (from `atoms`):
```python
data.sections    # tuple[FoldSection, ...] — one per kind
data.vertex      # str — vertex name

section.kind       # "decision", "thread", "message", etc.
section.items      # tuple[FoldItem, ...] — folded results
section.fold_type  # "by" (keyed upsert) or "collect" (bounded list)
section.key_field  # for "by" folds: the grouping key field name

item.payload     # dict[str, Any] — domain content
item.ts          # float | None — epoch seconds
item.observer    # str — who emitted
item.id          # str | None — source fact ULID
```

`fold_type` and `key_field` tell you how the data was folded — drive rendering from these rather than hardcoding per-kind logic. The fold lens uses `key_field` as the label; the prompt lens uses it for narrative structure.

**Stream lenses** get `{"facts": [...], "fold_meta": {...}, "vertex": str}`:
```python
facts[i]["kind"]       # str
facts[i]["ts"]         # str — ISO timestamp
facts[i]["observer"]   # str
facts[i]["payload"]    # dict[str, Any]
fold_meta[kind]["key_field"]  # str | None — from vertex declaration
```

## Zoom Levels

Every lens renders at four zoom levels. The lens decides what each means:

| Zoom | Intent | Typical rendering |
|------|--------|------------------|
| `MINIMAL` | One line, counts only | `19 decisions, 10 threads` |
| `SUMMARY` | Orient without drowning | Key field + body snippet |
| `DETAILED` | Everything visible | + secondary payload fields |
| `FULL` | All fields, all metadata | + ts, observer, origin, ULID |

`width=None` means piped (no truncation/padding). Respect it — piped output feeds system prompts, other tools.

## Resolution Chain

Lenses resolve through a 4-tier search (first match wins):

1. **Vertex-local**: `<vertex_dir>/lenses/<name>.py` — travels with the vertex
2. **Project-local**: `<cwd>/lenses/<name>.py` — repo-specific overrides
3. **User-global**: `~/.config/loops/lenses/<name>.py` — personal cross-project
4. **Built-in**: `loops.lenses.<name>` — this directory

CLI: `--lens <name>` overrides all tiers. Vertex `lens {}` declaration overrides tiers 3-4.

## Built-in Lenses (this directory)

**Core rendering** (the temporal modes):
- `fold` — default fold rendering, driven by section metadata
- `stream` — time-ordered event history

**User-global lenses** (graduated to `config/lenses/`):
- `prompt` — system prompt rendering (structured schema, domain-aware kind filtering)

**CLI command lenses** (wired to specific display commands):
- `compile`, `run`, `store`, `test`, `validate`, `vertices`, `pop`

**Utilities** (imported by other lenses):
- `gist` — content extraction from payloads (`content_gist(kind, payload)`)

## Writing a Lens

The rendering primitives come from `painted`:

```python
from painted import Block, Style, Zoom, join_vertical

def fold_view(data, zoom, width):
    plain = Style()
    rows = []
    for section in data.sections:
        for item in section.items:
            label = item.payload.get(section.key_field, "?")
            rows.append(Block.text(f"  {label}", plain))
    return join_vertical(*rows) if rows else Block.text("(empty)", plain)
```

Key patterns from existing lenses:
- **Drive from metadata, not kind**: use `section.key_field` and `section.fold_type` instead of `if kind == "decision":`
- **Progressive disclosure**: check `zoom` to decide what to show, not what to compute
- **Width discipline**: pass `width` to `Block.text()` when TTY, omit when `None` (piped)
- **Compose, don't duplicate**: custom lenses can `from loops.lenses.fold import fold_view` and wrap/extend
