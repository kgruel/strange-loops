"""Shared utilities for demos."""

from fidelis import Writer
from fidelis.tui import Buffer

# Shared writer instance
writer = Writer()


def render_buffer(buf: Buffer) -> None:
    """Render a buffer inline with a border for clarity."""
    print("┌" + "─" * buf.width + "┐")

    for y in range(buf.height):
        print("│", end="")
        for x in range(buf.width):
            cell = buf.get(x, y)
            sgr = writer.apply_style(cell.style)
            reset = writer.reset_style() if sgr else ""
            print(f"{sgr}{cell.char}{reset}", end="")
        print("│")

    print("└" + "─" * buf.width + "┘")
