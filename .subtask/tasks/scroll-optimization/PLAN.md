# Scroll Optimization Plan (Writer)

## Executive summary

Ultraviolet’s “hard scroll” optimization is a line-hash + hunk-growing algorithm that detects vertical shifts and emits terminal scroll operations (SU/SD, or IL/DL/LF/RI fallbacks) instead of repainting moved lines. For fidelis, adopting a **simplified** version is worth it: it cuts per-scroll output by ~25–40× in representative scenarios with today’s `Writer.write_frame()` (which is very byte-heavy per cell), and it also reduces CPU time spent building the output string.

Recommendation: **Do it**, but start with a narrow, high-confidence implementation (single contiguous scroll region, small `n`, fullscreen/alt-screen only), and gate it behind a feature flag until it’s proven stable across terminals.

---

## 1) How Ultraviolet’s scroll optimization works

### Where the logic lives

- Renderer core: `~/Code/forks/ultraviolet/terminal_renderer.go`
  - Per-line damage model (`RenderBuffer.Touched` / `TouchedLines()`), and the main render loop.
  - Cell-level “transformLine” diffing/writing once a line is selected for processing.
- Hard scroll implementation:
  - `~/Code/forks/ultraviolet/terminal_renderer_hardscroll.go` (`scrollOptimize`, `scrolln`, `scrollUp`, `scrollDown`, `scrollIdl`, `scrollBuffer`)
  - `~/Code/forks/ultraviolet/terminal_renderer_hashmap.go` (`updateHashmap`, `growHunks`, `costEffective`, `updateCost*`, `scrollOldhash`)
- Buffer/damage tracking: `~/Code/forks/ultraviolet/buffer.go` (`RenderBuffer`, `TouchLine`, etc.)

### High-level algorithm

1. **Compute per-line hashes** for old and new buffers (`oldhash`, `newhash`).
   - Hash input is **only `Cell.Content`** per cell (`hash()` writes `c.Content`, not style).
2. **Build a hash table** keyed by line-hash with counts/indices for old and new.
3. **Seed a mapping** `oldnum[newIndex] = oldIndex` for lines whose hashes are unique in both old and new (1:1 matches).
4. **Grow hunks** around those seeds (`growHunks`) both backward and forward:
   - If adjacent lines’ hashes match exactly, extend the hunk.
   - If hashes don’t match, it can still extend when `costEffective()` says the move reduces the number of differing cells to update.
5. **Filter hunks** that are too small or “move too far”:
   - Drops hunks with `size < 3` or where `size + min(size/8, 2) < abs(shift)`.
6. **Apply scroll operations** in two passes:
   - Top→bottom for positive shifts (“scroll up” / forward).
   - Bottom→top for negative shifts (“scroll down” / backward).
   - Each pass groups consecutive lines with the same `shift` into a scroll region and calls `scrolln()`.
7. **Update internal renderer state** to reflect the scroll:
   - `scrollBuffer()` mutates the renderer’s current buffer as if the terminal scrolled.
   - `scrollOldhash()` shifts the old hash slice so future matches remain valid.
   - It touches the affected lines so subsequent `transformLine()` calls validate/fix any remaining diffs.

### “Grows hunks” and the cost analysis

The “grow hunks” stage is what lets Ultraviolet detect scroll even when the mapping isn’t trivially 1:1 unique-hash matches:

- It extends a contiguous mapping by checking adjacent line pairs.
- When hashes don’t match, it consults `costEffective(from, to, blank)`:
  - `updateCost()` counts cell-level differences between two lines (using `cellEqual()`).
  - It compares “cost before move” vs “cost after move”, and accepts the extension if the move doesn’t increase cost.

Note: this cost model is “count of differing cells”, not “byte cost on the wire”.

### Terminal capabilities required (and fallbacks)

Ultraviolet is pragmatic:

- Prefers scroll commands:
  - **SU** (`CSI n S`) and **SD** (`CSI n T`) when `capSU/capSD` are enabled.
- Uses alternatives when needed:
  - Full-screen scroll-up by 1 can be done with a newline at the bottom (`\\n`).
  - Full-screen scroll-down by 1 can use **RI** (Reverse Index).
  - For region scrolling it uses:
    - **DECSTBM** (set top/bottom margins) plus SU/SD, or
    - **DL/IL** (delete/insert line) as a fallback (`scrollIdl`).

It also only enables hard-scroll optimization in **fullscreen/alt-screen** (`tFullscreen`) today (with a comment noting inline-mode would need reliable cursor state and margin handling).

### Edge cases and pitfalls observed in the code

- **Hashes ignore style**: line hashing uses only `Cell.Content`, so style-only changes won’t break scroll matching. That’s usually okay because the post-scroll `transformLine()` pass will still correct style diffs, but it can increase the chance of “false matches” (especially with repeated text).
- **Empty line / nil cell quirks**: `cellEqual()` intentionally treats `nil` specially due to scroll artifacts in empty lines (there’s a FIXME/TODO in `terminal_renderer.go` around this).
- **Partial scroll regions**: margins (`DECSTBM`) are necessary to scroll only part of the screen (e.g., list area without header/footer). Some terminals have bugs here (Ultraviolet currently disables these optimizations on Windows due to a Windows Terminal issue).
- **Wide chars**: both UV and fidelis represent wide chars across multiple cells; line scrolling is generally safe, but insert/delete-line style operations can interact poorly if your buffer model doesn’t preserve wide-char placeholders consistently.

---

## 2) Bandwidth difference (measured with fidelis’ current Writer)

fidelis today:

- `Buffer.diff()` (`src/fidelis/buffer.py`) compares every cell and returns `CellWrite[]`.
- `Writer.write_frame()` (`src/fidelis/writer.py`) emits, for *each* `CellWrite`:
  - `CSI y;x H` cursor move
  - (optional) `SGR` changes
  - the character
  - plus synchronized output wrapper (`CSI ? 2026 h` / `CSI ? 2026 l`)

This makes scrolling very expensive because a vertical shift typically turns into “rewrite most cells in the scrollable region”.

### Representative scenarios (measured in this workspace)

All measurements below are bytes of the string produced by `Writer.write_frame()` to an in-memory `StringIO` stream (so: **encoding + formatting cost**, not actual tty throughput).

1) **List-ish view**: 80×40 screen, only ~30 columns contain item text, scroll up by 1.

- Full repaint (current): `845` cell writes, `7395` bytes
- Scroll-optimized ideal (scroll + repaint only new line):
  - repaint-only writes: `28` cell writes, `268` bytes
  - plus scroll overhead (approx `move_cursor(0,39)` + `CSI 1 S`): `11` bytes
  - total: `~279` bytes
- Reduction: `7395 / 279 ≈ 26.5×`

2) **Worst-ish case**: 80×40, most cells differ on scroll.

- Full repaint (current): `3199` cell writes, `27735` bytes
- Scroll-optimized ideal: `~746` bytes (80 writes for new line + scroll overhead)
- Reduction: `27735 / 746 ≈ 37×`

### CPU cost (also matters locally)

Microbenchmark (StringIO, 120×50 screen, scroll by 1):

- Full repaint: `5998` writes, `~53.5KB` output, `~1.23ms` per `write_frame()`
- New-line-only repaint: `120` writes, `~1.1KB` output, `~0.025ms` per `write_frame()`

So scroll optimization can reduce *both* bytes and Python-side render time by ~50× in this scenario, even before considering real terminal I/O latency.

---

## 3) Fit with fidelis architecture (easy/hard, and where it belongs)

### Current pipeline

- Frame generation: `Surface.render()` paints into `self._buf` (`src/fidelis/app.py`)
- Diff: `writes = self._buf.diff(self._prev)` (cell-level, full-buffer scan)
- Output: `Writer.write_frame(writes)` (per-cell cursor move + char)
- State update: `self._prev = self._buf.clone()`

### What scroll optimization needs

1. **Detection step before cell diff**:
   - It must run on **row/line granularity** (hashes or equality) to discover a vertical shift.
2. **A way to emit scroll commands**:
   - Today `Writer` can only emit cell writes; it needs a “scroll” operation (at least for vertical region scrolling).
3. **A way to keep `_prev` consistent** after emitting a scroll:
   - Either mutate `_prev` as if it scrolled (UV’s approach), or diff against a virtual scrolled view.

### Minimal-change integration point

Best fit is `Surface._flush()` (`src/fidelis/app.py`), because it already owns:

- both buffers (current + previous),
- the decision to “optimize or not”, and
- the writer.

Suggested shape:

- Add a new `Buffer.detect_vertical_scroll(prev) -> ScrollPlan | None`
- Add `Buffer.scroll_region_in_place(...)` to mutate `_prev` when a scroll is emitted
- Extend writer to render a transaction that may include:
  - set scroll region (DECSTBM),
  - scroll up/down n,
  - repaint inserted lines,
  - reset scroll region.

This avoids forcing every component to “know about” scroll ops.

### Do we need Ultraviolet’s full damage model?

Probably not for a first iteration.

Ultraviolet’s `Touched[]` per-line tracking is valuable because it:

- avoids rehashing unchanged lines,
- avoids scanning lines that can’t possibly differ.

fidelis currently re-renders to a fresh buffer each frame and diffs whole-buffer anyway; a first scroll optimization can be implemented **on top of the existing model**, then later extended with per-line “damage” if needed.

---

## 4) Is it worth the complexity?

### Why it’s worth doing (now)

- The byte reduction is large (25–40× per scroll step in common cases with today’s writer).
- It likely reduces flicker and improves perceived responsiveness over slow terminals/SSH.
- It also reduces Python CPU time and syscall pressure (fewer bytes to write).

### Why it’s risky / complex

- Correct region selection is non-trivial when only part of the UI scrolls.
- Terminal scroll regions (DECSTBM) have emulator-specific quirks.
- “Scroll + partial edits” frames can be misdetected if the detection algorithm is too eager.

### Simpler alternatives that capture most value

If the goal is “make rendering fast”, scroll optimization is not the only lever:

- Coalesce writes in `Writer.write_frame()`:
  - Avoid emitting `CSI y;x H` for adjacent cells.
  - Prefer line writes (move once per run, write multiple chars).
- Diff at line granularity first (detect unchanged lines quickly).

These are complementary: do coalescing regardless; do scroll optimization for the big scroll wins.

---

## Recommendation

**Adopt scroll optimization**, but implement a constrained version first:

- only in fullscreen/alt-screen (`Surface` already uses `?1049h`)
- only for a single detected scroll region
- only for small `|n|` (start with `1`, then allow `<= 3`)
- only when detection confidence is high and estimated savings are large
- behind a flag (env var or `Surface` option) until stable

---

## Implementation plan (concrete file changes)

### Phase 0: scaffolding + tests

- Add tests for scroll detection and writer sequences.
  - New: `tests/test_scroll_optimization.py`

### Phase 1: writer support for scroll commands (no detection yet)

Files:

- `src/fidelis/writer.py`

Changes:

- Add helpers:
  - `set_scroll_region(top: int, bottom: int) -> str` (DECSTBM)
  - `reset_scroll_region() -> str` (`CSI r`)
  - `scroll_up(n: int) -> str` (`CSI n S`)
  - `scroll_down(n: int) -> str` (`CSI n T`)
- Add a transaction API so scroll + paints happen under a single sync-output wrapper:
  - e.g. `Writer.write_ops(ops: list[RenderOp])` where `RenderOp` can be `CellWrite` or `ScrollOp`
  - keep `write_frame()` as a compatibility wrapper that calls `write_ops()` with only `CellWrite`s

Tests:

- Verify sequences appear in output (string contains `\\x1b[<top>;<bot>r`, `\\x1b[1S`, `\\x1b[r`).

### Phase 2: buffer-side scroll simulation helpers

Files:

- `src/fidelis/buffer.py`

Changes:

- Add `line_hashes()` (hash per row) used for detection.
  - Include both `cell.char` and `cell.style` in hash input to avoid style-only false matches.
- Add `scroll_region_in_place(top: int, bottom: int, n: int, fill: Cell = EMPTY_CELL)`
  - Updates `_cells` as if the terminal scrolled that region.

Tests:

- Scroll a buffer region and assert post-scroll cell layout is correct.

### Phase 3: detection + integration in Surface

Files:

- `src/fidelis/app.py`

Changes:

- In `Surface._flush()`:
  1. Try detect a vertical scroll between `_prev` and `_buf`:
     - compute per-line hashes for both
     - search candidate shifts `n` in a small range (e.g. `-3..+3`)
     - choose `(top, bottom, n)` maximizing match count with a contiguous region constraint
     - require:
       - region height ≥ 6 (avoid tiny noise)
       - match ratio ≥ 0.7 within region
       - estimated bytes saved ≥ threshold (e.g. ≥ 1KB)
  2. If accepted:
     - emit scroll op for that region
     - mutate `_prev` via `scroll_region_in_place(...)`
     - diff `_buf` vs mutated `_prev` and emit remaining `CellWrite`s
  3. Else:
     - fall back to current full diff

Tests:

- Construct prev/new buffers representing a list scroll within a middle region and assert:
  - a scroll op is produced
  - only new-line cell writes remain

### Phase 4: opt-in + observability

- Add `Surface` option or env var to enable scroll optimization (default off initially).
- Add optional debug counters:
  - detected scrolls, rejected candidates, bytes estimated/actual (when stream is `StringIO` in tests).

---

## If we decide *not* to do it: what would change the answer

Defer if:

- fidelis targets only local terminals and rendering is already “fast enough”, and
- the team prefers to prioritize writer coalescing/run-length output first.

Reconsider (do it) when:

- UI interaction over SSH is a target, or
- scroll-heavy views (lists/tables/logs) are visibly laggy, or
- writer coalescing is done and scroll is still the dominant remaining output volume.

