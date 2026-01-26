"""Theme: named style constants for the render layer."""

from __future__ import annotations

from .cell import Style


# -- Colors --

HEADER_BG = 236
SELECTION_BG = 237
DEBUG_BG = 235


# -- Header --

HEADER_BASE = Style(bg=HEADER_BG)
HEADER_BOLD = Style(bold=True)
HEADER_DIM = Style(dim=True)
HEADER_CONNECTED = Style(fg="green")
HEADER_ERROR = Style(fg="red")
HEADER_SPINNER = Style(fg="yellow")
HEADER_LEVEL_FILTER = Style(fg="cyan")


# -- Footer --

FOOTER_KEY = Style(bold=True, dim=True)
FOOTER_DIM = Style(dim=True)
FOOTER_ACTIVE_FILTER = Style(fg="cyan", dim=True)


# -- Filter input --

FILTER_PROMPT = Style(fg="cyan", bold=True)
FILTER_CURSOR = Style(reverse=True)


# -- Log levels --

LEVEL_STYLES: dict[str | None, Style] = {
    "error": Style(fg="red", bold=True),
    "warn": Style(fg="yellow"),
    "info": Style(),
    "debug": Style(dim=True),
    "trace": Style(dim=True),
    None: Style(),
}


# -- Main area --

SELECTION_CURSOR = Style(fg="cyan", bold=True)
SELECTION_HIGHLIGHT = Style(bg=SELECTION_BG)
SOURCE_DIM = Style(dim=True)
DEBUG_OVERLAY = Style(fg="white", bg=DEBUG_BG)
