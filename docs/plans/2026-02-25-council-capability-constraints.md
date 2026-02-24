# Design Council: Terminal Capability Signal

## The Question

How should terminal capability information flow through the rendering pipeline so that views can make informed rendering decisions — and how does this relate to the existing "choice" context (Palette, IconSet, zoom)?

## Context

fidelis renders the same data at different fidelity levels via the Lens/zoom system. Palette and IconSet (landing now) provide aesthetic choice via ContextVar. But views are blind to terminal capabilities beyond width.

The rendering pipeline today:

```
state → Lens.render(state, zoom, width) → Block → Buffer → diff → Writer → terminal
```

What flows in: width (capability), zoom (choice). After fidelity-impl merges: palette and icons (choice, via ContextVar). What doesn't flow: color depth, unicode support, background light/dark, synchronized output, or any other terminal capability.

Width is the existence proof — it's a capability that already threads through. The question is whether and how to generalize this.

### Prior art from research

Terminal capabilities survey (`docs/plans/2026-02-25-terminal-capabilities-survey.md`) established:

- **Three reliability tiers**: certain (dimensions, is_tty), probable (color depth, unicode), heuristic/opaque (background light/dark)
- **Source tracking > confidence scores**: knowing *how* you detected something matters more than a numeric confidence
- **Two detection strategies**: env-var (instant, Rich's approach) and query-based (libvaxis, ~1 second startup)
- **Safe-to-try features**: some capabilities (mode 2026 synced output) can be enabled speculatively with no cost on failure
- **No framework models uncertainty**: the ecosystem uses booleans and enums, not confidence levels

### Key concept from design conversation

Two kinds of context matter for views:

- **Capability**: what the terminal can do (discovered from environment)
- **Choice**: what the user/app wants (decided by human or application)

Capabilities are "resolved beliefs" — detected, overridden, or defaulted. The uncertainty lives at the detection boundary, not the consumption boundary. By the time a view asks "color depth?", someone has already resolved the ambiguity.

### Progressive detection model

The leading design idea: don't choose between Rich's instant env-var approach and libvaxis's query-based approach. Do both, in sequence:

1. **Frame 0 (instant)**: render with env-var detection (is_tty, dimensions, COLORTERM, NO_COLOR)
2. **Frame N (~1s later)**: query probes return, capabilities upgrade, trigger re-render
3. **Ongoing**: push-based notifications (mode 2031) trigger re-render on change

This works because Surface already diff-renders — an upgrade re-render only rewrites affected cells.

### The browser model: baseline + progressive enhancement + feature detection

From the Terminal WG discussion (2019), Timothy Allen and Simon Edwards
articulated a three-layer compatibility model borrowed from web browsers:

1. **Baseline**: a defined set of behavior all modern terminals share
   (VT100/ANSI, basic SGR, cursor movement). Safe to assume. The equivalent of
   "every browser supports `<div>`."

2. **Progressive enhancement**: newer features designed so terminals silently
   ignore what they don't understand. An application can send the basic sequence
   then immediately override with the richer one. Example: enable mouse mode
   1000 (basic), then mode 1006 (SGR) — the terminal gives you the richest it
   supports. **No detection needed.**

3. **Feature detection**: actively query for things you need to know *before*
   acting. This is the small set of capabilities where the wrong assumption
   causes visible harm (not just degraded richness).

This narrows the design problem significantly. Most of what the research doc
cataloged falls into categories 1 and 2 — baseline assumptions and safe-to-try
features that don't need detection at all. Category 3, where you genuinely need
to ask first, is quite small:

- **Color depth** — affects palette mapping (truecolor vs 256 vs 16)
- **Background mode** (light/dark) — affects readability of color choices
- **Unicode width behavior** — affects layout correctness

Edwards also proposed coarse-grained capability keywords at the feature-spec
level (`TERM_CAPABILITIES="sixel hyperlinks truecolor notifications"`), not the
escape-code level. This is the right granularity for what views need — a view
doesn't care about CSI sequences, it cares about "can I use truecolor?"

The `LC_TERM_CAPABILITIES` trick (using the `LC_` prefix so OpenSSH forwards it
by default) addresses the SSH capability degradation problem identified in the
research doc.

**Implication for fidelis:** We may not be designing a "capability detection
system." We may be designing how a small number of genuinely-need-to-know
signals (color depth, background mode, unicode width) reach the rendering
pipeline, while everything else is either assumed (baseline) or tried
optimistically (progressive enhancement).

## Invariants (will not change)

- `Block` is immutable (tuples, frozen)
- All state types are frozen dataclasses
- `Style` is the style primitive (fg, bg, bold, italic, underline, reverse, dim)
- `Palette` delivers via ContextVar with kwarg escape hatch (landing in fidelity-impl)
- `IconSet` delivers via ContextVar with kwarg escape hatch (landing in fidelity-impl)
- `Zoom` is representation (cartographic — qualitatively different, not less detail)
- Lens IS the fidelity resolver — `(data, zoom, width) → Block`
- Surface diff-renders (only changed cells written)
- `run_cli` is the CLI entry point that sets ambient context
- `Writer` already knows `ColorDepth` for ANSI output

## Scope Boundary (not deciding)

- NOT redesigning zoom or the Lens signature (those are settled)
- NOT building a terminal capability database or terminfo replacement
- NOT implementing the actual detection probes (that's implementation, not design)
- NOT changing OutputMode or Format (those axes are settled)
- NOT adding capabilities to the Lens function signature directly (width already flows as a parameter — whether other capabilities should is an open question, not a foregone conclusion)
- NOT designing a general event/notification system (mode 2031 integration is a future concern)

## Existing Conventions

- ContextVar + kwarg escape hatch is the delivery mechanism for ambient context (Palette, IconSet both use this)
- `_setup_defaults()` in `run_cli` is the bridge that sets ambient context from CLI detection
- Views are pure functions: `(state, ...) → Block` — they read ambient context, they don't subscribe to events
- Width flows as an explicit parameter, not ambient context
- The project uses "Choices" (not "configuration") as the name for user/app decisions — this is opinionated and intentional

## Open Questions for the Council

1. **Is capability a single value (struct) or multiple independent ContextVars?** Width is already an independent parameter. Should color depth be another independent signal, or do capabilities compose into one ambient struct?

2. **Where does the progressive detection lifecycle live?** Surface? run_cli? A new coordinator? Who triggers the re-render when a probe returns?

3. **Does the Lens signature change?** Currently `(data, zoom, width) → Block`. Width is a capability that's an explicit parameter. Do other capabilities follow the same pattern, or do they go ambient? What's the principle that distinguishes explicit-parameter capabilities from ambient-context capabilities?

4. **What does a view actually do with capability information?** Concrete: if a view knows color depth is BASIC_16, what does it change? If it knows background is dark, what does it change? Are there real examples, or is this theoretical?

5. **Does "Choices" as a named concept earn its keep?** We've been developing capability vs choice as a distinction. Is it a real architectural boundary, or is it just two things that happen to be delivered the same way (ContextVar)?
