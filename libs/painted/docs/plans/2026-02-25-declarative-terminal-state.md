# Declarative Terminal State — Design Thread

Date: 2026-02-25
Status: **Deferred** — documented for future pickup when window composition is near-term.

## The Question

How should terminal mode declarations (alt screen, mouse mode, cursor visibility/position,
graphics protocols) flow through the composition model when multiple concurrent regions need
different things?

## Context

Charm's Bubble Tea v2 (released 2026-02-24) made `View()` return a struct carrying mode
declarations (`AltScreen`, `MouseMode`, `Cursor`, `KeyboardEnhancements`, `ReportFocus`).
The runtime diffs these declarations per frame and applies minimal terminal changes. This
solved a concrete v1 problem: distributed authority across separate libraries (Bubble Tea
reading input while Lip Gloss queried terminal state) caused I/O contention and deadlocks.

Research doc: `docs/research/2026-02-25-charm-v2-deep-dive.md`

## Why This Dissolved (For Now)

painted doesn't have the distributed authority problem. Surface is the sole terminal authority,
modes are set imperatively in `Surface.run()`, and the Layer stack centralizes input handling
(top layer wins). For modal overlays (help, search, confirm dialogs), this works because
layers are exclusive — only one handles input at a time.

The capability signal council (same session) established: "Capabilities resolve at boundaries,
not in pipelines." That resolved the rendering question (color downconversion at Writer). But
terminal *mode management* was out of scope because Surface-as-sole-authority made it a
non-problem.

## When This Stops Dissolving

The question becomes real when composition units are **concurrent, not modal**:

- **Windows/panels** that can be dragged, resized, cascaded — each may need different
  mouse modes (one wants drag tracking, another doesn't)
- **Image rendering** regions requiring kitty graphics protocol or sixel
- **Text input** widgets wanting a visible blinking terminal cursor at a specific position
- **AI agent interfaces** with multiple independent panes (Charm's stated v2 motivation)

In this world, the question isn't "how does color depth flow" — it's "who declares what
the terminal should be doing right now, and how do competing declarations reconcile?"

## The Pattern (When Ready to Implement)

**Composition units declare what they need. A reconciliation point merges declarations per
frame. Surface diffs the merged result against the previous frame and actuates changes.**

Concrete shape:

```python
@dataclass(frozen=True)
class ModeRequest:
    """What a composition unit needs from the terminal this frame."""
    mouse_mode: MouseMode | None = None      # None = "no opinion"
    cursor: CursorRequest | None = None      # position + shape + visibility
    # Future: graphics_protocol, keyboard_enhancements, etc.
```

Reconciliation rules (algebra):
- **Mouse:** highest mode wins (`ALL_MOTION > CELL_MOTION > NONE`)
- **Cursor:** only focused/active window owns it
- **Graphics protocol:** enabled if any region needs it
- **Alt screen:** always on in TUI mode (not per-window)

This is a **reconciliation algebra** — the same pattern as Layer stack's `Stay | Pop | Push | Quit`
but applied to terminal modes rather than navigation state.

## Key Distinction: Render Layers vs Navigation Layers

Lip Gloss v2 added a compositor (Layer/Canvas/Hit) for z-ordered visual composition with
mouse picking. painted's Layer stack is navigation algebra. These are orthogonal:

| | Navigation Layers (painted today) | Render Layers (future) |
|---|---|---|
| **Purpose** | Modal state stack | Visual composition with z-order |
| **Authority** | Top layer handles input | All visible, focused window handles input |
| **Rendering** | All paint into shared buffer, bottom-to-top | Each owns a region, composed |
| **Composition** | Exclusive (modal) | Concurrent (windowed) |

painted may need both. Navigation layers for modals (help, confirm, search overlays).
Render layers / windows for concurrent panes.

## Building Blocks Already In Place

- **Hit testing** (`Block.id` + `Buffer.hit(x, y)` + `Surface.hit()`) — merged this session.
  Maps mouse coordinates to semantic identifiers. First piece of the window picking story.
- **Scroll optimization** (`Surface._try_flush_scroll_optimized()`) — merged this session.
  DECSTBM scroll regions already work, which is the same mechanism needed for per-window
  scroll regions.
- **Capability boundary principle** — Writer resolves rendering capabilities. Terminal mode
  management would follow the same pattern: Surface resolves mode declarations at the
  frame boundary.

## What Would Trigger Implementation

- A concrete use case requiring concurrent windows (not just modal overlays)
- The Window/Region type taking shape as a composition unit
- AI agent interface work requiring multiple independent panes

## What NOT to Do Prematurely

- Don't add ModeRequest to Layer — current Layer stack is for modals, not windows
- Don't make Surface mode management declarative before the Window type exists —
  it would add complexity with no composition benefit
- Don't generalize reconciliation rules before seeing real conflicts to reconcile

## References

- Charm v2 deep dive: `docs/research/2026-02-25-charm-v2-deep-dive.md`
- Capability signal design (dissolution): `docs/plans/2026-02-25-capability-signal-design.md`
- Capability constraints: `docs/plans/2026-02-25-council-capability-constraints.md`
- Terminal capabilities survey: `docs/plans/2026-02-25-terminal-capabilities-survey.md`
- siftd: `decision:capability-boundary`, sessions from 2026-02-24 council
