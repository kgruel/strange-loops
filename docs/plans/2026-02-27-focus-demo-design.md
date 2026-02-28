# Focus & Navigation Demo Design

Date: 2026-02-27

## Summary

A patterns-level demo (`demos/patterns/focus.py`) that teaches painted's
two-tier focus model — navigation mode vs capture mode — by building a
form-like deploy configuration panel and replaying scripted interactions
through `TestSurface`. Results render at four zoom levels through `run_cli`.

## Motivation

The Focus primitive has a subtle two-tier design that existing demos don't
fully surface:

1. **Navigation mode** (`captured=False`): Tab/Shift-Tab moves between
   widgets. Arrow keys, typing, etc. are meaningless at the navigation level.
2. **Capture mode** (`captured=True`): The focused widget owns all key input.
   Tab no longer navigates — it might insert a tab character or do nothing.
   Escape releases capture back to navigation.

The `widgets.py` app demo uses Focus but never enters capture mode — it routes
keys based on `focus.id` without the `captured` flag. This means the
two-tier model, which is the *non-obvious* part of the API, has no demo.

Additionally, the navigation helpers (`ring_next`, `ring_prev`, `linear_next`,
`linear_prev`) and their relationship to `Focus.focus()` deserve a concrete
walkthrough. The helpers are pure functions over `Sequence[str]` — the
composition with Focus is the caller's job, and the demo shows that wiring.

## What the Demo Teaches

In order:

1. **Focus as frozen state** — `Focus(id="env", captured=False)`, transitions
   via `.focus()`, `.capture()`, `.release()`, `.toggle_capture()`
2. **Navigation mode** — Tab cycles focus ring via `ring_next`; the focused
   widget renders highlighted but doesn't intercept keys
3. **Capture mode** — Enter on a widget calls `.capture()`; the widget now
   owns all input (typing into text_input, selecting in list_view)
4. **Release** — Escape calls `.release()`, returning to navigation mode
5. **The routing pattern** — `if focus.captured:` routes to the active widget;
   `else:` routes to navigation. This if/else is the entire focus system.
6. **Search as capture composition** — typing into a Search filter is a
   capture-mode behavior: the Search widget captures keys, filters in real
   time, and Escape releases back to navigation.

## Demo Scenario

**Deploy configuration panel** — selecting environment, service, and
region before confirming a deploy. Real-ish data, same domain as testing.py
and profiler.py (infrastructure), visually distinct.

Three focusable widgets:

| Widget ID   | Type         | Data                                           |
|-------------|--------------|------------------------------------------------|
| `env`       | list_view    | production, staging, development, sandbox      |
| `service`   | text_input   | Fuzzy-filterable service name (Search-backed)  |
| `region`    | list_view    | us-east-1, us-west-2, eu-west-1, ap-southeast-1 |

A fourth non-focusable area shows the current selection summary and a
"Deploy" confirmation status.

The scenario exercises the full Focus lifecycle:

```
Tab          -> navigate to service (env -> service)
Enter        -> capture service text_input
type "api"   -> filter services via Search
Escape       -> release capture, back to navigation
Tab          -> navigate to region
Enter        -> capture region list
j, j         -> select eu-west-1
Escape       -> release capture
Tab          -> back to env
j             -> (ignored: navigation mode, env not captured)
Enter        -> capture env list
j             -> select staging
Escape       -> release
```

This sequence is the lesson. It shows: Tab skips to next widget. Enter
captures. Keys go to the captured widget. Escape releases. Keys are
ignored by non-captured widgets in navigation mode.

## Data Model

```python
ENVIRONMENTS = ("production", "staging", "development", "sandbox")

SERVICES = (
    "api-gateway", "auth-service", "worker", "scheduler",
    "metrics", "logger", "cache-proxy", "queue-consumer",
)

REGIONS = ("us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1")

FOCUS_IDS = ("env", "service", "region")

@dataclass(frozen=True)
class DeployConfig:
    """Frozen snapshot of the deploy form state."""
    focus: Focus
    env_cursor: Cursor          # selection in env list
    service_search: Search      # query + selected for service filter
    region_cursor: Cursor       # selection in region list

@dataclass(frozen=True)
class FocusEvent:
    """One focus transition captured during replay."""
    key: str
    focus_before: Focus
    focus_after: Focus
    description: str            # human-readable: "Tab: env -> service"

@dataclass(frozen=True)
class DemoResult:
    """Complete replay results."""
    events: tuple[FocusEvent, ...]
    final_config: DeployConfig
    emissions: tuple[tuple[str, dict], ...]
    frames: tuple[object, ...]  # CapturedFrame
```

## App Under Test

A minimal Surface subclass. The key routing pattern is the central teaching
point:

```python
def on_key(self, key: str) -> None:
    focus = self.state.focus

    if focus.captured:
        # --- Capture mode: widget owns all input ---
        if key == "escape":
            self.state = replace(self.state, focus=focus.release())
            self.emit("focus.release", widget=focus.id)
            return
        # Route to the captured widget
        self._handle_captured(key, focus.id)
    else:
        # --- Navigation mode: Tab moves focus ---
        if key == "tab":
            next_id = ring_next(FOCUS_IDS, focus.id)
            self.state = replace(self.state, focus=focus.focus(next_id))
            self.emit("focus.navigate", target=next_id)
        elif key == "shift-tab":
            prev_id = ring_prev(FOCUS_IDS, focus.id)
            self.state = replace(self.state, focus=focus.focus(prev_id))
            self.emit("focus.navigate", target=prev_id)
        elif key == "enter":
            self.state = replace(self.state, focus=focus.capture())
            self.emit("focus.capture", widget=focus.id)
```

The `_handle_captured` method dispatches by `focus.id` to the appropriate
widget's state update (list cursor movement, text input, search filtering).

## Emissions

Domain emissions that make the focus lifecycle visible in traces:

| Kind             | Data                        | When                          |
|------------------|-----------------------------|-------------------------------|
| `focus.navigate` | `{target: "service"}`       | Tab/Shift-Tab in nav mode     |
| `focus.capture`  | `{widget: "env"}`           | Enter in nav mode             |
| `focus.release`  | `{widget: "env"}`           | Escape in capture mode        |
| `focus.input`    | `{widget: "service", key: "a"}` | Any key in capture mode  |
| `deploy.config`  | `{env, service, region}`    | Final selection summary        |

## Zoom Levels

```
focus.py -q       # zoom=0: MINIMAL
  Focus: env (navigation)  3 widgets, 12 transitions

focus.py          # zoom=1: SUMMARY
  Focus transitions as a timeline:
    Tab       env -> service         (navigate)
    Enter     service                (capture)
    a         service                (input: "a")
    p         service                (input: "p")
    i         service                (input: "i")
    Escape    service                (release)
    Tab       service -> region      (navigate)
    ...
  Final: env=staging, service=api-gateway, region=eu-west-1

focus.py -v       # zoom=2: DETAILED
  Transition timeline (as above) + Focus state snapshots:
    [before] Focus(id="env", captured=False)
    [after]  Focus(id="service", captured=False)
  Emission trace grouped by kind (focus.navigate: 4, focus.capture: 3, ...)

focus.py -vv      # zoom=3: FULL
  Bordered sections per transition
  Frame text snapshots showing visual highlight changes
  Full emission log with data payloads
  Selection summary with Search filter state
```

## Rendering

Each zoom level as a named function:

```python
def render_minimal(result: DemoResult) -> Block: ...
def render_summary(result: DemoResult) -> Block: ...
def render_detailed(result: DemoResult, width: int) -> Block: ...
def render_full(result: DemoResult, width: int) -> Block: ...

def _render(ctx: CliContext, result: DemoResult) -> Block:
    if ctx.zoom == Zoom.MINIMAL:  return render_minimal(result)
    if ctx.zoom == Zoom.SUMMARY:  return render_summary(result)
    if ctx.zoom == Zoom.FULL:     return render_full(result, width=ctx.width)
    return render_detailed(result, width=ctx.width)
```

### Visual Encoding of Focus State

At zoom 2+, the render shows the two-tier state visually:

- **Unfocused widget**: dim border, dim label
- **Focused (navigation)**: accent border, bold label, no content interaction
- **Focused (captured)**: accent border + reverse label, content fully interactive

This visual distinction is the demo's core lesson — the border style
*changes meaning* when capture toggles, and the demo renders the state
explicitly so you can see it.

### Summary Block

At zoom 1+, a summary block shows the final deploy configuration:

```
Deploy Configuration
  env:     staging
  service: api-gateway  (filtered from 8 services)
  region:  eu-west-1
```

## Key Interactions (TestSurface Replay)

```python
SCENARIO_KEYS = [
    "tab",                          # nav: env -> service
    "enter",                        # capture: service text_input
    "a", "p", "i",                  # input: type "api" into search
    "escape",                       # release: back to navigation
    "tab",                          # nav: service -> region
    "enter",                        # capture: region list
    "j", "j",                       # input: select eu-west-1
    "escape",                       # release: back to navigation
    "tab",                          # nav: region -> env
    "j",                            # IGNORED: nav mode, env not captured
    "enter",                        # capture: env list
    "j",                            # input: select staging
    "escape",                       # release
    "q",                            # quit
]
```

The "j that gets ignored" at step 12 is pedagogically important — it
demonstrates that navigation mode swallows widget-specific keys. Without
capture, the cursor doesn't move.

## Code Sketch

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Focus & navigation — two-tier capture model for widget interaction.

TestSurface replays a deploy-config form, capturing focus transitions.
The output shows navigation vs capture mode at every zoom level.

    uv run demos/patterns/focus.py -q        # transition count
    uv run demos/patterns/focus.py           # focus timeline
    uv run demos/patterns/focus.py -v        # state snapshots + emissions
    uv run demos/patterns/focus.py -vv       # frames + full trace
"""

from __future__ import annotations
import sys
from dataclasses import dataclass, replace

from painted import (
    Block, CliContext, Style, Zoom,
    border, join_horizontal, join_vertical, pad,
    run_cli, ROUNDED,
)
from painted.palette import current_palette
from painted.tui import (
    Focus, ring_next, ring_prev,
    Surface, TestSurface,
)
from painted.tui import Cursor, Search, filter_fuzzy

# --- Constants ---
ENVIRONMENTS = (...)
SERVICES = (...)
REGIONS = (...)
FOCUS_IDS = ("env", "service", "region")
SCENARIO_KEYS = [...]

# --- Data model ---
@dataclass(frozen=True)
class DeployConfig: ...
@dataclass(frozen=True)
class FocusEvent: ...
@dataclass(frozen=True)
class DemoResult: ...

# --- App under test ---
class DeployForm(Surface):
    def __init__(self): ...
    def render(self) -> None: ...
    def on_key(self, key: str) -> None:
        # THE PATTERN: if captured -> widget; else -> navigation
        ...
    def _handle_captured(self, key: str, widget_id: str) -> None: ...

# --- Extraction ---
def _extract_events(emissions) -> tuple[FocusEvent, ...]: ...
def _fetch() -> DemoResult: ...

# --- Zoom renderers ---
def render_minimal(result: DemoResult) -> Block: ...
def render_summary(result: DemoResult) -> Block: ...
def render_detailed(result: DemoResult, width: int) -> Block: ...
def render_full(result: DemoResult, width: int) -> Block: ...

def _render(ctx: CliContext, result: DemoResult) -> Block: ...

def main() -> int:
    return run_cli(
        sys.argv[1:], render=_render, fetch=_fetch,
        description=__doc__, prog="focus.py",
    )
```

## What Makes This Demo Valuable

### 1. The if/else is the entire focus system

The demo makes the routing pattern explicit. Focus is not a framework
feature that handles dispatch for you — it's a *state primitive* and the
caller writes the if/else. This is the "explicit over implicit" design
philosophy of painted, and it's non-obvious from reading the Focus
dataclass alone.

### 2. Capture mode is invisible until you need it

The widgets.py demo works without capture because all widgets use
different key sets (arrows vs typing). The illusion breaks when two
widgets respond to the same key (j/k in two lists). Capture mode solves
the ambiguity — and the demo's "ignored j" step makes the problem and
solution visible in a single keystroke.

### 3. Search composes with Focus, it doesn't subsume it

Search has its own state (`query`, `selected`) but no concept of focus.
The demo shows Search as a capture-mode behavior: Focus captures, keys
route to Search.type()/Search.backspace(), Escape releases Focus.
Search doesn't know about Focus. Focus doesn't know about Search.
They compose through the caller's routing.

### 4. Navigation helpers are pure functions, not methods

`ring_next(FOCUS_IDS, focus.id)` returns a string. `focus.focus(next_id)`
returns a new Focus. The demo makes the two-step nature visible: compute
the next ID, then transition Focus. This is different from frameworks
where `focus.next()` does both.

### 5. The emission trace teaches Focus lifecycle

The zoom 1 timeline shows the full lifecycle as a sequence:
navigate -> capture -> input -> input -> release -> navigate.
This is the mental model. Reading the Focus class gives you the API.
The timeline gives you the *rhythm* of use.

## Demo Ladder Update

```
patterns/
  rendering.py      Rendering patterns: --explicit, --custom, --palette   done
  fidelity.py       CLI harness: -q -> default -> -v -> -i               done
  live.py           Live streaming: fetch_stream, spinners, --live       done
  testing.py        Replay testing: emit capture, observation traces     done
  profiler.py       Self-profiling: frame cost, emission timeline        done
  focus.py          Focus & navigation: two-tier capture, ring nav       NEW
```

## Deferred

- **Interactive mode (-i)**: A live TUI version of the deploy form where
  you actually Tab/Enter/Escape through widgets in real time. Natural
  Phase B — the static replay teaches the pattern, interactive mode lets
  you feel it.
- **Cursor + Viewport composition**: The demo uses Cursor for list
  selection but doesn't need Viewport (lists are short). A future demo
  with long scrollable lists would teach Viewport.scroll_into_view()
  composed with Cursor.
- **linear_next/linear_prev**: The demo uses ring navigation (Tab wraps).
  Linear navigation (stopping at edges) is appropriate for ordered
  sequences like wizard steps. Deferred until a wizard-pattern demo
  emerges.
