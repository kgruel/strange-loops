# KeyboardInput: build-vs-buy + test plan

Date: 2026-02-23

## 1) Build vs buy recommendation

### Current state (baseline)
`src/fidelis/keyboard.py` is a small VT-style parser with:
- cbreak via `termios`/`tty`
- non-blocking reads via `select.select()` + `os.read()`
- CSI (arrows/home/end/insert/delete/page up/down/shift-tab), SS3 (F1–F4 + alt arrows), SGR mouse (1006), UTF-8 assembly, and a 50ms ESC timeout

The biggest risk today is *not* “too much code”; it’s that the behavior isn’t pinned down by tests (and there are known edge cases, e.g. CSI modifier variants for arrows like `ESC [ 1 ; 5 A` currently degrade to `"escape"`).

### Candidate scan (scoped input parsing only)

Quick comparison (as of 2026-02-23):
- `prompt_toolkit`: actively maintained; dependency footprint is “one big package” (+ `wcwidth`).
- `readchar`: small; keyboard-only; no mouse protocol.
- `pynput`: not terminal/stdin; OS hooks.
- `blessed`: feature-fit but explicitly out-of-scope per requirements.

#### `readchar`
- Fit: **No** (keyboard only; not mouse; typical API is blocking `readkey()` usage).
- Why it’s not enough: doesn’t cover SGR mouse (and is not designed as a VT sequence parser you feed bytes to).

#### `pynput`
- Fit: **No** (global OS-level keyboard/mouse hooks; not terminal escape-sequence parsing; not appropriate for stdin polling).

#### `blessed` / `blessings`
- Fit on features: **Yes** (supports `inkey(..., esc_delay=...)`, and SGR mouse parsing/enablement).
- Fit on constraints: **No** for this project’s stated requirement (“no blessed” + it brings output/terminal capability surface area we don’t otherwise need).

#### `prompt_toolkit` input layer
- Fit on features: **Mostly yes** (actively maintained; minimal deps; has a VT100 input parser with an ESC disambiguation/flush mechanism, and it enables xterm SGR (1006) mouse mode).
- Fit on constraints: **Borderline** (it’s not a full TUI framework, but it is a “kitchen sink” interactive-input library; adopting it solely for parsing is a meaningful dependency/size jump compared to ~232 LOC).
- API fit: **Possible**, but not plug-and-play; you’d either:
  1) wrap its stdin reader/event loop model, or
  2) directly instantiate the parser and feed it bytes you read non-blockingly (then map its key/mouse events back into Fidelis’s `str | MouseEvent` model).

### Recommendation

**Keep our hand-rolled parser for now, and close the test gap first.**

Rationale:
- The current parser already meets Fidelis’s required input categories with **zero extra deps**.
- No clearly “scoped, small” third-party library cleanly meets *all* constraints while also being a strict improvement in scope and dependency footprint.
- The highest ROI is to “lock in” behavior via tests; only then decide whether the maintenance burden is actually high enough to justify “buying” a larger dependency.

When to revisit “buy”:
- If we decide we *need* correct, standardized handling of modifier combos (Ctrl/Alt/Shift variants), Alt+key sequences, wider function key coverage (F5+), and portability quirks across terminal emulators.
- In that case, `prompt_toolkit` is the best candidate to re-evaluate first.

## 2) Test plan (keep-or-buy)

### Test strategy
- Unit-test at the `KeyboardInput.get_input()` level by patching `KeyboardInput._read_byte(timeout)` with a deterministic byte stream.
- Add pure unit tests for `parse_sgr_mouse()` (no terminal I/O required).
- Keep existing “single-byte” tests (enter/backspace/tab/etc), but add sequence coverage in a new file to keep diffs reviewable.

### Proposed new test file (if we keep our parser)
Write: `tests/test_keyboard_sequences.py`

Optionally split later:
- `tests/test_keyboard_sequences.py` (keyboard VT sequences + UTF-8 + ESC timeout)
- `tests/test_mouse_sgr.py` (mouse protocol + `parse_sgr_mouse`)

### Helpers (recommended)
In `tests/test_keyboard_sequences.py`, create a tiny helper that turns a list of bytes/None into a `_read_byte` replacement:
- It should ignore the `timeout` argument and just yield the next item.
- For ESC-timeout tests, use a side-effect function that returns `None` specifically when called *after* receiving ESC (to exercise the timeout path).

### Coverage checklist

#### A) Named key mappings (CSI final byte)
Each should return the named key string:
- Up: `b\"\\x1b[A\"` → `"up"`
- Down: `b\"\\x1b[B\"` → `"down"`
- Right: `b\"\\x1b[C\"` → `"right"`
- Left: `b\"\\x1b[D\"` → `"left"`
- Home: `b\"\\x1b[H\"` → `"home"`
- End: `b\"\\x1b[F\"` → `"end"`
- Shift-tab: `b\"\\x1b[Z\"` → `"shift_tab"`

Also validate the SS3 alternate encodings:
- Up/Down/Right/Left: `b\"\\x1bOA\"` / `b\"\\x1bOB\"` / `b\"\\x1bOC\"` / `b\"\\x1bOD\"`
- Home/End: `b\"\\x1bOH\"` / `b\"\\x1bOF\"`

#### B) Named key mappings (CSI parameter + `~`)
- Insert: `b\"\\x1b[2~\"` → `"insert"`
- Delete: `b\"\\x1b[3~\"` → `"delete"`
- Page up: `b\"\\x1b[5~\"` → `"page_up"`
- Page down: `b\"\\x1b[6~\"` → `"page_down"`

#### C) F-keys (SS3)
- F1–F4: `b\"\\x1bOP\"` / `b\"\\x1bOQ\"` / `b\"\\x1bOR\"` / `b\"\\x1bOS\"` → `"f1"` … `"f4"`

#### D) Bare ESC (timeout path)
Simulate:
- first `_read_byte(0)` returns `b\"\\x1b\"`
- then `_read_byte(_ESC_TIMEOUT)` returns `None`
Expect: `"escape"`

Also add a regression test to ensure we don’t “eat” the next byte if ESC is followed by a non-`[`/`O` byte.

#### E) Shift-tab
Already covered above via CSI `Z`, but add:
- `get_key()` returns `"shift_tab"` (through `get_input()` path)

#### F) UTF-8 multi-byte characters
For each, feed the UTF-8 bytes as separate single-byte reads:
- 2-byte: `"é"` (`b\"\\xc3\\xa9\"`)
- 3-byte: `"€"` (`b\"\\xe2\\x82\\xac\"`)
- 4-byte: `"😀"` (`b\"\\xf0\\x9f\\x98\\x80\"`)

Add incomplete sequences (graceful degradation):
- leading byte only (e.g. `b\"\\xc3\"` then `None`) should return a replacement character (`\"�\"`) rather than raising.

#### G) SGR mouse sequences
Test both the `KeyboardInput` integration path and the pure parser:

1) `parse_sgr_mouse()` direct unit tests
- Left press: params `"0;10;5"`, final `"M"` → `MouseAction.PRESS`, `MouseButton.LEFT`, `(x=9,y=4)`
- Left release: params `"0;10;5"`, final `"m"` → `MouseAction.RELEASE`, `MouseButton.LEFT`
- Right press: params `"2;10;5"`, final `"M"` → `MouseButton.RIGHT`
- Scroll up/down: params `"64;10;5"` / `"65;10;5"`, final `"M"` → `MouseAction.SCROLL` + `scroll_delta` -1/+1
- Modifiers:
  - Shift: cb bit 4 set (e.g. `"4;10;5"`) → `shift=True`
  - Meta: cb bit 8 set (e.g. `"8;10;5"`) → `meta=True`
  - Ctrl: cb bit 16 set (e.g. `"16;10;5"`) → `ctrl=True`
- Motion:
  - Drag motion with left button: cb includes bit 32 and button 0 (e.g. `"32;10;5"`) → `MouseAction.MOVE`, `MouseButton.LEFT`
  - Hover motion: cb = 32 + 3 (e.g. `"35;10;5"`) → `MouseAction.MOVE`, `MouseButton.NONE`
- Malformed:
  - wrong arity (`"0;10"`) → `None`
  - non-integer (`"x;10;5"`) → `None`

2) `KeyboardInput.get_input()` SGR integration tests
Feed the full sequence as bytes:
- Press: `b\"\\x1b[<0;10;5M\"` returns `MouseEvent(...)`
- Release: `b\"\\x1b[<0;10;5m\"` returns `MouseEvent(...)`
- Malformed should degrade to `"escape"` (because `_read_sgr_mouse()` returns `None` and `get_input()` maps that to `"escape"`).

#### H) Modifier combinations (keys)
Decide and test the intended behavior. Two viable options:

Option 1 (minimal): **ignore modifiers but still return the base key**
- Examples to add tests for:
  - Ctrl+Up: `ESC [ 1 ; 5 A` → `"up"`
  - Shift+Left: `ESC [ 1 ; 2 D` → `"left"`

Option 2 (richer): **surface modifiers in the return value**
- Change API to return a `KeyEvent` dataclass (or a structured string like `"ctrl+up"`), then update downstream handlers accordingly.

Given Fidelis currently uses `str` keys everywhere, Option 1 is the smallest behavior improvement and can be done without any API churn.

#### I) Malformed / incomplete sequences (graceful degradation)
Add tests to ensure we never raise and we don’t leave “garbage” in the buffer:
- `ESC` then `ESC_TIMEOUT` hit mid-sequence returns `"escape"`
- `ESC [` then timeout returns `"escape"`
- `ESC [ <` then timeout returns `"escape"`
- Unknown CSI final byte returns `"escape"` (e.g. `ESC [ X`)

#### J) `get_key()` filter (mouse events filtered out)
- Patch `KeyboardInput.get_input()` to return a `MouseEvent` and assert `get_key()` returns `None`.

## 3) If we later choose a library: migration sketch (prompt_toolkit)

If we decide to “buy” parsing:
- Add dependency: `prompt_toolkit` (keeps `wcwidth`).
- Implement a small adapter that:
  - keeps `KeyboardInput`’s public API (`get_input()` returns `str | MouseEvent | None`)
  - reads bytes using the existing non-blocking `_read_byte()` loop
  - feeds bytes to the `prompt_toolkit` VT parser
  - maps prompt_toolkit key names to Fidelis key strings (`up/down/...`, `f1..f4`, etc.)
  - maps prompt_toolkit mouse events into `src/fidelis/_mouse.py:MouseEvent`
- Keep the exact same test plan, but switch assertions to match any intentional behavior differences (especially around modifier combos and Alt+key).

## 4) Immediate next steps (keep-our-own)

1) Add `tests/test_keyboard_sequences.py` with the checklist above.
2) Fix any failures exposed by tests (expected near-term fixes):
   - CSI modifier variants for arrows/home/end should return base keys (not `"escape"`).
3) Add `tests/test_mouse_sgr.py` (optional) if `tests/test_keyboard_sequences.py` becomes too large.
