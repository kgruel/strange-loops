#!/usr/bin/env python3
"""Demo: Buffer creation, styled text, diffing, and Writer output."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from render import Buffer, Style, Writer

WIDTH, HEIGHT = 40, 10


def main():
    writer = Writer()
    print(f"Terminal color depth: {writer.detect_color_depth().name}")
    print(f"Buffer size: {WIDTH}x{HEIGHT} = {WIDTH * HEIGHT} cells\n")

    # --- Frame 1: initial content ---
    buf1 = Buffer(WIDTH, HEIGHT)

    title_style = Style(fg="cyan", bold=True)
    buf1.put_text(2, 1, "Cell Buffer Demo", title_style)

    body_style = Style(fg="white")
    buf1.put_text(2, 3, "This is frame 1.", body_style)

    border_style = Style(fg="green")
    buf1.fill(0, 0, WIDTH, 1, "-", border_style)
    buf1.fill(0, HEIGHT - 1, WIDTH, 1, "-", border_style)

    # --- Frame 2: modified content ---
    buf2 = buf1.clone()

    buf2.put_text(2, 3, "This is frame 2!", Style(fg="yellow", bold=True))
    buf2.put_text(2, 5, "New line added.", Style(fg="magenta"))

    # Use a region to write inside a box
    view = buf2.region(25, 3, 12, 4)
    view.fill(0, 0, 12, 4, ".", Style(fg=240))  # 256-color gray fill
    view.put_text(1, 1, "region!", Style(fg="#ff8800", bold=True))

    # --- Diff ---
    diff = buf2.diff(buf1)
    total_cells = WIDTH * HEIGHT

    print(f"Diff: {len(diff)} changed cells out of {total_cells} total")
    print(f"  -> {100 * len(diff) / total_cells:.1f}% of screen rewritten\n")

    # Print the diff details (positions only)
    print("Changed positions:")
    for w in diff[:20]:
        print(f"  ({w.x:2d}, {w.y:2d}) = {w.cell.char!r}")
    if len(diff) > 20:
        print(f"  ... and {len(diff) - 20} more")

    # --- Write to terminal ---
    print("\n--- Rendering diff to terminal ---\n")

    # Move down a bit so we don't overwrite our own output
    # In real use you'd use alt screen; here we just show it works
    print("\n" * HEIGHT)

    # Write frame using the diff
    writer.write_frame(diff)

    # Move cursor below the rendered area
    sys.stdout.write(f"\x1b[{HEIGHT + 2}B\n")
    sys.stdout.flush()

    print("\nDone. Only changed cells were written to terminal.")


if __name__ == "__main__":
    main()
