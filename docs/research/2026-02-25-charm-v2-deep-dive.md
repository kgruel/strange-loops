# Charm v2 Deep Dive (Bubble Tea v2, Lip Gloss v2, Bubbles v2)

Date: 2026-02-25  
Audience: `fidelis` (Python, cell-buffer TUI)

## Status Snapshot (as of 2026-02-25)

- Bubble Tea `v2.0.0` released on 2026-02-24: https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0
- Lip Gloss `v2.0.0` released on 2026-02-24: https://github.com/charmbracelet/lipgloss/releases/tag/v2.0.0
- Bubbles `v2.0.0` released on 2026-02-24: https://github.com/charmbracelet/bubbles/releases/tag/v2.0.0
- All three Go modules moved to vanity import paths under `charm.land` (e.g. `charm.land/bubbletea/v2`): Bubble Tea release notes + upgrade guide.
- A shared lower-level foundation, **Ultraviolet**, powers key parts of Bubble Tea v2 and Lip Gloss v2: https://github.com/charmbracelet/ultraviolet
  - Note: Ultraviolet’s README explicitly says it exists to serve internal use cases and has **no stability guarantees** (yet).

## Executive Summary (What Matters for `fidelis`)

- **The big v2 move is “declarative terminal state.”** Bubble Tea v2 replaces imperative “enter alt screen / enable mouse / hide cursor…” commands and program options with fields on the value returned by `View()`. This is a direct answer to v1 “state fights” and is extremely aligned with `fidelis`’s “pure render returns everything needed.”  
  - Sources: Bubble Tea upgrade guide + v2 “What’s New” discussion. https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md, https://github.com/charmbracelet/bubbletea/discussions/1374
- **The renderer is now truly cell-based and diff-driven (“Cursed Renderer”).** Bubble Tea v2 parses the rendered ANSI string into cells, writes it into a screen buffer, and emits minimal terminal updates using an ncurses-inspired algorithm (Ultraviolet).  
  - Sources: Bubble Tea v2.0.0 notes + Ultraviolet README + renderer code. https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0, https://github.com/charmbracelet/ultraviolet, https://github.com/charmbracelet/bubbletea/blob/v2.0.0/cursed_renderer.go
- **Lip Gloss v2 was made “pure” by removing its renderer and moving capability decisions to the output layer.** Styles become deterministic value types; downsampling and background detection become explicit at boundaries. This eliminates I/O contention and makes the stack composable (local, redirected, SSH, etc.).  
  - Sources: Lip Gloss v2.0.0 notes + upgrade guide. https://github.com/charmbracelet/lipgloss/releases/tag/v2.0.0, https://github.com/charmbracelet/lipgloss/blob/v2.0.0/UPGRADE_GUIDE_V2.md
- **Ultraviolet is the real architectural “why.”** Charm’s v2 story is: build a production-grade, cross-platform terminal substrate (input + cell rendering + diffs + correctness), then rebase Bubble Tea/Lip Gloss/Bubbles on top.  
  - Sources: Charm blog v2 post + “Crush, Welcome Home” + Ultraviolet README. https://charm.land/blog/v2.md, https://charm.land/blog/crush-comes-home.md, https://github.com/charmbracelet/ultraviolet

### Explicit `fidelis` Callouts (high-signal)

- **`fidelis already does:`** frozen state + pure render, cell buffers, diff rendering, capability resolution at Writer boundaries.
- **`fidelis should consider:`**
  - Make terminal “mode requests” a first-class part of the render output (Bubble Tea’s `tea.View` is the proof this pays dividends).
  - Adopt a **damage model** (touched lines / dirty ranges) as an internal performance primitive, not just “compare whole buffers.”
  - Add optional support for terminal correctness/perf modes analogous to Bubble Tea’s “synchronized output” (mode 2026) and “Unicode core” (mode 2027) where appropriate.
- **`interesting but not applicable:`**
  - The `charm.land` vanity import path change is Go-module-specific; the *idea* (stable import surface + ecosystem cohesion) matters, not the mechanism.

---

## 1) Architectural Changes in Bubble Tea v2 (the “why”, not just “what”)

### v1 Pain: imperative terminal control + I/O contention

Bubble Tea v1 mixed:
- program startup options (`WithAltScreen`, `WithMouse…`) set at `NewProgram`, and
- runtime commands (`EnterAltScreen`, `EnableMouse…`, `SetWindowTitle…`) emitted from `Update`.

In isolation that works. In a real app, it creates **distributed authority** over terminal state: multiple components and libraries can fight over “who owns” alt-screen, mouse tracking, bracketed paste, focus reporting, and other features.

Charm explicitly calls out that Bubble Tea and Lip Gloss v1 could “fight over I/O” (Bubble Tea reading input while Lip Gloss queried terminal state), producing lockups.  
Source: Bubble Tea v2.0.0 release notes section “No more fighting”. https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0

### v2 Answer: “Declarative Views”

Bubble Tea v2 makes `View()` return a `tea.View` value (not `string`), with fields that declare:
- terminal modes (`AltScreen`, `MouseMode`, `ReportFocus`, bracketed paste),
- window-level state (`WindowTitle`),
- cursor state (`Cursor`, cursor color/style/blink),
- and other terminal features (progress bar, keyboard enhancements, etc.).

The runtime diffs **view state** and applies the minimal terminal changes needed.  
Sources: Bubble Tea upgrade guide “The Big Idea: Declarative Views” + `tea.View` type. https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md, https://github.com/charmbracelet/bubbletea/blob/v2.0.0/tea.go

> **fidelis already does:** “render is the whole truth,” not a stream of imperative toggles.  
> **fidelis should consider:** encode terminal-mode requests (alt-screen, mouse mode, cursor style, title, etc.) into the render result in a single place so feature ownership is compositional and testable.

#### Why this matters for component composition

In v1, any component could emit a command like “enter alt screen” at any time. In v2, **the only way** to request that state is to set `view.AltScreen = true` in the returned view.

That forces a design rule that’s valuable for `fidelis` too:
- **Feature requests must reconcile at a single render boundary.**
- Conflicting requests are now an application-level decision (or a deterministic merge rule), not an emergent runtime race.

### Ecosystem cohesion: Bubble Tea becomes the I/O “conductor”

The v2 stack makes a clear boundary:
- Bubble Tea manages I/O (terminal queries, keyboard protocols, etc.).
- Lip Gloss becomes pure and only transforms inputs into styled output.

This is an explicit architectural rebalancing to avoid deadlocks/lockups and eliminate “two libraries calling the shots.”  
Source: Bubble Tea v2.0.0 release notes “No more fighting”. https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0

> **fidelis already does:** “capabilities resolve at boundaries (Writer), not in pipelines.”  
> **fidelis should consider:** ensure *only one subsystem* is responsible for terminal I/O queries, so styling/layout libraries can be fully deterministic.

### Testing and determinism hooks (small but important)

Bubble Tea v2 adds program options meant for deterministic testing (e.g. forcing window size / forcing a color profile).  
Source: Bubble Tea upgrade guide “New Program Options”. https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md

> **fidelis should consider:** “test harness knobs” that make renders repeatable (fixed size, fixed capability profile), rather than relying on environment-dependent terminal probing during tests.

---

## 2) Rendering Model Changes (Bubble Tea v2 → cell buffer + ncurses-style diffs)

### What changed

Bubble Tea v2 ships with the “Cursed Renderer,” described as:
- built from the ground up,
- modeled after the ncurses rendering algorithm,
- optimized for speed, efficiency, and accuracy,
- producing large wins over SSH/Wish due to less output bandwidth.

Sources: Bubble Tea v2.0.0 release notes + Charm v2 blog post + Ultraviolet README.  
https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0  
https://charm.land/blog/v2.md  
https://github.com/charmbracelet/ultraviolet

### How it works (key abstractions)

At a high level, Bubble Tea v2 now does:

1. Your app returns a `tea.View` with `Content` as a styled ANSI string and other declarative fields.
2. The renderer parses `Content` into a structured form (`uv.StyledString` → cells).
3. The renderer draws that into a **screen buffer** (`uv.ScreenBuffer` / `uv.RenderBuffer`).
4. A terminal renderer diffs the new buffer vs. current screen state and writes minimal ANSI updates.

Concrete code path to read:
- Bubble Tea v2 `cursedRenderer.flush`: parses content, draws to cell buffer, toggles modes, renders diff, flushes updates.  
  https://github.com/charmbracelet/bubbletea/blob/v2.0.0/cursed_renderer.go
- Ultraviolet `StyledString` parsing ANSI into cells (SGR + hyperlinks) and drawing into a screen.  
  https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/styled.go
- Ultraviolet `TerminalRenderer.Render`: touched-line-driven rendering + scroll optimizations.  
  https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/terminal_renderer.go
- Ultraviolet `RenderBuffer` tracks “touched” line ranges (damage).  
  https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/buffer.go

#### Inline vs fullscreen rendering is first-class

Ultraviolet (and Bubble Tea v2’s renderer) explicitly supports both:
- **fullscreen / alt-screen** (fixed terminal-sized surface), and
- **inline** (a frame whose height is derived from content, rendered relative to the current cursor).

Bubble Tea’s renderer adjusts the “frame area” height based on `Content` height when not in alt screen, and uses relative cursor addressing in inline mode.  
Source: `cursedRenderer.flush` logic around `frameArea` + `SetRelativeCursor`. https://github.com/charmbracelet/bubbletea/blob/v2.0.0/cursed_renderer.go

> **fidelis already has:** orthogonal output modes in the CLI harness.  
> **fidelis should consider:** ensuring inline-mode is not “second-class,” because it’s where performance/correctness edge cases (wrapping, scrollback interactions, cursor placement) are hardest.

### What’s surprising (and useful to `fidelis`)

Bubble Tea’s external API is still largely “render a string,” but internally it:
- **decodes ANSI back into a cell grid** to do correct diff rendering.

This is a pragmatic bridge:
- It preserves the huge existing ecosystem of “ANSI-styled strings,”
- while enabling cell-accurate diffs, width correctness, and scroll optimizations.

> **fidelis already does:** cell-buffer rendering natively (no decode step).  
> **fidelis should consider:** the “decode ANSI → cells” approach as a compatibility layer if `fidelis` ever needs to ingest third-party ANSI output and still diff it correctly.

### Correctness + terminal capability features bundled into rendering

Bubble Tea v2 also bakes in:
- **Synchronized output** (terminal mode 2026) to reduce tearing/cursor flicker.  
  Source: Bubble Tea v2.0.0 notes. https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0
- **Unicode core mode** (terminal mode 2027) for accurate wide unicode/emoji handling where supported.  
  Source: Bubble Tea v2.0.0 notes + renderer code toggling Unicode mode based on width method.  
  https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0  
  https://github.com/charmbracelet/bubbletea/blob/v2.0.0/cursed_renderer.go

> **fidelis should consider:** representing “render correctness modes” as capabilities negotiated at the Writer boundary and activated declaratively, similar to Bubble Tea’s approach.

---

## 3) Lip Gloss v2 (Styling as a pure, deterministic value system)

### The core design change: remove Renderer, remove implicit I/O

Lip Gloss v1 styles were coupled to a renderer that:
- held output/color-profile state, and
- performed downsampling during `Style.Render()`.

Lip Gloss v2 removes `Renderer` entirely:
- `Style` becomes a plain value type (no pointer to renderer),
- `Style.Render()` emits full-fidelity ANSI (deterministic),
- downsampling happens at print/output boundaries via a writer.

Sources: Lip Gloss upgrade guide (“Renderer Removal”, “Printing and Color Downsampling”) + writer implementation.  
https://github.com/charmbracelet/lipgloss/blob/v2.0.0/UPGRADE_GUIDE_V2.md  
https://github.com/charmbracelet/lipgloss/blob/v2.0.0/writer.go

> **fidelis already does:** capability resolution at boundaries; rendering pipeline is pure.  
> **fidelis should consider:** adopting a “full-fidelity internal styling, downsample at writer” policy (if not already implicit), and making the “writer profile” an explicit dependency for any output-mode adapters.

#### A subtle but crucial consequence: fewer “spooky action at a distance” bugs

Lip Gloss v2 is explicitly motivated by cases like:
- writing UI to `stderr` while `stdout` is redirected (v1 could incorrectly conclude “no TTY → strip color”), and
- serving TUIs over SSH (Wish), where `stdin/stdout` are not the relevant streams.

Source: Lip Gloss v2.0.0 release notes sections “Querying the right inputs and outputs” and “Going beyond localhost”. https://github.com/charmbracelet/lipgloss/releases/tag/v2.0.0

> **fidelis should consider:** a crisp separation between “render output” (pure) and “output transport” (TTY/SSH/recording), with the transport owning stripping/downsampling decisions.

### Color + capability strategy: make choices explicit

Lip Gloss v2 changes:
- `Color` becomes a function returning `image/color.Color` (not a string type).
- Adaptive colors become explicit helpers (`LightDark`, `Complete(profile)`), and v1-style globals move to a `compat` package.
- Background detection requires explicit input/output (no more hidden `stdin/stdout` assumptions).

Sources: Lip Gloss upgrade guide + v2 “What’s changing?” discussion/notes.  
https://github.com/charmbracelet/lipgloss/blob/v2.0.0/UPGRADE_GUIDE_V2.md  
https://github.com/charmbracelet/lipgloss/discussions/506

> **fidelis should consider:** whenever styling depends on environment (TTY, color depth, light/dark background), ensure the dependency is injected rather than global.

### “Layout engine” expands: compositing + hit testing

Lip Gloss v2 adds (or formalizes) a small compositing model:
- `Layer`: pure tree of positioned/z-indexed content
- `Canvas`: a cell buffer to compose drawables
- `Compositor`: flattens layers once, can render and hit test (`Hit(x,y) → layer ID`)

Code to read:
- https://github.com/charmbracelet/lipgloss/blob/v2.0.0/layer.go
- https://github.com/charmbracelet/lipgloss/blob/v2.0.0/canvas.go
- Bubble Tea clickable example using `Compositor.Hit` and `View.OnMouse`: https://github.com/charmbracelet/bubbletea/blob/v2.0.0/examples/clickable/main.go

> **fidelis should consider:** a first-class “layer id” / hit-test story for mouse (or future pointer events), especially if `fidelis` wants to support composited overlays with deterministic picking.

---

## 4) Component Model (Composition, “frozen state”, and effects)

### What stayed the same

Bubble Tea remains recognizably Elm-architecture-inspired:
- `Init() tea.Cmd` for initial effects
- `Update(msg) (Model, Cmd)` as the single state transition point
- `View() tea.View` as pure rendering from state

Source: Bubble Tea README + API. https://github.com/charmbracelet/bubbletea/blob/v2.0.0/README.md

### What changed that impacts composition

The “declarative view fields” move changes how components share terminal features:
- v1: any component could emit commands like `EnterAltScreen`, `HideCursor`, etc.
- v2: terminal feature requests must be resolved into a single `tea.View` return value.

This is effectively a **composition rule**: if you want multiple components to request features, the top-level view must reconcile them.

> **fidelis already does:** top-level surface decides terminal output behavior.  
> **fidelis should consider:** making feature reconciliation explicit (e.g., “cursor wants to be visible at x,y”, “mouse wants cell motion”, “screen wants alt-screen”) rather than letting it happen imperatively.

### A new composition affordance: `View.OnMouse`

Bubble Tea v2 adds `View.OnMouse`, which lets a view compute a command based on the *previously rendered view content*. This is explicitly described as a way to implement view-specific behavior without breaking unidirectional data flow.

In practice, this pairs with Lip Gloss v2’s compositor/hit testing:
- render layers → render string
- use compositor `Hit(x,y)` in `OnMouse` to map mouse coordinates to a semantic layer ID
- emit a message (`LayerHitMsg`) back into `Update`

Source: `tea.View` docs + clickable example.  
https://github.com/charmbracelet/bubbletea/blob/v2.0.0/tea.go  
https://github.com/charmbracelet/bubbletea/blob/v2.0.0/examples/clickable/main.go

> **fidelis should consider:** a similar pattern for pointer events: “render produces a pick map” (or layer tree) that can be queried by input handlers to produce semantic events.

---

## 5) Layout System (What Charm chose, and what to steal for `fidelis`)

### Charm’s framing: Lip Gloss is the layout engine

Charm’s v2 announcement frames the ecosystem as:
- Bubble Tea = interaction layer
- Lip Gloss = layout engine
- Bubbles = UI primitives

Source: Charm blog v2 post. https://charm.land/blog/v2.md

In practice:
- Lip Gloss remains largely a **string/cell layout toolkit** (padding, borders, joining, placing, width/height constraints),
- but v2 strengthens layout/composition by adding **cell-buffer compositing** primitives (Layer/Canvas/Compositor).

### Ultraviolet layout primitives: rectangle splitting + constraints

Ultraviolet includes a small `layout` package:
- `Fixed`, `Percent`, `Ratio` constraints
- `SplitVertical`, `SplitHorizontal`, and rectangle placement helpers (center/top-left/etc.)

Source: https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/layout/layout.go

This is closer to “region-based layout” (think: “split the screen into panes”) than a full constraint solver or flexbox.

> **fidelis already does:** Block composition (join/pad/border).  
> **fidelis should consider:** adding an explicit “rect layout” layer (split panes, allocate regions, then render blocks into regions) if it improves clarity/perf, especially for apps that naturally think in rectangles.

### Where Lip Gloss compositing overlaps with `fidelis` layer algebra

Lip Gloss v2’s compositor is effectively:
- a z-ordered layer tree (with IDs),
- with deterministic render order,
- and deterministic hit-testing (“topmost layer at (x,y)”).

That’s conceptually adjacent to `fidelis`’s layer stack algebra (`Stay | Pop | Push | Quit`), even though the mechanics differ:
- Lip Gloss layers are *render-time composition* primitives.
- `fidelis` layers are *application navigation / state-stack* primitives.

> **fidelis should consider:** whether `fidelis` needs a *render-layer* concept distinct from *navigation layers*, especially for overlays/tooltips/modals with mouse picking.

---

## 6) Input Handling (keyboard, mouse, focus, paste)

### Keyboard: progressive enhancements + richer events

Bubble Tea v2’s key handling overhaul includes:
- separate `KeyPressMsg` and `KeyReleaseMsg`
- modifier set (`Mod`) instead of booleans
- richer key identity (`Code`, `Text`, plus shifted/base codes and repeats when supported)
- opt-in requests for additional keyboard protocol features via `View.KeyboardEnhancements`

Sources: Bubble Tea v2.0.0 notes + upgrade guide + Ultraviolet key model.  
https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0  
https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md  
https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/key.go

> **fidelis should consider:** separating “raw input decoding” from “semantic keybindings” and designing the key model so it can grow into modern terminal protocols (Kitty) without breaking API again.

#### Bubble Tea’s pattern: request capabilities, then adapt

Bubble Tea v2’s approach is:
- request keyboard enhancements declaratively via `View.KeyboardEnhancements`,
- receive a `KeyboardEnhancementsMsg` indicating what’s actually supported,
- then conditionally enable richer bindings (shift+enter, repeats, releases, etc.).

Source: Bubble Tea v2.0.0 notes “Keyboard Enhancements”. https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0

### Mouse: typed events + declarative mouse mode

Bubble Tea v2:
- makes mouse messages interfaces with specific types (`MouseClickMsg`, `MouseMotionMsg`, etc.)
- controls mouse mode via `View.MouseMode` (declarative)
- adds `View.OnMouse` for view-aware mouse handling

Sources: Bubble Tea upgrade guide + `mouse.go` + clickable example.  
https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md  
https://github.com/charmbracelet/bubbletea/blob/v2.0.0/mouse.go  
https://github.com/charmbracelet/bubbletea/blob/v2.0.0/examples/clickable/main.go

### Focus + paste: explicit event streams

- Focus reporting is declarative via `View.ReportFocus` producing `FocusMsg` / `BlurMsg`.  
  Source: `tea.View` docs + `focus.go`. https://github.com/charmbracelet/bubbletea/blob/v2.0.0/tea.go, https://github.com/charmbracelet/bubbletea/blob/v2.0.0/focus.go
- Bracketed paste now produces dedicated message types (`PasteMsg`, `PasteStartMsg`, `PasteEndMsg`).  
  Source: upgrade guide + `paste.go`. https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md, https://github.com/charmbracelet/bubbletea/blob/v2.0.0/paste.go

---

## 7) Performance Patterns (diffs, batching, and network-minded rendering)

### Damage tracking (touched lines / ranges)

Ultraviolet’s `RenderBuffer` tracks touched lines and cell ranges:
- `SetCell` marks a line/range as touched only when a cell actually changes.
- `TerminalRenderer.Render` short-circuits when there are no touched lines.

Sources: `RenderBuffer` and `TerminalRenderer.Render`.  
https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/buffer.go  
https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/terminal_renderer.go

> **fidelis already does:** diff-based rendering (only changed cells written).  
> **fidelis should consider:** a first-class damage model (touched-line ranges) to avoid scanning or comparing large buffers when the app already knows what changed.

### Cursor-movement optimizations + scroll region optimization

Ultraviolet’s terminal renderer contains optimizations around:
- cursor movement (hard tabs/backspace decisions),
- scroll optimizations in fullscreen mode,
- and conditional clears in inline mode.

Sources: Ultraviolet README + renderer implementation details.  
https://github.com/charmbracelet/ultraviolet  
https://github.com/charmbracelet/ultraviolet/blob/524a6607adb8/terminal_renderer.go

> **interesting but not applicable (mostly):** Bubble Tea/Ultraviolet invest heavily in generating optimal ANSI cursor movement sequences because their public render surface is “ANSI strings.” `fidelis` already owns cells directly, but may still want similar cursor-movement optimizations in the final “cells → ANSI” writer.

### Synchronized output (2026) as a “flicker budget” tool

Bubble Tea v2 uses synchronized output mode (when supported) to make updates atomic and reduce flicker/tearing.  
Source: Bubble Tea v2.0.0 notes + `cursed_renderer.go`. https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0, https://github.com/charmbracelet/bubbletea/blob/v2.0.0/cursed_renderer.go

### Color downsampling centralized

Bubble Tea v2 includes built-in downsampling using `colorprofile`, so ANSI output “just works” across truecolor/256/16/no-color contexts.  
Source: Bubble Tea v2.0.0 notes + colorprofile repo. https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0, https://github.com/charmbracelet/colorprofile

> **fidelis already does:** capability resolution at output boundaries.  
> **fidelis should consider:** treating downsampling as a generic “writer transform” (a pipeline stage after rendering, before bytes hit the terminal).

---

## 8) Lessons Learned (most transferable takeaways)

### 8.1 “Declarative beats imperative” in terminal state

The biggest v1 lesson is not about rendering speed; it’s about **who owns terminal state**.

Declarative view fields:
- remove ordering problems (“did we enter alt screen before enabling kitty keyboard?”),
- prevent component-level races (“who toggled bracketed paste off?”),
- and make the runtime responsible for correctness.

Sources: Bubble Tea upgrade guide + v2 notes/discussion.  
https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md  
https://github.com/charmbracelet/bubbletea/discussions/1374

### 8.2 Keep styling/layout pure; centralize I/O and capabilities

Charm explicitly calls out I/O fights as motivation for making Lip Gloss pure and letting Bubble Tea “call the shots.”  
Sources: Bubble Tea v2.0.0 notes + Lip Gloss v2.0.0 notes.  
https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0  
https://github.com/charmbracelet/lipgloss/releases/tag/v2.0.0

### 8.3 Optimize for SSH and “served TUIs”

Both Bubble Tea and Lip Gloss v2 notes emphasize:
- correctness when stdout/stderr are redirected,
- intentionality about which streams are TTYs,
- and bandwidth reduction for remote TUIs (Wish/SSH).

Sources: Lip Gloss v2.0.0 notes + Bubble Tea v2.0.0 notes.  
https://github.com/charmbracelet/lipgloss/releases/tag/v2.0.0  
https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0

> **fidelis should consider:** designing the Writer boundary to explicitly represent “this output is remote/ssh” vs “local tty” vs “recording/logging,” and ensuring capability negotiation happens there.

### 8.4 Build the substrate first (Ultraviolet), then rebuild the framework

Charm’s narrative is: v2 exists because the platform load changed (AI agents + terminal as primary UI), requiring production-grade rendering and input, and they built Ultraviolet as the substrate.  
Sources: Charm blog v2 + “Crush comes home” + Ultraviolet README.  
https://charm.land/blog/v2.md  
https://charm.land/blog/crush-comes-home.md  
https://github.com/charmbracelet/ultraviolet

---

## Appendix: Source Index (high-signal)

- Charm blog: v2 announcement (2026-02-23): https://charm.land/blog/v2.md
- Charm blog: Crush + Ultraviolet context (2025-07-30): https://charm.land/blog/crush-comes-home.md
- Bubble Tea v2.0.0 release notes: https://github.com/charmbracelet/bubbletea/releases/tag/v2.0.0
- Bubble Tea “What’s New” discussion (2025-03-26): https://github.com/charmbracelet/bubbletea/discussions/1374
- Bubble Tea v2 upgrade guide: https://github.com/charmbracelet/bubbletea/blob/v2.0.0/UPGRADE_GUIDE_V2.md
- Lip Gloss v2.0.0 release notes: https://github.com/charmbracelet/lipgloss/releases/tag/v2.0.0
- Lip Gloss “What’s New” discussion: https://github.com/charmbracelet/lipgloss/discussions/506
- Lip Gloss v2 upgrade guide: https://github.com/charmbracelet/lipgloss/blob/v2.0.0/UPGRADE_GUIDE_V2.md
- Bubbles v2.0.0 release notes: https://github.com/charmbracelet/bubbles/releases/tag/v2.0.0
- Bubbles v2 upgrade guide: https://github.com/charmbracelet/bubbles/blob/v2.0.0/UPGRADE_GUIDE_V2.md
- Ultraviolet README + code: https://github.com/charmbracelet/ultraviolet
- colorprofile: https://github.com/charmbracelet/colorprofile
