"""SequentialSource: run sources in order with exit-on-failure gating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

from atoms.fact import Fact

if TYPE_CHECKING:
    from atoms.source import Source


@dataclass(frozen=True)
class SequentialSource:
    """Runs sources sequentially with exit-on-failure gating.

    Each source runs as a subprocess. Facts are yielded as they arrive.
    If a source raises SourceError, remaining sources are skipped and
    the error propagates to the caller (executor).

    Implements the same collect protocol as Source, so the Executor treats it
    as a single source — no executor changes needed.
    """

    sources: tuple[Source, ...]
    _observer: str

    @property
    def observer(self) -> str:
        return self._observer

    @property
    def kind(self) -> str:
        """Primary kind — first inner source's kind.

        SequentialSource wraps multiple sources, but the executor needs
        a single kind for dependency graphs and status reporting.
        The first source's kind represents the block.
        """
        return self.sources[0].kind if self.sources else ""

    @property
    def command(self) -> str:
        """Primary command — first inner source's command."""
        return self.sources[0].command if self.sources else ""

    async def collect(self) -> AsyncIterator[Fact]:
        """Collect facts from each source in order. Stop on failure.

        SourceError propagates naturally — if a source fails, remaining
        sources are skipped and the executor records the failure.
        """
        for source in self.sources:
            async for fact in source.collect():
                yield fact
