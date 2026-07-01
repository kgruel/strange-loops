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
class Edge:
    """A typed graph edge lifted from a declared payload field at read time.

    ``predicate`` is the payload field name the address came from (e.g.
    ``stakeholder``, or ``ref`` for the grandfathered union edge);
    ``address`` is the normalized ``kind:key`` target. Edges are a READ-TIME
    PROJECTION of declared fields (see EdgeDecl in lang) — the raw address
    persisted at emit lights up as an edge only once the field is declared.
    Overlay semantics: the latest folded field value IS the current edge set.
    """

    predicate: str
    address: str


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
        id: ID of the source fact (26-char ULID via python-ulid).
            For "by" folds, the ID of the most recent contributing fact.
            For "collect" folds, the exact fact. None for computed/
            synthetic items.
        n: Number of facts compressed into this item. For "by" folds,
            how many times this key has been upserted. For "collect" folds,
            always 1 (each item is one fact). Reconstructed on replay —
            reads produce the same n as the emit history.
        refs: Accumulated outbound references from the literal ``ref`` field —
            the grandfathered UNION edge (attention-events accumulate, not
            correct). Union of all ``ref`` payload values across all upserts
            to this key. Each ref is a ``kind/key`` entity reference (e.g.
            ``decision/auth``). Empty for items that never carried a ``ref``
            field. NOTE: ``ref`` is the ONLY union edge; typed edges declared
            via ``edge <field> targets=<kind>`` are OVERLAY (last-set wins)
            and surface separately in ``edges`` — see decision:
            architecture/typed-edges-overlay-default.
        edges: Typed OVERLAY edges lifted from declared payload fields at read
            time (predicate = field name, address = normalized ``kind:key``).
            The latest folded field value IS the edge set — re-emit corrects.
            Empty unless the item's kind declares ``edge`` fields that this
            item carries. See ``Edge``.
    """

    payload: dict[str, Any]
    ts: float | None = None
    observer: str = ""
    origin: str = ""
    id: str | None = None
    n: int = 1
    refs: tuple[str, ...] = ()
    edges: tuple[Edge, ...] = ()


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
        preview_fields: Payload field names that the fold lens should render
            in the SUMMARY trailing slot, joined by separator. Order is
            significant — the first field gets the full width budget, later
            fields shrink-then-drop as the line tightens. Empty tuple means
            "no declaration" and the lens falls back to its default rule
            (first non-label payload field).
    """

    kind: str
    items: tuple[FoldItem, ...] = ()
    sections: tuple[FoldSection, ...] = ()
    fold_type: str = "collect"
    key_field: str | None = None
    scalars: dict[str, Any] = field(default_factory=dict)
    preview_fields: tuple[str, ...] = ()
    edge_fields: tuple[tuple[str, str], ...] = ()
    """Declared typed-edge fields for this kind: ``(field, target_kind)`` pairs
    (lang-type-free so atoms stays portable). Read-time consumers use these to
    exclude declared edges when scanning for promotion candidates and to know
    each edge field's target kind. Empty when the kind declares no edges."""

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
class WalkedItem:
    """An entity reached via ref-graph walk from a primary anchor.

    Populated by ``fetch_fold(refs_depth=N)`` when walking from one or more
    primary entities through their outbound refs. Lives parallel to primary
    sections in ``FoldState.walked`` so consumers that ignore the walk
    keep working unchanged.

    Attributes:
        item: The folded item at this address (same shape as primary).
        section_kind: The kind ("decision", "thread", ...) of this entity —
            preserves the type info that's normally carried by the enclosing
            FoldSection, so lenses can render appropriately without a join.
        key_field: The payload field used as fold key for this entity's
            kind (e.g. ``"topic"`` for decision, ``"name"`` for thread).
            Carried alongside section_kind so the lens can derive the
            entity's label without re-parsing the vertex AST or maintaining
            a side-channel kind→key_field map. None for "collect" kinds.
        via_anchor: The ``kind/key`` address of the entity whose outbound ref
            pulled this entity in. For depth=1, that's a primary anchor. For
            depth=2, that's a depth-1 walked entity. Preserves the lineage
            chain so lenses can render nested ``↳`` markers.
        via_direction: Direction of the ref edge that pulled this in.
            ``"outbound"`` means via_anchor's ``ref=`` pointed here.
            ``"inbound"`` is reserved for a future inbound-walk extension —
            A2 walks outbound only.
        depth: Distance from the nearest primary anchor (1 = direct ref of
            a primary, 2 = ref-of-ref, etc.). depth=0 is reserved for primaries
            (which live in ``sections``, not here).
    """

    item: FoldItem
    section_kind: str
    via_anchor: str
    key_field: str | None = None
    via_direction: str = "outbound"
    depth: int = 1


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
        walked: Entities reached via ref-graph walk from primaries (when
            ``fetch_fold(refs_depth>0)``). Empty by default — back-compat
            with consumers that don't render the walk. See WalkedItem.
    """

    sections: tuple[FoldSection, ...]
    vertex: str
    unfolded: dict[str, int] = field(default_factory=dict)
    source_facts: dict[str, list[dict]] = field(default_factory=dict)
    """When retain_facts=True, maps ``kind/key`` to the source facts that
    were compressed into each fold item. Empty by default."""
    walked: tuple[WalkedItem, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True if all sections are empty."""
        return all(s.is_empty for s in self.sections)
