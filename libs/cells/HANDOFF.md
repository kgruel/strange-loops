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
- **Big text rendering**: 3-row block-character font using `█▀▄` elements. Prototype built
  during tour development — renders any text at 3× height using a glyph map. Could become
  a convenience method (e.g. `Block.big("title", style)` or `render_big(text, style) -> Block`).
  Glyph set covers lowercase a-z and common symbols. Implementation pattern:
  ```python
  _BIG = {
      'a': ('▄▀▄', '█▀█', '▀ ▀'),
      'c': ('▄▀▀', '█  ', '▀▀▀'),
      # ... width-3 glyphs, 3 rows each
  }
  def render_big_text(text: str, style: Style) -> Block:
      # concatenate glyph rows with 1-char gaps, return join_vertical of 3 Block.text rows
  ```
  Looked good in practice — readable, fits 80 cols for ~15 char strings. Deferred: add full
  alphabet, variable-width glyphs, optional font selection.
