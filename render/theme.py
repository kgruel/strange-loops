"""Theme: named style constants for the logs viewer app."""

from __future__ import annotations

from .cell import Style


# -- Colors --

HEADER_BG = "#1a2035"
FOOTER_BG = "#1a1a2a"
FILTER_INPUT_BG = "#2a2040"
SELECTION_BG = "#1a2a3a"


# -- Header --

HEADER_BASE = Style(bg=HEADER_BG)
HEADER_DIM = Style(dim=True, bg=HEADER_BG)
HEADER_TARGET = Style(fg="white", bold=True, bg=HEADER_BG)
HEADER_CONNECTED = Style(fg="green", bg=HEADER_BG)
HEADER_ERROR = Style(fg="red", bg=HEADER_BG)
HEADER_SPINNER = Style(fg="cyan", bg=HEADER_BG)


# -- Footer --

FOOTER_BASE = Style(dim=True, bg=FOOTER_BG)
FOOTER_KEY = Style(bold=True, bg=FOOTER_BG)
FOOTER_SEPARATOR = Style(dim=True, bg=FOOTER_BG)
FOOTER_ACTIVE_FILTER = Style(fg="cyan", bg=FOOTER_BG)


# -- Filter input --

FILTER_PROMPT = Style(bold=True, fg="cyan", bg=FILTER_INPUT_BG)
FILTER_INPUT = Style(bg=FILTER_INPUT_BG)
FILTER_CURSOR = Style(reverse=True, bg=FILTER_INPUT_BG)


# -- Log levels --

LEVEL_STYLES = {
    "error": Style(fg="red", bold=True),
    "warn": Style(fg="yellow"),
    "info": Style(fg="green"),
    "debug": Style(fg="cyan"),
    "trace": Style(fg="magenta", dim=True),
}

LEVEL_LABELS = ("err", "wrn", "inf", "dbg", "trc")
LEVEL_NAMES = ("error", "warn", "info", "debug", "trace")


# -- Main area --

SELECTION_CURSOR = Style(fg="cyan", bold=True)
SELECTION_HIGHLIGHT = Style(bg=SELECTION_BG)
SOURCE_DIM = Style(dim=True)
SCROLL_PAUSED = Style(dim=True, italic=True)
ERROR_TEXT = Style(fg="red")
