"""FrameTimer: per-phase timing for render loop profiling."""

from __future__ import annotations

import json
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FrameRecord:
    """Timing for a single frame, keyed by phase name."""
    phases: dict[str, float] = field(default_factory=dict)
    meta: dict[str, object] = field(default_factory=dict)
    total: float = 0.0
    timestamp: float = 0.0


class FrameTimer:
    """Accumulates per-phase timings across frames.

    Usage:
        timer = FrameTimer(profile=True)

        # In the render loop:
        timer.begin_frame()
        with timer.phase("filter"):
            ...
        timer.set_meta("items", 1320)
        timer.end_frame()

        # On exit:
        timer.dump_jsonl(Path("profile.jsonl"))
    """

    def __init__(self, *, history: int = 60, profile: bool = False):
        self._history: deque[FrameRecord] = deque(maxlen=history)
        self._current: FrameRecord | None = None
        self._frame_start: float = 0.0
        self._profile = profile
        self._log: list[FrameRecord] = [] if profile else []

    def begin_frame(self) -> None:
        self._current = FrameRecord(timestamp=time.time())
        self._frame_start = time.perf_counter()

    def end_frame(self) -> None:
        if self._current is not None:
            self._current.total = (time.perf_counter() - self._frame_start) * 1000
            self._history.append(self._current)
            if self._profile:
                self._log.append(self._current)
            self._current = None

    @contextmanager
    def phase(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if self._current is not None:
                self._current.phases[name] = elapsed_ms

    def set_meta(self, key: str, value: object) -> None:
        """Attach metadata to the current frame."""
        if self._current is not None:
            self._current.meta[key] = value

    def last(self) -> FrameRecord | None:
        return self._history[-1] if self._history else None

    def avg(self, phase: str) -> float:
        """Average ms for a phase over recent history."""
        vals = [f.phases.get(phase, 0.0) for f in self._history]
        return sum(vals) / len(vals) if vals else 0.0

    def max(self, phase: str) -> float:
        """Max ms for a phase over recent history."""
        vals = [f.phases.get(phase, 0.0) for f in self._history]
        return max(vals) if vals else 0.0

    def avg_total(self) -> float:
        return sum(f.total for f in self._history) / len(self._history) if self._history else 0.0

    def phase_names(self) -> list[str]:
        """All phase names seen, in insertion order from most recent frame."""
        last = self.last()
        return list(last.phases.keys()) if last else []

    def dump_jsonl(self, path: Path) -> int:
        """Write all logged frames to a JSONL file. Returns frame count."""
        with open(path, "w") as f:
            for record in self._log:
                obj = {
                    "t": round(record.timestamp, 3),
                    "total_ms": round(record.total, 2),
                    "phases": {k: round(v, 2) for k, v in record.phases.items()},
                }
                if record.meta:
                    obj["meta"] = record.meta
                f.write(json.dumps(obj) + "\n")
        return len(self._log)
