#!/usr/bin/env python3
"""Integration profiling: run the framework under load with instrumentation.

Unlike micro-benchmarks (computed_scaling, system_profile), this exercises
the full reactive pipeline: events → Signal → Effect → Computed → render.

Reports what the framework's own instrumentation captures, showing how
the system behaves end-to-end at various throughput levels.

Usage: uv run bench/integration.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reaktiv",
#     "typing_extensions",
#     "rich",
# ]
# ///

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from reaktiv import Signal, Computed, Effect

sys.path.insert(0, str(Path(__file__).parent.parent))
from framework import EventStore, metrics


# =============================================================================
# MINIMAL APP SIMULATION (no TUI, just the reactive pipeline)
# =============================================================================

@dataclass(frozen=True)
class Event:
    pid: str
    kind: Literal["created", "state_change", "log"]
    ts: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)


class MinimalReactiveApp:
    """Stripped-down reactive app: store + computeds + effect, no Rich."""

    def __init__(self, num_processes: int = 20):
        self.store: EventStore[Event] = EventStore()
        self.num_processes = num_processes
        self.render_count = 0

        # Computeds (same patterns as process_manager)
        self.process_list = Computed(lambda: self._compute_list())
        self.process_logs = Computed(lambda: self._compute_logs())
        self.process_states = Computed(lambda: self._compute_states())

        # Render effect
        self._render_dirty = False
        self._effect = Effect(lambda: self._on_signal_change())

    def _on_signal_change(self):
        # Only read Signals — Computeds evaluate lazily in render
        self.store.version()
        self._render_dirty = True
        metrics.count("effect_fires")

    def _compute_list(self):
        self.store.version()
        with metrics.time("computed_list"):
            processes = {}
            for event in self.store.events:
                if event.kind == "created":
                    processes[event.pid] = {"state": "stopped", "starts": 0}
                elif event.kind == "state_change" and event.pid in processes:
                    processes[event.pid]["state"] = event.payload.get("to", "unknown")
            return processes

    def _compute_logs(self):
        self.store.version()
        with metrics.time("computed_logs"):
            logs: dict[str, list] = {}
            for event in self.store.events:
                if event.kind == "log":
                    if event.pid not in logs:
                        logs[event.pid] = []
                    logs[event.pid].append(event)
                    if len(logs[event.pid]) > 50:
                        logs[event.pid] = logs[event.pid][-50:]
            return logs

    def _compute_states(self):
        with metrics.time("computed_states"):
            return {pid: info["state"] for pid, info in self.process_list().items()}

    def do_render(self):
        """Simulate debounced render (called from main loop, not per-event)."""
        if self._render_dirty:
            self._render_dirty = False
            with metrics.time("render"):
                # Simulate reading computed values (forces evaluation)
                _ = self.process_list()
                _ = self.process_logs()
                _ = self.process_states()
            self.render_count += 1
            metrics.count("frames_rendered")


async def run_load_test(events_per_sec: int, duration_sec: float, num_processes: int = 20):
    """Generate events at a target rate, render at 20fps, report metrics."""
    app = MinimalReactiveApp(num_processes)

    # Seed processes
    for i in range(num_processes):
        app.store.add(Event(pid=f"proc-{i}", kind="created", ts=time.time(),
                           payload={"name": f"worker-{i}"}))
        app.store.add(Event(pid=f"proc-{i}", kind="state_change", ts=time.time(),
                           payload={"from": "stopped", "to": "running"}))

    metrics.reset()
    metrics.enable()

    start = time.time()
    events_generated = 0
    target_interval = 1.0 / events_per_sec if events_per_sec > 0 else 0.001
    render_interval = 0.05  # 20fps
    last_render = start

    while (time.time() - start) < duration_sec:
        # Generate a batch of events
        batch_size = max(1, int(events_per_sec * 0.01))  # ~10ms worth
        for _ in range(batch_size):
            pid = f"proc-{events_generated % num_processes}"
            app.store.add(Event(pid=pid, kind="log", ts=time.time(),
                               payload={"message": "tick", "level": "info"}))
            events_generated += 1

        # Render at frame rate
        now = time.time()
        if now - last_render >= render_interval:
            app.do_render()
            last_render = now

        # Yield to event loop
        await asyncio.sleep(0.001)

    # Final render
    app.do_render()
    metrics.disable()

    actual_rate = events_generated / (time.time() - start)
    return {
        "target_rate": events_per_sec,
        "actual_rate": actual_rate,
        "total_events": events_generated,
        "frames_rendered": app.render_count,
        "metrics": metrics.snapshot(),
    }


async def main():
    print("Integration Profile: Full Reactive Pipeline")
    print("=" * 70)
    print()

    scenarios = [
        ("Low load",     100, 3.0, 10),
        ("Medium load", 1000, 3.0, 20),
        ("High load",   5000, 3.0, 50),
        ("Stress",     10000, 3.0, 100),
        ("Extreme",    50000, 2.0, 200),
    ]

    for label, rate, duration, num_procs in scenarios:
        print(f"--- {label}: target={rate} events/sec, {num_procs} processes, {duration}s ---")
        result = await run_load_test(rate, duration, num_procs)

        m = result["metrics"]
        print(f"  Actual rate:     {result['actual_rate']:>8.0f} events/sec")
        print(f"  Total events:    {result['total_events']:>8,}")
        print(f"  Frames rendered: {result['frames_rendered']:>8}")
        print(f"  Effect fires:    {m['counters'].get('effect_fires', 0):>8,}")

        # Show timing breakdown
        if m["timings"]:
            print(f"  Timings:")
            for name in ["render", "computed_list", "computed_logs", "computed_states"]:
                if name in m["timings"]:
                    t = m["timings"][name]
                    print(f"    {name:<18} avg={t['avg_ms']:>7.2f}ms  "
                          f"p95={t['p95_ms']:>7.2f}ms  max={t['max_ms']:>7.2f}ms")

        # Compute waste ratio
        effects = m["counters"].get("effect_fires", 0)
        frames = result["frames_rendered"]
        if frames > 0:
            waste = effects / frames
            print(f"  Effect/frame ratio: {waste:.1f}x (1.0 = optimal)")

        print()

    print("Key insights:")
    print("  - Effect/frame ratio shows how many Effect fires per actual render")
    print("  - With debounce, this should be >1 (many signals, few renders)")
    print("  - Computed times show per-frame cost at each event count")
    print("  - If p95 render > 50ms, the system is struggling to maintain 20fps")


if __name__ == "__main__":
    asyncio.run(main())
