"""Loops palette — domain semantic styles for store and monitoring display.

Extends the painted Theme system with loops-specific color tokens:
kind colors, freshness gradient, content hierarchy, structural chrome.

The palette is the bridge between painted's generic styles and loops'
domain rendering. Lenses receive a palette and use it for all styling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import md5

from painted import Style


# ---------------------------------------------------------------------------
# Freshness thresholds (seconds)
# ---------------------------------------------------------------------------

_FRESH = 600       # < 10 min
_RECENT = 3600     # < 1 hour
_STALE = 86400     # < 1 day


# ---------------------------------------------------------------------------
# Default kind color pool — deterministic rotation for unmapped kinds
# ---------------------------------------------------------------------------

_DEFAULT_KIND_POOL: tuple[Style, ...] = (
    Style(fg="cyan"),
    Style(fg="green"),
    Style(fg="yellow"),
    Style(fg="magenta"),
    Style(fg="blue"),
    Style(fg=174),      # salmon
    Style(fg=114),      # soft green
    Style(fg=179),      # gold
)


# ---------------------------------------------------------------------------
# LoopsPalette
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopsPalette:
    """Domain semantic styles for loops rendering.

    Content hierarchy:
        content     — primary reading text (what you're actually looking at)
        metadata    — counts, timestamps, secondary info
        chrome      — borders, leaders, section markers

    Freshness gradient:
        fresh/recent/stale/old — time-based emphasis

    Kind styles:
        kind_styles — explicit mapping for known kinds
        kind_pool   — fallback rotation for unknown kinds
    """

    # Content hierarchy
    content: Style = field(default_factory=Style)
    metadata: Style = field(default_factory=lambda: Style(dim=True))
    chrome: Style = field(default_factory=lambda: Style(dim=True))

    # Headers / emphasis
    header: Style = field(default_factory=lambda: Style(bold=True))
    section: Style = field(default_factory=lambda: Style(bold=True, dim=True))

    # Freshness gradient
    fresh: Style = field(default_factory=lambda: Style(fg="green"))
    recent: Style = field(default_factory=Style)
    stale: Style = field(default_factory=lambda: Style(dim=True))
    old: Style = field(default_factory=lambda: Style(dim=True, fg=240))

    # Kind color system
    kind_styles: dict[str, Style] = field(default_factory=dict)
    kind_pool: tuple[Style, ...] = field(default=_DEFAULT_KIND_POOL)

    def kind_style(self, kind: str) -> Style:
        """Style for a fact kind — explicit mapping or deterministic fallback."""
        if kind in self.kind_styles:
            return self.kind_styles[kind]
        if not self.kind_pool:
            return Style()
        # Stable hash via md5 — immune to PYTHONHASHSEED randomization
        idx = int.from_bytes(md5(kind.encode()).digest()[:4]) % len(self.kind_pool)
        return self.kind_pool[idx]

    def freshness_style(self, seconds_ago: float) -> Style:
        """Style based on how long ago something happened."""
        if seconds_ago < _FRESH:
            return self.fresh
        if seconds_ago < _RECENT:
            return self.recent
        if seconds_ago < _STALE:
            return self.stale
        return self.old


# ---------------------------------------------------------------------------
# Default palette
# ---------------------------------------------------------------------------

DEFAULT_PALETTE = LoopsPalette()
