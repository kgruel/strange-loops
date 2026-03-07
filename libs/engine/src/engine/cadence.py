"""Cadence: store predicate for source scheduling.

Separates *when* to run a source from *what* it does. Three shapes:
- elapsed(kind, interval) — time since last {kind}.complete
- triggered(trigger_kinds, source_kind) — event since last complete
- always() — run every time (one-shot / cursor-based sources)

Cadence is pure: give it a store and a timestamp, get a boolean.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class Cadence:
    """Store predicate: should this source run now?"""

    _kind: str
    _mode: str  # "elapsed", "triggered", "always"
    _interval: float | None = None
    _trigger_kinds: tuple[str, ...] = ()

    @classmethod
    def elapsed(cls, kind: str, interval: float) -> Cadence:
        """True if interval seconds passed since last {kind}.complete fact."""
        return cls(_kind=kind, _mode="elapsed", _interval=interval)

    @classmethod
    def triggered(cls, trigger_kinds: str | tuple[str, ...], source_kind: str) -> Cadence:
        """True if any trigger_kind fact exists since last {source_kind}.complete.

        OR semantics: any matching trigger kind satisfies the predicate.
        """
        if isinstance(trigger_kinds, str):
            trigger_kinds = (trigger_kinds,)
        return cls(_kind=source_kind, _mode="triggered", _trigger_kinds=trigger_kinds)

    @classmethod
    def always(cls) -> Cadence:
        """Always true. For run-once / cursor-based sources."""
        return cls(_kind="", _mode="always")

    def should_run(self, store: object, now: float | None = None) -> bool:
        """Evaluate this predicate against the store.

        Args:
            store: Store with latest_by_kind() and has_kind_since() methods.
            now: Epoch seconds. Defaults to time.time().
        """
        if self._mode == "always":
            return True

        if now is None:
            now = time.time()

        if self._mode == "elapsed":
            complete_kind = f"{self._kind}.complete"
            last = store.latest_by_kind_where(complete_kind, "status", "ok")
            if last is None:
                return True
            return (now - last.ts) >= self._interval

        if self._mode == "triggered":
            complete_kind = f"{self._kind}.complete"
            last_complete = store.latest_by_kind_where(complete_kind, "status", "ok")
            if last_complete is None:
                # Never completed — run if any trigger exists
                for kind in self._trigger_kinds:
                    if store.latest_by_kind(kind) is not None:
                        return True
                return False
            # Check if any trigger kind arrived after last complete
            for kind in self._trigger_kinds:
                if store.has_kind_since(kind, last_complete.ts):
                    return True
            return False

        return False

    def __str__(self) -> str:
        if self._mode == "always":
            return "always"
        if self._mode == "elapsed":
            return f"elapsed({self._kind}, {self._interval}s)"
        if self._mode == "triggered":
            kinds = ", ".join(self._trigger_kinds)
            return f"triggered({kinds} -> {self._kind})"
        return self._mode
