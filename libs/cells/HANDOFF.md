# cells — Handoff

## 2026-01-26
Feedback loop: RenderApp renamed to Surface. Added Emit protocol
(`Callable[[str, dict], None]`) with three emission strata — raw input
(key), UI structure (action, resize), domain (subclass-emitted).
`Surface.handle_key()` wraps `process_key()` with action auto-emission.
No cross-lib imports; integration layer wires to Fact.of() + Stream.emit().

Python minimum bumped from 3.10 to 3.11 (aligning with all other libs).
Added `py.typed` marker and `[tool.pytest.ini_options]`.

## Open
- **Viewport dataclass**: `vslice` compose function landed. Next: frozen `Viewport` dataclass
  carrying `offset`, `content_height`, `visible_height` with clamping methods. Signal: scroll
  offset overshoot in tour (handler can't clamp because it doesn't know content height — render
  clamps visually but state drifts). The dataclass solves this by owning the clamping.
- **Mouse/trackpad input**: Surface currently keyboard-only. Trackpad scroll events arrive as
  terminal escape sequences (SGR mouse mode). Tour exposed this — trackpad scrolling felt odd
  against keyboard-only navigation. Defer until Viewport exists to receive scroll deltas.
- **ShapeLens extensions**: Tree lens, chart lens, other convention-based renderers.
- **Zoom propagation**: Global vs independent vs relative in composed views. Undecided.
- **CLI -> TUI continuum**: Verbosity spectrum (Level 0-4). Documented in demos/VERBOSITY.md.
## 2026-01-28
Big text rendering API: `render_big(text, style, size=1, format=BigTextFormat.FILLED) -> Block`

Features:
- **Two sizes**: size=1 (3-row, 3-wide glyphs), size=2 (5-row, 5-wide glyphs)
- **Two formats**: `BigTextFormat.FILLED` (solid), `BigTextFormat.OUTLINE` (hollow)
- **Glyph coverage**: a-z, 0-9, space, 30+ punctuation/symbols
- **Case-folding**: uppercase converted to lowercase
- **Fallback**: unknown chars render as box placeholder

Demo at `demos/cells/demo_big_text.py` — 4 modes (rainbow, fire, size comparison, showcase),
toggle size with 's', format with 'f'.
