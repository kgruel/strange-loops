"""Lightweight instrumentation for framework internals.

Zero-cost when disabled. Records counters, timings, and gauges that can be
consumed by bench scripts (offline) or the debug pane (live).

Usage:
    from framework.instrument import metrics

    # Enable collection (disabled by default = zero cost)
    metrics.enable()

    # Record metrics
    metrics.count("effect_fires")
    with metrics.time("render"):
        do_render()
    metrics.gauge("store_size", len(events))

    # Read results
    snap = metrics.snapshot()
    metrics.reset()
"""

from __future__ import annotations

import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field


# How many timing samples to retain per metric
_MAX_SAMPLES = 200


@dataclass
class TimingSamples:
    """Ring buffer of timing samples with summary stats."""
    samples: deque = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))
    total_count: int = 0
    total_sum: float = 0.0

    def add(self, duration_ms: float) -> None:
        self.samples.append(duration_ms)
        self.total_count += 1
        self.total_sum += duration_ms

    @property
    def last(self) -> float:
        return self.samples[-1] if self.samples else 0.0

    @property
    def avg(self) -> float:
        return self.total_sum / self.total_count if self.total_count else 0.0

    @property
    def max(self) -> float:
        return max(self.samples) if self.samples else 0.0

    @property
    def min(self) -> float:
        return min(self.samples) if self.samples else 0.0

    def percentile(self, p: float) -> float:
        """Approximate percentile from retained samples."""
        if not self.samples:
            return 0.0
        sorted_s = sorted(self.samples)
        idx = int(len(sorted_s) * p / 100)
        return sorted_s[min(idx, len(sorted_s) - 1)]


class Metrics:
    """Global metrics collector. Zero-cost when disabled."""

    def __init__(self):
        self._enabled = False
        self._counters: dict[str, int] = {}
        self._timings: dict[str, TimingSamples] = {}
        self._gauges: dict[str, float] = {}
        self._start_time: float = 0.0

    def enable(self) -> None:
        self._enabled = True
        self._start_time = time.time()

    def disable(self) -> None:
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def count(self, name: str, n: int = 1) -> None:
        """Increment a counter."""
        if not self._enabled:
            return
        self._counters[name] = self._counters.get(name, 0) + n

    @contextmanager
    def time(self, name: str):
        """Context manager for timing a block (records in milliseconds)."""
        if not self._enabled:
            yield
            return
        t0 = time.perf_counter()
        yield
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if name not in self._timings:
            self._timings[name] = TimingSamples()
        self._timings[name].add(elapsed_ms)

    def gauge(self, name: str, value: float) -> None:
        """Set a point-in-time gauge value."""
        if not self._enabled:
            return
        self._gauges[name] = value

    def snapshot(self) -> dict:
        """Return current state of all metrics."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        return {
            "elapsed_sec": elapsed,
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "timings": {
                name: {
                    "count": t.total_count,
                    "last_ms": round(t.last, 3),
                    "avg_ms": round(t.avg, 3),
                    "min_ms": round(t.min, 3),
                    "max_ms": round(t.max, 3),
                    "p50_ms": round(t.percentile(50), 3),
                    "p95_ms": round(t.percentile(95), 3),
                    "p99_ms": round(t.percentile(99), 3),
                }
                for name, t in self._timings.items()
            },
        }

    def reset(self) -> None:
        """Clear all metrics."""
        self._counters.clear()
        self._timings.clear()
        self._gauges.clear()
        self._start_time = time.time()

    def report(self) -> str:
        """Human-readable summary."""
        snap = self.snapshot()
        lines = []
        lines.append(f"Elapsed: {snap['elapsed_sec']:.1f}s")

        if snap["counters"]:
            lines.append("\nCounters:")
            for name, val in sorted(snap["counters"].items()):
                rate = val / snap["elapsed_sec"] if snap["elapsed_sec"] > 0 else 0
                lines.append(f"  {name:<24} {val:>10,}  ({rate:>8.1f}/s)")

        if snap["timings"]:
            lines.append("\nTimings:")
            for name, t in sorted(snap["timings"].items()):
                lines.append(f"  {name:<24} n={t['count']:>6}  "
                           f"avg={t['avg_ms']:>7.2f}ms  "
                           f"p95={t['p95_ms']:>7.2f}ms  "
                           f"max={t['max_ms']:>7.2f}ms")

        if snap["gauges"]:
            lines.append("\nGauges:")
            for name, val in sorted(snap["gauges"].items()):
                lines.append(f"  {name:<24} {val:>10.1f}")

        return "\n".join(lines)


# Global instance — import and use directly
metrics = Metrics()
