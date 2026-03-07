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
    If a source exits non-zero (detected via {kind}.complete with status="error"),
    remaining sources are skipped.

    Implements the same collect protocol as Source, so the Executor treats it
    as a single source — no executor changes needed.
    """

    sources: tuple[Source, ...]
    _observer: str

    @property
    def observer(self) -> str:
        return self._observer

    async def collect(self) -> AsyncIterator[Fact]:
        """Collect facts from each source in order. Stop on failure."""
        for source in self.sources:
            failed = False
            async for fact in source.collect():
                yield fact
                if fact.kind == f"{source.kind}.complete" and fact.payload.get("status") == "error":
                    failed = True
            if failed:
                yield Fact.of(
                    "sources.sequential.stopped",
                    self._observer,
                    failed_command=source.command,
                    failed_kind=source.kind,
                    status="failed",
                )
                break
