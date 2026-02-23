#!/usr/bin/env python3
"""Span and Line — styled text primitives.

Span: a run of text with one style.
Line: a sequence of Spans that paints to a BufferView.

These are lighter-weight than Block for inline styled text.

Run: uv run python demos/primitives/span_line.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fidelis import Style, Span, Line
from fidelis.tui import Buffer
from demo_utils import render_buffer

# --- Span: text + style ---

s1 = Span("Hello", Style(fg="green", bold=True))
s2 = Span(" world", Style(fg="cyan"))

print(f"Span stores text + style:")
print(f"  s1.text={s1.text!r}, s1.width={s1.width}")
print(f"  s2.text={s2.text!r}, s2.width={s2.width}")
print()

# --- Line: sequence of spans ---

line = Line(spans=(s1, s2))
print(f"Line combines spans: width={line.width}")

buf = Buffer(20, 3)
view = buf.region(0, 0, 20, 3)
line.paint(view, x=1, y=1)
render_buffer(buf)
print()

# --- Line.plain: convenience for uniform style ---

plain = Line.plain("Simple text", Style(fg="yellow"))
buf = Buffer(20, 3)
plain.paint(buf.region(0, 0, 20, 3), x=1, y=1)
render_buffer(buf)
print()

# --- Line.truncate: cut to width ---

long_line = Line(spans=(
    Span("Error: ", Style(fg="red", bold=True)),
    Span("something went wrong with the configuration", Style(fg="white")),
))

print(f"Long line width={long_line.width}")
truncated = long_line.truncate(30)
print(f"Truncated to 30: width={truncated.width}")

buf = Buffer(35, 3)
truncated.paint(buf.region(0, 0, 35, 3), x=1, y=1)
render_buffer(buf)
print()

# --- Style inheritance: Line style merges onto Span ---

base_style = Style(fg="blue")
line_with_base = Line(
    spans=(Span("inherit", Style(bold=True)),),  # no fg, inherits blue
    style=base_style
)

buf = Buffer(15, 3)
line_with_base.paint(buf.region(0, 0, 15, 3), x=1, y=1)
print("Line style merges onto spans (blue fg + bold from span):")
render_buffer(buf)
print()

# --- Wide character support ---

wide = Line(spans=(Span("日本語", Style(fg="magenta")),))
print(f"Wide chars: text='日本語', width={wide.width} (3 chars, 6 columns)")

buf = Buffer(12, 3)
wide.paint(buf.region(0, 0, 12, 3), x=1, y=1)
render_buffer(buf)
print()

print("Span/Line are for inline text. Surface runs the event loop (demo_07).")
