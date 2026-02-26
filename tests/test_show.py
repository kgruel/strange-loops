"""Tests for show() — zero-config display entry point."""

import io

from fidelis import Block, Style, show


class TestShowBlock:
    """show() with a pre-built Block passes it through to print_block."""

    def test_block_passthrough_outputs_content(self):
        """show(block) prints the block's content."""
        block = Block.text("hello", Style())
        buf = io.StringIO()
        show(block, file=buf)
        assert "hello" in buf.getvalue()

    def test_block_passthrough_ignores_lens(self):
        """show(block, lens=...) ignores the lens kwarg."""
        block = Block.text("direct", Style())
        buf = io.StringIO()
        # lens should not be called
        boom = lambda data, zoom, width: (_ for _ in ()).throw(AssertionError("lens called"))
        show(block, lens=boom, file=buf)
        assert "direct" in buf.getvalue()
