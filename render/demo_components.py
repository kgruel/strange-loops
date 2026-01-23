"""Demo script exercising all interactive component primitives.

Run with: python -m render.demo_components
"""

from .cell import Style
from .buffer import Buffer
from .block import StyledBlock
from .compose import Align, join_horizontal, join_vertical, pad, border
from .borders import ROUNDED
from .writer import Writer
from .components import (
    SpinnerState, SpinnerFrames, DOTS, LINE, BRAILLE, spinner,
    ProgressState, progress_bar,
    ListState, list_view,
    TextInputState, text_input,
    Column, TableState, table,
)


def demo_spinner() -> None:
    print("=== Spinner ===\n")

    # Basic rendering
    state = SpinnerState()
    block = spinner(state)
    assert block.width == 1 and block.height == 1
    assert block.row(0)[0].char == "⠋"
    print(f"  Initial frame: '{block.row(0)[0].char}' (width={block.width}, height={block.height})")

    # Tick advances frame
    state2 = state.tick()
    assert state2.frame == 1
    block2 = spinner(state2)
    assert block2.row(0)[0].char == "⠙"
    print(f"  After tick: '{block2.row(0)[0].char}' (frame={state2.frame})")

    # Wrap around
    state_wrap = SpinnerState(frame=9)  # last DOTS frame
    state_wrap = state_wrap.tick()
    assert state_wrap.frame == 0
    print(f"  Wrap around: frame 9 → tick → frame {state_wrap.frame}")

    # Different frame sets
    line_state = SpinnerState(frames=LINE)
    line_block = spinner(line_state)
    assert line_block.row(0)[0].char == "-"
    print(f"  LINE frames: '{line_block.row(0)[0].char}'")

    braille_state = SpinnerState(frames=BRAILLE)
    braille_block = spinner(braille_state)
    assert braille_block.row(0)[0].char == "⣾"
    print(f"  BRAILLE frames: '{braille_block.row(0)[0].char}'")

    # Style application
    styled_block = spinner(state, style=Style(fg="cyan", bold=True))
    assert styled_block.row(0)[0].style.fg == "cyan"
    assert styled_block.row(0)[0].style.bold is True
    print(f"  Styled: fg={styled_block.row(0)[0].style.fg}, bold={styled_block.row(0)[0].style.bold}")

    print("  ✓ All spinner assertions passed\n")


def demo_progress() -> None:
    print("=== Progress Bar ===\n")

    # Empty bar
    state = ProgressState(value=0.0)
    bar = progress_bar(state, 20)
    assert bar.width == 20 and bar.height == 1
    assert all(c.char == "░" for c in bar.row(0))
    print(f"  0%: width={bar.width}, all empty chars")

    # Full bar
    state_full = ProgressState(value=1.0)
    bar_full = progress_bar(state_full, 20)
    assert all(c.char == "█" for c in bar_full.row(0))
    print(f"  100%: all filled chars")

    # Half bar
    state_half = state.set(0.5)
    assert state_half.value == 0.5
    bar_half = progress_bar(state_half, 20)
    filled = sum(1 for c in bar_half.row(0) if c.char == "█")
    empty = sum(1 for c in bar_half.row(0) if c.char == "░")
    assert filled == 10 and empty == 10
    print(f"  50%: {filled} filled, {empty} empty")

    # Clamping
    state_over = state.set(1.5)
    assert state_over.value == 1.0
    state_under = state.set(-0.5)
    assert state_under.value == 0.0
    print(f"  Clamping: set(1.5)={state_over.value}, set(-0.5)={state_under.value}")

    # Custom chars and styles
    bar_custom = progress_bar(
        ProgressState(value=0.75), 10,
        filled_char="=", empty_char=".",
        filled_style=Style(fg="blue"),
        empty_style=Style(fg="red"),
    )
    filled_count = sum(1 for c in bar_custom.row(0) if c.char == "=")
    assert filled_count == 8  # round(0.75 * 10) = 8
    print(f"  Custom: 75% of 10 = {filled_count} filled '=' chars")

    print("  ✓ All progress bar assertions passed\n")


def demo_list_view() -> None:
    print("=== List View ===\n")

    items = [
        StyledBlock.text(f"Item {i}", Style()) for i in range(8)
    ]

    # Basic rendering
    state = ListState(selected=0, scroll_offset=0, item_count=8)
    block = list_view(state, items, visible_height=5)
    assert block.height == 5
    print(f"  Basic: height={block.height}, width={block.width}")

    # Cursor char on selected row
    assert block.row(0)[0].char == "▸"
    assert block.row(1)[0].char == " "
    print(f"  Cursor: row 0 has '▸', row 1 has ' '")

    # Move down
    state2 = state.move_down()
    assert state2.selected == 1
    block2 = list_view(state2, items, visible_height=5)
    assert block2.row(1)[0].char == "▸"
    print(f"  move_down: selected={state2.selected}, cursor on row 1")

    # Move to
    state3 = state.move_to(4)
    assert state3.selected == 4
    print(f"  move_to(4): selected={state3.selected}")

    # Clamping
    state_clamp = state.move_to(100)
    assert state_clamp.selected == 7  # last item
    state_clamp2 = state.move_to(-5)
    assert state_clamp2.selected == 0
    print(f"  Clamping: move_to(100)={state_clamp.selected}, move_to(-5)={state_clamp2.selected}")

    # scroll_into_view
    state4 = ListState(selected=7, scroll_offset=0, item_count=8)
    state4 = state4.scroll_into_view(visible_height=5)
    assert state4.scroll_offset == 3  # 7 - 5 + 1 = 3
    print(f"  scroll_into_view: selected=7, visible=5 → offset={state4.scroll_offset}")

    # Move up at top
    state_top = ListState(selected=0, scroll_offset=0, item_count=8)
    assert state_top.move_up().selected == 0
    print(f"  move_up at top: stays at 0")

    # Empty list
    empty_block = list_view(ListState(item_count=0), [], visible_height=3)
    assert empty_block.height == 3
    print(f"  Empty list: height={empty_block.height}")

    print("  ✓ All list view assertions passed\n")


def demo_text_input() -> None:
    print("=== Text Input ===\n")

    # Basic rendering
    state = TextInputState()
    block = text_input(state, 20)
    assert block.width == 20 and block.height == 1
    print(f"  Empty: width={block.width}, height={block.height}")

    # Insert text
    state2 = state.insert("hello")
    assert state2.text == "hello" and state2.cursor == 5
    block2 = text_input(state2, 20)
    assert block2.row(0)[0].char == "h"
    print(f"  insert('hello'): text='{state2.text}', cursor={state2.cursor}")

    # Move cursor
    state3 = state2.move_left()
    assert state3.cursor == 4
    state4 = state3.move_home()
    assert state4.cursor == 0
    state5 = state4.move_end()
    assert state5.cursor == 5
    print(f"  Navigation: left→{state3.cursor}, home→{state4.cursor}, end→{state5.cursor}")

    # Delete
    state6 = state2.move_left().delete_back()
    assert state6.text == "helo" and state6.cursor == 3
    print(f"  delete_back: text='{state6.text}', cursor={state6.cursor}")

    state7 = TextInputState(text="hello", cursor=2).delete_forward()
    assert state7.text == "helo" and state7.cursor == 2
    print(f"  delete_forward: text='{state7.text}', cursor={state7.cursor}")

    # set_text
    state8 = state.set_text("world")
    assert state8.text == "world" and state8.cursor == 5
    print(f"  set_text('world'): cursor at end={state8.cursor}")

    # Scroll behavior
    long_state = TextInputState(text="abcdefghijklmnopqrst", cursor=15)
    block_scroll = text_input(long_state, 10)
    assert block_scroll.width == 10
    # After _ensure_visible, scroll_offset should make cursor visible
    visible_state = long_state._ensure_visible(10)
    assert visible_state.cursor >= visible_state.scroll_offset
    assert visible_state.cursor < visible_state.scroll_offset + 10
    print(f"  Scroll: cursor=15, width=10 → offset={visible_state.scroll_offset}")

    # Placeholder
    placeholder_block = text_input(TextInputState(), 20, focused=False, placeholder="Type here...")
    assert placeholder_block.row(0)[0].char == "T"
    print(f"  Placeholder shown when unfocused + empty")

    # Cursor at end (visible as reversed space)
    end_state = TextInputState(text="hi", cursor=2)
    end_block = text_input(end_state, 10, focused=True)
    # Cursor should be at position 2
    assert end_block.row(0)[2].style.reverse is True
    print(f"  Cursor at end: position 2 has reverse style")

    # Edge: delete_back at start is no-op
    assert TextInputState(text="x", cursor=0).delete_back().text == "x"
    # Edge: delete_forward at end is no-op
    assert TextInputState(text="x", cursor=1).delete_forward().text == "x"
    # Edge: move_left at 0 is no-op
    assert TextInputState(cursor=0).move_left().cursor == 0
    # Edge: move_right at end is no-op
    assert TextInputState(text="x", cursor=1).move_right().cursor == 1
    print(f"  Edge cases: no-ops at boundaries")

    print("  ✓ All text input assertions passed\n")


def demo_table() -> None:
    print("=== Table ===\n")

    columns = [
        Column(header="Name", width=12),
        Column(header="Status", width=8, align=Align.CENTER),
        Column(header="Count", width=6, align=Align.END),
    ]

    rows = [
        ["Alice", "Active", "42"],
        ["Bob", "Idle", "7"],
        ["Charlie", "Active", "123"],
        ["Diana", "Offline", "0"],
        ["Eve", "Active", "99"],
    ]

    state = TableState(selected_row=0, scroll_offset=0, row_count=5)
    block = table(state, columns, rows, visible_height=5)

    # Total width = 12 + 8 + 6 + 1*2 (separators) = 28
    expected_width = 12 + 8 + 6 + 1 * 2
    assert block.width == expected_width
    print(f"  Dimensions: width={block.width}, height={block.height}")

    # Header + separator + 5 data rows = 7
    assert block.height == 7
    print(f"  Height = header(1) + separator(1) + rows(5) = {block.height}")

    # Move down
    state2 = state.move_down()
    assert state2.selected_row == 1
    print(f"  move_down: selected_row={state2.selected_row}")

    # Move to
    state3 = state.move_to(3)
    assert state3.selected_row == 3
    print(f"  move_to(3): selected_row={state3.selected_row}")

    # Clamping
    state_clamp = state.move_to(100)
    assert state_clamp.selected_row == 4
    print(f"  Clamping: move_to(100)={state_clamp.selected_row}")

    # Scrolling
    state4 = TableState(selected_row=4, scroll_offset=0, row_count=5)
    state4 = state4.scroll_into_view(visible_height=3)
    assert state4.scroll_offset == 2  # 4 - 3 + 1 = 2
    print(f"  scroll_into_view: selected=4, visible=3 → offset={state4.scroll_offset}")

    block_scrolled = table(state4, columns, rows, visible_height=3)
    # Header + separator + 3 visible rows = 5
    assert block_scrolled.height == 5
    print(f"  Scrolled table height: {block_scrolled.height}")

    # Alignment verification
    # The "Count" column uses END alignment, so "42" right-aligned in 6 chars = "    42"
    # Check the header row has the column headers
    header_text = "".join(c.char for c in block.row(0))
    assert "Name" in header_text
    assert "Status" in header_text
    assert "Count" in header_text
    print(f"  Header: '{header_text}'")

    # Separator row
    sep_text = "".join(c.char for c in block.row(1))
    assert "─" in sep_text
    print(f"  Separator: '{sep_text}'")

    print("  ✓ All table assertions passed\n")


def demo_composition() -> None:
    print("=== Composed Layout ===\n")

    # Build a composed UI: bordered list next to a progress bar stack
    items = [StyledBlock.text(name, Style()) for name in ["Build", "Test", "Deploy"]]
    ls = ListState(selected=1, scroll_offset=0, item_count=3)
    ls_block = list_view(ls, items, visible_height=3)
    ls_bordered = border(pad(ls_block, left=1, right=1), ROUNDED, Style(fg="cyan"))

    # Stack of progress bars with labels
    bars = []
    for label, value in [("Build", 1.0), ("Test", 0.6), ("Deploy", 0.0)]:
        lbl = StyledBlock.text(f"{label:>6} ", Style(dim=True))
        bar = progress_bar(ProgressState(value=value), 15)
        bars.append(join_horizontal(lbl, bar))

    bars_block = join_vertical(*bars)
    bars_bordered = border(pad(bars_block, left=1, right=1, top=0, bottom=0), ROUNDED, Style(fg="yellow"))

    # Join horizontally
    composed = join_horizontal(ls_bordered, bars_bordered, gap=2)
    print(f"  Composed: width={composed.width}, height={composed.height}")
    assert composed.height == max(ls_bordered.height, bars_bordered.height)

    # Paint to buffer
    writer = Writer()
    cols, term_rows = writer.size()
    buf = Buffer(cols, term_rows)
    prev = buf.clone()

    composed.paint(buf, x=2, y=0)
    writes = buf.diff(prev)

    if writes:
        writer.write_frame(writes)
        print(f"\x1b[{composed.height + 1};1H", end="")

    print(f"  Painted {len(writes)} cells")

    # Also paint a spinner and text input below
    sp = spinner(SpinnerState(frame=3), style=Style(fg="green"))
    ti = text_input(
        TextInputState(text="search query", cursor=12),
        width=20,
        focused=True,
    )
    input_row = join_horizontal(sp, StyledBlock.text(" ", Style()), ti, gap=0)
    input_bordered = border(input_row, ROUNDED, Style(fg="magenta"))

    input_bordered.paint(buf, x=2, y=composed.height + 1)
    writes2 = buf.diff(prev)
    if writes2:
        writer.write_frame(writes2)
        total_h = composed.height + 1 + input_bordered.height + 1
        print(f"\x1b[{total_h};1H", end="")

    print(f"  Input row: width={input_bordered.width}, height={input_bordered.height}")

    print("  ✓ Composition demo complete\n")


def main() -> None:
    demo_spinner()
    demo_progress()
    demo_list_view()
    demo_text_input()
    demo_table()
    demo_composition()
    print("=== All component demos passed ===")


if __name__ == "__main__":
    main()
