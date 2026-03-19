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
    """

    sections: tuple[FoldSection, ...]
    vertex: str

    @property
    def is_empty(self) -> bool:
        """True if all sections are empty."""
        return all(s.is_empty for s in self.sections)
