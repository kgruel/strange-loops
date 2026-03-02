# Terminal Capability Signal: Cold-Reactor Perspective

Date: 2026-02-25

## Role

I read the design doc with zero context from the council discussion. My job is to assess readability, completeness, novelty calibration, merge semantics, and done-ness — the experience of a future developer (or future-me) encountering this document cold.

## What You Found / Proposed / Challenged

### First impression

The document is remarkably clear. The "restated after session" paragraph at the top is the best sentence in the document — it tells me in one breath what the council discovered, not what they were asked. Most design docs bury the punchline; this one leads with it.

The dissolution table is the second-best artifact. It answers "what changes?" and "what doesn't change?" in a way that lets me audit the blast radius without reading the full argument.

### Concerns raised (see Technical Review below)

1. **print_block / InPlaceRenderer path is invisible in the design.** The design talks exclusively about Writer.write_frame() as the resolution point. But `print_block` and `_write_block_ansi` also call `apply_style` -> `_color_codes`. The proposed change to `_color_codes` will automatically cover these paths too — but the design doc never acknowledges that two distinct output paths exist. A reader might wonder if CLI static output gets downconversion or only TUI mode.

2. **detect_color_depth() called per color emission is wasteful phrasing.** The implementation already caches (`self._color_depth`), but the dissolution table says "detect_color_depth() called on every color emission" which reads as "detection logic runs per cell." Misleading for a future reader who hasn't looked at the caching implementation.

3. **_rgb_to_256 is O(240) linear scan.** Fine for the palette sizes involved, but the doc doesn't acknowledge this or note that a lookup table would be the obvious optimization if profiling shows it matters. Given that this runs in the hot path (every styled cell on every frame for sub-truecolor terminals), worth a sentence.

4. **Named color offset math assumes NAMED_COLORS maps to 0-7.** The `_color_codes` design returns `str(base + idx)` for named colors. Cell.py's NAMED_COLORS maps to 0-7, so `base + idx` gives 30-37 (fg) or 40-47 (bg). This is correct for the standard 8 colors but doesn't handle bright variants (90-97/100-107). Not a regression — the current code has the same limitation — but worth noting since the design claims named colors are "already safe."

5. **The design doesn't address the print_block(use_ansi=False) path.** When `use_ansi=False`, characters are emitted without any style processing. This is correct behavior (plain text doesn't need color downconversion), but the "What Doesn't Change" section doesn't mention it, leaving a reader to wonder whether plain output is affected.

## Where You Were Wrong

This section is unusual for a cold-reactor — I enter at the end, so I don't have proposals that were rejected. Instead, I note where my initial skepticism was wrong:

- **I expected the "no pipeline changes" claim to be handwaving.** It isn't. I verified: no view in `_components/` or `_lens.py` constructs a color value from terminal state. They all accept Style objects as parameters or use bare `Style()`. The claim is load-bearing and true.

- **I expected the _color_codes change to miss edge cases.** But the three-way dispatch (hex -> truecolor/256/16, int -> 256/16, named -> always 16) is complete. The only gap is bright named colors, which is a pre-existing limitation, not introduced by this design.

## Where You Were Right

- **The print_block / InPlaceRenderer blind spot is real.** Two output paths share `_color_codes` but the design only narratively discusses one. This won't cause bugs (the fix is structural — changing `_color_codes` covers both paths), but it will confuse a reader.

- **The caching note matters.** "Called on every color emission" is technically true (the method is called) but functionally false (detection runs once). The design doc should match the implementation's actual behavior.

## Cross-Agent Dynamics

As the cold-reactor I didn't participate in the council discussion. I can observe the system effects from the output:

- The siftd findings are the backbone of the argument. Finding #10 ("no view has ever made a capability-dependent rendering decision") is the load-bearing discovery. Without it, the dissolution argument would be speculative.

- The muser's dissolution framing is genuinely useful — the "before/after" table and the principle "if no view consumes it, don't thread it" convert what could be a complex architectural debate into a straightforward absence proof.

- The web-researcher's ecosystem survey validates rather than drives. This is correct — the internal evidence (no consumers) is stronger than external evidence (other frameworks do X).

## Retrospective on the Process

**What worked:** The design doc is self-contained. I could review it without reading constraints docs, research findings, or discussion transcripts. The historical grounding table gives me provenance without requiring me to chase sources. The "restated after session" paragraph is an excellent pattern — it separates the question-as-asked from the question-as-resolved.

**What could improve:** The implementation code blocks are detailed enough to copy-paste, which is good for implementation but makes the design doc long. Consider moving the full implementation to a separate file and keeping only the key signature change (`_color_codes` now calls `detect_color_depth()`) in the design doc. The design decisions are what matter for the design doc; the color arithmetic is an implementation detail.

**The cold-reactor format works.** One pass, fresh eyes, then done. The temptation to re-read and second-guess is real, but the value is in the first impression. I trust that impression.
