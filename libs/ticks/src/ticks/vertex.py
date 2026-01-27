"""Vertex: where loops meet.

A Vertex manages fold engines, routes facts by kind to the right
consumer, holds an optional Store, and produces Ticks when a
temporal boundary fires.

Kind-based routing: register a fold for each kind. When a fact
arrives, the Vertex dispatches to the matching fold engine.
Projection is the internal fold engine detail — callers register
folds, not Projections.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .projection import Projection
from .store import Store
from .tick import Tick

class Vertex:
    """Where loops meet.

    Register folds by kind. Receive facts routed by kind. Fire a
    temporal boundary to produce a Tick snapshot of all fold states.

    Optionally backed by a Store — if provided, every received fact
    is appended to the store before routing.
    """

    def __init__(self, name: str = "", *, store: Store | None = None) -> None:
        self._name = name
        self._folds: dict[str, Projection] = {}
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
    ) -> None:
        """Register a fold engine for a fact kind.

        Creates an internal Projection with the given initial state and
        fold function. Facts received with this kind will be routed to
        this fold engine.

        Raises ValueError if the kind is already registered.
        """
        if kind in self._folds:
            raise ValueError(f"Kind already registered: {kind}")
        self._folds[kind] = Projection(initial, fold=fold)

    def receive(self, kind: str, payload: Any) -> None:
        """Route a fact payload to the fold engine registered for `kind`.

        If a Store is attached, the (kind, payload) tuple is appended
        before routing. Unregistered kinds are silently ignored — they
        pass through to the store but don't fold.
        """
        if self._store is not None:
            self._store.append((kind, payload))
        proj = self._folds.get(kind)
        if proj is not None:
            proj.fold_one(payload)

    def tick(self, name: str, ts: datetime) -> Tick[dict[str, Any]]:
        """Fire a temporal boundary.

        Snapshots all fold engine states into a dict keyed by kind,
        wraps in a Tick with the given name and timestamp.
        Origin is stamped from the vertex name.
        """
        state = {kind: proj.state for kind, proj in self._folds.items()}
        return Tick(name=name, ts=ts, payload=state, origin=self._name)

    @property
    def kinds(self) -> list[str]:
        """Registered kinds, in registration order."""
        return list(self._folds.keys())

    def state(self, kind: str) -> Any:
        """Current fold state for a registered kind.

        Raises KeyError if kind is not registered.
        """
        return self._folds[kind].state

    def version(self, kind: str) -> int:
        """Current fold version for a registered kind.

        Raises KeyError if kind is not registered.
        """
        return self._folds[kind].version
