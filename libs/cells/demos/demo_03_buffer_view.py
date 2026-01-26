#!/usr/bin/env python3
"""Demo 03: BufferView — clipped, translated regions.

BufferView wraps a Buffer region with coordinate translation.
Write at (0,0) in the view, it appears at the view's origin in the buffer.
Writes outside the view bounds are silently clipped.

Run: uv run python demos/demo_03_buffer_view.py
"""

from cells import Buffer, Style
from demo_utils import render_buffer

# --- Setup: buffer with border markers ---

buf = Buffer(30, 10)

# Draw a visual border around the whole buffer
for x in range(30):
    buf.put(x, 0, "─", Style(dim=True))
    buf.put(x, 9, "─", Style(dim=True))
for y in range(10):
    buf.put(0, y, "│", Style(dim=True))
    buf.put(29, y, "│", Style(dim=True))
buf.put(0, 0, "┌", Style(dim=True))
buf.put(29, 0, "┐", Style(dim=True))
buf.put(0, 9, "└", Style(dim=True))
buf.put(29, 9, "┘", Style(dim=True))

print("Buffer with border (30x10):")
render_buffer(buf)
print()

# --- Create a view: sub-region of the buffer ---

# View starts at (2, 2), size 12x4
view = buf.region(2, 2, 12, 4)

print(f"Created view: buf.region(2, 2, 12, 4)")
print(f"  view.width = {view.width}, view.height = {view.height}")
print()

# --- Write into view at (0, 0) ---

view.put_text(0, 0, "View origin", Style(fg="green"))

print("After view.put_text(0, 0, 'View origin'):")
render_buffer(buf)
print()

# --- Coordinate translation ---

view.put_text(0, 1, "Line 2", Style(fg="yellow"))
view.put_text(0, 2, "Line 3", Style(fg="cyan"))

print("View coordinates translate to buffer coordinates:")
print("  view(0,1) -> buffer(2,3)")
print("  view(0,2) -> buffer(2,4)")
render_buffer(buf)
print()

# --- Clipping: writes outside view bounds are ignored ---

view.put_text(0, 3, "This line is long and will be clipped at view edge", Style(fg="red"))

print("Text longer than view width gets clipped:")
render_buffer(buf)
print()

# --- Multiple views into same buffer ---

view2 = buf.region(18, 2, 10, 4)
view2.fill(0, 0, 10, 4, "░", Style(fg="magenta"))
view2.put_text(1, 1, "View 2", Style(fg="white", bold=True))

print("Second view at (18, 2), size 10x4:")
render_buffer(buf)
print()

# --- Views are windows, not copies ---

print("Views share the underlying buffer - no copying.")
print()
print("Block gives us immutable rectangles to compose (demo_04).")
