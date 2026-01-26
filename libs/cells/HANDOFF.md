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
- **ShapeLens extensions**: Tree lens, chart lens, other convention-based renderers.
- **Zoom propagation**: Global vs independent vs relative in composed views. Undecided.
- **CLI -> TUI continuum**: Verbosity spectrum (Level 0-4). Documented in demos/VERBOSITY.md.
