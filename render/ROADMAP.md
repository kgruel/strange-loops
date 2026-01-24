# render — Roadmap

## Proven (working in apps today)

Interactive patterns validated by the logs viewer and demo:

- Keyboard navigation (arrow keys, tab focus, key dispatch)
- Scrollable list with selection (ListState — up/down/page/scroll_into_view)
- Text input with cursor (TextInputState — insert/delete/move)
- Focus ring across components (FocusRing — tab/shift-tab)
- Multi-screen navigation (stage paging — left/right)
- Async data streaming with live updates (SSH stdout → mark_dirty)
- Animated rendering (canvas mode — time-varying state, computed positions)
- Modal input (filter overlay — escape to dismiss)
- Toggle states (level filters, auto-scroll, debug overlay)
- Resize handling (SIGWINCH → relayout)
- Frame profiling (FrameTimer — per-phase timing, JSONL dump, debug overlay)

## Possible (primitives support, not yet built)

Patterns the architecture supports without new primitives:

- **Multi-pane splits** — Region already carves rectangular areas from the buffer
- **Popup/overlay panels** — paint a Block on top of existing content
- **Tree/hierarchy navigation** — ListState + indent level tracking
- **Vim-style modal editing** — modal key dispatch is just a state field
- **Tab bar / panel switching** — FocusRing + conditional render
- **Progress workflows** — SpinnerState + ProgressState, sequenced
- **Notification toasts** — timed overlay Block, dismissed on key or timeout
- **Command palette** — TextInputState + filtered ListState (both exist)

## Missing (require new primitives)

Capabilities that need new terminal I/O or component work:

- **Mouse support** — parse mouse escape sequences in KeyboardInput
- **Clipboard** — OSC 52 read/write through Writer
- **Multi-line text editing** — new component (TextAreaState: lines, cursor row/col, scroll)
- **Scrollable containers** — generic viewport wrapping any Block (clip + scroll_offset)
- **Color detection** — query terminal for truecolor/256/16 support (DA1/DA2)
- **Bracketed paste** — detect paste mode, deliver as single string

## Cleanup (from decoupling refactor)

- Move KeyboardInput from framework/ to render/ (pure stdlib, no framework deps)
- Remove framework import from render/app.py
- render/ should depend on nothing except wcwidth
