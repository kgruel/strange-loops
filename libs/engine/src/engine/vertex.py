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

import fnmatch
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from .loop import Loop
from .projection import Projection
from .store import Store
from .tick import Tick

if TYPE_CHECKING:
    from atoms import Fact
    from .peer import Grant


# Observer-state kind pattern: kind.{observer_name}
_OBSERVER_STATE_PATTERN = re.compile(r"^(focus|scroll|selection)\.(.+)$")


def _json_default(obj: object) -> object:
    """Handle MappingProxyType in JSON serialization."""
    from types import MappingProxyType
    if isinstance(obj, MappingProxyType):
        return dict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _eval_condition(state: Any, condition: Any) -> bool:
    """Evaluate a single BoundaryCondition against fold state.

    State can be a dict (named targets) or MappingProxyType. The condition's
    target is looked up in state, then compared using the operator.
    """
    from types import MappingProxyType
    if isinstance(state, MappingProxyType):
        state = dict(state)
    if not isinstance(state, dict):
        return False
    value = state.get(condition.target)
    if value is None:
        return False
    try:
        fval = float(value)
        fcomp = float(condition.value)
    except (ValueError, TypeError):
        # Fall back to string comparison for == and !=
        if condition.op == "==":
            return str(value) == str(condition.value)
        if condition.op == "!=":
            return str(value) != str(condition.value)
        return False
    if condition.op == ">=":
        return fval >= fcomp
    if condition.op == "<=":
        return fval <= fcomp
    if condition.op == ">":
        return fval > fcomp
    if condition.op == "<":
        return fval < fcomp
    if condition.op == "==":
        return fval == fcomp
    if condition.op == "!=":
        return fval != fcomp
    return False


def _eval_conditions(state: Any, conditions: tuple) -> bool:
    """Evaluate all BoundaryConditions — AND semantics."""
    return all(_eval_condition(state, c) for c in conditions)


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
        self._loops: dict[str, Loop] = {}
        self._boundary_map: dict[str, str] = {}  # boundary_kind → fold_kind
        self._boundary_match: dict[str, tuple[tuple[str, str], ...]] = {}  # boundary_kind → match
        self._boundary_conditions: dict[str, tuple] = {}  # boundary_kind → conditions
        self._vertex_boundary: str | None = None  # vertex-level boundary kind
        self._vertex_boundary_match: tuple[tuple[str, str], ...] = ()
        self._vertex_boundary_conditions: tuple = ()
        self._vertex_period_start: datetime | None = None
        self._store = store
        self._replaying = False  # suppress boundaries during replay
        self._children: list[Vertex] = []
        self._routes: dict[str, str] = {}  # pattern → loop_name
        self._parse_pipelines: dict[str, list] = {}  # kind → compiled ParseOp list

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

    def set_routes(self, routes: dict[str, str]) -> None:
        """Set pattern-based routing rules.

        Routes map glob patterns to loop names. When a fact arrives,
        patterns are checked in order and the first match determines
        which loop receives the fact.

        Pattern syntax (fnmatch):
        - * matches any sequence of characters
        - ? matches any single character
        - [seq] matches any character in seq

        Examples:
            {"disk.*": "disk"}      # disk.usage, disk.io → disk loop
            {"proc.*": "proc"}      # proc.cpu, proc.mem → proc loop
            {"disk": "disk"}        # exact match (no wildcards)

        Args:
            routes: Dict mapping glob patterns to loop names
        """
        self._routes = routes.copy()

    def set_parse_pipelines(self, pipelines: dict[str, list]) -> None:
        """Set per-kind parse pipelines.

        Parse pipelines transform fact payloads before routing to folds.
        Derived fields are added alongside originals.

        Args:
            pipelines: Dict mapping kind name to list of compiled ParseOps
        """
        self._parse_pipelines = pipelines.copy()

    def _resolve_route(self, kind: str) -> str | None:
        """Resolve a fact kind to a loop name via route patterns.

        Returns the loop name if a route matches, None otherwise.
        Patterns are checked in dict order (Python 3.7+ preserves insertion order).
        """
        for pattern, loop_name in self._routes.items():
            if fnmatch.fnmatch(kind, pattern):
                return loop_name
        return None

    def accepts(self, kind: str) -> bool:
        """Check if this vertex handles a kind.

        Returns True if the kind is registered as a route (fold engine),
        loop name, boundary kind, or matches a pattern route — or if any
        child accepts it. Used by parent vertices to determine whether
        to forward facts to this child.
        """
        if kind in self._loops or kind in self._boundary_map or kind == self._vertex_boundary:
            return True
        # Check pattern-based routes
        if self._resolve_route(kind) is not None:
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
        """Convenience: create a Loop from args and register it.

        Preserves the original API — all existing callers keep working.
        Internally everything routes through _loops via register_loop().

        Raises ValueError if the kind is already registered or the boundary
        kind is already claimed by another engine.
        """
        loop = Loop(
            name=kind,
            projection=Projection(initial, fold=fold),
            boundary_kind=boundary,
            reset=reset,
        )
        self.register_loop(loop)

    def register_loop(self, loop: Loop) -> None:
        """Register an explicit Loop object.

        The loop's name becomes the routing kind. If the loop has a
        boundary_kind, that kind will trigger fire() on boundary receipt.

        Raises ValueError if the loop name is already registered or the
        boundary kind is already claimed.
        """
        kind = loop.name
        if kind in self._loops:
            raise ValueError(f"Kind already registered: {kind}")
        if loop.boundary_kind is not None:
            if loop.boundary_kind in self._boundary_map:
                raise ValueError(f"Boundary kind already registered: {loop.boundary_kind}")
            self._boundary_map[loop.boundary_kind] = kind
            if loop.boundary_match:
                self._boundary_match[loop.boundary_kind] = loop.boundary_match
            if loop.boundary_conditions:
                self._boundary_conditions[loop.boundary_kind] = loop.boundary_conditions
        self._loops[kind] = loop

    def register_vertex_boundary(
        self,
        kind: str,
        match: tuple[tuple[str, str], ...] = (),
        conditions: tuple = (),
    ) -> None:
        """Register a vertex-level boundary.

        When a fact of this kind arrives (and matches payload conditions,
        and all fold-state conditions are met), ALL loop states are snapshot
        into a single Tick. This is the vertex's cycle boundary — e.g.
        session close snapshots everything.

        Vertex-level boundaries take precedence over loop-level boundaries
        for the same kind.
        """
        if kind in self._boundary_map:
            raise ValueError(
                f"Boundary kind '{kind}' already registered at loop level"
            )
        self._vertex_boundary = kind
        self._vertex_boundary_match = match
        self._vertex_boundary_conditions = conditions

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

        # Track vertex-level period start (first fact after reset)
        # Suppressed during replay — replay sets period from last tick instead
        if (self._vertex_boundary is not None
                and self._vertex_period_start is None
                and not self._replaying):
            self._vertex_period_start = fact_ts

        # Resolve routing: exact match first, then pattern-based routes
        routed_kind = kind  # Default: route to same name as fact kind
        if kind not in self._loops:
            # No exact match — try pattern-based routes
            resolved = self._resolve_route(kind)
            if resolved is not None:
                routed_kind = resolved

        # Apply per-kind parse pipeline (transforms payload before fold)
        parse_pipeline = self._parse_pipelines.get(routed_kind)
        if parse_pipeline is not None:
            from atoms import run_parse
            # Convert MappingProxyType to dict for parse pipeline
            parse_input = dict(payload) if hasattr(payload, 'keys') else payload
            parsed = run_parse(parse_input, parse_pipeline)
            if parsed is None:
                # Parse rejected this fact — skip fold and routing,
                # consistent with source-level parse where None means
                # "drop the record." Fact is already stored for audit.
                return None
            payload = parsed

        # Route to Loop — Loop tracks its own period_start internally
        # Loop.receive() returns True if a count-based boundary should fire
        loop = self._loops.get(routed_kind)
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

        # During replay, fold only — no boundaries fire
        if self._replaying:
            return None

        # Check count-based boundary trigger (Loop returned True)
        if count_boundary_fire and loop is not None:
            tick = loop.fire(fact_ts, origin=self._name)
            self._store_tick(tick)
            return tick

        # Check vertex-level boundary first (fires all loops)
        if self._vertex_boundary == kind:
            if not self._vertex_boundary_match or all(
                payload.get(k) == v for k, v in self._vertex_boundary_match
            ):
                # Check fold-state conditions (if any)
                if self._vertex_boundary_conditions:
                    # Vertex-level: check conditions against the routed loop's state
                    cond_loop = self._loops.get(routed_kind)
                    if cond_loop is None or not _eval_conditions(
                        cond_loop.state, self._vertex_boundary_conditions
                    ):
                        return None
                tick = self._fire_vertex_boundary(fact_ts, payload)
                self._store_tick(tick)
                return tick

        # Check loop-level kind-based boundary trigger
        fold_kind = self._boundary_map.get(kind)
        if fold_kind is None:
            return None

        # Check payload match conditions (if any)
        match = self._boundary_match.get(kind, ())
        if match and not all(payload.get(k) == v for k, v in match):
            return None

        # Check fold-state conditions (if any)
        conditions = self._boundary_conditions.get(kind, ())
        if conditions:
            target_loop = self._loops[fold_kind]
            if not _eval_conditions(target_loop.state, conditions):
                return None

        # Fire from the target loop
        target_loop = self._loops[fold_kind]
        tick = target_loop.fire(fact_ts, origin=self._name,
                                boundary_payload=payload)
        self._store_tick(tick)
        return tick

    def _fire_vertex_boundary(
        self, ts: datetime, boundary_payload: dict,
    ) -> Tick[dict[str, Any]]:
        """Fire a vertex-level boundary — snapshot ALL loop states.

        Unlike loop.fire() which snapshots one loop, this captures the
        full vertex state. Used for observer lifecycle boundaries like
        session close, where the tick should carry everything.
        """
        import json

        # Snapshot all loop states — JSON round-trip to strip MappingProxy
        raw = {kind: loop.state for kind, loop in self._loops.items()}
        state = json.loads(json.dumps(raw, default=_json_default))
        state["_boundary"] = dict(boundary_payload)
        tick = Tick(
            name=self._name,
            ts=ts,
            payload=state,
            origin=self._name,
            since=self._vertex_period_start,
        )
        self._vertex_period_start = None  # reset for next period
        return tick

    def tick(self, name: str, ts: datetime) -> Tick[dict[str, Any]]:
        """Fire a temporal boundary.

        Snapshots all Loop states into a dict keyed by kind,
        wraps in a Tick with the given name and timestamp.
        Origin is stamped from the vertex name.
        """
        state = {kind: loop.state for kind, loop in self._loops.items()}
        return Tick(name=name, ts=ts, payload=state, origin=self._name)

    @property
    def kinds(self) -> list[str]:
        """Registered kinds, in registration order."""
        return list(self._loops.keys())

    def state(self, kind: str) -> Any:
        """Current fold state for a registered kind.

        Raises KeyError if kind is not registered.
        """
        return self._loops[kind].state

    def version(self, kind: str) -> int:
        """Current fold version for a registered kind.

        Raises KeyError if kind is not registered.
        """
        return self._loops[kind].version

    def replay(self) -> int:
        """Replay stored facts to rebuild fold state.

        Reads all facts from the store and routes them through the folds
        without re-appending or firing boundaries. This makes a one-shot
        CLI invocation indistinguishable from a persistent runtime — fold
        state reflects all historical facts, not just the current invocation.

        After replay, initializes the vertex period start from the last
        stored tick. This ensures the next boundary fire produces a tick
        with ``since`` pointing to the previous boundary, not the first
        fact in history.

        Returns the number of facts replayed.
        """
        if self._store is None:
            return 0
        facts = self._store.since(0)
        if not facts:
            return 0
        store = self._store
        self._store = None  # suppress re-append during replay
        self._replaying = True  # suppress boundary firing and period tracking
        for fact in facts:
            self.receive(fact)
        self._replaying = False
        self._store = store  # restore

        # Initialize period start from last vertex-level tick.
        # Vertex-level boundary ticks use self._name as tick name.
        # The last such tick's ts is the end of the previous period —
        # the next boundary's since should start from there.
        if self._vertex_boundary is not None and hasattr(store, 'ticks_since'):
            for tick in reversed(store.ticks_since(0)):
                if tick.name == self._name:
                    self._vertex_period_start = tick.ts
                    break

        return len(facts)

    def to_fact(self, tick: Tick) -> Fact:
        """Convert a Tick to a Fact with this vertex as observer.

        Used when forwarding ticks from one vertex to another.
        The tick becomes a fact with kind="tick.{tick.name}" and
        the vertex name as observer. Origin is preserved from the tick.
        """
        from atoms import Fact

        return Fact(
            kind=f"tick.{tick.name}",
            ts=tick.ts.timestamp(),
            payload=tick.payload,
            observer=self._name,
            origin=tick.origin,
        )

    def _store_tick(self, tick: Tick) -> None:
        """Persist tick to store if it supports tick persistence."""
        if self._store is not None and hasattr(self._store, 'append_tick'):
            self._store.append_tick(tick)

    def _tick_to_fact(self, tick: Tick, child_name: str) -> Fact:
        """Convert a child's Tick to a Fact for re-entry.

        The tick's name becomes the fact kind (emit name → kind).
        The child vertex name becomes the observer.
        Payload is spread into the fact. Origin is preserved from the tick.
        """
        from atoms import Fact

        payload = tick.payload if isinstance(tick.payload, dict) else {"value": tick.payload}
        return Fact(
            kind=tick.name,
            ts=tick.ts.timestamp(),
            payload=payload,
            observer=child_name,
            origin=tick.origin,
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
        from atoms import Fact

        fact = Fact.of(kind, observer, **payload)
        return self.receive(fact, grant)
