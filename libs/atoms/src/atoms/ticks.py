"""TickWindow — weighted-fact shape at the temporal-window level.

A Tick is a fact produced when a temporal boundary fires. Its payload
carries the folded state at that moment — the *depth* of the window.
The tick's ``since → ts`` interval defines the *window*. The number of
observations compressed, and how that composition changed versus the
previous window, is the *weight*.

``TickWindow`` surfaces that weight as a typed, consumer-ready shape.
Engine produces Ticks; a fetch layer derives TickWindow from a
sequence of Ticks (payload + previous-tick diff). Consumers — lenses,
hooks, higher-level folds — read TickWindow without recomputing.

This is the gripping-hand step at the window level: the Tick's payload
(fold state) becomes input to the next level (TickWindow), carrying
density and depth as observable data. The shape is closed under
recursion — a TickWindow can itself re-enter as a fact payload.

    engine produces:  Tick (fold state at boundary)
    fetch derives:    TickWindow (density + depth + delta vs prior tick)
    lens consumes:    TickWindow → Block

Not an atom in the vocabulary sense (Fact, Spec, Tick are the
primitives). Lives in atoms-the-package so any consumer can import
without pulling in engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TickWindow:
    """Typed density-and-depth summary for one tick's window.

    Fields are newest-first relative to siblings: ``index=0`` is the
    most recent tick in the series. Delta fields compare against the
    previous tick in that ordering (older by ``index + 1``).

    Attributes:
        index: Position in newest-first ordering (0 = most recent).
        name: Tick identity — vertex name for vertex-level boundaries,
            loop name for loop-level boundaries.
        ts: Boundary timestamp (epoch seconds). End of the window.
        since: Period start (epoch seconds). Beginning of the window.
            None when no prior boundary exists (first tick in the series).
        duration_secs: Window length in seconds (``ts - since``). None
            when ``since`` is None.
        observer: Who triggered this boundary (from ``_boundary`` payload).
            Empty string when not set or not applicable.
        boundary_trigger: Human-readable trigger label, e.g. ``"kyle closed"``.
            Empty string when not available.
        total_items: Sum of item counts across all kinds in the snapshot.
        total_facts: Sum of ``_n`` across all items — total observations
            compressed into this tick's state.
        kind_summary: Per-kind item counts, e.g. ``{"decision": 240,
            "thread": 95}``.
        kind_compression: Per-kind average ``_n`` (facts per item), e.g.
            ``{"decision": 1.1, "thread": 3.1}``. Empty for kinds with
            zero items.
        ref_count: Number of items carrying outbound references.
        delta_added: Total new items versus previous tick, summed across
            all kinds. For by-folds this counts newly-keyed items; for
            collect-folds this counts item-count growth.
        delta_updated: Total items whose ``_n`` grew versus previous
            tick. By-folds only (collect-folds contribute 0; they have
            no per-item identity).
        added_keys: Per-kind tuples of newly-added keys. Empty for
            collect-folds. Values sorted alphabetically within each kind.
        updated_keys: Per-kind tuples of keys whose ``_n`` grew. Empty
            for collect-folds. Values sorted alphabetically within each
            kind.
    """

    # Identity
    index: int
    name: str
    ts: float
    since: float | None = None
    duration_secs: float | None = None

    # Trigger
    observer: str = ""
    boundary_trigger: str = ""

    # Density — cumulative at this tick
    total_items: int = 0
    total_facts: int = 0
    kind_summary: dict[str, int] = field(default_factory=dict)
    kind_compression: dict[str, float] = field(default_factory=dict)
    ref_count: int = 0

    # Delta vs previous tick (older by index + 1)
    delta_added: int = 0
    delta_updated: int = 0
    added_keys: dict[str, tuple[str, ...]] = field(default_factory=dict)
    updated_keys: dict[str, tuple[str, ...]] = field(default_factory=dict)
