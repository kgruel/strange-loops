"""Lens: observation parameters for rendering.

A Lens controls *how* data is presented — zoom level and scope filtering.
Distinct from Peer (who observes) and Horizon (what can be seen).

Lens is a rendering concern, not an access control concern.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Lens:
    """Observation parameters: zoom level and scope filter.

    Attributes:
        zoom: Detail level. 0=minimal, 1=summary (default), 2=detail, 3+=verbose
        scope: Kind filter. None=all kinds, frozenset=only these kinds
    """

    zoom: int = 1
    scope: frozenset[str] | None = None

    @classmethod
    def minimal(cls) -> Lens:
        """Zoom 0: minimal detail."""
        return cls(zoom=0)

    @classmethod
    def summary(cls) -> Lens:
        """Zoom 1: summary (default)."""
        return cls(zoom=1)

    @classmethod
    def detail(cls) -> Lens:
        """Zoom 2: detailed view."""
        return cls(zoom=2)

    @classmethod
    def verbose(cls) -> Lens:
        """Zoom 3+: maximum detail."""
        return cls(zoom=3)

    def with_zoom(self, zoom: int) -> Lens:
        """Return a new Lens with the given zoom level."""
        return Lens(zoom=zoom, scope=self.scope)

    def with_scope(self, *kinds: str) -> Lens:
        """Return a new Lens scoped to the given kinds."""
        return Lens(zoom=self.zoom, scope=frozenset(kinds) if kinds else None)

    def includes(self, kind: str) -> bool:
        """Check if this lens includes the given kind."""
        return self.scope is None or kind in self.scope
