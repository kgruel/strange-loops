"""Source protocol: adapters from the external world into Vertex."""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Protocol

if TYPE_CHECKING:
    from atoms.fact import Fact


class SourceProtocol(Protocol):
    """Protocol for sources that produce facts from the external world.

    Sources are infrastructure at the ingress boundary — adapters that
    convert external signals (commands, files, network events) into Facts.
    Not atoms — they don't appear in the fundamental model.

    A Source has an observer identity and yields facts as they arrive.
    The stream runs until cancelled or the source is exhausted.
    """

    @property
    def observer(self) -> str:
        """Identity for facts produced by this source."""
        ...

    async def stream(self) -> AsyncIterator[Fact]:
        """Yield facts as they arrive. Runs until cancelled or exhausted."""
        ...
