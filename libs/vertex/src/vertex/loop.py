"""Loop: explicit fold cycle with boundary semantics.

A Loop wraps a Projection and adds boundary-driven tick emission.
It represents a single named fold cycle — facts go in, state accumulates,
and when a boundary fires, a Tick snapshot is produced.

This makes the loop primitive explicit rather than hiding it inside
Vertex's _FoldEngine. Vertex becomes the routing layer; Loop owns
the fold-and-fire semantics.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .projection import Projection
from .tick import Tick


@dataclass
class Loop:
    """A named fold cycle with boundary semantics.

    Wraps a Projection and adds:
      - name: identity for the Tick this loop produces
      - boundary_kind: the fact kind that triggers a fire()
      - reset: whether to reset projection state after fire()

    The Loop doesn't route — it just folds and fires. Vertex handles
    routing facts to the right Loop.

    Fidelity traversal:
      Tracks _period_start — when the first fact was received after the
      last boundary. The produced Tick includes this as `since`, enabling
      Store.between(tick.since, tick.ts) to retrieve contributing facts.
    """

    name: str
    projection: Projection
    boundary_kind: str | None = None
    reset: bool = True
    _initial: Any = field(default=None, repr=False)
    _period_start: datetime | None = field(default=None, repr=False)

    def __post_init__(self):
        # Capture initial state for reset
        if self._initial is None:
            self._initial = copy.deepcopy(self.projection.state)

    def receive(self, payload: dict, ts: datetime | None = None) -> None:
        """Fold a payload into the projection.

        Tracks period start for fidelity traversal — the first receive()
        after construction or reset records when the period began.

        Args:
            payload: The fact payload to fold
            ts: Optional timestamp (defaults to now if not provided)
        """
        if self._period_start is None:
            self._period_start = ts if ts is not None else datetime.now(timezone.utc)
        self.projection.fold_one(payload)

    def fire(self, ts: datetime, origin: str = "") -> Tick:
        """Snapshot current state into a Tick.

        If reset=True, the projection resets to its initial state after
        producing the Tick. Also clears period_start so the next receive()
        starts a new period.

        The Tick includes `since` for fidelity traversal — use
        Store.between(tick.since, tick.ts) to retrieve contributing facts.
        """
        tick = Tick(
            name=self.name,
            ts=ts,
            payload=self.projection.state,
            origin=origin,
            since=self._period_start,
        )
        if self.reset:
            self.projection.reset(copy.deepcopy(self._initial))
            self._period_start = None
        return tick

    @property
    def state(self) -> Any:
        """Current fold state."""
        return self.projection.state

    @property
    def version(self) -> int:
        """Current fold version."""
        return self.projection.version
