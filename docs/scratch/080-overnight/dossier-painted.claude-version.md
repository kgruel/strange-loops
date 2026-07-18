# Dossier: painted capability triage for the 0.8.0 TUI

Chapter of the 0.8.0 grounding dossier. Empirical survey of what painted (the
rendering library, standalone repo `/Users/kaygee/Code/painted`) provides
TODAY versus what the TUI mocks assume, with exact quotes and file:line
citations. Written 2026-07-17 (overnight run).

Mock corpus referenced throughout: `~/Downloads/Terminal UI for loops/`
(9 lens studies + shell + Static TTY + palettes, per
decision:design/roadmap-060-static-honest-wave).

---

## 0. Version state — what the monorepo actually runs

| Surface | Version | Evidence |
|---|---|---|
| painted repo working tree | `0.12.1` + 8 unreleased commits | `/Users/kaygee/Code/painted/pyproject.toml` (`version = "0.12.1"`); `git describe` → `v0.12.1-8-g5f400de` |
| Monorepo pin | `painted>=0.12.1,<0.13` | `/Users/kaygee/Code/loops/pyproject.toml:17` |
| App declarations | bare `"painted"` (workspace pin governs) | `/Users/kaygee/Code/loops/apps/loops/pyproject.toml:6`, `apps/tasks/pyproject.toml:6`, `apps/hlab/pyproject.toml:7` |
| Workspace venv | `0.12.1` | `/Users/kaygee/Code/loops/.venv/lib/python3.13/site-packages/painted-0.12.1.dist-info` |
| Installed CLI (`sl`/`loops`) | `0.12.1` | `~/.local/bin/sl` → `~/.local/share/uv/tools/strange-loops/bin/sl`; that tool venv carries `painted-0.12.1.dist-info` |

The prompt's "consumed from PyPI at 0.12.1" is **confirmed** at every layer.
The load-bearing addition: painted's `main` is **8 commits ahead of the
released 0.12.1**, and all 8 are the 0.13 host-rung arc — directly relevant
to the TUI session but **not installable from PyPI yet**:

```
5f400de host-rung S2: evidence-row builder + frame assembly — evidence_row/assemble_frame
        public in painted.views, IconSet scroll slots ...
7a3907b host-rung S1: height declaration + offer matrix — HeightRenderer protocol,
        height_renderer= binding, _RendererBinding record, three-row offer matrix ...
57e7799 docs(design): ratify HOST_RUNG_DESIGN — PLANNED → RATIFIED (Kyle, 2026-07-15)
b3be094 docs(design): mint HOST_RUNG_DESIGN.md (PLANNED) — 0.13/M6 arc opened
```
(`git log --oneline v0.12.1..HEAD` in the painted repo)

painted's only runtime dependency is `wcwidth>=0.2`
(`/Users/kaygee/Code/painted/pyproject.toml`, `dependencies` list). There is
**no Textual/urwid/etc. anywhere** — painted's TUI layer is its own.

---

## 1. Painted's Surface/App loop today — event model, refresh model

The interactive substrate is `painted.tui` (`src/painted/tui/__init__.py:1-61`
exports: `Surface`, `Emit`, `LifecycleHook`, `Buffer`/`BufferView`/`CellWrite`,
`KeyboardInput`/`Input`, `MouseEvent`/`MouseButton`/`MouseAction`,
`Layer`/`Stay`/`Pop`/`Push`/`Quit`/`process_key`/`render_layers`,
`Focus` + ring/linear helpers, `Search` + filters, `Cursor`/`CursorMode`,
`Region`, `TestSurface`/`CapturedFrame`).

### The Surface base class (`src/painted/tui/surface.py`)

> "Base class for buffer-rendered applications. Subclasses override layout(),
> render(), and on_key() to build interactive terminal UIs using the
> cell-buffer rendering system." (surface.py:38-43)

Constructor knobs (surface.py:45-57): `fps_cap=60`, `enable_mouse=False`,
`mouse_all_motion=False`, `scroll_optimization`, `on_emit`, `on_start`,
`on_stop` (async lifecycle hooks), `no_color`.

**The run loop** (surface.py:85-171) is a single asyncio task on the alt
screen: enter alt screen → hide cursor → size buffers → `layout(w,h)` →
install SIGWINCH handler → then per iteration:

1. **Drain all pending input** non-blocking (surface.py:121-143):
   `self._keyboard.get_input()` until `None`; each `MouseEvent` →
   `self.on_mouse(inp)` + `emit("ui.mouse", ...)`, each key →
   `self.on_key(inp)` + `emit("ui.key", ...)`; any input sets `_dirty`.
2. **`self.update()`** every iteration — "Called every iteration. Override to
   advance animations/timers. Call mark_dirty() if state changed and a
   re-render is needed." (surface.py:176-180)
3. **Render only if dirty** (surface.py:149-153): inside `_frame_scope()`
   (the capability bracket — NO_COLOR/depth/glyph/hyperlink resolved from the
   Surface's own writer, surface.py:185-221), call `self.render()` then
   `self._flush()`.
4. **Adaptive frame sleep** (surface.py:25-35, 159-162): when input flowed or
   a re-render is queued, yield `MIN_YIELD = 0.001`; otherwise sleep only the
   *remainder* of the frame period ("a slow render shortens the sleep instead
   of stretching the frame").

**Refresh model**: diff-based. `_flush()` diffs current vs previous `Buffer`
and writes only changed cells (`self._buf.diff(self._prev)` →
`writer.write_frame(writes)`, surface.py:294-310), with an opt-in
vertical-scroll optimization that emits a `ScrollOp` + repaint of changed
lines when a scroll region is detected (surface.py:312-396, gated by
`PAINTED_SCROLL_OPTIM` env or `scroll_optimization=`).

**Input model**: cbreak, not raw — "``tty.setcbreak`` disables ECHO and ICANON
but leaves ISIG on" (keyboard.py:10-12); "Two reader shapes over one cbreak
session: ``get_input``/``get_key`` are *non-blocking* (the ``Surface`` render
loop polls between frames), and ``read_key`` *blocks* for one key"
(keyboard.py:14-16). Mouse arrives as SGR-parsed `MouseEvent`s through the
same stream (`src/painted/mouse.py`).

**Resize**: SIGWINCH → `_on_resize` → new buffers, `layout(w,h)`,
`_needs_clear`, `emit("ui.resize", ...)` (surface.py:280-292).

**Hit testing**: `Surface.hit(x, y)` — "Return the semantic ref at a screen
coordinate, if any" (surface.py:229-236), backed by refs painted into the
Buffer.

**Modal stacking**: `Layer` (tui/layer.py:46-58) bundles
`name/state/handle/render`; `process_key` routes a key to the top layer and
interprets `Stay | Pop | Push | Quit` actions (layer.py:61-98);
`render_layers` paints "bottom-to-top into buffer" (layer.py:101-110).
`Surface.handle_key(...)` wraps `process_key` and auto-emits
`ui.action action=quit/pop/stay` (surface.py:243-270).

**State primitives** (all frozen dataclasses): `Cursor` — "Bounded cursor
position over a domain of `count` items", CLAMP/WRAP modes (cursor.py:16-30);
`Viewport` — "Scroll state for a vertically-scrollable view. Tracks offset
(first visible row), visible height, and content height ... Use with vslice()"
(viewport.py:8-18); `Region` — "A named rectangular area of the buffer" with
`.view(buffer) -> BufferView` (tui/region.py:10-21); `Focus`, `Search`.

**Testing**: `TestSurface` — "Deterministic Surface runner for tests" with an
input queue and captured frames/emissions (tui/testing.py:63-100).

### The live-CLI tier beside it

- `InPlaceRenderer` (`src/painted/inplace.py:1-11,91`) — "ephemeral liveness
  in the scrollback ... Sustained animation belongs on the alt screen
  (Surface), which is immune."
- `StreamSurface` (`src/painted/cli/stream_surface.py:45-65`) — "Generic
  stream-consuming Surface. **Private to the cli package.**" It hosts an app
  `fetch_stream()` async iterator as a task next to the render loop; each
  yielded state is stored atomically and triggers `mark_dirty()`
  (stream_surface.py:169-219). Keys: `q`/ctrl-c quit, space pauses
  (stream_surface.py:276-280).

---

## 2. Triage item (1): temporal scrubber widget — MISSING

**No scrubber, slider, or timeline-drag widget exists in painted.** Empirical
check: `grep -rniE "scrub|slider|toast|notif|banner|flash" src/` in the
painted repo matches only `scrub_control` (C0/C1 control-character scrubbing,
core/cell.py:62) and its prompt-line consumers. `grep -rniE "timeline"`
matches only `record_timeline` (views/record.py:393) — a **static**
"chronological timeline of records, grouped by date" render, not interactive.

The component roster (`src/painted/views/components/__init__.py:1-37`) is:
spinner, progress_bar, list_view, text_input, table, sparkline /
sparkline_with_range, cost_meter, data_explorer. Nothing positional-drag.

What the mock wants (Rewind View.dc.html:32-42):

```
  ◀◀ rewind                                       now · Jan 15
  ████████████████████████████░░░░░░░░░░░░░░░░░
                              ▲
  asof Fri Jan 10 · 17:00   ·   the mark is a cursor, not a cutoff   ·   rewound 4d 19h
```

> "In the TUI this is the one view that literally wants a scrubber — drag the
> ruler and every other lens (fold, stream, graph) reframes to that instant;
> release on now and you're live again." (Rewind View.dc.html:109)

> "And it's Rewind's twin on one control: drag the scrubber back to review,
> release on now and you're watching again." (Watch View.dc.html:89)

**Nearest existing primitives to build from**: `Cursor` (bounded index state,
cursor.py:16-30) for the mark position; `progress_bar`
(views/components/progress.py:27) for the filled/empty bar rendering; mouse
drag events (`MouseEvent` with `mouse_all_motion=True`, surface.py:50,
mouse.py). The composition would be consumer-side or a new painted component;
painted's `ROADMAP_1.0.0.md` does not schedule a scrubber anywhere
(no match for scrub/slider/timeline in that file).

---

## 3. Triage item (2): toast/notification — MISSING

**No toast, notification, or timed-overlay primitive exists** (same grep as
above). What the mock does (Loops TUI.dc.html:374):

```js
toast(msg){ if(this._tt)clearTimeout(this._tt); this.setState({toast:msg});
            this._tt=setTimeout(()=>this.setState({toast:null}),2800); }
```

rendered as an absolutely-positioned overlay bottom-right
(Loops TUI.dc.html:590: `position:'absolute',right:'18px',bottom:'62px',...
border:'1px solid '+t.success`), fired after emit actions:
`'✓ stored  '+id+'  →  '+v+' · '+kind`, `'⚠ stored orphaned  '+id+...`,
`'◦ dry-run — '+kind+' validated, not stored'` (Loops TUI.dc.html:430-448).

**Nearest existing pieces**:

- `callout` (views/components/_callout.py:1-12) — "a severity-tagged message
  line (or boxed panel) ... a colored severity glyph plus a message ... The
  severity drives BOTH the glyph (from the ambient IconSet) and the color
  (from the ambient Palette role)". Static Block; no positioning, no timer,
  no dismissal.
- `Layer` stacking (layer.py) gives the overlay mechanism (top layer renders
  last, bottom-to-top, layer.py:101-110) — a toast could be a pushed layer.
- Timed auto-dismiss has a natural home in `Surface.update()` ("advance
  animations/timers", surface.py:176-180) — but nothing packaged exists. The
  only "timer" in painted is `_timer.py` = "FrameTimer: per-phase timing for
  render loop profiling" (_timer.py:1), unrelated.

---

## 4. Triage item (3): theme roles — mock wants 17 slots, Palette carries 5 roles (+ substrate)

### What Palette IS (quote)

Full class body, quoted without elision from
`/Users/kaygee/Code/painted/src/painted/palette.py:58-131`:

```python
@dataclass(frozen=True)
class Palette:
    """Ambient color policy: semantic roles plus a categorical ramp.

    Two distinct color concepts, both delivered as Styles (not Colors) so
    monochrome palettes can differentiate with modifiers (bold, underline,
    dim) instead of hue:

    * **Semantic roles** (``success``/``warning``/``error``/``accent``/
      ``muted``) map *meaning* to style — "what does this value signify?"
    * **``series``** is a *categorical* (qualitative) ramp — distinct,
      "just-different" styles indexed by *position*, with no inherent
      meaning — "make these N peers visually separable."

    The two are independent: a palette's ``series`` need not relate to its
    roles. (That DEFAULT's first four happen to echo the role hues is a
    historical coincidence — it reproduces the original flame cycle — not a
    coupling.) The label->index assignment that consumes ``series`` lives in
    ``flame_lens`` today; it is the general form a reusable ramp helper would
    factor out, once a second consumer exists.
    """

    success: Style = field(default_factory=lambda: Style(fg="green"))
    warning: Style = field(default_factory=lambda: Style(fg="yellow"))
    error: Style = field(default_factory=lambda: Style(fg="red"))
    accent: Style = field(default_factory=lambda: Style(fg="cyan"))
    muted: Style = field(default_factory=lambda: Style(dim=True))
    # Substrate ownership: the default style for otherwise-unstyled content.
    # ``text`` supplies a foreground (and any attributes) wherever a cell's
    # ``Style`` leaves ``fg`` unset; ``surface`` supplies a background wherever
    # ``bg`` is unset. Both default to ``None`` — the terminal's own fg/bg, i.e.
    # today's behavior byte-for-byte. An explicit ``fg``/``bg`` on the cell always
    # wins. This lets a Theme own "body text" (and optionally a base canvas)
    # rather than coloring only the five roles. See ``resolve_style`` and the
    # writer's emission boundary. (Roles are *meaning*; ``text``/``surface`` are
    # the *substrate* those roles sit on.)
    text: Style | None = None
    surface: Style | None = None
    series: tuple[Style, ...] = field(
        default_factory=lambda: (
            Style(fg="red"),
            Style(fg="yellow"),
            Style(fg="green"),
            Style(fg="cyan"),
        )
    )

    def resolve_style(self, style: Style) -> Style:
        """Resolve a cell ``Style`` against this palette's substrate defaults.

        ``text`` is layered *under* the cell style (so the cell's explicit
        ``fg``/attributes win) and ``surface`` supplies the base ``bg``. When
        both are ``None`` the input is returned unchanged — identity, so output
        is byte-identical to a palette without a substrate. This is the single
        point where the ambient palette reaches the SGR-emission boundary; the
        writer's ``Style → SGR`` conversion stays pure.
        """
        base: Style | None = self.text
        if self.surface is not None:
            base = self.surface if base is None else base.merge(self.surface)
        if base is None:
            return style
        return base.merge(style)

    def series_for(self, key: str) -> Style:
        """Deterministic ``series`` style for ``key`` — the open-set assignment.

        For dynamic sets that can't be enumerated at declaration time (chart
        lines, observers arriving at runtime, unknown vocabulary members under
        ``overflow="series"``): the same key always maps to the same ramp style.
        An empty ramp yields a bare ``Style()``. See ``series_index``.
        """
        ramp = self.series
        return Style() if not ramp else ramp[series_index(key, len(ramp))]
```

Count: **five named semantic color roles** (`success`, `warning`, `error`,
`accent`, `muted`); **seven named style slots** if the foreground/background
substrates (`text`, `surface`) are included; and eight dataclass fields if the
positional `series` ramp is counted. Thus “Palette's 5” is true only in the
semantic-role sense used by Painted's own module docstring
(`/Users/kaygee/Code/painted/src/painted/palette.py:1-5`).

`CORE_ROLE_NAMES = frozenset({"success", "warning", "error", "accent",
"muted", "text"})` (palette.py:35). Presets: `DEFAULT_PALETTE`,
`NORD_PALETTE`, `MONO_PALETTE`, `PAINTED_PALETTE` (palette.py:136-188).
`Palette.resolve_style` layers `text`/`surface` under cell styles at the SGR
boundary (palette.py:105-120).

### What the mock wants (quote)

`Loops TUI.dc.html:30-38` defines `THEMES` with **7 palettes** (PAINTED,
DEFAULT, NORD, MONO, SIGNAL, TEMPORAL, STRANGE), each carrying exactly these
**17 keys** (MONO adds an 18th boolean `mono:true`):

```js
PAINTED: {bg:'#0b0e13',win:'#0c1016',bar:'#12161d',border:'#1b212b',
          text:'#c3c8d2',bright:'#eef1f6',body:'#a7aeba',muted:'#79808f',
          accent:'#44e0e0',success:'#4fdc82',warning:'#f5cf52',error:'#ff5b6a',
          refIn:'#f5cf52',refOut:'#d7af5f',stale:'#ff9d4d',
          selBg:'#13202e',selBar:'#44e0e0'},
```

Note the mock's PAINTED role hexes match painted's `PAINTED_PALETTE` exactly
(`#4fdc82/#f5cf52/#ff5b6a/#44e0e0/#79808f`, palette.py:172-177) — the mock
was drawn against the real palette. The palettes study itself says: "Each maps
painted's five semantic roles plus a categorical observer ramp onto a calm
terminal substrate." (Loops Palettes.dc.html:26)

### Gap analysis — the prompt's "Palette has 5" needs refinement

The 17 mock slots decompose against what painted has:

| Mock slot | Painted today | Status |
|---|---|---|
| `success, warning, error, accent, muted` | the 5 core roles (palette.py:80-84) | EXISTS |
| `text` | `Palette.text` substrate (palette.py:94) | EXISTS (0.12 substrate slot) |
| `bg` | `Palette.surface` substrate (palette.py:95) | EXISTS (as base canvas) |
| `refIn, refOut, stale` | app-declarable roles via `Role`/`Vocabulary` + `Theme.roles` overrides | EXTENSIBLE TODAY, consumer-side declaration |
| `bright, body` | nothing (two extra foreground tiers between `text` and `muted`) | MISSING |
| `win, bar` | nothing (window/statusbar chrome backgrounds distinct from `bg`) | MISSING |
| `border` (a color) | `BorderChars` themes border *glyphs* only (theme.py:69, core/borders) — no border-color slot | MISSING |
| `selBg, selBar` | nothing (selection background + selection accent bar) | MISSING |

The extensibility path that already exists: "Declaring the role is what makes
the value *themeable* rather than hardcoded: a palette or theme overrides an
app role by name (``Theme(roles={"stale": Style(...)})``) exactly as it
overrides a core role." (vocabulary.py:71-76, `Role` docstring; `Theme.roles`
described at theme.py:49-60, "Role overrides are **forward-tolerant by
design**"). `mark_style(vocab_name, value)` is "the single point where a
value becomes a ``Style``" (vocabulary.py:19-20). Theme composes
Palette + IconSet + BorderChars + roles as one ambient unit
(theme.py:40-70, `use_theme` theme.py:131-147).

**So the honest statement**: painted has 5 *meaning* roles + 2 *substrate*
slots + a series ramp + an open app-role mechanism. The irreducible gap for
the mock is the **7 chrome slots** (`bright, body, win, bar, border-color,
selBg, selBar`) — chrome/selection is a category Palette deliberately does
not model today ("Roles are *meaning*; ``text``/``surface`` are the
*substrate* those roles sit on", palette.py:92-93). `refIn/refOut/stale` need
no upstream change, only a loops-side vocabulary declaration.

---

## 5. Triage item (4): external-change feed into Surface — PATTERN EXISTS, API DOES NOT

**Can a Surface be updated from outside an input event? Yes — three working
routes today, none of them a first-class "change feed" API:**

1. **Poll in `update()`**: called every loop iteration regardless of input
   (surface.py:146, 176-180); call `mark_dirty()` (surface.py:272-274,
   sets `self._dirty = True`). Wakeup latency is bounded by the frame sleep
   (≤ 1/fps_cap when idle, surface.py:159-162).
   *Live consumer precedent in this monorepo*:
   `AutoresearchApp` (apps/loops/src/loops/tui/autoresearch_app.py:540-609) —
   `fps_cap=10`, `self._refresh_interval = 2.0`, `update()` re-runs
   `fetch_fold(...)` on the timer and calls `self.mark_dirty()`
   (autoresearch_app.py:605-609, 569-603). Its header admits the model:
   "Live-refreshes to show in-progress iteration activity as it streams in"
   (autoresearch_app.py:5-6) — a full re-fetch every 2s, cursor/focus/scroll
   manually preserved across reloads (autoresearch_app.py:585-599).
2. **Spawn a consumer task in `on_start`**: the async lifecycle hook runs
   inside the loop (surface.py:116-117). `StreamSurface` is the canonical
   form — `_spawn` creates an asyncio task that iterates the app's
   `fetch_stream()` and calls `self.mark_dirty()` per state
   (stream_surface.py:149-151, 169-211). Caveat: it is "Private to the cli
   package" (stream_surface.py:46) and has no key routing beyond q/space.
3. **Any code with a reference can call `mark_dirty()`** — it is a plain
   attribute write; but ContextVar-based ambient state (palette, vocabularies,
   refs) "does not cross threads" (vocabulary.py:38-39), so cross-thread
   feeding must confine rendering to the loop task.

**What does NOT exist**: an inward event-injection seam (no
`post_event()`/queue/channel; `Surface.emit()` is outward-only — "Emit an
observation", surface.py:238-241). This is explicitly scheduled as 0.13
design territory in painted's roadmap:

> "The inward host-event seam is designed here, against the streaming/
> interactive consumer app — and stays separate from `Surface.emit()`, which
> remains an outward observation channel." (ROADMAP_1.0.0.md, Milestone 6
> "0.13", lines ~266-269)

This aligns with the loops-side framing (thread:080-design-wave, session 2):
ticked's poll, Watch's change-detection, and TUI live-refresh are "the SAME
missing primitive ... change feed into an event loop" — on the painted side
the receiving half of that seam is ratified-but-unbuilt.

---

## 6. Triage item (5): renderer-contract adoption state

The contract as painted defines it (`src/painted/core/renderer.py:5-14`):

```
def renderer(data, fidelity: Fidelity, width: int | None) -> Block: ...
```

> "data — domain state, whatever ``fetch`` produced; painted never interprets
> it. fidelity — the compiled disclosure spec, intact (never decomposed into
> kwargs). width — the offered allocation ... returns — a content ``Block``;
> never writes, never exits, never consults delivery."

`Renderer` is a plain Callable alias (renderer.py:45); status per
HOST_RUNG_DESIGN.md:12-13: "Companion to `docs/RENDERER_CONTRACT_DESIGN.md`
(IMPLEMENTED 0.11/0.12)". Note the prompt wrote "renderer=(data,fidelity,width)"
— confirmed, that is the shape.

**Adoption in apps/loops — two-tier, migration incomplete:**

- **Command-level renderers: ADOPTED.** Inline `def renderer(data, fidelity,
  width)` closures passed to `run_cli` throughout: commands/store.py:1246,
  1324, 1403; commands/sync.py:173, 320; commands/population.py:81;
  commands/ticks.py:110, 155; commands/stream.py:92; commands/ls.py:204, 523;
  commands/devtools.py:86, 192, 255; cli/dispatch.py:397.
- **Lens layer: NOT migrated — still the legacy Zoom shape.**
  `LensRenderFn = Callable  # (data, zoom: Zoom, width: int | None) -> Block`
  (lens_resolver.py:46); built-ins e.g. `compile_view(data, zoom: Zoom, ...)`
  (lenses/compile.py:9), `run_facts_view` (lenses/run.py:17), `test_view`
  (lenses/test.py:16), `sync_view` (lenses/sync.py:51). apps/loops/CLAUDE.md
  still states the convention: "Lenses are pure: `(data, zoom, width) ->
  Block`."
- **The bridge**: `zoom_from_fidelity` — "Adapt the renderer contract's open
  depth to a legacy lens Zoom ... the one compatibility seam that owns its
  required two-sided clamp" (`Zoom(min(max(fidelity.depth, 0), 3))`,
  lens_resolver.py:49-65), applied inside `call_lens(fn, data, fidelity,
  width, **kwargs)` which also signature-sniffs optional lens kwargs
  (lens_resolver.py:461-490). Some lenses additionally take a `piped=`
  register kwarg (the register-split parity concern, apps/loops/CLAUDE.md
  "Register-split lenses need a parity test").

So: **one seam, two vocabularies** — `Fidelity` above `call_lens`, clamped
`Zoom` below it. This is the "zoom-signature unification" follow-up named in
MEMORY (painted-011-adoption) and the "ONE coordinated lens-signature
migration instead of three" item in thread:080-design-wave session 3.

**Height-aware extension (unreleased)**: `HeightRenderer` protocol —
`(data, fidelity, width, *, height: int | None) -> Block`, "When passed an
integer ``H`` the returned Block must have exactly ``H`` rows"
(renderer.py:48-74) — plus the `height_renderer=` binding on the CLI runner
(cli/runner.py:144, 259-272) and `evidence_row`/`assemble_frame` in
`painted.views` (views/__init__.py:64-65, 176-177) landed on painted main as
host-rung S1/S2 (commits 7a3907b, 5f400de) but are **not in any release the
monorepo can install** (pin is `<0.13`, PyPI has 0.12.1).

---

## 7. Triage item (6): TUI-app layer — what lives in painted vs the consumer

**In painted** (`painted.tui`): the generic substrate only — Surface loop,
Buffer diffing, keyboard/mouse, Layer stack, Focus/Search/Cursor/Viewport/
Region, TestSurface (section 1 above). Plus the cli-private `StreamSurface`
(alt-screen live delivery for `run_cli`'s live mode) and `InPlaceRenderer`
(scrollback liveness). There is **no application framework** — no
widget-tree, no bindings table, no screens/router, no CSS-like theming beyond
Theme/Palette ambient state.

**The gap painted itself names**: HOST_RUNG_DESIGN.md:21-31 (RATIFIED
2026-07-15, status flips "to IMPLEMENTED at ship"):

> "Three rungs honor that today: `print_block` (STATIC), `InPlaceRenderer` and
> `StreamSurface` (LIVE). The fourth — interactive `Surface` — does not: a
> Surface app paints a `Buffer` directly, so reusing a CLI command's renderer
> in a TUI means hand-rolling the glue every consumer has hand-rolled
> (evidence, §8). The host rung is the Block-returning path around `Surface`:
> a semantic renderer produces a content Block; a host-rung adapter owns the
> frame — viewport, scroll state, evidence, chrome, input routing, hit
> testing."

0.13 exit criteria (ROADMAP_1.0.0.md:274-280): "One reference renderer works
through `print_block`, `InPlaceRenderer`, `StreamSurface`, and interactive
`Surface` delivery ... Existing direct Buffer-painting Surface applications
remain supported." As of 2026-07-17 only S1 (height declaration) and S2
(evidence/frame assembly) have landed; the Surface-side adapter itself
(viewport wiring, input routing, the inward event seam) is not built.

**In the consumer (apps/loops)** — two hand-rolled direct-Buffer Surface apps,
exactly the pattern the host rung means to replace:

- `StoreExplorerApp(Surface)` (`src/loops/tui/store_app.py:84`), launched via
  `loops store <db> -i`. Imports `from painted.tui import Surface`
  (store_app.py:17), frozen-dataclass state (`StoreExplorerState`,
  store_app.py:33-45), quits on `q`/`Q`/`escape` (store_app.py:130-132 — the
  key the 080 thread flags as colliding with the mock's `q`=zoom-out).
- `AutoresearchApp(Surface)` (`src/loops/tui/autoresearch_app.py:540`),
  launched via `loops read VERTEX --lens autoresearch -i`; the 2s-poll
  live-refresh described in section 5.

Naming hazard for downstream sessions: `src/loops/surface.py` is **not** a
painted Surface — it is "surface — the typed, addressable projection between
fetch and render" (surface.py:1-3), the loops data keystone, "PAINTED-FREE"
(surface.py:26). Two unrelated `Surface` types coexist in the same app.

---

## 8. Summary matrix

| Capability | State | Where |
|---|---|---|
| Interactive event loop (alt screen, input drain, dirty-flag render, diff flush) | EXISTS | painted.tui.Surface (surface.py:85-171) |
| Mouse (SGR), hit-testing by ref | EXISTS | surface.py:127-138, 229-236; mouse.py |
| Modal layers, focus, search, cursor, viewport, region | EXISTS | painted.tui exports |
| Headless test harness | EXISTS | tui/testing.py:63 |
| Scrubber / slider / draggable timeline | **MISSING** | no match in painted src; not on roadmap |
| Toast / timed notification overlay | **MISSING** | no match; nearest = static `callout` + Layer stack |
| 5 semantic roles + text/surface substrate + series ramp | EXISTS | palette.py:58-103 |
| App-declared roles themable by name (refIn/refOut/stale) | EXISTS (mechanism) | vocabulary.py Role; theme.py:49-60 |
| Chrome slots (bright, body, win, bar, border-color, selBg, selBar) | **MISSING** (7 of the mock's 17) | no Palette/Theme fields |
| External update → repaint (poll/task + mark_dirty) | EXISTS (pattern) | surface.py:176-180, 272-274; stream_surface.py:169-211; autoresearch_app.py:605-609 |
| Inward host-event seam (injection API) | **MISSING** — ratified 0.13 design item | ROADMAP_1.0.0.md M6 |
| `(data, fidelity, width) -> Block` contract | EXISTS (painted 0.11/0.12); adopted at loops command tier | core/renderer.py:45 |
| Same contract at loops lens tier | **NOT migrated** — Zoom clamp bridge | lens_resolver.py:46-65, 461-490 |
| Height-aware renderer + frame assembly | EXISTS on painted main, **UNRELEASED** (post-0.12.1) | renderer.py:48-74; commits 7a3907b, 5f400de |
| Block-through-Surface host adapter (0.13 exit criterion) | **NOT BUILT** | HOST_RUNG_DESIGN.md:1-8; roadmap M6 |
| TUI app shell (tabs, command bar, composer) | consumer territory; two hand-rolled precedents | loops tui/store_app.py, tui/autoresearch_app.py |

### Missing-item ownership

| Missing item | Can loops build it downstream on 0.12.1? | Upstream requirement |
|---|---|---|
| Temporal scrubber widget | **Yes.** Compose `Cursor`, `progress_bar`, `MouseEvent`, hit refs, and `Surface.on_mouse`; keyboard-only scrubbing is simpler still. | None for the 0.8.0 feature. Upstreaming would only make it reusable and standardized. |
| Toast/timed notification | **Yes.** Store message/deadline in app state, render last as a `Layer`, expire it from `update()`, then `mark_dirty()`. | None. A generic Painted component is convenience, not a gate. |
| Seven mock chrome/selection slots | **Yes.** Keep a loops-owned 17-slot theme dataclass; use Painted `Style`s and declare `refIn/refOut/stale` through `Vocabulary`/`Theme.roles`. | Upstream only if these chrome names must become portable Painted-wide contracts. They do not need to block 0.8.0. |
| First-class inward event injection API | **Yes for the concrete file-watcher/queue use case.** Poll a queue in `update()`, or spawn an async consumer from `on_start`, mutate app state on the loop task, and call `mark_dirty()`. | **Yes only for a generic, supported host-event seam** with wakeup/ordering/thread-safety semantics; Painted schedules that for 0.13. |
| Block-through-Surface host adapter | Direct Buffer painting remains possible, so a loops TUI can ship without it; renderer reuse requires consumer glue. | **Upstream** for the promised universal renderer host rung and removal of duplicated glue. |

The roadmap claim “painted ALREADY HAS the interactive substrate — no
upstream build gate” is therefore **substantially true for shipping a direct-
Buffer 0.8.0 TUI**: terminal ownership, asyncio loop, keyboard/mouse, resize,
dirty rendering, diff flush, layers, state helpers, and testing already exist.
It is false if interpreted as “Painted already has every reusable widget,
inbound event abstraction, or renderer-to-Surface adapter.”

### Version-skew risks: Painted main versus the PyPI pin

The lock resolves the published artifact, not the sibling checkout:
`/Users/kaygee/Code/loops/uv.lock:598-606` names `painted` 0.12.1 and its PyPI
sdist/wheel; `/Users/kaygee/Code/loops/pyproject.toml:17` permits
`>=0.12.1,<0.13`; `/Users/kaygee/Code/loops/apps/loops/pyproject.toml:6` merely
declares bare `painted`. Consequently:

- The canonical three-argument contract has **no skew**: v0.12.1 defines
  `Renderer = Callable[[T, "Fidelity", "int | None"], "Block"]`
  (`v0.12.1:/Users/kaygee/Code/painted/src/painted/core/renderer.py:40`), and
  main retains exactly that alias
  (`/Users/kaygee/Code/painted/src/painted/core/renderer.py:45`).
- Main adds an **unreleased parallel contract**, `HeightRenderer(data,
  fidelity, width, *, height=...)`, at
  `/Users/kaygee/Code/painted/src/painted/core/renderer.py:48-74`, together
  with runner binding/frame helpers. Code developed against the sibling
  checkout can import or call these successfully and then fail under the
  monorepo's locked 0.12.1.
- The audited `Palette`, `Surface`, and keyboard machinery are unchanged from
  v0.12.1 (`git diff v0.12.1..HEAD --` for those files is empty), so the
  scrubber/toast/external-update conclusions apply to the installed pin as
  well as main.
- The `<0.13` ceiling means a future 0.13 release will **not** be selected
  automatically. Consuming the host-rung work requires an explicit pin bump,
  lock refresh, and compatibility pass; copying unreleased APIs downstream
  now risks duplicate abstractions and later migration.

## 9. Corrections / refinements to the prompt's assertions

1. **"Palette has 5"** — true for *semantic roles*, but incomplete: Palette
   also carries `text`/`surface` substrate slots and the `series` ramp
   (palette.py:94-103), and the Role/vocabulary system already makes
   meaning-roles (the mock's `refIn/refOut/stale`) declarable without any
   painted change. The real upstream gap is 7 chrome/selection slots, not 12.
2. **"consumed from PyPI at 0.12.1"** — confirmed everywhere, but painted
   main is 8 commits ahead with the 0.13 host-rung S1/S2 already merged
   (HeightRenderer, evidence_row/assemble_frame). A TUI design that wants
   them must either wait for a painted 0.13 release + pin bump (current pin
   `<0.13`, pyproject.toml:17) or scope to 0.12.1.
3. **"renderer contract renderer=(data,fidelity,width) adoption state"** —
   shape confirmed; adoption is split: loops command renderers speak
   Fidelity, all lenses still speak Zoom through the `zoom_from_fidelity`
   clamp (lens_resolver.py:49-65). "Adopted" is only true above the
   `call_lens` seam.
4. **External-change feed** — the question "can a Surface be updated from
   outside an input event?" is **yes** today (update()/mark_dirty polling,
   on_start-spawned tasks; two shipped precedents). What's missing is a
   first-class inbound event/queue API — explicitly deferred by painted to
   the 0.13 host-rung ("the inward host-event seam is designed here").
