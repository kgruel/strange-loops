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
# Horizon proximity thresholds — where a meter ramps warn/critical. Live on
# the palette (not the lens) so the ramp is a palette policy, not a hardcode.
# ---------------------------------------------------------------------------

_HORIZON_WARN = 0.6      # ≥ .6 → approaching the boundary
_HORIZON_CRITICAL = 0.85  # ≥ .85 → about to seal


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
# Default kind styles for the core vocabulary — so the common kinds carry a
# stable, legible hue instead of depending on md5-hash luck. Hues track the
# palette's existing fg roles (accent/warn/critical + the pool's colours).
# ---------------------------------------------------------------------------

_DEFAULT_KIND_STYLES: dict[str, Style] = {
    "decision": Style(fg="cyan"),       # the primary settled-choice kind
    "thread": Style(fg="yellow"),       # open arcs — attention-warm
    "task": Style(fg="green"),          # tracked work
    "friction": Style(fg=208),          # orange — process pain
    "hypothesis": Style(fg="magenta"),  # falsifiable prediction
    "observation": Style(fg="blue"),    # noticed-true, no prescription
    "session": Style(fg=245),           # session chrome — recedes
    "change": Style(fg=179),            # gold — mechanical deltas
    "log": Style(fg=240),               # reflex reroutes — dimmest
}


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

    # Proximity ramp (horizon meter, potential warnings)
    accent: Style = field(default_factory=lambda: Style(fg="cyan"))
    warn: Style = field(default_factory=lambda: Style(fg="yellow"))
    critical: Style = field(default_factory=lambda: Style(fg="red"))

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

    def observer_style(self, observer: str) -> Style:
        """Stable identity colour for an observer.

        Aliased over the kind hash pool for now — a distinct method so kind and
        observer hues can diverge later (once declared Peers give observers a
        typed face). Empty/unattributed observers recede to metadata.
        """
        if not observer:
            return self.metadata
        if not self.kind_pool:
            return Style()
        idx = int.from_bytes(md5(observer.encode()).digest()[:4]) % len(self.kind_pool)
        return self.kind_pool[idx]

    def rail_style(self, tier: str) -> Style:
        """Gutter-glyph style per rail tier (decision:design/rail-wins-gutter).

        The text authority is ``_grammar.TIER_GLYPHS``; this is the parallel
        colour map. ``high`` pops (bold content), ``mid`` is default content,
        ``tail`` recedes to metadata, ``stale`` warns via the old-age hue,
        untiered ("") recedes to chrome. An UNKNOWN tier falls back to the mid
        style — mirroring ``rail_glyph``'s unknown→mid glyph fallback, so an
        unrecognized tier never renders a mid glyph in tail clothing.
        """
        if tier == "":
            return self.chrome
        return {
            "high": self.header,
            "mid": self.content,
            "tail": self.metadata,
            "stale": self.old,
        }.get(tier, self.content)

    def freshness_style(self, seconds_ago: float) -> Style:
        """Style based on how long ago something happened."""
        if seconds_ago < _FRESH:
            return self.fresh
        if seconds_ago < _RECENT:
            return self.recent
        if seconds_ago < _STALE:
            return self.stale
        return self.old

    def horizon_meter_style(self, ratio: float) -> Style:
        """Proximity-meter colour by closeness to the boundary.

        ``ratio`` = unsealed facts / declared count. ``< .6`` accent (calm),
        ``.6–.85`` warn (approaching), ``≥ .85`` critical (about to seal).
        Thresholds live here, not in the lens.
        """
        if ratio >= _HORIZON_CRITICAL:
            return self.critical
        if ratio >= _HORIZON_WARN:
            return self.warn
        return self.accent

    def horizon_approaching(self, ratio: float) -> bool:
        """Is this proximity ratio APPROACHING its boundary? ▲ ≡ critical.

        One threshold telling one story: the ▲ status overlay fires exactly
        where the meter ramp turns critical (≥ .85), so glyph and colour never
        disagree (decision:design/horizon-proximity-sort, amended). The
        threshold lives here — the lens carries no proximity constant.
        """
        return ratio >= _HORIZON_CRITICAL


# ---------------------------------------------------------------------------
# Default palette
# ---------------------------------------------------------------------------

DEFAULT_PALETTE = LoopsPalette(kind_styles=dict(_DEFAULT_KIND_STYLES))
