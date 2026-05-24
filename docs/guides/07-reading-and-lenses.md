# Rung 07 — Reading Deeply: zoom, keys & lenses

> **What you'll learn:** How to navigate vertex state at any fidelity — from single-line counts to the full fact graph — and how the lens resolution chain determines what renders it.
> **Prerequisites:** [Rung 06 — The Fact Graph: refs & cites](06-the-fact-graph-refs-and-cites.md)
> **Time:** ~20 min

The `loops read` verb is a router, not a single command. Depending on which flags you pass, it delegates to `fold` (current state), `stream` (temporal event history), or `ticks` (period boundaries). This rung walks each path and the rendering machinery underneath all of them.

---

## The zoom/fidelity ladder

Every view receives a zoom level derived from your verbosity flags. The mapping is:

| Flag | Zoom | What changes |
|------|------|-------------|
| `-q` | MINIMAL | One-liner counts — "19 decisions, 10 threads" |
| (none) | SUMMARY | Key field + body snippet + badges |
| `-v` | DETAILED | All payload fields, observer, partial ID |
| `-vv` | FULL | Everything at SUMMARY plus `_id`, `_ts`, `_observer`, `_origin`, `_n`, `_inbound_refs` |

These names (MINIMAL, SUMMARY, DETAILED, FULL) correspond to the `Zoom` enum in `painted`. The `cli/fidelity.py` module converts `-q` to depth=0, one `-v` to depth=2, two `-v` flags (`-vv`) to depth=3. The default is depth=1 (SUMMARY).

### What each level reveals in practice

```bash
# MINIMAL — counts only, fits in a status bar
loops read project -q
# → 19 decisions, 10 threads, 4 tasks

# SUMMARY — the default: label + body snippet + revision/ref badges
loops read project
# Decisions (19):
#   design/ (6)
#     auth [×3 ←2 2d]: JWT over sessions for statelessness

# DETAILED — add observer, payload fields (status, feature=, ops=, ...)
loops read project -v
# Decisions (19):
#   design/ (6)
#     auth [×3 ←2 2d]: JWT over sessions for statelessness
#       observer: kyle
#       id:01J3R...
#       feature: auth-refactor

# FULL — add all metadata (_id, _ts, _observer, _origin, _n, _inbound_refs)
loops read project -vv
# Decisions (19):
#   design/ (6)
#     auth [×3 ←2 2d]: JWT over sessions for statelessness
#       _id: 01J3RKZMF...
#       _ts: 2026-05-15T09:30:00+00:00
#       _observer: kyle
#       _n: 3
#       _inbound_refs: 2
```

Badges at SUMMARY: `[×N]` is the revision count (how many facts folded into this item), `[←N]` is the inbound ref count (salience from the graph), `[→N]` is outbound ref count, and the recency tag (`2d`, `3w`, `Jun 4`) shows age.

---

## The four read-path traversal modes

`loops read` pre-parses a small set of routing flags and delegates accordingly:

```
default (no special flag)          → fold (current folded state)
--ticks                            → ticks (period/boundary history)
--facts + (--since or --id)        → stream (temporal query)
--facts alone                      → fold with facts visibility layer
```

### Folded state (default)

```bash
loops read project                         # full fold
loops read project --kind decision         # one section
loops read project --kind thread --key arc # prefix filter within threads
```

This renders the Vertex's current collapsed state: for each `by` fold, one item per unique fold key (the latest fact wins); for `collect` folds, the bounded accumulation.

### Prefix scan with `--key`

`--key <prefix>` is the DEFAULT scoping move when entering a namespace. It filters items whose fold key starts with the given prefix. The match is prefix-based and case-insensitive.

```bash
# Show only decisions in the design/ namespace
loops read project --kind decision --key design/

# Exact item — type the full key (startswith still matches uniquely)
loops read project --kind decision --key design/auth

# Cross-kind prefix scan (omit --kind to scan all sections)
loops read project --key design/
```

`--key` appeared in v0.3.1. Before it existed, you had to embed the key in `--kind` using slash syntax (`--kind decision/design/`). That embedded form still works as back-compat, but `--key` is the explicit, recommended form.

### Fact event history (`--facts`)

`--facts` adds the "facts" visibility layer to the fold view. For any fold item that has been revised (`n > 1`), the source facts that built it are shown beneath it — most-recent first, last 3 at SUMMARY, all at DETAILED.

```bash
loops read project --kind decision --facts          # fold + source facts for decisions
loops read project --kind decision --facts -v       # show all source facts per item
```

When combined with `--since` or `--id`, the router delegates to the **stream** view (raw event history, not folded):

```bash
# Event history for the last 7 days
loops read project --facts --since 7d

# History for a specific kind in the last 24 hours
loops read project --facts --kind decision --since 24h

# Single fact by ULID (or unique prefix)
loops read project --facts --id 01J3RKZ
```

Duration formats accepted: `7d`, `24h`, `1h`, `30m`.

### Ticks view (`--ticks`)

Ticks are the periodic snapshots that mark temporal boundaries (see [Rung 02 — Vertices & Loops](02-engine-vertices-and-loops.md) and [Rung 03 — Persistence & Replay](03-persistence-and-replay.md)). `--ticks` is routed to its own dedicated view and lens:

```bash
loops read project --ticks                # tick history with compression bars
```

### Ref graph expansion (`--refs`)

`--refs` adds edge expansion to the fold view. Each item shows its inbound and outbound edges from the fact graph. You can optionally walk N hops deep:

```bash
loops read project --refs               # 1-hop edge expansion
loops read project --refs 2             # walk 2 hops out from matching items
```

Walked items appear in a `## REFS (N)` section below the primary sections, grouped by their anchor in the primary result set.

---

## Output and rendering modes

### `--plain` — pipe-safe output

When piped, `width` is already `None` (no truncation). `--plain` additionally strips ANSI color codes. Use it to feed other tools or write to files:

```bash
loops read project --lens prompt --plain | pbcopy  # system prompt to clipboard
loops read project --kind decision --plain > decisions.txt
loops read project --plain --since 7d --facts      # structured, no color
```

### `--json` — raw data

Short-circuits the lens entirely. Renders the fetched `FoldState` as JSON, bypassing all Block/Style rendering:

```bash
loops read project --json
loops read project --kind thread --json | jq '.sections[0].items[].payload'
```

### `--live` — poll and re-render

Runs the fetch in an async loop, re-rendering the display in place every 2 seconds using `InPlaceRenderer` from `painted`. Useful for watching a vertex during an active session or sync:

```bash
loops read project --live              # re-render every 2s
loops store project --live             # store view also supports --live
```

Interrupt with Ctrl-C; the process exits with code 130 (SIGINT convention).

### `--diff` — entity lifecycle deltas

Shows cumulative field-by-field changes across an entity's entire fact history. Requires a `kind/key` target:

```bash
loops read project decision/design/auth --diff
```

This uses the internal `trace` lens, which renders each fact as a delta against the prior. You cannot pass `--lens trace` directly — `--diff` is the only entry point.

---

## Three-tier lens resolution

When `loops read` runs, it resolves which lens function to call through a 3-tier chain:

```
Tier 1  --lens <name> flag         explicit override — fails loudly if not found
Tier 2  vertex lens{} declaration  parsed from the .vertex file
Tier 3  built-in default           lenses/fold.py (fold_view) or lenses/stream.py (stream_view)
```

The 3-tier chain selects the lens **name**. A separate 4-tier **file search** then finds the Python file for that name.

---

## Four-tier lens file search

Given a lens name (e.g., `"prompt"`), the resolver searches in order — first match wins:

```
1. <vertex_dir>/lenses/<name>.py       vertex-local — travels with the vertex
2. <cwd>/lenses/<name>.py              project-local — repo-specific overrides
3. ~/.config/loops/lenses/<name>.py    user-global — personal cross-project lenses
4. loops.lenses.<name>                 built-in package (fold, stream, trace, ticks)
```

**Worked example.** You run `loops read comms` from `~/Code/loops`. The `comms.vertex` file declares `lens { fold "comms" }`. The resolver searches:

1. `~/.config/loops/comms/lenses/comms.py` — not found (comms vertex dir has no lenses/ subdir)
2. `~/Code/loops/lenses/comms.py` — not found (no project-local override)
3. `~/.config/loops/lenses/comms.py` — **found** — this is where user-global lenses live
4. (skipped — match found)

The file at step 3 is loaded and its `fold_view` function is called.

If you ran `loops read comms --lens myview` and `~/.config/loops/lenses/myview.py` doesn't exist, the resolver fails loudly with a message listing the searched paths. Explicit lens requests never silently fall back to a different view — hiding a missing lens is the same failure shape as referencing the wrong state.

**Path-style names** bypass the hierarchy entirely:

```bash
loops read project --lens ./lenses/custom.py    # relative to vertex dir
loops read project --lens /abs/path/custom.py   # absolute path
```

---

## Declaring a lens on a vertex

A `.vertex` file can declare its default lens in a `lens {}` block. This is Tier 2 of the 3-tier chain — it overrides the built-in default but yields to any `--lens` flag:

```kdl
// project.vertex
name "project"
store "./data/project.db"
lens {
  fold "my_lens"       // name searched through 4-tier file search
  stream "my_lens"     // optional — custom stream view (defaults to built-in if omitted)
}
```

Both `fold` and `stream` keys are optional within the block, but the block must contain at least one.

Real example from `comms.vertex`:

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

When `loops read comms` runs, the resolver finds the `lens { fold "comms" }` declaration, runs the 4-tier file search for `"comms"`, finds `~/.config/loops/lenses/comms.py`, and calls its `fold_view`.

---

## Writing a custom lens

A lens is a Python file exporting a render function. The fold contract:

```python
# ~/.config/loops/lenses/timeline.py
from __future__ import annotations
from typing import TYPE_CHECKING
from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldState

def fold_view(data: FoldState, zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render decisions as a chronological timeline."""
    rows = []
    for section in data.sections:
        if section.kind != "decision" or not section.items:
            continue
        rows.append(Block.text(f"# Decisions", Style(bold=True), width=width))
        # items are sorted by salience in the fold — re-sort by ts for timeline
        by_time = sorted(section.items, key=lambda i: i.ts or 0)
        for item in by_time:
            key = item.payload.get(section.key_field or "topic", "?")
            msg = item.payload.get("message", "")
            if zoom >= Zoom.DETAILED:
                rows.append(Block.text(f"  {key}: {msg}", Style(), width=width))
            else:
                rows.append(Block.text(f"  {key}", Style(), width=width))
    return join_vertical(*rows) if rows else Block.text("(empty)", Style(dim=True))
```

Use it:

```bash
loops read project --lens timeline
```

The resolver finds `~/.config/loops/lenses/timeline.py` at tier 3. No restart needed; the file is loaded on every invocation.

A lens may also declare a `fetch` function alongside its view. When present, the CLI uses it instead of the default `fetch_fold` — the lens declares its complete input contract. This enables composition lenses that combine fold state with other data (ticks, refs graph) without requiring new top-level commands.

---

**Next:** [Rung 08 — Sources & Cadence](08-sources-and-cadence.md)
**See also:** [deep dive: LENSES](../LENSES.md) · [CLI cheatsheet](../CLI-CHEATSHEET.md) · [API reference](../api-reference.md) · [guide index](README.md)
