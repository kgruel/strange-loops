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

Decoupled boundary evaluation: evaluate_boundaries() checks boundary
triggers for facts that arrived via external emit (between vertex runs).
Facts folded during replay don't trigger boundaries — evaluate_boundaries()
scans the current period's facts and fires any matching boundaries against
the fully-rebuilt fold state. Called by the Executor before source execution.

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
        self._has_loop_boundaries = False
        self._boundary_match: dict[str, tuple[tuple[str, str], ...]] = {}  # boundary_kind → match
        self._boundary_conditions: dict[str, tuple] = {}  # boundary_kind → conditions
        self._vertex_boundary: str | None = None  # vertex-level boundary kind
        self._has_vertex_boundary = False
        self._vertex_boundary_match: tuple[tuple[str, str], ...] = ()
        self._vertex_boundary_conditions: tuple = ()
        self._vertex_boundary_run: str | None = None  # boundary run clause
        self._vertex_period_start: datetime | None = None
        self._store = store
        self._replaying = False  # suppress boundaries during replay
        self._has_children = False
        self._children: list[Vertex] = []
        self._routes: dict[str, str] = {}  # pattern → loop_name
        self._has_routes = False
        self._route_cache: dict[str, str | None] = {}
        self._accepts_cache: dict[str, bool] = {}
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
        self._has_children = True
        self._accepts_cache.clear()

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
        self._has_routes = bool(self._routes)
        self._route_cache.clear()
        self._accepts_cache.clear()

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
        Caches per-kind results because receive() and accepts() often see the
        same kinds repeatedly.
        """
        cached = self._route_cache.get(kind, None)
        if kind in self._route_cache:
            return cached
        for pattern, loop_name in self._routes.items():
            if fnmatch.fnmatch(kind, pattern):
                self._route_cache[kind] = loop_name
                return loop_name
        self._route_cache[kind] = None
        return None

    def accepts(self, kind: str) -> bool:
        """Check if this vertex handles a kind.

        Returns True if the kind is registered as a route (fold engine),
        loop name, boundary kind, or matches a pattern route — or if any
        child accepts it. Used by parent vertices to determine whether
        to forward facts to this child.
        """
        cached = self._accepts_cache.get(kind)
        if cached is not None:
            return cached

        accepted = (
            kind in self._loops
            or kind in self._boundary_map
            or kind == self._vertex_boundary
            or (self._has_routes and self._resolve_route(kind) is not None)
            or (self._has_children and any(child.accepts(kind) for child in self._children))
        )
        self._accepts_cache[kind] = accepted
        return accepted

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
            initial=initial,
            fold=fold,
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
            self._has_loop_boundaries = True
            if loop.boundary_match:
                self._boundary_match[loop.boundary_kind] = loop.boundary_match
            if loop.boundary_conditions:
                self._boundary_conditions[loop.boundary_kind] = loop.boundary_conditions
        self._loops[kind] = loop
        self._accepts_cache.clear()

    def _routed_kind(self, kind: str) -> str:
        """Resolve incoming fact kind to the target loop name, if any."""
        if kind in self._loops or not self._has_routes:
            return kind
        resolved = self._resolve_route(kind)
        return resolved if resolved is not None else kind

    def _apply_parse_pipeline(self, routed_kind: str, payload: Any) -> Any:
        """Apply per-kind parse pipeline, returning None when the fact is dropped."""
        parse_pipeline = self._parse_pipelines.get(routed_kind)
        if parse_pipeline is None:
            return payload

        from atoms import run_parse

        parse_input = dict(payload) if hasattr(payload, "keys") else payload
        return run_parse(parse_input, parse_pipeline)

    def register_vertex_boundary(
        self,
        kind: str,
        match: tuple[tuple[str, str], ...] = (),
        conditions: tuple = (),
        run: str | None = None,
    ) -> None:
        """Register a vertex-level boundary.

        When a fact of this kind arrives (and matches payload conditions,
        and all fold-state conditions are met), ALL loop states are snapshot
        into a single Tick. This is the vertex's cycle boundary — e.g.
        session close snapshots everything.

        Vertex-level boundaries take precedence over loop-level boundaries
        for the same kind.

        Optional run clause: shell command carried on the Tick for app-layer
        execution when the boundary fires.
        """
        if kind in self._boundary_map:
            raise ValueError(
                f"Boundary kind '{kind}' already registered at loop level"
            )
        self._vertex_boundary = kind
        self._has_vertex_boundary = True
        self._vertex_boundary_match = match
        self._vertex_boundary_conditions = conditions
        self._vertex_boundary_run = run
        self._accepts_cache.clear()

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
        if kind[:6] in {"focus.", "scroll"} or kind.startswith("selection."):
            _, _, owner_name = kind.partition(".")
            if owner_name and owner_name != observer:
                return None

        # Store the full fact (not just kind/payload) for replay
        if self._store is not None:
            self._store.append(fact)

        # Convert fact timestamp for Loop routing
        fact_ts = datetime.fromtimestamp(fact.ts, tz=timezone.utc)

        # Track vertex-level period start (first fact after reset)
        # Suppressed during replay — replay sets period from last tick instead
        if (self._has_vertex_boundary
                and self._vertex_period_start is None
                and not self._replaying):
            self._vertex_period_start = fact_ts

        if self._has_routes:
            routed_kind = self._routed_kind(kind)
        else:
            routed_kind = kind

        if self._parse_pipelines:
            payload = self._apply_parse_pipeline(routed_kind, payload)
            if payload is None:
                # Parse rejected this fact — skip fold and routing,
                # consistent with source-level parse where None means
                # "drop the record." Fact is already stored for audit.
                return None

        # Route to Loop — Loop tracks its own period_start internally
        # Loop.receive() returns True if a count-based boundary should fire
        loop = self._loops.get(routed_kind)
        count_boundary_fire = False
        if loop is not None:
            count_boundary_fire = loop.receive(payload, ts=fact_ts)

        # Forward to children that accept this kind
        # Skip the child that produced this fact (prevents loopback)
        if self._has_children:
            for child in self._children:
                if child.name == _from_child:
                    continue
                if child.accepts(kind):
                    child_tick = child.receive(fact, grant)
                    if child_tick is not None:
                        # Child produced a tick — convert to fact and re-enter parent
                        child_fact = self._tick_to_fact(child_tick, child.name)
                        self.receive(child_fact, grant, _from_child=child.name)

        # Phase: boundary (live only — replay bypasses receive entirely)
        if self._replaying:
            return None

        return self._fire_live_boundaries(
            kind, routed_kind, payload, loop, count_boundary_fire, fact_ts,
        )

    def _fire_live_boundaries(
        self,
        kind: str,
        routed_kind: str,
        payload: Any,
        loop: Loop | None,
        count_boundary_fire: bool,
        fact_ts: datetime,
    ) -> Tick | None:
        """Fire boundaries after a live fact fold.

        Handles count-based, vertex-level, and loop-level boundary triggers.
        Only called on the live path — replay reconstructs fold state without
        firing boundaries.

        Extracted from receive() — the autoresearch proved empirically that
        boundary evaluation is a distinct phase from fold routing. Every
        optimization that skipped boundary work on the hot path improved
        performance, because the cost is in deciding whether to fire, not
        in folding.
        """
        # Count-based boundary trigger (Loop returned True during fold)
        if count_boundary_fire and loop is not None:
            tick = loop.fire(fact_ts, origin=self._name)
            self._store_tick(tick)
            return tick

        if not self._has_vertex_boundary and not self._has_loop_boundaries:
            return None

        # Vertex-level boundary (fires all loops)
        if self._has_vertex_boundary and self._vertex_boundary == kind:
            if not self._vertex_boundary_match or all(
                payload.get(k) == v for k, v in self._vertex_boundary_match
            ):
                if self._vertex_boundary_conditions:
                    cond_loop = self._loops.get(routed_kind)
                    if cond_loop is None or not _eval_conditions(
                        cond_loop.state, self._vertex_boundary_conditions
                    ):
                        return None
                tick = self._fire_vertex_boundary(fact_ts, payload)
                self._store_tick(tick)
                return tick

        # Loop-level kind-based boundary trigger
        fold_kind = self._boundary_map.get(kind)
        if fold_kind is None:
            return None

        match = self._boundary_match.get(kind, ())
        if match and not all(payload.get(k) == v for k, v in match):
            return None

        conditions = self._boundary_conditions.get(kind, ())
        if conditions:
            target_loop = self._loops[fold_kind]
            if not _eval_conditions(target_loop.state, conditions):
                return None

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
            run=self._vertex_boundary_run,
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

        store = self._store
        has_parse_pipelines = bool(self._parse_pipelines)
        use_raw = (
            not self._has_routes
            and not has_parse_pipelines
            and not self._has_children
            and hasattr(store, 'since_raw')
        )

        if use_raw:
            loops = self._loops
            # Pre-build mutating fold dispatch: kind → (fns, projection)
            # Uses Projection.fold_one_mut — fold logic stays in Projection.
            mut_dispatch: dict[str, tuple] = {}
            for kind, loop in loops.items():
                fold_fn = loop._projection._fold
                if fold_fn is not None and hasattr(fold_fn, '__self__'):
                    spec = fold_fn.__self__
                    if hasattr(spec, 'folds') and hasattr(spec, '_cached_fold_fns'):
                        mut_dispatch[kind] = (spec._cached_fold_fns, loop._projection)

            # Stream path: store provides data, vertex dispatches to projections
            if mut_dispatch and hasattr(store, 'replay_cursor'):
                self._store = None
                self._replaying = True
                get = mut_dispatch.get
                count = 0
                for kind, payload in store.replay_cursor(0):
                    entry = get(kind)
                    if entry is not None:
                        fns, proj = entry
                        proj.fold_one_mut(payload, fns)
                    count += 1
                if count == 0:
                    self._replaying = False
                    self._store = store
                    return 0
            else:
                raw_facts = store.since_raw(0)
                if not raw_facts:
                    return 0
                count = len(raw_facts)
                self._store = None
                self._replaying = True
                if mut_dispatch:
                    for kind, payload in raw_facts:
                        entry = mut_dispatch.get(kind)
                        if entry is not None:
                            fns, proj = entry
                            proj.fold_one_mut(payload, fns)
                else:
                    for kind, payload in raw_facts:
                        loop = loops.get(kind)
                        if loop is not None:
                            loop._projection.fold_one(payload)
        else:
            # Fallback: full Fact objects needed for routes/parse/children
            facts = store.since(0)
            if not facts:
                return 0
            count = len(facts)
            self._store = None
            self._replaying = True
            for fact in facts:
                routed_kind = self._routed_kind(fact.kind) if self._has_routes else fact.kind
                payload = fact.payload
                if has_parse_pipelines:
                    payload = self._apply_parse_pipeline(routed_kind, payload)
                    if payload is None:
                        continue
                loop = self._loops.get(routed_kind)
                if loop is not None:
                    loop.receive(payload, ts=datetime.fromtimestamp(fact.ts, tz=timezone.utc))
                if self._has_children:
                    for child in self._children:
                        if child.accepts(fact.kind):
                            child.receive(fact)
        self._replaying = False
        self._store = store  # restore

        # Reconcile count-based boundary state after replay.
        # During replay, loop.receive() may or may not have been called
        # (fast path bypasses it). Either way, the count needs to reflect
        # how many facts of the loop's kind were replayed, modulo the
        # boundary threshold. For "after" mode: if threshold was reached,
        # mark exhausted. For "every" mode: keep the residual count.
        for loop in self._loops.values():
            if loop.boundary_count is not None:
                replayed = loop._projection.cursor
                if loop.boundary_mode == "after":
                    if replayed >= loop.boundary_count:
                        loop._boundary_exhausted = True
                        loop._count_since_boundary = 0
                    else:
                        loop._count_since_boundary = replayed
                elif loop.boundary_mode == "every":
                    loop._count_since_boundary = replayed % loop.boundary_count
                else:
                    loop._count_since_boundary = replayed

        # Initialize period start from last vertex-level tick.
        # Vertex-level boundary ticks use self._name as tick name.
        # The last such tick's ts is the end of the previous period —
        # the next boundary's since should start from there.
        if self._has_vertex_boundary:
            if hasattr(store, 'last_tick_ts'):
                ts = store.last_tick_ts(self._name)
                if ts is not None:
                    self._vertex_period_start = ts
            elif hasattr(store, 'ticks_since'):
                for tick in reversed(store.ticks_since(0)):
                    if tick.name == self._name:
                        self._vertex_period_start = tick.ts
                        break

        return count

    def evaluate_boundaries(self) -> list[Tick]:
        """Evaluate boundaries for facts that arrived since the last boundary fire.

        Call after replay() to handle externally-emitted facts. During replay,
        boundary evaluation is suppressed — the fold state is rebuilt but
        boundaries don't fire. This method scans facts in the current period
        and checks them against boundary triggers with the fully-rebuilt fold
        state.

        Handles kind-based, payload-match, and predicate (fold-state condition)
        boundaries. Does NOT handle count-based boundaries (inherently
        event-driven — they count facts as they arrive via receive()).

        Returns list of Ticks produced by fired boundaries.
        """
        if self._store is None:
            return []

        ticks: list[Tick] = []

        # Determine scan window: facts since the most recent tick.
        # After a boundary fires (or on second evaluate), _vertex_period_start
        # may be None (reset). Use the latest stored tick's timestamp as the
        # authoritative scan start — avoids re-scanning already-evaluated facts.
        since_ts: float = 0.0
        if hasattr(self._store, 'ticks_since'):
            stored_ticks = self._store.ticks_since(0)
            if stored_ticks:
                since_ts = stored_ticks[-1].ts.timestamp()
        if self._vertex_period_start is not None:
            ps_ts = self._vertex_period_start.timestamp()
            if ps_ts > since_ts:
                since_ts = ps_ts

        import time as _time
        period_facts = self._store.between(since_ts, _time.time())
        if not period_facts:
            return ticks

        # Exclude facts at exactly the scan start — they were already
        # evaluated in a previous cycle (the tick that set since_ts was
        # produced from one of those facts).
        if since_ts > 0 and not self._has_vertex_boundary:
            period_facts = [f for f in period_facts if f.ts > since_ts]
            if not period_facts:
                return ticks

        if self._has_vertex_boundary and not self._boundary_map:
            return self._evaluate_vertex_only_boundaries(period_facts, since_ts)

        # Track which loop-level boundaries have fired this evaluation
        # (one fire per boundary per evaluation cycle)
        fired_boundaries: set[str] = set()

        for fact in period_facts:
            kind = fact.kind
            payload = fact.payload
            fact_ts = datetime.fromtimestamp(fact.ts, tz=timezone.utc)

            # Track vertex-level period start if not set
            if self._has_vertex_boundary and self._vertex_period_start is None:
                self._vertex_period_start = fact_ts

            # --- Vertex-level boundary ---
            if self._has_vertex_boundary and self._vertex_boundary == kind:
                if not self._vertex_boundary_match or all(
                    payload.get(k) == v for k, v in self._vertex_boundary_match
                ):
                    if self._vertex_boundary_conditions:
                        routed_kind = self._routed_kind(kind)
                        cond_loop = self._loops.get(routed_kind)
                        if cond_loop is None or not _eval_conditions(
                            cond_loop.state, self._vertex_boundary_conditions
                        ):
                            continue
                    tick = self._fire_vertex_boundary(fact_ts, payload)
                    self._store_tick(tick)
                    ticks.append(tick)
                    break  # Vertex-level fire ends the period
                continue

            # --- Loop-level boundary ---
            fold_kind = self._boundary_map.get(kind)
            if fold_kind is None or fold_kind in fired_boundaries:
                continue

            # Check payload match conditions
            match = self._boundary_match.get(kind, ())
            if match and not all(payload.get(k) == v for k, v in match):
                continue

            # Check fold-state conditions
            conditions = self._boundary_conditions.get(kind, ())
            if conditions:
                target_loop = self._loops[fold_kind]
                if not _eval_conditions(target_loop.state, conditions):
                    continue

            # Fire
            target_loop = self._loops[fold_kind]
            tick = target_loop.fire(fact_ts, origin=self._name,
                                    boundary_payload=payload)
            self._store_tick(tick)
            ticks.append(tick)
            fired_boundaries.add(fold_kind)

        return ticks

    def _evaluate_vertex_only_boundaries(
        self, period_facts: list, since_ts: float,
    ) -> list[Tick]:
        """Evaluate boundaries when only a vertex-level boundary exists.

        Fast path with no loop-level boundary scanning. Further specializes
        for the common case where the vertex boundary has no fold-state
        conditions — the majority of real vertices (project stores, identity
        stores, session lifecycle).
        """
        ticks: list[Tick] = []
        vertex_boundary = self._vertex_boundary
        vertex_boundary_match = self._vertex_boundary_match
        vertex_boundary_conditions = self._vertex_boundary_conditions

        if not vertex_boundary_conditions:
            # Add 1μs tolerance for float→datetime→float round-trip precision loss
            adjusted_since = since_ts + 1e-6 if since_ts > 0 else 0
            for fact in period_facts:
                if adjusted_since > 0 and fact.ts <= adjusted_since:
                    continue
                kind = fact.kind
                payload = fact.payload
                if kind != vertex_boundary:
                    continue
                fact_ts = datetime.fromtimestamp(fact.ts, tz=timezone.utc)
                if self._vertex_period_start is None:
                    self._vertex_period_start = fact_ts
                if vertex_boundary_match and not all(
                    payload.get(k) == v for k, v in vertex_boundary_match
                ):
                    continue
                tick = self._fire_vertex_boundary(fact_ts, payload)
                self._store_tick(tick)
                ticks.append(tick)
                return ticks
            return ticks

        loops = self._loops
        routed_kind = self._routed_kind
        adjusted_since_cond = since_ts + 1e-6 if since_ts > 0 else 0
        for fact in period_facts:
            if adjusted_since_cond > 0 and fact.ts <= adjusted_since_cond:
                continue
            kind = fact.kind
            payload = fact.payload
            if kind != vertex_boundary:
                continue
            fact_ts = datetime.fromtimestamp(fact.ts, tz=timezone.utc)
            if self._vertex_period_start is None:
                self._vertex_period_start = fact_ts
            if vertex_boundary_match and not all(
                payload.get(k) == v for k, v in vertex_boundary_match
            ):
                continue
            cond_loop = loops.get(routed_kind(kind))
            if cond_loop is None or not _eval_conditions(
                cond_loop.state, vertex_boundary_conditions
            ):
                continue
            tick = self._fire_vertex_boundary(fact_ts, payload)
            self._store_tick(tick)
            ticks.append(tick)
            return ticks
        return ticks

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
