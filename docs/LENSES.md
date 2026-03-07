# Lenses

Lenses are pure rendering functions. Engine computes fold state, lenses render it. The same vertex data can look completely different through different lenses — a human terminal view, an LLM system prompt, a hook status bar.

This document is progressive. Start at the level that matches your intent.

## Level 0 — Using lenses

Every `loops read` command renders through a lens. When you don't specify one, you get the generic default.

### Default rendering

```bash
loops read project          # generic fold lens — sections with items, metadata-driven
loops read comms            # comms custom lens — lifecycle-aware messages, presence
loops read docs             # docs custom lens — vocab grouped by category, guides by level
```

Comms, docs, and identity get custom rendering because their vertex files declare a lens:

```kdl
// comms.vertex
lens {
  fold "comms"
}
```

Project has no lens declaration, so it falls through to the generic default.

### Overriding with --lens

The `--lens` flag overrides everything — vertex declarations, app overrides, defaults:

```bash
loops read identity --lens prompt    # override: generic schema prompt instead of identity's default narrative
loops read project --lens state      # project rendered as session orientation
loops read project --lens prompt     # project rendered as structured schema for LLM
```

Note: `loops read identity` already renders as narrative by default — identity.vertex declares `lens { fold "identity_prompt" }`. The `--lens prompt` flag would *override* that to the generic schema prompt, which is less useful for identity. The flag is for overriding, not for activating.

### Zoom levels

Every lens receives a zoom level. Control it with `-v` flags:

| Flag | Zoom | What you see |
|------|------|-------------|
| (none) | SUMMARY | Key information — labels, bodies, structure |
| `-v` | DETAILED | Expanded fields, IDs, additional context |
| `-vv` | FULL | All metadata — timestamps, observers, origins |
| `--minimal` | MINIMAL | One-liner counts |

The lens decides what each level means. The generic fold lens shows counts at MINIMAL, label + body at SUMMARY, all payload fields at DETAILED, and metadata (ts, observer, origin) at FULL. Custom lenses define their own progressive disclosure.

### Piped output

When piped (not a TTY), `width` is `None` — no truncation, no padding. The output IS the data:

```bash
loops read identity --lens prompt --plain | pbcopy   # system prompt to clipboard
loops read comms --plain                              # comms status for a hook
```

`--plain` strips ANSI styling. `width=None` means the lens should produce full-length text.

## Level 1 — Writing a custom lens

A custom lens is a Python file that exports a render function. No framework, no base class — just a function with the right signature.

### The fold lens contract

```python
def fold_view(data: FoldState, zoom: Zoom, width: int | None, **kwargs) -> Block:
    ...
```

**Parameters:**
- `data` — `FoldState` from `libs/atoms/src/atoms/fold_state.py`
- `zoom` — `Zoom` enum from `libs/painted/src/painted/fidelity.py` (MINIMAL=0, SUMMARY=1, DETAILED=2, FULL=3)
- `width` — terminal width in columns, or `None` when piped
- `**kwargs` — optional context (currently `vertex_name: str | None`)

**Returns:** `Block` from `libs/painted/` — the rendered output.

### What FoldState looks like

```
FoldState
  .vertex: str                    # "project", "comms", etc.
  .sections: tuple[FoldSection, ...]

FoldSection
  .kind: str                      # "decision", "thread", "message", etc.
  .items: tuple[FoldItem, ...]
  .fold_type: str                 # "by" (keyed upsert) or "collect" (bounded list)
  .key_field: str | None          # for "by" folds, the grouping field
  .count: int                     # len(items)

FoldItem
  .payload: dict[str, Any]        # domain fields — the actual content
  .ts: float | None               # epoch seconds of most recent contributing fact
  .observer: str                  # who emitted the fact(s)
  .origin: str                    # source attribution (discord, lobsters, etc.)
  .id: str | None                 # ULID of the source fact
```

`FoldSection.fold_type` and `key_field` tell you how facts were compressed. A "by" fold with `key_field="topic"` means each item is the latest fact for a unique topic. A "collect" fold means the last N facts in arrival order.

### Minimal working example

```python
"""My custom lens — renders decisions as a numbered list."""
from __future__ import annotations
from typing import TYPE_CHECKING
from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldState

def fold_view(data: FoldState, zoom: Zoom, width: int | None, **kwargs) -> Block:
    rows = []
    for section in data.sections:
        if not section.items:
            continue
        rows.append(Block.text(f"## {section.kind.upper()}", Style(bold=True), width=width))
        for i, item in enumerate(section.items, 1):
            label = item.payload.get(section.key_field or "name", "?")
            rows.append(Block.text(f"  {i}. {label}", Style(), width=width))
    return join_vertical(*rows) if rows else Block.text("(empty)", Style(dim=True))
```

Save this to `~/.config/loops/lenses/my_lens.py`, then use it:

```bash
loops read project --lens my_lens
```

### The stream lens contract

```python
def stream_view(data: dict | list, zoom: Zoom, width: int | None, **kwargs) -> Block:
    ...
```

Stream data arrives as `{"facts": [...], "fold_meta": {...}}` (canonical) or a bare list of fact dicts (legacy). Each fact dict has `kind`, `ts`, `payload`, `observer`, `origin`, `id`.

### Alternative function names

The resolver tries multiple names when searching a lens module:

- For fold: `fold_view`, then `<lens_name>_view` (e.g., `prompt_view` in the prompt lens)
- For stream: `stream_view`, then `stream_<lens_name>_view`, then `<lens_name>_view`

This allows a single lens file to export both views, or a lens named after its primary function (like `prompt_view`).

### Where to put the file

User-global: `~/.config/loops/lenses/<name>.py` — available to all vertices. This is where comms.py, docs.py, and state.py live.

### Existing custom lenses to reference

| File | Vertex | What it does |
|------|--------|-------------|
| `config/lenses/comms.py` | comms | Lifecycle-aware messaging — NEW/DELIVERED/HANDLED states, presence detection, self-scoping. Exports `fold_view` + `stream_view`. |
| `config/lenses/docs.py` | docs | Living documentation — vocab grouped by category, guides with progressive levels, scope grouping. Exports `fold_view`. |
| `config/lenses/identity_prompt.py` | identity | Identity narrative — self, principles, observations, intentions, decisions composed for LLM consumption. Exports `fold_view`. |
| `config/lenses/state.py` | (via --lens) | Session orientation — tasks by priority, open threads, recent decisions. Exports `fold_view`. |
| `apps/loops/src/loops/lenses/prompt.py` | (via --lens) | LLM system prompt — structured schema for non-identity vertices. Built-in. Exports `prompt_view` + `stream_prompt_view`. |

## Level 2 — Declaring a lens on a vertex

A vertex can declare its default lens in the `.vertex` file. This is Tier 2 of the resolution chain — it overrides the built-in default but yields to `--lens` flags.

### The lens block

```kdl
// In a .vertex file:
lens {
  fold "comms"          // custom fold lens name
  stream "comms"        // custom stream lens name (optional)
}
```

Both `fold` and `stream` are optional, but at least one must be present. Names are resolved through the file search path (see Level 3).

### Real examples

**comms.vertex** — combines discord and native sources, declares the comms lens:

```kdl
name "comms"
lens {
  fold "comms"
}
combine {
  vertex "./discord/discord.vertex"
  vertex "./native/native.vertex"
}
```

When you run `loops read comms`, the resolver finds `comms.vertex`'s lens declaration, searches for `comms.py` in the lens path, loads `fold_view` from it, and renders.

**docs.vertex** — declares the docs lens for progressive documentation rendering:

```kdl
name "docs"
store "./data/docs.db"
lens {
  fold "docs"
}
```

**identity.vertex** — declares the identity prompt lens. The prompt lens is identity configuration, not generic infrastructure. This means `loops read identity` gets narrative rendering by default, no `--lens` flag needed:

```kdl
name "identity"
store "./data/identity.db"
scope "observer"
lens {
  fold "identity_prompt"
}
```

### When to declare vs. rely on default

Declare a lens when:
- The domain has rendering needs the generic can't handle (lifecycle states, category grouping, narrative composition)
- The vertex's primary consumer expects a specific rendering (agents expect prompt format, hooks expect status bars)

Rely on the generic default when:
- The data is simple key-value with standard label fields (topic, name, title)
- Progressive zoom on the generic fold lens adequately shows the data

Most vertices don't need custom lenses. Of the 18 vertex files in config/, only 3 declare lenses (comms, docs, identity). The generic default handles the rest adequately — that's by design (see `generic-defaults-simplicity` in DESIGN-DECISIONS.md).

## Level 3 — Resolution chain

The full 4-tier resolution happens in `apps/loops/src/loops/main.py:1260-1315` (`_resolve_render_fn`).

### The 4 tiers

```
1. --lens flag          →  resolve_lens(flag_value, view_name)
2. Vertex lens{} decl   →  parse .vertex, extract LensDecl, resolve_lens(decl.fold, ...)
3. App module override   →  mod.fold_view or mod.status_view or mod.PAYLOAD_LENS
4. Built-in default      →  lenses/fold.py or lenses/stream.py
```

Each tier is tried in order. First match wins. If a tier returns None, fall through to the next.

### File search path (for tiers 1 and 2)

`resolve_lens()` in `apps/loops/src/loops/lens_resolver.py:41-79` searches:

```
1. <vertex_dir>/lenses/<name>.py     # vertex-local (travels with vertex)
2. <cwd>/lenses/<name>.py            # project-local
3. ~/.config/loops/lenses/<name>.py  # user-global (where config/lenses/ lands)
4. loops.lenses.<name>               # built-in package (fold, stream, prompt)
```

**Name-style** (`"comms"`, `"prompt"`) — searched through the hierarchy.
**Path-style** (`"./custom.py"`, `"/abs/path.py"`) — resolved relative to the vertex directory.

### Tier 3: app module override

Apps (siftd, strange-loops) register modules that can provide lenses. `_resolve_app_view()` in `main.py:1339-1367` checks:

1. `mod.fold_view` or `mod.stream_view` — direct view function
2. `mod.status_view` or `mod.log_view` — legacy aliases
3. `mod.PAYLOAD_LENS` — app provides a payload interpreter, the system wraps it in a generic view

This tier exists so apps can provide domain rendering without requiring vertex declarations. It's a compatibility layer — for vertices in config/, Tier 2 (vertex declaration + custom lens file) is preferred.

### call_lens: optional context kwargs

`call_lens()` in `lens_resolver.py:157-166` passes context like `vertex_name` to lenses that accept it:

```python
def call_lens(fn, data, zoom, width, **kwargs) -> Block:
    try:
        return fn(data, zoom, width, **kwargs)
    except TypeError:
        return fn(data, zoom, width)
```

Lenses that want context add `**kwargs` or specific keyword arguments. Lenses that don't care use the basic 3-argument signature — the TypeError fallback handles it.

### Design principles governing the chain

- **app-boundary**: Apps never own the read path. You never need an app installed to see vertex state. If an app lens isn't available, the built-in default renders the data adequately.
- **generic-defaults-simplicity**: The generic default is simple, not smart. It renders sections with items, driven by metadata (key_field, fold_type). Domain-specific rendering belongs in custom lenses.
- **lens-escalation-path**: Three real tiers of capability — generic default (any vertex, adequate), custom lens (domain-specific, travels with config), app (domain verbs beyond read/emit/sync). Each tier is a graduation, not a replacement.

See `DESIGN-DECISIONS.md` for the full decision set.
