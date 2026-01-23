"""Demo script exercising all StyledBlock composition operations.

Run with: python -m render.demo_compose
"""

from .cell import Style, Cell
from .buffer import Buffer
from .block import StyledBlock, Wrap
from .compose import Align, join_horizontal, join_vertical, pad, border, truncate
from .borders import ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII
from .writer import Writer


def main() -> None:
    writer = Writer()
    cols, rows = writer.size()

    # Use a buffer sized to terminal
    buf = Buffer(cols, rows)
    prev = buf.clone()

    print("=== StyledBlock Composition Demo ===\n")

    # --- 1. Basic text blocks ---
    title_style = Style(fg="cyan", bold=True)
    body_style = Style(fg="white")
    dim_style = Style(dim=True)

    title = StyledBlock.text("Hello, Blocks!", title_style)
    print(f"1. text('Hello, Blocks!') → width={title.width}, height={title.height}")
    assert title.width == 14 and title.height == 1

    # --- 2. Text with width + wrapping ---
    wrapped = StyledBlock.text("hello world", body_style, width=8, wrap=Wrap.WORD)
    print(f"2. text('hello world', width=8, WORD) → width={wrapped.width}, height={wrapped.height}")
    assert wrapped.width == 8 and wrapped.height == 2

    char_wrap = StyledBlock.text("abcdefghij", body_style, width=4, wrap=Wrap.CHAR)
    print(f"3. text('abcdefghij', width=4, CHAR) → width={char_wrap.width}, height={char_wrap.height}")
    assert char_wrap.width == 4 and char_wrap.height == 3

    ellipsis_block = StyledBlock.text("truncated text here", body_style, width=10, wrap=Wrap.ELLIPSIS)
    print(f"4. text('truncated text here', width=10, ELLIPSIS) → width={ellipsis_block.width}, height={ellipsis_block.height}")
    assert ellipsis_block.width == 10 and ellipsis_block.height == 1
    # Verify ellipsis char is present
    assert ellipsis_block.row(0)[9].char == "…"

    none_trunc = StyledBlock.text("hello world", body_style, width=5, wrap=Wrap.NONE)
    print(f"5. text('hello world', width=5, NONE) → width={none_trunc.width}, height={none_trunc.height}")
    assert none_trunc.width == 5 and none_trunc.height == 1
    assert "".join(c.char for c in none_trunc.row(0)) == "hello"

    # --- 3. Empty block ---
    spacer = StyledBlock.empty(3, 1)
    print(f"6. empty(3, 1) → width={spacer.width}, height={spacer.height}")
    assert spacer.width == 3 and spacer.height == 1

    # --- 4. Padding ---
    padded = pad(title, left=1, right=1, top=1, bottom=1, style=dim_style)
    print(f"7. pad(title, 1,1,1,1) → width={padded.width}, height={padded.height}")
    assert padded.width == title.width + 2
    assert padded.height == title.height + 2

    # --- 5. Border ---
    bordered = border(title, ROUNDED, Style(fg="yellow"))
    print(f"8. border(title, ROUNDED) → width={bordered.width}, height={bordered.height}")
    assert bordered.width == title.width + 2
    assert bordered.height == title.height + 2

    # --- 6. Horizontal join ---
    left = StyledBlock.text("LEFT", Style(fg="green", bold=True))
    right = StyledBlock.text("RIGHT", Style(fg="red", bold=True))
    horiz = join_horizontal(left, right, gap=2)
    print(f"9. join_horizontal(LEFT, RIGHT, gap=2) → width={horiz.width}, height={horiz.height}")
    assert horiz.width == left.width + 2 + right.width
    assert horiz.height == 1

    # --- 7. Vertical join ---
    top_block = StyledBlock.text("top line", Style(fg="blue"))
    bot_block = StyledBlock.text("bottom line", Style(fg="magenta"))
    vert = join_vertical(top_block, bot_block, align=Align.CENTER)
    print(f"10. join_vertical(top, bottom, CENTER) → width={vert.width}, height={vert.height}")
    assert vert.width == max(top_block.width, bot_block.width)
    assert vert.height == top_block.height + bot_block.height

    # --- 8. Truncate ---
    long_block = StyledBlock.text("a very long piece of text", body_style)
    trunc = truncate(long_block, width=10)
    print(f"11. truncate(25-char block, width=10) → width={trunc.width}, height={trunc.height}")
    assert trunc.width == 10 and trunc.height == 1
    assert trunc.row(0)[-1].char == "…"

    # No-op truncate
    short_block = StyledBlock.text("hi", body_style)
    trunc_noop = truncate(short_block, width=10)
    assert trunc_noop.width == 2  # unchanged

    # --- 9. Nested composition ---
    print("\n=== Nested Composition ===\n")

    header = StyledBlock.text("Status Panel", Style(fg="cyan", bold=True))
    separator = StyledBlock.text("─" * 14, Style(fg="yellow", dim=True))
    body = StyledBlock.text("All systems OK", Style(fg="green"))

    inner = join_vertical(
        pad(header, left=1, right=1),
        pad(separator, left=1, right=1),
        pad(body, left=1, right=1),
    )
    panel = border(inner, ROUNDED, Style(fg="yellow"))
    print(f"Panel → width={panel.width}, height={panel.height}")

    # --- 10. Horizontal join with height mismatch + alignment ---
    tall_block = StyledBlock.text("line 1", body_style, width=8, wrap=Wrap.NONE)
    tall_block_2 = join_vertical(
        StyledBlock.text("A", Style(fg="red")),
        StyledBlock.text("B", Style(fg="green")),
        StyledBlock.text("C", Style(fg="blue")),
    )
    aligned = join_horizontal(tall_block, tall_block_2, gap=1, align=Align.CENTER)
    print(f"12. join_horizontal(1-row, 3-row, CENTER) → width={aligned.width}, height={aligned.height}")
    assert aligned.height == 3

    # --- 11. Multiple border styles ---
    print("\n=== Border Styles ===\n")
    for name, chars in [("ROUNDED", ROUNDED), ("HEAVY", HEAVY),
                        ("DOUBLE", DOUBLE), ("LIGHT", LIGHT), ("ASCII", ASCII)]:
        b = border(StyledBlock.text(f" {name} ", body_style), chars, Style(fg="cyan"))
        print(f"  {name}: width={b.width}, height={b.height}")

    # --- 12. Paint to buffer and write ---
    print("\n=== Rendering to Terminal ===\n")

    # Build a composed block
    label = StyledBlock.text("Render", Style(fg="green", bold=True))
    value = StyledBlock.text("OK", Style(fg="cyan"))
    status_line = join_horizontal(label, StyledBlock.text(": ", dim_style), value)
    status_panel = border(pad(status_line, left=1, right=1), ROUNDED, Style(fg="yellow"))

    # Paint into buffer at position (2, 0)
    status_panel.paint(buf, x=2, y=0)

    # Diff and write
    writes = buf.diff(prev)
    if writes:
        writer.write_frame(writes)
        # Move cursor below the rendered panel
        print(f"\x1b[{status_panel.height + 1};1H", end="")

    print(f"  Painted {len(writes)} cells to buffer")
    print(f"  Panel dimensions: {status_panel.width}x{status_panel.height}")

    print("\n=== All assertions passed ===")


if __name__ == "__main__":
    main()
