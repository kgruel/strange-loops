# Terminal Capability Signal — Design

Date: 2026-02-25
Status: Decided (council session)

## The Question

How should terminal capability information flow through the rendering pipeline so that views can make informed rendering decisions?

**Restated after session:** The question assumed capabilities needed to reach views. They don't. The rendering pipeline carries *intent* (Style objects). The terminal boundary (Writer) resolves intent against capability. The design is: wire up the color downconversion that Writer already has detection for, and leave the pipeline untouched.

## Council Process

5-role persistent swarm: muser (provocation + types), siftd (conversation archaeology), web-researcher (ecosystem survey), ux-reactor (call-site grounding), cold-reactor (one-pass review). Orchestrated by team lead.

Phase 1: siftd and web-researcher researched in parallel. Phase 2: muser proposed dissolution, ux-reactor stress-tested at call sites. Phase 3: design doc from converged outcome.

Key inputs:
- Constraints doc: `docs/plans/2026-02-25-council-capability-constraints.md`
- Fidelity implementation: `docs/plans/2026-02-25-fidelity-implementation.md`

## Key Insights That Shaped the Design

1. **No view constructs a color value.** (muser, codebase audit) Every view in fidelis consumes Style objects — from Palette, from callers, or bare `Style()`. Views express rendering *intent*, not terminal-specific output. This means capability information has no consumer in the pipeline.

2. **Writer.detect_color_depth() exists but is dead code.** (siftd, finding #6) The detection side is built. The output side (`_color_codes`) ignores it — blindly emits truecolor/256-color codes regardless of terminal. The missing piece is the bridge between detection and output: color downconversion.

3. **Capabilities resolve at boundaries, not in pipelines.** (muser, principle) Width works this way already: views receive a width budget and render within it, never asking "what kind of terminal is this?" Color should follow the same pattern — views express intent (Style), the boundary resolves capability (Writer).

4. **Most "capabilities" dissolve into existing mechanisms.** (muser, dissolution test)
   - Synchronized output → Writer already uses mode 2026 unconditionally
   - Unicode width → `_text_width.py` / wcwidth handles this
   - Background light/dark → Palette choice (DARK_PALETTE vs LIGHT_PALETTE)
   - Color depth → Writer boundary concern (this design)

5. **Ecosystem converges on "resolve at owner, give views resolved values."** (web-researcher) No framework threads raw capability through rendering. Rich, Textual, lipgloss all resolve at the output object. fidelis's Writer is that object.

6. **Koblinger's sync-first model wins.** (constraints doc, async/sync bridge) Sync detection (env vars) covers the common case. Async queries are a bridge that populates sync state. Views always read resolved state, never query directly. This eliminates the progressive re-render complexity.

7. **The prior council's RenderContext rejection stands.** (siftd, finding #3) UX-reactor argued: DX regression (REPL use becomes struct construction), conflates "who decides" (width is allocated by parents, not runtime), mode/format/is_tty are never read by views. All still true.

8. **"Capability vs choice" is a useful analysis tool, not an architectural boundary.** (muser, dissolution #3) The real axis is "layout parameter" (width, zoom — vary per call site, allocated by parent) vs "ambient default" (Palette, IconSet — set per frame, override at point of need). This doesn't need new vocabulary.

## The Design

### Change 1: Color downconversion in Writer._color_codes()

Writer uses its already-detected `ColorDepth` to automatically downgrade color values that exceed the terminal's capability.

```python
# writer.py

def _color_codes(self, color: str | int, foreground: bool) -> list[str]:
    """Convert a color value to SGR parameter strings.

    Automatically downgrades colors when terminal color depth is limited:
    - Hex RGB → 256-color → 16-color, as needed
    - 256-color index → 16-color, as needed
    - Named colors always emit as 16-color (already safe)
    """
    depth = self.detect_color_depth()
    base = 30 if foreground else 40

    if isinstance(color, int):
        # 256-color index
        if depth.value >= ColorDepth.EIGHT_BIT.value:
            prefix = "38" if foreground else "48"
            return [prefix, "5", str(color)]
        # Downconvert 256 → 16
        return [str(base + _nearest_basic(color))]

    if isinstance(color, str):
        if color.startswith("#") and len(color) == 7:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            if depth == ColorDepth.TRUECOLOR:
                prefix = "38" if foreground else "48"
                return [prefix, "2", str(r), str(g), str(b)]
            if depth == ColorDepth.EIGHT_BIT:
                prefix = "38" if foreground else "48"
                return [prefix, "5", str(_rgb_to_256(r, g, b))]
            # 16-color fallback
            return [str(base + _rgb_to_basic(r, g, b))]

        # Named color — always 16-color safe
        idx = NAMED_COLORS.get(color.lower())
        if idx is not None:
            return [str(base + idx)]

    return []
```

### Change 2: Color arithmetic functions (pure, no dependencies)

```python
# writer.py — module-level functions

# The 6x6x6 color cube starts at index 16, grayscale at 232
_CUBE_START = 16
_GRAY_START = 232

# Basic 16 colors as approximate RGB for nearest-match
_BASIC_RGB: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),       # 0: black
    (128, 0, 0),     # 1: red
    (0, 128, 0),     # 2: green
    (128, 128, 0),   # 3: yellow
    (0, 0, 128),     # 4: blue
    (128, 0, 128),   # 5: magenta
    (0, 128, 128),   # 6: cyan
    (192, 192, 192),  # 7: white
    (128, 128, 128),  # 8: bright black (gray)
    (255, 0, 0),     # 9: bright red
    (0, 255, 0),     # 10: bright green
    (255, 255, 0),   # 11: bright yellow
    (0, 0, 255),     # 12: bright blue
    (255, 0, 255),   # 13: bright magenta
    (0, 255, 255),   # 14: bright cyan
    (255, 255, 255),  # 15: bright white
)


def _color_distance_sq(r1: int, g1: int, b1: int, r2: int, g2: int, b2: int) -> int:
    """Squared Euclidean distance in RGB space."""
    return (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2


def _idx_to_rgb(idx: int) -> tuple[int, int, int]:
    """Convert a 256-color index to approximate RGB."""
    if idx < 16:
        return _BASIC_RGB[idx]
    if idx < _GRAY_START:
        # 6x6x6 color cube
        idx -= _CUBE_START
        b = (idx % 6) * 51
        idx //= 6
        g = (idx % 6) * 51
        r = (idx // 6) * 51
        return (r, g, b)
    # Grayscale ramp: 24 shades from 8 to 238
    gray = 8 + (idx - _GRAY_START) * 10
    return (gray, gray, gray)


def _rgb_to_256(r: int, g: int, b: int) -> int:
    """Find nearest 256-color index for an RGB value."""
    # Check cube colors (indices 16-231)
    best_idx = 16
    best_dist = _color_distance_sq(r, g, b, *_idx_to_rgb(16))
    for i in range(17, 256):
        ir, ig, ib = _idx_to_rgb(i)
        d = _color_distance_sq(r, g, b, ir, ig, ib)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def _rgb_to_basic(r: int, g: int, b: int) -> int:
    """Find nearest basic 16-color index for an RGB value."""
    best_idx = 0
    best_dist = _color_distance_sq(r, g, b, *_BASIC_RGB[0])
    for i in range(1, 16):
        d = _color_distance_sq(r, g, b, *_BASIC_RGB[i])
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def _nearest_basic(idx_256: int) -> int:
    """Convert a 256-color index to the nearest basic 16-color index."""
    r, g, b = _idx_to_rgb(idx_256)
    return _rgb_to_basic(r, g, b)
```

### All output paths covered

Because both `write_frame()` (TUI) and `print_block()`/`InPlaceRenderer` (CLI) share `_color_codes()`, the downconversion applies to all styled output paths.

### Change 3: No other changes

That's the complete design. No new types. No new ContextVars. No Lens signature change. No view modifications.

## What Dissolves

| Before | After | Change |
|--------|-------|--------|
| Writer._color_codes blindly emits whatever color type it receives | Writer._color_codes downgrades based on detect_color_depth() | ~40 lines of color arithmetic added |
| detect_color_depth() is dead code | detect_color_depth() result (cached) used on every color emission | Wired up to _color_codes |
| NORD_PALETTE silently broken on 16-color terminals | NORD_PALETTE auto-downgrades gracefully | No palette changes — Writer handles it |
| "Capability signal" as an architectural concept | Capability resolves at Writer boundary | No pipeline changes needed |
| "Choices" as a named architectural concept | "Layout parameter" vs "ambient default" (unnamed convention) | Existing pattern, no new vocabulary |

## What Doesn't Change

- **Lens signature** `(data, zoom, width) -> Block` — untouched
- **Block** — immutable, no capability metadata
- **Style** — `fg: Color, bg: Color` representation unchanged
- **Palette / IconSet** — ContextVar delivery unchanged
- **_setup_defaults()** — still bridges Format.PLAIN -> ASCII_ICONS
- **Surface / Buffer / diff pipeline** — untouched
- **All view functions** — no signature changes, no new kwargs
- **CliContext** — no new fields
- **ColorDepth enum** — already correct (NONE, BASIC, EIGHT_BIT, TRUECOLOR)

## Design Principles Established

1. **Capabilities resolve at boundaries, not in pipelines.** The rendering pipeline carries intent (Style). The terminal boundary (Writer) resolves intent against capability. Don't thread detection results through intermediate layers.

2. **If no view consumes it, don't thread it.** Before designing a delivery mechanism, identify the consumer. Zero views in fidelis make capability-dependent rendering decisions. The consumer is Writer.

3. **Dissolution before extension.** The constraints doc listed 5 open questions about delivery mechanisms. The dissolution test showed all 5 had the wrong premise — the thing being delivered had no consumer in the proposed destination.

4. **Width is the existence proof — and the counter-example.** Width flows as an explicit parameter because parents *allocate* it to children (it varies per call site). Color depth doesn't flow as a parameter because views don't branch on it — they express intent and let the boundary resolve. Same framework, different appropriate delivery based on consumption pattern.

5. **Build consumers before delivery mechanisms.** If a future view genuinely needs capability information, the ContextVar pattern exists and is well-tested. Add it then, with the consumer that justifies it.

## Considered Alternatives (with real rejection reasons)

### A. TerminalCaps ContextVar (single struct for all capabilities)

```python
@dataclass(frozen=True)
class TerminalCaps:
    color_depth: ColorDepth
    unicode_safe: bool
    background: Literal["light", "dark", "unknown"]
```

**Rejected because:** No view reads these fields. Every proposed consumer turned out to be either Writer (color depth), already handled (_text_width for unicode), or a Palette choice (light/dark). Creating the struct without consumers is premature abstraction.

### B. Multiple independent ContextVars (one per capability)

```python
_color_depth: ContextVar[ColorDepth] = ContextVar("color_depth", default=ColorDepth.TRUECOLOR)
```

**Rejected because:** Same problem as A — no view reads color depth. The only consumer (Writer) already owns its detection via `detect_color_depth()`. A ContextVar would duplicate state without adding a consumer.

### C. Lens signature change to `(data, zoom, width, caps) -> Block`

**Rejected twice.** First by the prior council (DX regression, conflates "who decides," no view reads mode/format). Second by this council (no view needs `caps` — the entire purpose of the question dissolves).

### D. Progressive re-render on capability upgrade

Frame 0 renders with env-var detection, Frame N re-renders when probe results arrive.

**Rejected because:** Koblinger's sync-first model is simpler and covers the common case. Async queries, if ever needed, should populate sync state before rendering — not trigger mid-render upgrades. Surface's diff-render *could* support this cheaply, but "could" isn't "should."

### E. AdaptiveColor / AdaptiveStyle (lipgloss-style per-value alternatives)

```python
@dataclass(frozen=True)
class AdaptiveStyle:
    light: Style
    dark: Style
```

**Rejected because:** Palette already solves this at a higher level. An app that cares about light/dark creates `LIGHT_PALETTE` and `DARK_PALETTE`, sets one in `_setup_defaults()`. Per-value alternatives add complexity without new capability — Palette is the general form.

## Historical Grounding

| Finding | Source | Impact |
|---------|--------|--------|
| Lens signature `(data, zoom, width)` was emergent, not deliberately minimal | siftd #1 | Supports leaving it alone — it works, but not because someone proved it's complete |
| LensContext experiment existed but never merged | siftd #2 | Someone tried richer context, it didn't stick — evidence against threading more through |
| RenderContext rejected by prior council (DX, "who decides," no readers) | siftd #3 | Hard prior constraint. This council's proposal must not replicate the rejection |
| ContextVar was a VALUES decision: "consistency as default, override at point of need" | siftd #4 | Palette/IconSet pattern is settled. New ContextVars need the same justification (a consumer) |
| Writer.detect_color_depth() exists but is dead code | siftd #6 | The detection half is built. This design wires up the output half |
| Writer uses mode 2026 unconditionally — safe-to-try in practice | siftd #7 | Progressive enhancement already works at the Writer level |
| `_setup_defaults` embodies capability→choice bridge | siftd #8 | Pattern for future bridges (e.g., detect light/dark → set Palette) |
| Two delivery mechanisms correlate: explicit params for per-call, ContextVar for per-frame | siftd #9 | Confirms "layout parameter vs ambient default" as the real axis |
| No view has ever made a capability-dependent rendering decision | siftd #10 | The load-bearing finding. No consumer = no delivery mechanism needed |
| Ecosystem converges on resolve-at-owner, not thread-through-pipeline | web-researcher #1 | Validates Writer as the right resolution point |
| No framework separates capability from choice as first-class | web-researcher #2 | The distinction is useful for analysis, not architecture |
| lipgloss v1→v2: global → explicit Renderer for multi-output | web-researcher #6 | Single Surface means Writer-level resolution is fine; revisit if multi-output arises |

## Implementation Sequence

1. **Add color arithmetic functions to writer.py** (`_idx_to_rgb`, `_rgb_to_256`, `_rgb_to_basic`, `_nearest_basic`, `_color_distance_sq`). Pure functions, no dependencies. Test with known color mappings.

2. **Modify Writer._color_codes() to use detect_color_depth()** for automatic downconversion. The three paths: hex RGB → truecolor/256/16, int index → 256/16, named → 16 (unchanged).

3. **Add tests for color downconversion.** Test each path: truecolor terminal gets raw codes, 256-color terminal gets nearest 256 index, 16-color terminal gets nearest basic index. Test NORD_PALETTE specifically (256-color indices on 16-color terminal).

4. **Verify existing tests pass.** The change is backward-compatible — truecolor terminals get identical output. Only lower-capability terminals see different (better) output.

## Out of Scope (explicit deferrals)

- **Light/dark background detection.** No current consumer. When an app wants this, pattern is: detect in `_setup_defaults()`, set ambient Palette. Deferred until someone builds a Palette that cares.

- **`TERM_CAPABILITIES` / `LC_TERM_CAPABILITIES` env var consumption.** The ecosystem hasn't converged on this yet. When it does, `detect_color_depth()` is the natural place to read it. Deferred until ecosystem adoption.

- **Async capability probes (DA1/DA2/DECRQSS).** Koblinger's argument holds: sync-first, async as bridge for SSH gaps. If needed, the result populates Writer state before rendering. Deferred until someone encounters a terminal where env-var detection fails and it matters.

- **Multi-output (different terminals at different capabilities).** lipgloss hit this; fidelis has single Surface. If multi-output arises, each Writer carries its own ColorDepth. The design already supports this — detection is per-Writer instance. Deferred until multi-output is real.

- **Perceptual color distance (CIEDE2000 vs Euclidean RGB).** Euclidean RGB is good enough for the 16/256 palette sizes involved. Upgrade to perceptual distance if color matching quality becomes a complaint. Deferred until evidence of poor matches.
