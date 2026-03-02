"""Tests for optional hit-testing (mouse picking) support."""

from painted import Block, Style, border, join_horizontal, join_vertical, pad, truncate, vslice
from painted.tui import Buffer


def test_buffer_hit_none_when_unused():
    buf = Buffer(3, 1)
    buf.put(0, 0, "x", Style())
    assert buf.hit(0, 0) is None


def test_block_paint_records_id():
    buf = Buffer(5, 3)
    b = Block.text("hi", Style(), id="greet")
    b.paint(buf, 1, 1)
    assert buf.hit(1, 1) == "greet"
    assert buf.hit(2, 1) == "greet"
    assert buf.hit(0, 0) is None


def test_bufferview_translates_hit():
    buf = Buffer(6, 4)
    view = buf.region(2, 1, 3, 2)
    Block.text("X", Style(), id="x").paint(view, 1, 0)
    assert buf.hit(3, 1) == "x"
    assert view.hit(1, 0) == "x"
    assert view.hit(2, 1) is None


def test_join_horizontal_preserves_ids_and_gap_is_none():
    a = Block.text("AA", Style(), id="a")
    b = Block.text("BB", Style(), id="b")
    joined = join_horizontal(a, b, gap=1)

    buf = Buffer(joined.width, joined.height)
    joined.paint(buf, 0, 0)

    assert buf.hit(0, 0) == "a"
    assert buf.hit(1, 0) == "a"
    assert buf.hit(2, 0) is None  # gap
    assert buf.hit(3, 0) == "b"
    assert buf.hit(4, 0) == "b"


def test_pad_propagates_uniform_id():
    b = Block.text("X", Style(), id="padded")
    padded = pad(b, left=1, right=1, top=1, bottom=1)

    buf = Buffer(padded.width, padded.height)
    padded.paint(buf, 0, 0)

    assert buf.hit(0, 0) == "padded"  # padding
    assert buf.hit(1, 1) == "padded"  # content


def test_border_default_inherits_uniform_id():
    b = Block.text("X", Style(), id="inner")
    framed = border(b)

    buf = Buffer(framed.width, framed.height)
    framed.paint(buf, 0, 0)

    assert buf.hit(0, 0) == "inner"  # border
    assert buf.hit(1, 1) == "inner"  # content


def test_border_id_overrides_border_cells_only():
    b = Block.text("X", Style(), id="inner")
    framed = border(b, id="border")

    buf = Buffer(framed.width, framed.height)
    framed.paint(buf, 0, 0)

    assert buf.hit(0, 0) == "border"  # border
    assert buf.hit(1, 1) == "inner"  # content


def test_truncate_preserves_uniform_id():
    b = Block.text("hello", Style(), id="t")
    t = truncate(b, 3)

    buf = Buffer(t.width, t.height)
    t.paint(buf, 0, 0)

    assert buf.hit(0, 0) == "t"
    assert buf.hit(1, 0) == "t"
    assert buf.hit(2, 0) == "t"


def test_vslice_preserves_composed_ids():
    top = Block.text("A", Style(), id="a")
    bot = Block.text("B", Style(), id="b")
    joined = join_vertical(top, bot)
    sliced = vslice(joined, 1, 1)

    buf = Buffer(sliced.width, sliced.height)
    sliced.paint(buf, 0, 0)
    assert buf.hit(0, 0) == "b"
