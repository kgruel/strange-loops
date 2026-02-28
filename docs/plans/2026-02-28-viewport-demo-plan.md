# Viewport & Scroll Pattern Demo Plan

Date: 2026-02-28

## Summary

A patterns-level demo (`demos/patterns/viewport.py`) that teaches Painted’s
scroll state model — `Viewport(offset, visible, content)` — and the canonical
composition with `Cursor` (`viewport.scroll_into_view(cursor.index)`) by
rendering deterministic “frames” of a scrolling dataset at multiple zoom levels.

The demo is static output (golden-testable) and follows the patterns rule:
exposes `_fetch()` and `_render(ctx, data) -> Block`.

## Motivation

Painted already has:

- `Viewport` (`src/painted/viewport.py`) as reusable scroll state.
- `Cursor` (`src/painted/cursor.py`) as bounded selection state.
- Components like `ListState` that compose the two, but the general pattern
  isn’t demonstrated directly in a patterns demo.

This demo should make the “windowing” mental model obvious: the data stays
fixed, the viewport moves, and the visible slice is derived.

## What the demo teaches

1. `content > visible` implies `max_offset = max(0, content - visible)`
2. `vslice(content_block, offset, visible)` is the literal windowing operation
3. Cursor-follow pattern:
   - update cursor (`next/prev/home/end`)
   - update viewport dimensions (`with_visible`, `with_content`)
   - call `scroll_into_view(cursor.index)` to keep selection visible
4. Manual scroll pattern:
   - `viewport.scroll(delta)` clamps to `[0, max_offset]`
5. Resizing pattern (optional):
   - changing `visible` changes `max_offset` and clamps `offset`

## Demo data + cases

`_fetch()` returns a small, deterministic set of cases:

- A fixed “log-ish” dataset of ~18–24 lines, each prefixed with a stable row
  number (`00`, `01`, …) to make window movement easy to see.
- `visible` height ~6–8.
- Cases (FULL zoom can show all; default can show just one):
  - cursor-follow sequence (cursor moves down through content)
  - manual scroll sequence (offset changes, cursor fixed)
  - optional resize sequence (visible height changes)
  - optional edge cases: `content <= visible`, `visible == 0`, `content == 0`

Internally, represent each case as a list of deterministic “steps” (frames)
containing the cursor + viewport state to render.

## Rendering design

### Window panel (all zooms except MINIMAL)

For each step, show:

- A compact state strip:
  - `cursor=<idx> offset=<offset> visible=<visible> content=<content> max=<max_offset>`
  - `window=[<offset>..<end-1>]` where `end = min(offset + visible, content)`
- A windowed list panel of exactly `visible` rows:
  - absolute index + selection marker (`▸`) + text

### Overlay panel (DETAILED+)

To teach “window over fixed dataset”, show the full dataset with an overlay:

- Rows inside the viewport window are normal; outside are dim/muted.
- Selected row reads strongly (accent + bold).
- Window boundaries marked in the left gutter (e.g. `┌`/`└`).

This is the visual anchor: viewers can see the viewport moving.

## Zoom behavior

- MINIMAL (`-q`): one-line summary per case (`offset/visible/content`, window range)
- SUMMARY (default): a short cursor-follow sequence (3–5 frames)
- DETAILED (`-v`): same sequence + full-content overlay per frame
- FULL (`-vv`): multiple cases side-by-side (follow vs scroll vs resize + edge cases)

## Golden testing

Add `tests/golden/test_demo_viewport.py` following `tests/golden/CLAUDE.md`:

- Import the demo file directly with `spec_from_file_location`
- Parametrize across `Zoom`
- `data = _fetch(); block = _render(ctx, data); golden.assert_match(block_to_text(block), "output")`

Bootstrap with:

`uv run --package painted pytest tests/golden/test_demo_viewport.py --update-goldens -q`

