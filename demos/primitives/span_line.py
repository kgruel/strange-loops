#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Span and Line — mixed styles in a single line.

Span is a run of text with one style. Line combines spans,
giving you mixed styles within a single line — the thing
Block.text() can't do.

Run: uv run demos/primitives/span_line.py
"""

from painted import Block, Style, Span, Line, join_vertical, print_block


def header(text: str) -> Block:
    """Dim section header."""
    return Block.text(f"  {text}", Style(dim=True))


def spacer() -> Block:
    return Block.text("", Style())


def show(line: Line) -> Block:
    """Convert a Line to a Block at its natural width."""
    return line.to_block(line.width)


# --- Spans: styled text runs ---

spans = join_vertical(
    header("spans"),
    spacer(),
    show(Line((Span("  deploy successful", Style(fg="green", bold=True)),))),
    show(Line((Span("  connection timed out", Style(fg="red")),))),
    show(Line((Span("  waiting for response", Style(fg="yellow", italic=True)),))),
    show(Line((Span("  cached result", Style(dim=True)),))),
)

# --- Mixed styles: the point of Span/Line ---

mixed = join_vertical(
    header("mixed styles"),
    spacer(),
    show(Line((
        Span("  Error: ", Style(fg="red", bold=True)),
        Span("connection timed out", Style()),
    ))),
    show(Line((
        Span("  12:04:31 ", Style(dim=True)),
        Span("INFO  ", Style(fg="green", bold=True)),
        Span("request handled in 42ms", Style()),
    ))),
    show(Line((
        Span("  status  ", Style(dim=True)),
        Span("healthy", Style(fg="green", bold=True)),
    ))),
    show(Line((
        Span("  latency ", Style(dim=True)),
        Span("127ms", Style(fg="yellow")),
    ))),
)

# --- Style inheritance: Line style merges onto spans ---

base = Style(fg="blue")

inherit = join_vertical(
    header("style inheritance"),
    spacer(),
    show(Line(
        spans=(Span("  base style only  ", Style()),),
        style=base,
    )),
    show(Line(
        spans=(Span("  span adds bold   ", Style(bold=True)),),
        style=base,
    )),
    show(Line(
        spans=(Span("  span overrides fg", Style(fg="red")),),
        style=base,
    )),
)

# --- Truncation: cut to width, preserving styles ---

long_line = Line((
    Span("  Error: ", Style(fg="red", bold=True)),
    Span("the configuration file at /etc/app/config.yaml could not be parsed",
         Style()),
))

truncation = join_vertical(
    header("truncation"),
    spacer(),
    show(long_line),
    show(long_line.truncate(40)),
    show(long_line.truncate(20)),
)

# --- Wide characters: width-aware ---

wide = join_vertical(
    header("wide characters"),
    spacer(),
    show(Line((
        Span("  ", Style()),
        Span("日本語", Style(fg="magenta")),
        Span(" width=6", Style(dim=True)),
    ))),
    show(Line((
        Span("  ", Style()),
        Span("café", Style(fg="cyan")),
        Span("   width=4", Style(dim=True)),
    ))),
)

# --- Print it ---

print_block(join_vertical(
    spacer(),
    spans,
    spacer(),
    mixed,
    spacer(),
    inherit,
    spacer(),
    truncation,
    spacer(),
    wide,
    spacer(),
))
