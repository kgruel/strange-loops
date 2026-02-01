"""Vertex: where loops meet.

A Vertex manages fold engines, routes facts by kind to the right
consumer, holds an optional Store, and produces Ticks when a
temporal boundary fires.

Kind-based routing: register a fold for each kind. When a fact
arrives, the Vertex dispatches to the matching fold engine.
Projection is the internal fold engine detail — callers register
folds, not Projections.

Boundary triggering: a fold engine can declare a boundary kind.
When a fact with that kind arrives, the engine's state is snapshot
into a Tick and optionally reset. The boundary fires after the fold
completes (fold-before-boundary).

Grant-aware receive: the Vertex gates facts against an optional Grant's
potential. Observer-state kinds (focus.{observer}, scroll.{observer},
selection.{observer}) must match the fact's observer.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from .loop import Loop
from .projection import Projection
from .store import Store
from .tick import Tick

if TYPE_CHECKING:
    from data import Fact
    from vertex.peer import Grant


# Observer-state kind pattern: kind.{observer_name}
_OBSERVER_STATE_PATTERN = re.compile(r"^(focus|scroll|selection)\.(.+)$")


@dataclass
class _FoldEngine:
    """Internal: projection + boundary config."""

    projection: Projection
    boundary: str | None
    reset: bool
    initial: Any


class Vertex:
    """Where loops meet.

    Register folds by kind. Receive facts routed by kind. Fire a
    temporal boundary to produce a Tick snapshot of all fold states.

    Optionally backed by a Store — if provided, every received fact
    is appended to the store before routing.

    Grant-aware: receive() takes a Fact (with observer) and optional Grant.
    The Vertex gates facts against the grant's potential (if provided) and
    enforces observer-state kind ownership based on fact.observer.

    Nesting: a Vertex can contain child vertices. After local routing,
    facts are forwarded to children that accept the kind. Child ticks
    become facts that re-enter the parent.
    """

    def __init__(self, name: str = "", *, store: Store | None = None) -> None:
        self._name = name
        self._engines: dict[str, _FoldEngine] = {}
        self._loops: dict[str, Loop] = {}
        self._boundary_map: dict[str, str] = {}  # boundary_kind → fold_kind
        self._store = store
        self._children: list[Vertex] = []

    @property
    def name(self) -> str:
        """Vertex name — stamped as origin on produced Ticks."""
        return self._name

    @property
    def children(self) -> list[Vertex]:
        """Child vertices, in registration order."""
        return list(self._children)

    def add_child(self, child: Vertex) -> None:
        """Add a child vertex.

        Facts received by this vertex will be forwarded to children that
        accept the kind. Ticks produced by children become facts that
        re-enter this vertex.
        """
        self._children.append(child)

    def accepts(self, kind: str) -> bool:
        """Check if this vertex handles a kind.

        Returns True if the kind is registered as a route (fold engine),
        loop name, or boundary kind — or if any child accepts it.
        Used by parent vertices to determine whether to forward facts
        to this child.
        """
        if kind in self._engines or kind in self._loops or kind in self._boundary_map:
            return True
        return any(child.accepts(kind) for child in self._children)

    def register(
        self,
        kind: str,
        initial: Any,
        fold: Callable[[Any, Any], Any],
        *,
        boundary: str | None = None,
        reset: bool = True,
    ) -> None:
        """Register a fold engine for a fact kind.

        Creates an internal Projection with the given initial state and
        fold function. Facts received with this kind will be routed to
        this fold engine.

        If boundary is provided, receiving a fact with that boundary kind
        will snapshot this engine's state into a Tick and optionally reset
        the engine (if reset=True). The boundary kind must be unique across
        all registered engines.

        Raises ValueError if the kind is already registered or the boundary
        kind is already claimed by another engine.
        """
        if kind in self._engines:
            raise ValueError(f"Kind already registered: {kind}")
        if boundary is not None and boundary in self._boundary_map:
            raise ValueError(f"Boundary kind already registered: {boundary}")
        if boundary is not None:
            self._boundary_map[boundary] = kind
        self._engines[kind] = _FoldEngine(
            projection=Projection(initial, fold=fold),
            boundary=boundary,
            reset=reset,
            initial=copy.deepcopy(initial),
        )

    def register_loop(self, loop: Loop) -> None:
        """Register an explicit Loop object.

        The loop's name becomes the routing kind. If the loop has a
        boundary_kind, that kind will trigger fire() on boundary receipt.

        Raises ValueError if the loop name is already registered or the
        boundary kind is already claimed.
        """
        kind = loop.name
        if kind in self._loops or kind in self._engines:
            raise ValueError(f"Kind already registered: {kind}")
        if loop.boundary_kind is not None:
            if loop.boundary_kind in self._boundary_map:
                raise ValueError(f"Boundary kind already registered: {loop.boundary_kind}")
            self._boundary_map[loop.boundary_kind] = kind
        self._loops[kind] = loop

    def receive(
        self,
        fact: Fact,
        grant: Grant | None = None,
        *,
        _from_child: str | None = None,
    ) -> Tick | None:
        """Route a fact to the appropriate fold engine, gated by optional grant.

        Gating rules:
        1. If grant.potential is not None and fact.kind not in potential → reject
        2. For observer-state kinds (focus.{name}, scroll.{name}, selection.{name}),
           the {name} must match fact.observer → reject if mismatch

        If a Store is attached, the fact is appended before routing.
        Unregistered kinds are silently ignored — they pass through to the
        store but don't fold.

        After local routing, forwards to children that accept the kind.
        Child ticks become facts that re-enter this vertex (but not back
        to the originating child, to prevent recursion).

        After folding, checks if the incoming kind triggers a boundary.
        If so, snapshots the triggered engine's state into a Tick and
        optionally resets the engine. Returns the Tick, or None.

        Returns None on rejection (fact not permitted by grant).

        Args:
            fact: The Fact to receive
            grant: Optional Grant for potential gating
            _from_child: Internal - name of child that produced this fact (prevents loopback)
        """
        kind = fact.kind
        payload = fact.payload
        observer = fact.observer

        # Gate 1: potential check (only if grant provided)
        if grant is not None and grant.potential is not None and kind not in grant.potential:
            return None

        # Gate 2: observer-state ownership
        match = _OBSERVER_STATE_PATTERN.match(kind)
        if match:
            owner_name = match.group(2)
            if owner_name != observer:
                return None

        # Store the full fact (not just kind/payload) for replay
        if self._store is not None:
            self._store.append(fact)

        # Convert fact timestamp for Loop routing
        fact_ts = datetime.fromtimestamp(fact.ts, tz=timezone.utc)

        # Route to _FoldEngine (legacy path - no fidelity tracking)
        engine = self._engines.get(kind)
        if engine is not None:
            engine.projection.fold_one(payload)

        # Route to Loop (Loop tracks its own period_start internally)
        # Loop.receive() returns True if a count-based boundary should fire
        loop = self._loops.get(kind)
        count_boundary_fire = False
        if loop is not None:
            count_boundary_fire = loop.receive(payload, ts=fact_ts)

        # Forward to children that accept this kind
        # Skip the child that produced this fact (prevents loopback)
        for child in self._children:
            if child.name == _from_child:
                continue
            if child.accepts(kind):
                child_tick = child.receive(fact, grant)
                if child_tick is not None:
                    # Child produced a tick — convert to fact and re-enter parent
                    child_fact = self._tick_to_fact(child_tick, child.name)
                    self.receive(child_fact, grant, _from_child=child.name)

        # Check count-based boundary trigger (Loop returned True)
        if count_boundary_fire and loop is not None:
            return loop.fire(fact_ts, origin=self._name)

        # Check kind-based boundary trigger
        fold_kind = self._boundary_map.get(kind)
        if fold_kind is None:
            return None

        # Fire from Loop if registered there
        if fold_kind in self._loops:
            target_loop = self._loops[fold_kind]
            # Loop.fire() handles reset internally
            # Use boundary fact's timestamp for consistency with fact-based time tracking
            return target_loop.fire(fact_ts, origin=self._name)

        # Fire from _FoldEngine (legacy path - no fidelity tracking, since=None)
        engine = self._engines[fold_kind]
        tick = Tick(
            name=fold_kind,
            ts=fact_ts,
            payload=engine.projection.state,
            origin=self._name,
        )
        if engine.reset:
            engine.projection.reset(copy.deepcopy(engine.initial))
        return tick

    def tick(self, name: str, ts: datetime) -> Tick[dict[str, Any]]:
        """Fire a temporal boundary.

        Snapshots all fold engine and Loop states into a dict keyed by kind,
        wraps in a Tick with the given name and timestamp.
        Origin is stamped from the vertex name.
        """
        state = {kind: eng.projection.state for kind, eng in self._engines.items()}
        state.update({kind: loop.state for kind, loop in self._loops.items()})
        return Tick(name=name, ts=ts, payload=state, origin=self._name)

    @property
    def kinds(self) -> list[str]:
        """Registered kinds, in registration order."""
        return list(self._engines.keys()) + list(self._loops.keys())

    def state(self, kind: str) -> Any:
        """Current fold state for a registered kind.

        Raises KeyError if kind is not registered.
        """
        if kind in self._loops:
            return self._loops[kind].state
        return self._engines[kind].projection.state

    def version(self, kind: str) -> int:
        """Current fold version for a registered kind.

        Raises KeyError if kind is not registered.
        """
        if kind in self._loops:
            return self._loops[kind].version
        return self._engines[kind].projection.version

    def to_fact(self, tick: Tick) -> Fact:
        """Convert a Tick to a Fact with this vertex as observer.

        Used when forwarding ticks from one vertex to another.
        The tick becomes a fact with kind="tick.{tick.name}" and
        the vertex name as observer.
        """
        from data import Fact

        return Fact(
            kind=f"tick.{tick.name}",
            ts=tick.ts.timestamp(),
            payload=tick.payload,
            observer=self._name,
        )

    def _tick_to_fact(self, tick: Tick, child_name: str) -> Fact:
        """Convert a child's Tick to a Fact for re-entry.

        The tick's name becomes the fact kind (emit name → kind).
        The child vertex name becomes the observer.
        Payload is spread into the fact.
        """
        from data import Fact

        payload = tick.payload if isinstance(tick.payload, dict) else {"value": tick.payload}
        return Fact(
            kind=tick.name,
            ts=tick.ts.timestamp(),
            payload=payload,
            observer=child_name,
        )

    def ingest(
        self,
        kind: str,
        payload: dict,
        observer: str,
        grant: Grant | None = None,
    ) -> Tick | None:
        """Convenience: create a Fact and receive it in one call.

        Useful for sources and bridges that have raw data rather than
        pre-constructed Facts.

        Args:
            kind: Fact kind
            payload: Dict payload (will be wrapped in Fact.of)
            observer: Who produced this observation
            grant: Optional Grant for potential gating

        Returns:
            Tick if a boundary fired, None otherwise.
        """
        from data import Fact

        fact = Fact.of(kind, observer, **payload)
        return self.receive(fact, grant)
