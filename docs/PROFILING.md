# Profiling painted Apps

Profile your app's rendering pipeline and visualize the results as flame graphs — all within painted.

## Quick Start

Wrap any code block in `profile()`, render the result with `flame_lens`:

```python
from painted import show
from painted.views import profile, flame_lens

with profile() as result:
    app.run()

show(result[0].flame_dict, lens=flame_lens)
```

The flame graph shows where CPU time goes: function call tree with proportional widths.

## The profile() Context Manager

```python
from painted.views import profile

with profile(module="myapp", top_n=30) as result:
    do_work()

r = result[0]  # ProfileResult available after the block exits
r.flame_dict    # nested dict ready for flame_lens
r.total_time    # cumulative seconds across all functions
r.call_count    # total function calls recorded
```

**`module`** — Filter to functions whose filename contains this string. Use `module="painted"` to see only painted internals, or `module="myapp"` to focus on your code. Omit for everything (including stdlib and C builtins).

**`top_n`** — Keep only the N most expensive functions by cumulative time. Keeps the flame graph readable. Default 20.

**`result[0]` pattern** — The result isn't available until profiling completes (after the block exits), but `yield` must provide something at entry. The yielded list gets populated on exit.

## Rendering Options

```python
from painted.views import flame_lens

# Horizontal flame graph (call tree, one row per depth level)
block = flame_lens(r.flame_dict, zoom=2, width=80)

# Vertical columns (per-function comparison)
block = flame_lens(r.flame_dict, zoom=1, width=80, height=12)
```

Zoom levels:
- **0**: Total value one-liner
- **1**: Top-level segments only
- **2+**: Expand children into additional rows

## External Profiler Data

`parse_collapsed()` handles Brendan Gregg's collapsed-stack format — the interchange format that py-spy, perf, and most profiling tools emit.

```python
from painted.views import parse_collapsed, flame_lens
from painted import show

# From py-spy:  py-spy record -f folded -o profile.folded -- python myapp.py
text = Path("profile.folded").read_text()
d = parse_collapsed(text)
show(d, lens=flame_lens)
```

The collapsed format is one stack per line, semicolon-separated frames, space + sample count:

```
main;handle_request;parse_json 150
main;render_response;serialize 42
main;handle_request;validate 80
```

## What to Look For

The flame graph answers "where does time go?" at a glance:

- **Wide segments** = expensive functions. If `diff` dominates, your state changes are touching too many cells.
- **Deep stacks** = long call chains. If `style.merge` appears deep under `render`, style computation may be redundant.
- **`[self]` entries** = time spent in a function's own code (not in subcalls). Large `[self]` next to small children means the function itself is the bottleneck.

## Background: Why This Exists

`flame_lens` is a composable `(data, zoom, width) -> Block` renderer, but without an intake path you had to hand-build the nested dict. The `_profile` module closes that gap: cProfile data in, flame_lens dict out.

`_timer.py` (FrameTimer) is complementary — it captures per-frame phase timing within the render loop. `_profile` wraps arbitrary code via cProfile's instrumentation profiler. Use FrameTimer for live performance monitoring, `profile()` for post-hoc analysis.

## Example: Profiling a Surface App

```python
from painted.tui import Surface, TestSurface
from painted.views import profile, flame_lens
from painted import show

app = MyApp()
harness = TestSurface(app, width=120, height=40, input_queue=inputs)

with profile(module="painted") as result:
    harness.run_to_completion()

# Where did painted spend time?
show(result[0].flame_dict, lens=flame_lens)
```

See `demos/patterns/profiler.py` for a complete working example.
