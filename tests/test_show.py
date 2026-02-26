"""Tests for show() — zero-config display entry point."""

import io
import json

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


class TestShowJSON:
    """show() with Format.JSON serializes data directly."""

    def test_json_dict(self):
        """show(dict, format=JSON) outputs valid JSON."""
        from fidelis import Format
        buf = io.StringIO()
        show({"status": "ok", "count": 42}, format=Format.JSON, file=buf)
        parsed = json.loads(buf.getvalue())
        assert parsed["status"] == "ok"
        assert parsed["count"] == 42

    def test_json_list(self):
        """show(list, format=JSON) outputs valid JSON."""
        from fidelis import Format
        buf = io.StringIO()
        show([1, 2, 3], format=Format.JSON, file=buf)
        parsed = json.loads(buf.getvalue())
        assert parsed == [1, 2, 3]

    def test_json_non_serializable_uses_str(self):
        """show() with non-serializable data falls back to str()."""
        from fidelis import Format
        from datetime import datetime
        buf = io.StringIO()
        dt = datetime(2026, 2, 25, 12, 0, 0)
        show({"when": dt}, format=Format.JSON, file=buf)
        parsed = json.loads(buf.getvalue())
        assert "2026" in parsed["when"]


from fidelis import Zoom


class TestShowRendered:
    """show() renders data through lens and prints the Block."""

    def test_dict_renders_via_shape_lens(self):
        """show(dict) uses shape_lens by default and produces output."""
        buf = io.StringIO()
        show({"name": "alice", "age": 30}, file=buf)
        output = buf.getvalue()
        assert len(output) > 0  # shape_lens produced something

    def test_custom_lens(self):
        """show(data, lens=fn) uses the provided lens."""
        def my_lens(data, zoom, width):
            return Block.text(f"custom:{data}", Style())

        buf = io.StringIO()
        show(42, lens=my_lens, file=buf)
        assert "custom:42" in buf.getvalue()

    def test_zoom_passed_to_lens(self):
        """show(data, zoom=X) passes zoom to the lens."""
        received = {}

        def spy_lens(data, zoom, width):
            received["zoom"] = zoom
            return Block.text("ok", Style())

        buf = io.StringIO()
        show("hello", zoom=Zoom.DETAILED, lens=spy_lens, file=buf)
        assert received["zoom"] == Zoom.DETAILED

    def test_string_renders(self):
        """show(str) renders the string."""
        buf = io.StringIO()
        show("hello world", file=buf)
        assert "hello" in buf.getvalue()
