"""Tests for TextInputState operations and text_input() rendering."""

from painted.cell import Cell, Style
from painted.views import TextInputState, text_input


# --- TextInputState creation and defaults ---


def test_default_state() -> None:
    s = TextInputState()
    assert s.text == ""
    assert s.cursor == 0
    assert s.scroll_offset == 0


def test_state_with_initial_text() -> None:
    s = TextInputState(text="hello", cursor=5)
    assert s.text == "hello"
    assert s.cursor == 5


# --- insert ---


def test_insert_char_at_start() -> None:
    s = TextInputState()
    s = s.insert("a")
    assert s.text == "a"
    assert s.cursor == 1


def test_insert_multiple_chars() -> None:
    s = TextInputState()
    s = s.insert("abc")
    assert s.text == "abc"
    assert s.cursor == 3


def test_insert_at_middle() -> None:
    s = TextInputState(text="ac", cursor=1)
    s = s.insert("b")
    assert s.text == "abc"
    assert s.cursor == 2


def test_insert_at_end() -> None:
    s = TextInputState(text="ab", cursor=2)
    s = s.insert("c")
    assert s.text == "abc"
    assert s.cursor == 3


# --- delete_back (backspace) ---


def test_backspace_removes_char_before_cursor() -> None:
    s = TextInputState(text="abc", cursor=2)
    s = s.delete_back()
    assert s.text == "ac"
    assert s.cursor == 1


def test_backspace_at_start_is_noop() -> None:
    s = TextInputState(text="abc", cursor=0)
    result = s.delete_back()
    assert result is s  # same object returned


def test_backspace_at_end() -> None:
    s = TextInputState(text="abc", cursor=3)
    s = s.delete_back()
    assert s.text == "ab"
    assert s.cursor == 2


# --- delete_forward ---


def test_delete_forward_at_cursor() -> None:
    s = TextInputState(text="abc", cursor=1)
    s = s.delete_forward()
    assert s.text == "ac"
    assert s.cursor == 1


def test_delete_forward_at_end_is_noop() -> None:
    s = TextInputState(text="abc", cursor=3)
    result = s.delete_forward()
    assert result is s


def test_delete_forward_at_start() -> None:
    s = TextInputState(text="abc", cursor=0)
    s = s.delete_forward()
    assert s.text == "bc"
    assert s.cursor == 0


# --- cursor movement ---


def test_move_left() -> None:
    s = TextInputState(text="abc", cursor=2)
    s = s.move_left()
    assert s.cursor == 1


def test_move_left_at_start_is_noop() -> None:
    s = TextInputState(text="abc", cursor=0)
    result = s.move_left()
    assert result is s


def test_move_right() -> None:
    s = TextInputState(text="abc", cursor=1)
    s = s.move_right()
    assert s.cursor == 2


def test_move_right_at_end_is_noop() -> None:
    s = TextInputState(text="abc", cursor=3)
    result = s.move_right()
    assert result is s


def test_move_home() -> None:
    s = TextInputState(text="abc", cursor=2)
    s = s.move_home()
    assert s.cursor == 0


def test_move_end() -> None:
    s = TextInputState(text="abc", cursor=0)
    s = s.move_end()
    assert s.cursor == 3


# --- set_text ---


def test_set_text_replaces_and_moves_cursor_to_end() -> None:
    s = TextInputState(text="old", cursor=1)
    s = s.set_text("new text")
    assert s.text == "new text"
    assert s.cursor == 8


# --- _ensure_visible (scroll adjustment) ---


def test_ensure_visible_zero_width() -> None:
    s = TextInputState(text="abc", cursor=1, scroll_offset=1)
    result = s._ensure_visible(0)
    assert result.scroll_offset == 0


def test_ensure_visible_cursor_in_view() -> None:
    s = TextInputState(text="abcdef", cursor=2, scroll_offset=0)
    result = s._ensure_visible(10)
    # cursor col 2 is within [0, 10), so no scroll change
    assert result.scroll_offset == 0


def test_ensure_visible_cursor_past_right_edge() -> None:
    s = TextInputState(text="abcdefghij", cursor=8, scroll_offset=0)
    result = s._ensure_visible(5)
    # cursor col 8 >= offset_col 0 + width 5, so scrolls right
    assert result.scroll_offset > 0


def test_ensure_visible_cursor_before_offset() -> None:
    s = TextInputState(text="abcdefghij", cursor=1, scroll_offset=5)
    result = s._ensure_visible(5)
    # cursor col 1 < offset col 5, scrolls left
    assert result.scroll_offset <= 1


# --- text_input() render function ---


def _extract_chars(block) -> str:
    """Extract the character string from a rendered block's first row."""
    return "".join(cell.char for cell in block.row(0))


def test_render_empty_focused() -> None:
    s = TextInputState()
    block = text_input(s, width=10, focused=True)
    assert block.width == 10
    assert block.height == 1
    assert len(block.row(0)) == 10


def test_render_shows_text() -> None:
    s = TextInputState(text="hello", cursor=5)
    block = text_input(s, width=10, focused=False)
    chars = _extract_chars(block)
    assert chars.startswith("hello")


def test_render_cursor_highlighted() -> None:
    cursor_style = Style(reverse=True)
    s = TextInputState(text="abc", cursor=1)
    block = text_input(s, width=10, focused=True, cursor_style=cursor_style)
    row = block.row(0)
    # Character at cursor position (index 1) should have cursor_style
    assert row[1].style == cursor_style
    # Character not at cursor should not have cursor_style
    assert row[0].style != cursor_style


def test_render_cursor_at_end_shows_space() -> None:
    cursor_style = Style(reverse=True)
    s = TextInputState(text="ab", cursor=2)
    block = text_input(s, width=10, focused=True, cursor_style=cursor_style)
    row = block.row(0)
    # Cursor is past text, should render as space with cursor style
    assert row[2].char == " "
    assert row[2].style == cursor_style


def test_render_unfocused_no_cursor() -> None:
    cursor_style = Style(reverse=True)
    s = TextInputState(text="abc", cursor=1)
    block = text_input(s, width=10, focused=False, cursor_style=cursor_style)
    row = block.row(0)
    for cell in row:
        assert cell.style != cursor_style


def test_render_placeholder_when_empty_unfocused() -> None:
    s = TextInputState()
    block = text_input(s, width=10, focused=False, placeholder="Type here")
    chars = _extract_chars(block)
    assert chars.startswith("Type here")
    # Placeholder should use dim style
    assert block.row(0)[0].style == Style(dim=True)


def test_render_no_placeholder_when_focused() -> None:
    s = TextInputState()
    block = text_input(s, width=10, focused=True, placeholder="Type here")
    # When focused, even with empty text, placeholder should not show
    # First cell should not be dim placeholder text
    assert block.row(0)[0].style != Style(dim=True)


def test_render_no_placeholder_when_has_text() -> None:
    s = TextInputState(text="x", cursor=1)
    block = text_input(s, width=10, focused=False, placeholder="Type here")
    chars = _extract_chars(block)
    assert chars.startswith("x")


# --- overflow / scrolling ---


def test_render_long_text_scrolls() -> None:
    s = TextInputState(text="abcdefghij", cursor=10)
    block = text_input(s, width=5, focused=True)
    chars = _extract_chars(block)
    # With cursor at end in a 5-wide field, should show tail of text
    assert len(block.row(0)) == 5
    # The visible text should contain the end portion
    assert "j" in chars or block.row(0)[3].char == "j" or block.row(0)[4].char == " "


def test_render_width_always_matches() -> None:
    """Block width should always equal requested width."""
    for text, cursor in [("", 0), ("a", 0), ("abc", 3), ("x" * 20, 10)]:
        s = TextInputState(text=text, cursor=cursor)
        block = text_input(s, width=8, focused=True)
        assert block.width == 8
        assert len(block.row(0)) == 8


# --- edge cases ---


def test_empty_text_backspace() -> None:
    s = TextInputState()
    result = s.delete_back()
    assert result is s
    assert result.text == ""


def test_empty_text_delete_forward() -> None:
    s = TextInputState()
    result = s.delete_forward()
    assert result is s
    assert result.text == ""


def test_single_char_operations() -> None:
    s = TextInputState().insert("x")
    assert s.text == "x"
    assert s.cursor == 1

    left = s.move_left()
    assert left.cursor == 0

    deleted = s.delete_back()
    assert deleted.text == ""
    assert deleted.cursor == 0


def test_frozen_state() -> None:
    """TextInputState should be immutable."""
    s = TextInputState(text="hello", cursor=3)
    s2 = s.insert("x")
    # Original unchanged
    assert s.text == "hello"
    assert s.cursor == 3
    # New state reflects change
    assert s2.text == "helxlo"
    assert s2.cursor == 4
