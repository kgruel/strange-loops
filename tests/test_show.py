"""Tests for show() and print_block() — zero-config display."""

import io
import json

from painted import Block, Style, show
from painted.writer import print_block


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
        from painted import Format
        buf = io.StringIO()
        show({"status": "ok", "count": 42}, format=Format.JSON, file=buf)
        parsed = json.loads(buf.getvalue())
        assert parsed["status"] == "ok"
        assert parsed["count"] == 42

    def test_json_list(self):
        """show(list, format=JSON) outputs valid JSON."""
        from painted import Format
        buf = io.StringIO()
        show([1, 2, 3], format=Format.JSON, file=buf)
        parsed = json.loads(buf.getvalue())
        assert parsed == [1, 2, 3]

    def test_json_non_serializable_uses_str(self):
        """show() with non-serializable data falls back to str()."""
        from painted import Format
        from datetime import datetime
        buf = io.StringIO()
        dt = datetime(2026, 2, 25, 12, 0, 0)
        show({"when": dt}, format=Format.JSON, file=buf)
        parsed = json.loads(buf.getvalue())
        assert "2026" in parsed["when"]


from painted import Zoom


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


class TestShowScalars:
    """Scalars bypass shape_lens — no structure to inspect."""

    def test_string_no_padding(self):
        """show(str) outputs the string without width padding."""
        buf = io.StringIO()
        show("hello", file=buf)
        assert buf.getvalue() == "hello\n"

    def test_int(self):
        """show(int) prints the integer."""
        buf = io.StringIO()
        show(42, file=buf)
        assert buf.getvalue() == "42\n"

    def test_float(self):
        """show(float) prints the float."""
        buf = io.StringIO()
        show(3.14, file=buf)
        assert buf.getvalue() == "3.14\n"

    def test_bool(self):
        """show(bool) prints the boolean."""
        buf = io.StringIO()
        show(True, file=buf)
        assert buf.getvalue() == "True\n"

    def test_none(self):
        """show(None) prints None."""
        buf = io.StringIO()
        show(None, file=buf)
        assert buf.getvalue() == "None\n"

    def test_scalar_with_explicit_lens_uses_lens(self):
        """show(scalar, lens=fn) respects the lens override."""
        def my_lens(data, zoom, width):
            return Block.text(f"[{data}]", Style())

        buf = io.StringIO()
        show("hello", lens=my_lens, file=buf)
        assert "[hello]" in buf.getvalue()

    def test_scalar_json_still_works(self):
        """show(scalar, format=JSON) still outputs JSON."""
        from painted import Format
        buf = io.StringIO()
        show(42, format=Format.JSON, file=buf)
        assert json.loads(buf.getvalue()) == 42


class TestShowAutoDetect:
    """show() auto-detects format from TTY state."""

    def test_non_tty_stream_uses_plain(self):
        """Writing to a non-TTY stream produces plain text (no ANSI codes)."""
        buf = io.StringIO()
        show({"key": "value"}, file=buf)
        output = buf.getvalue()
        # StringIO.isatty() returns False -> format resolves to PLAIN
        assert "\x1b[" not in output  # no ANSI escape codes

    def test_format_json_override(self):
        """format=JSON forces JSON output regardless of TTY."""
        from painted import Format
        buf = io.StringIO()
        show({"key": "value"}, format=Format.JSON, file=buf)
        parsed = json.loads(buf.getvalue())
        assert parsed["key"] == "value"

    def test_format_plain_override(self):
        """format=PLAIN forces plain text (no ANSI)."""
        from painted import Format
        buf = io.StringIO()
        show({"key": "value"}, format=Format.PLAIN, file=buf)
        output = buf.getvalue()
        assert "\x1b[" not in output


class TestPrintBlockAutoDetect:
    """print_block() auto-detects ANSI from stream.isatty()."""

    def test_non_tty_default_no_ansi(self):
        """StringIO (non-TTY) produces plain text by default."""
        block = Block.text("hello", Style(fg="red", bold=True))
        buf = io.StringIO()
        print_block(block, buf)
        output = buf.getvalue()
        assert "hello" in output
        assert "\x1b[" not in output

    def test_explicit_use_ansi_true(self):
        """use_ansi=True forces ANSI even on non-TTY stream."""
        block = Block.text("hello", Style(fg="red"))
        buf = io.StringIO()
        print_block(block, buf, use_ansi=True)
        output = buf.getvalue()
        assert "\x1b[" in output

    def test_explicit_use_ansi_false(self):
        """use_ansi=False forces plain text."""
        block = Block.text("hello", Style(fg="red"))
        buf = io.StringIO()
        print_block(block, buf, use_ansi=False)
        output = buf.getvalue()
        assert "hello" in output
        assert "\x1b[" not in output

    def test_stream_without_isatty(self):
        """Stream without isatty() method defaults to no ANSI."""

        class BareStream:
            def __init__(self):
                self.data = []

            def write(self, s):
                self.data.append(s)

            def flush(self):
                pass

        block = Block.text("hi", Style(fg="red"))
        stream = BareStream()
        print_block(block, stream)
        output = "".join(stream.data)
        assert "hi" in output
        assert "\x1b[" not in output
