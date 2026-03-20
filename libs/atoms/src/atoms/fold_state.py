"""FoldState — the typed output of fold computation.

Facts go in, Spec processes, FoldState comes out. This is the contract
between engine (which computes fold state) and lenses (which render it).

Not an atom in the vocabulary sense (Fact, Spec, Tick are the primitives).
Lives in atoms-the-package for portability — any lens author can import
these types without pulling in engine.

    engine computes: Facts + Spec → FoldState
    lens consumes:   FoldState → Block
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TickWindow:
    """Tick metadata for temporal window rendering.

    Not the full engine Tick — the fields a lens needs to render
    the output perspective. Each window defines a ``since → ts``
    interval with computed statistics from the tick payload.

    Attributes:
        index: Position in newest-first ordering (0 = most recent).
        name: Tick identity — vertex name for vertex-level boundaries,
            loop name for loop-level boundaries.
        ts: Boundary timestamp (epoch seconds). End of the window.
        since: Period start (epoch seconds). Beginning of the window.
            None for the first tick (no prior boundary).
        observer: Who triggered this boundary (from boundary payload).
        duration_secs: Window duration in seconds (ts - since). None
            when since is unknown.
        boundary_trigger: What fired this boundary (e.g. "session closed").
        total_items: Total fold items in the snapshot at this tick.
        total_facts: Sum of _n across all items (facts compressed).
        kind_summary: Per-kind item counts, e.g. {"decision": 240, "thread": 95}.
        kind_compression: Per-kind avg compression, e.g. {"decision": 1.1, "thread": 3.1}.
        ref_count: Number of items with outbound references.
        delta_added: Items present in this tick but not in previous.
        delta_updated: Items with changed _n vs previous tick.
    """

    index: int
    name: str
    ts: float
    since: float | None = None
    observer: str = ""
    duration_secs: float | None = None
    boundary_trigger: str = ""
    # Computed from tick payload
    total_items: int = 0
    total_facts: int = 0
    kind_summary: dict[str, int] = field(default_factory=dict)
    kind_compression: dict[str, float] = field(default_factory=dict)
    ref_count: int = 0
    # Delta vs previous tick
    delta_added: int = 0
    delta_updated: int = 0


@dataclass(frozen=True)
class FoldItem:
    """A single item that survived fold computation.

    Not a Fact — the fold may have merged multiple facts into this item
    (e.g. FoldBy keeps the latest per key, overwriting previous). The item
    is the *result* of facts colliding through the fold.

    Attributes:
        payload: Domain fields — the actual content. Access via
            ``item.payload["topic"]``, ``item.payload.get("status")``.
        ts: Epoch seconds of the most recent fact that produced this item.
            None if no timestamp available.
        observer: Who emitted the fact(s) that produced this item.
        origin: Which vertex/loop produced the source fact(s).
        id: ULID of the source fact. For "by" folds, the ID of the most
            recent contributing fact. For "collect" folds, the exact fact.
            None for computed/synthetic items.
        n: Number of facts compressed into this item. For "by" folds,
            how many times this key has been upserted. For "collect" folds,
            always 1 (each item is one fact). Reconstructed on replay —
            reads produce the same n as the emit history.
        refs: Accumulated outbound references from this item. Union of all
            ``ref`` payload values across all upserts to this key. Each ref
            is a ``kind/key`` entity reference (e.g. ``decision/auth``).
            Empty for items that never carried a ``ref`` field.
    """

    payload: dict[str, Any]
    ts: float | None = None
    observer: str = ""
    origin: str = ""
    id: str | None = None
    n: int = 1
    refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class FoldSection:
    """A group of folded items — one per kind, nestable for aggregation.

    Leaf sections have items. Branch sections have sub-sections (e.g. an
    aggregation vertex that discovers child vertices). A section can have
    both — items at this level plus nested sub-groups.

    Attributes:
        kind: The fact kind this section represents ("decision", "thread", etc.)
        items: Folded items in this section.
        sections: Nested sub-sections (for aggregation, prefix grouping, etc.)
        fold_type: How facts were folded — "by" (keyed upsert) or "collect"
            (bounded list). Informs lens rendering strategy.
        key_field: For "by" folds, the field used as the grouping key.
            None for "collect" folds.
        scalars: Non-items fold targets — scalar values computed by the fold
            (count, updated, sum, etc.). Keyed by fold target name.
            Empty when no scalar targets are declared.
    """

    kind: str
    items: tuple[FoldItem, ...] = ()
    sections: tuple[FoldSection, ...] = ()
    fold_type: str = "collect"
    key_field: str | None = None
    scalars: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """Total items in this section (not counting nested sections)."""
        return len(self.items)

    @property
    def is_empty(self) -> bool:
        """True if this section has no items and no non-empty sub-sections."""
        if self.items:
            return False
        return all(s.is_empty for s in self.sections)


@dataclass(frozen=True)
class FoldState:
    """The complete output of fold computation for a vertex.

    This is the contract that every lens receives. Engine computes it,
    lenses render it. The shape is stable — lens authors depend on it.

    Attributes:
        sections: Ordered fold sections (declaration order from vertex AST).
        vertex: Name of the vertex that produced this state.
        unfolded: Kinds present in the store but not declared in the vertex.
            Maps kind name to fact count. Empty when all store kinds are
            declared. Signals incomplete vertex coverage — data exists
            but isn't being folded (no n, no key, no accumulation).
    """

    sections: tuple[FoldSection, ...]
    vertex: str
    unfolded: dict[str, int] = field(default_factory=dict)
    source_facts: dict[str, list[dict]] = field(default_factory=dict)
    """When retain_facts=True, maps ``kind/key`` to the source facts that
    were compressed into each fold item. Empty by default."""
    tick_windows: tuple[TickWindow, ...] = ()
    """When populated, tick boundaries for temporal window grouping.
    Newest-first ordering. Each FoldItem's ts determines which window
    it belongs to. Empty by default — populated when ticks visibility
    layer is active."""

    @property
    def is_empty(self) -> bool:
        """True if all sections are empty."""
        return all(s.is_empty for s in self.sections)
