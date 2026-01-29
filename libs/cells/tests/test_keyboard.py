"""Tests for keyboard input handling."""

from unittest.mock import patch

from cells.tui import KeyboardInput


class TestGetKey:
    """Test KeyboardInput.get_key() byte handling."""

    def test_cr_returns_enter(self):
        """CR (0x0D) returns 'enter'."""
        kb = KeyboardInput()
        kb._available = True
        with patch.object(kb, "_read_byte", return_value=b"\x0d"):
            assert kb.get_key() == "enter"

    def test_lf_returns_enter(self):
        """LF (0x0A) returns 'enter' — some terminals send this instead of CR."""
        kb = KeyboardInput()
        kb._available = True
        with patch.object(kb, "_read_byte", return_value=b"\x0a"):
            assert kb.get_key() == "enter"

    def test_backspace_returns_backspace(self):
        """DEL (0x7F) returns 'backspace'."""
        kb = KeyboardInput()
        kb._available = True
        with patch.object(kb, "_read_byte", return_value=b"\x7f"):
            assert kb.get_key() == "backspace"

    def test_tab_returns_tab(self):
        """TAB (0x09) returns 'tab'."""
        kb = KeyboardInput()
        kb._available = True
        with patch.object(kb, "_read_byte", return_value=b"\x09"):
            assert kb.get_key() == "tab"

    def test_none_when_no_input(self):
        """Returns None when no input available."""
        kb = KeyboardInput()
        kb._available = True
        with patch.object(kb, "_read_byte", return_value=None):
            assert kb.get_key() is None

    def test_none_when_unavailable(self):
        """Returns None when keyboard not available."""
        kb = KeyboardInput()
        kb._available = False
        assert kb.get_key() is None
