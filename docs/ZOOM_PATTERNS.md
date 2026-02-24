# Zoom Propagation Patterns

Research on zoom management in multi-lens applications.

## Context

The fidelis lens system provides three lens functions:
- `shape_lens`: convention-based rendering of Python data structures
- `tree_lens`: hierarchical tree visualization
- `chart_lens`: sparklines and bar charts

All share the signature `(data, zoom, width) -> Block`, where:
- `zoom`: integer detail level (0=minimal, 1=summary, 2+=full)
- `width`: available horizontal space

The `Lens` dataclass bundles a render function with `max_zoom` metadata.

## Question 1: Global vs Independent Zoom

**Should all lenses share one zoom level, or should each lens have its own?**

### Use Cases for Global Zoom

| Scenario | Why global works |
|----------|------------------|
| Dashboard with multiple panels | User wants consistent information density across all views |
| Progressive disclosure | `-/=` keys uniformly zoom all content for quick overview vs deep dive |
| Narrow terminal | Globally reduce detail to fit available space |
| Presentation mode | Toggle entire UI between "show" and "tell" modes |

Global zoom models a single rendering context. The mental model: "how much detail
do I want to see right now?" The answer applies everywhere.

### Use Cases for Independent Zoom

| Scenario | Why independent works |
|----------|----------------------|
| Mixed-priority data | Health status needs detail (zoom=2), metrics need summary (zoom=1) |
| Focus vs context | Expand detail on selected item, collapse surrounding items |
| Per-role defaults | Operator wants full trace, monitor wants high-level status |
| Responsive layout | Dense column stays at zoom=0, wide column expands to zoom=2 |

Independent zoom models per-lens concerns. The mental model: "this lens shows
data that wants a specific level of detail."

### Observed Pattern: review_lens.py

The experiment uses **global zoom stored as state**:

```python
# Lens primitive with zoom + scope
@dataclass(frozen=True)
class Lens:
    zoom: int = 1
    scope: frozenset[str] | None = None

# Lens changes are facts that fold
def lens_fold(state: dict, payload: dict) -> dict:
    return {
        "zoom": payload.get("zoom", state.get("zoom", 1)),
        "scope_name": payload.get("scope", state.get("scope_name", "all")),
    }

# Per-peer defaults
PEER_LENS: dict[str, Lens] = {
    "kyle": Lens(zoom=2, scope=None),
    "kyle/monitor": Lens(zoom=1, scope=SCOPE_DOMAIN),
}
```

**Key insight**: The experiment applies global zoom, but allows per-peer defaults.
When you switch peers, their default lens applies. Within a peer's session, zoom
is global.

### Recommendation

**Default to global zoom with per-lens overrides.**

```
┌─────────────────────────────────────────┐
│  Global zoom = 1  (user-controlled)     │
├──────────────────┬──────────────────────┤
│  health: zoom=1  │  trace: zoom=1       │  (inherits global)
│  metrics: zoom=0 │  log: zoom=2         │  (per-lens override)
└──────────────────┴──────────────────────┘
```

Rationale:
1. Global provides the common case (consistent density)
2. Overrides handle the exceptions (mixed-priority data)
3. Per-peer defaults give role-appropriate starting points
4. User adjustments affect global; overrides are declarative

## Question 2: Zoom State Management

**Where does zoom state live in a multi-lens app?**

### Options

| Location | Model | Trade-off |
|----------|-------|-----------|
| Local variable | `zoom = 1` in render function | Simple but not shareable |
| App state | `self._zoom` on Surface subclass | Shared, but outside the loop |
| Vertex state | `lens` kind with zoom/scope | In the loop, folds, persists |
| Per-lens state | `lens_{name}` kinds | Independent zoom per lens |

### Observed Patterns

**review.py** (pre-lens): `_debug_open` is a boolean flag on the app. Toggle
with 'd' key. Not in the loop — pure presentation state.

**review_lens.py** (with lens): Lens state folds through the vertex:

```python
# Lens changes emit as facts
self.emit("lens", zoom=new_zoom)

# State reconstructs on restart (persistence)
state = self.vertex.state("lens")
zoom = state.get("zoom", 1)
```

### Recommendation

**Zoom state belongs in the vertex when**:
- It needs to persist across sessions
- Multiple observers need to see it
- Changes should appear in the trace/audit

**Zoom state stays local when**:
- It's purely presentation (like debug panel width)
- No persistence needed
- Single observer, no sharing

The test: "Is this an observation about the world, or a configuration of my
viewer?" Observations go in the vertex. Configuration stays local.

For most multi-lens apps: **vertex state**. Lens changes become facts, fold
history captures presentation decisions, restart reconstructs view configuration.

## Question 3: Zoom-Width Interaction

**How do zoom level and available width interact?**

### Current Behavior

Each lens function handles width internally:

```python
# shape_lens
if width <= 0:
    return Block.empty(0, 1)
# ... then truncates/wraps content to fit

# tree_lens
content_width = width - len(branch_prefix)
if content_width <= 0:
    continue  # skip this branch
```

Zoom and width are orthogonal:
- Zoom controls how much information to include
- Width controls how much space to render into

### Scenarios

| Width | Zoom | Result |
|-------|------|--------|
| Wide (80+) | 0 | Minimal info, lots of whitespace |
| Wide (80+) | 2 | Full detail, comfortable layout |
| Narrow (20) | 0 | Minimal info, fits |
| Narrow (20) | 2 | Full detail, truncated |

**The narrow+high-zoom case is the interesting one.** User wants detail but
doesn't have space. Options:

1. **Truncate**: Keep zoom=2, truncate at width (current behavior)
2. **Auto-reduce**: Narrow width forces lower zoom
3. **Scroll**: Maintain full render, horizontal scroll
4. **Reflow**: Vertical expansion instead of horizontal

### Observed Pattern

`_lens.py` truncates with ellipsis:

```python
def _truncate_ellipsis(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"
```

**This is the right default.** Truncation preserves user intent (they asked for
zoom=2) while respecting physical constraints (terminal is narrow). The ellipsis
signals lost information.

### Recommendation

**Keep zoom and width orthogonal.** Don't auto-reduce zoom based on width.

Rationale:
1. User explicitly chose zoom level — respect it
2. Truncation is visible (ellipsis) — user can adjust if needed
3. Auto-reduction creates mode confusion ("why did my detail disappear?")
4. Responsive layouts should adjust zoom explicitly, not implicitly

For responsive applications that want width-aware zoom:

```python
# Composition layer decides, not the lens
if width < 40:
    effective_zoom = min(zoom, 1)  # cap at summary for narrow
else:
    effective_zoom = zoom

block = shape_lens(data, effective_zoom, width)
```

## Question 4: Lens Default Zoom

**Should `Lens` carry a default zoom? Current: `Lens(render, max_zoom=2)`**

### Current Design

```python
@dataclass(frozen=True, slots=True)
class Lens(Generic[T]):
    render: Callable[[T, int, int], Block]
    max_zoom: int = 2
```

`max_zoom` is metadata about capability, not a default. The caller always
provides zoom explicitly.

### Options for Default Zoom

| Option | Signature | Trade-off |
|--------|-----------|-----------|
| No default | `lens.render(data, zoom, width)` | Explicit, caller controls |
| Default on Lens | `Lens(render, max_zoom=2, default_zoom=1)` | Lens carries preference |
| Default via wrapper | `def auto_lens(data, width): return lens.render(data, lens.default, width)` | Separation of concerns |

### Analysis

**Arguments for Lens carrying default**:
- Some lenses have natural defaults (tree_lens makes sense at zoom=1)
- Reduces boilerplate when using lenses
- Per-lens customization without composition layer logic

**Arguments against**:
- Zoom is context-dependent, not lens-dependent
- Same lens might want different defaults in different contexts
- Adds state to a stateless transformation

### Observed Pattern

The experiment in `review_lens.py` puts defaults on **Peer, not Lens**:

```python
PEER_LENS: dict[str, Lens] = {
    "kyle": Lens(zoom=2, scope=None),
    "kyle/monitor": Lens(zoom=1, scope=SCOPE_DOMAIN),
}
```

This separates:
- `fidelis.views.Lens`: render function + capability metadata
- `experiments.Lens`: zoom + scope (view configuration)

Two different types with the same name. The experiment's Lens is richer — it
carries presentation state. The library's Lens is minimal — it's just a
render function wrapper.

### Recommendation

**Keep library Lens minimal. Add `default_zoom` as optional metadata, not behavior.**

```python
@dataclass(frozen=True, slots=True)
class Lens(Generic[T]):
    render: Callable[[T, int, int], Block]
    max_zoom: int = 2
    default_zoom: int = 1  # optional hint, not enforced
```

Usage:
```python
# Caller can use default or override
zoom = user_zoom if user_zoom is not None else lens.default_zoom
block = lens.render(data, zoom, width)
```

This:
- Keeps Lens stateless (hint, not state)
- Allows per-lens defaults when useful
- Doesn't change the calling convention
- Composition layer still controls

## Summary

| Question | Recommendation |
|----------|----------------|
| Global vs independent zoom | Global with per-lens overrides |
| Zoom state location | Vertex state (folds, persists) |
| Zoom-width interaction | Orthogonal; truncate, don't auto-reduce |
| Lens default zoom | Optional `default_zoom` metadata |

### Pattern: Zoom Propagation Model

```
User input (-, =)
      │
      ▼
┌──────────────────────────────────────┐
│  Global zoom (vertex state)          │
│  emit("lens", zoom=new_zoom)         │
└──────────────────────────────────────┘
      │
      ├── per-lens override? ─────────► use override
      │         │
      │         no
      │         │
      ▼         ▼
┌──────────────────────────────────────┐
│  lens.render(data, zoom, width)      │
│  - zoom controls detail level        │
│  - width controls available space    │
│  - truncate if needed (…)            │
└──────────────────────────────────────┘
      │
      ▼
   Block
```

### Pattern: Per-Peer Lens Defaults

```python
# Defaults are role-appropriate
PEER_DEFAULTS = {
    "operator": {"zoom": 2, "scope": None},       # full access, full detail
    "monitor": {"zoom": 1, "scope": DOMAIN},      # summary, domain only
    "debug": {"zoom": 3, "scope": INFRA},         # verbose, infrastructure
}

# Switching peer applies default
def select_peer(peer_name):
    default = PEER_DEFAULTS.get(peer_name, {})
    emit("lens", **default)
```

### Non-Pattern: Auto-Zoom Based on Width

Avoid this:
```python
# Anti-pattern: implicit zoom reduction
def adaptive_lens(data, zoom, width):
    if width < 30:
        zoom = 0  # silently reduced
    elif width < 60:
        zoom = min(zoom, 1)  # silently capped
    return shape_lens(data, zoom, width)
```

Why it's problematic:
1. User asks for zoom=2, gets zoom=0 — violates expectation
2. No signal that detail was lost (different from truncation)
3. Width fluctuates (resize) causing zoom to flicker
4. Hard to debug ("why does this show less in narrow terminal?")

If responsive zoom is needed, make it explicit at the composition layer:
```python
# Explicit: composition layer decides
if terminal_width < 40:
    ui_zoom = min(user_zoom, 1)
    status_message = "(narrow mode)"
else:
    ui_zoom = user_zoom
```
