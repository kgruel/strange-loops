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
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .projection import Projection
from .store import Store
from .tick import Tick


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
    """

    def __init__(self, name: str = "", *, store: Store | None = None) -> None:
        self._name = name
        self._engines: dict[str, _FoldEngine] = {}
        self._boundary_map: dict[str, str] = {}  # boundary_kind → fold_kind
        self._store = store

    @property
    def name(self) -> str:
        """Vertex name — stamped as origin on produced Ticks."""
        return self._name

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

    def receive(self, kind: str, payload: Any) -> Tick | None:
        """Route a fact payload to the fold engine registered for `kind`.

        If a Store is attached, the (kind, payload) tuple is appended
        before routing. Unregistered kinds are silently ignored — they
        pass through to the store but don't fold.

        After folding, checks if the incoming kind triggers a boundary.
        If so, snapshots the triggered engine's state into a Tick and
        optionally resets the engine. Returns the Tick, or None.
        """
        if self._store is not None:
            self._store.append((kind, payload))
        proj = self._engines.get(kind)
        if proj is not None:
            proj.projection.fold_one(payload)

        # Check boundary trigger
        fold_kind = self._boundary_map.get(kind)
        if fold_kind is None:
            return None
        engine = self._engines[fold_kind]
        tick = Tick(
            name=fold_kind,
            ts=datetime.now(timezone.utc),
            payload=engine.projection.state,
            origin=self._name,
        )
        if engine.reset:
            engine.projection.reset(copy.deepcopy(engine.initial))
        return tick

    def tick(self, name: str, ts: datetime) -> Tick[dict[str, Any]]:
        """Fire a temporal boundary.

        Snapshots all fold engine states into a dict keyed by kind,
        wraps in a Tick with the given name and timestamp.
        Origin is stamped from the vertex name.
        """
        state = {kind: eng.projection.state for kind, eng in self._engines.items()}
        return Tick(name=name, ts=ts, payload=state, origin=self._name)

    @property
    def kinds(self) -> list[str]:
        """Registered kinds, in registration order."""
        return list(self._engines.keys())

    def state(self, kind: str) -> Any:
        """Current fold state for a registered kind.

        Raises KeyError if kind is not registered.
        """
        return self._engines[kind].projection.state

    def version(self, kind: str) -> int:
        """Current fold version for a registered kind.

        Raises KeyError if kind is not registered.
        """
        return self._engines[kind].projection.version
