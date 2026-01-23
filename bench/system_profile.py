#!/usr/bin/env python3
"""System profiling: Signal/Effect fan-out, Rich rendering, memory pressure.

Measures:
1. reaktiv fan-out: how many Computed re-evaluations per event?
2. Rich rendering: table construction + terminal string generation at various row counts
3. Memory: RSS growth as events accumulate
4. Persistence I/O: JSONL append throughput

Usage: uv run bench/system_profile.py
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
import json
import os
import resource
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from reaktiv import Signal, Computed, Effect
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text


# =============================================================================
# SHARED EVENT TYPE
# =============================================================================

@dataclass(frozen=True)
class Event:
    pid: str
    kind: Literal["created", "state_change", "log"]
    ts: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)


def make_event(i: int, num_processes: int = 20) -> Event:
    pid = f"proc-{i % num_processes}"
    return Event(pid=pid, kind="log", ts=time.time(),
                 payload={"message": f"msg-{i}", "level": "info"})


# =============================================================================
# BENCH 1: Signal/Effect Fan-out
# =============================================================================

def bench_fanout(*, n_events: int = 100, print_output: bool = True) -> dict[str, Any]:
    """Measure how reaktiv handles Computed re-evaluation on Signal changes."""
    if print_output:
        print("\n1. Signal/Effect Fan-out")
        print("-" * 60)

    events: list[Event] = []
    version = Signal(0)
    eval_counts = {"list": 0, "logs": 0, "states": 0, "filtered": 0, "selected": 0}

    def compute_list():
        version()  # dependency
        eval_counts["list"] += 1
        # Simulate work
        return [e for e in events if e.kind == "created"]

    def compute_logs():
        version()
        eval_counts["logs"] += 1
        return [e for e in events if e.kind == "log"][-50:]

    def compute_states():
        _ = c_list()  # depends on process_list
        eval_counts["states"] += 1
        return {}

    def compute_filtered():
        _ = c_list()
        eval_counts["filtered"] += 1
        return []

    def compute_selected():
        _ = c_filtered()
        eval_counts["selected"] += 1
        return None

    c_list = Computed(compute_list)
    c_logs = Computed(compute_logs)
    c_states = Computed(compute_states)
    c_filtered = Computed(compute_filtered)
    c_selected = Computed(compute_selected)

    render_count = 0

    def render_effect():
        nonlocal render_count
        # Read all computeds (like the real render does)
        version()
        c_list()
        c_logs()
        c_states()
        c_filtered()
        c_selected()
        render_count += 1

    effect = Effect(render_effect)

    # Now bump version N times and see how many evaluations happen
    for i in range(n_events):
        events.append(make_event(i))
        version.set(i + 1)

    result = {
        "events_added": n_events,
        "effect_renders": render_count,
        "computed_evals": dict(eval_counts),
    }

    if print_output:
        print(f"  Events added:      {n_events}")
        print(f"  Effect renders:    {render_count}")
        print(f"  Computed evals:")
        for name, count in eval_counts.items():
            print(f"    {name:>12}: {count:>6} ({count/n_events:.1f}x per event)")

    # Cleanup
    del effect
    return result


# =============================================================================
# BENCH 2: Rich Rendering Cost
# =============================================================================

def bench_rich_rendering(
    *,
    row_counts: list[int] | None = None,
    iterations: int = 20,
    print_output: bool = True,
) -> dict[str, Any]:
    """Measure Rich table/layout construction and string generation."""
    if print_output:
        print("\n2. Rich Rendering Cost")
        print("-" * 60)

    console = Console(file=open(os.devnull, "w"), width=120, height=40)
    rows = row_counts or [10, 50, 100, 500, 1000]

    results: dict[str, Any] = {"rows": {}}

    for n_rows in rows:
        # Build a table similar to process list
        times_build = []
        times_render = []

        for _ in range(iterations):
            t0 = time.perf_counter()
            table = Table(show_header=True)
            table.add_column("PID", width=10)
            table.add_column("Name", width=15)
            table.add_column("State", width=10)
            table.add_column("Uptime", width=10)
            table.add_column("Restarts", width=8)

            for i in range(n_rows):
                table.add_row(
                    f"proc-{i}", f"worker-{i}", "running",
                    "00:05:32", str(i % 5),
                )

            layout = Layout()
            layout.split_column(
                Layout(name="main", ratio=1),
                Layout(Text("status"), name="status", size=1),
            )
            layout.split_row(
                Layout(Panel(table, title="Processes"), ratio=1),
                Layout(Panel(Text("logs here\n" * min(n_rows, 20)), title="Logs"), ratio=1),
            )
            t_build = time.perf_counter() - t0
            times_build.append(t_build * 1000)

            # Render to string (simulates what Live does)
            t0 = time.perf_counter()
            with console.capture() as capture:
                console.print(layout)
            t_render = time.perf_counter() - t0
            times_render.append(t_render * 1000)

        build_med = sorted(times_build)[len(times_build) // 2]
        render_med = sorted(times_render)[len(times_render) // 2]
        total_med = build_med + render_med
        results["rows"][str(n_rows)] = {
            "build_median_ms": round(build_med, 3),
            "render_median_ms": round(render_med, 3),
            "total_median_ms": round(total_med, 3),
        }
        if print_output:
            print(
                f"  {n_rows:>5} rows: build={build_med:>6.2f}ms  "
                f"render={render_med:>6.2f}ms  total={total_med:>6.2f}ms"
            )

    console.file.close()
    return results


# =============================================================================
# BENCH 3: Memory Pressure
# =============================================================================

def bench_memory(*, print_output: bool = True) -> dict[str, Any]:
    """Measure memory growth as events accumulate.

    Notes:
    - tracemalloc reports Python allocation size (current + peak).
    - ru_maxrss is *peak* resident set size (platform-dependent units) and may not decrease after GC.
    """
    if print_output:
        print("\n3. Memory Pressure")
        print("-" * 60)

    import gc
    import tracemalloc

    def ru_maxrss_mb() -> float:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_bytes = rss if sys.platform == "darwin" else rss * 1024  # Linux reports KB
        return rss_bytes / 1048576

    mb = 1024 * 1024

    tracemalloc.start()
    base_cur, base_peak = tracemalloc.get_traced_memory()
    base_rss = ru_maxrss_mb()
    if print_output:
        print(
            f"  Baseline: tracemalloc={base_cur/mb:>6.1f} MB (peak {base_peak/mb:>6.1f} MB)  "
            f"ru_maxrss={base_rss:>6.1f} MB (peak)"
        )

    events: list[Event] = []
    last_cur = base_cur
    points: list[dict[str, Any]] = []
    for n in [10_000, 50_000, 100_000, 500_000, 1_000_000]:
        while len(events) < n:
            events.append(make_event(len(events)))
        cur, peak = tracemalloc.get_traced_memory()
        last_cur = cur
        rss_peak = ru_maxrss_mb()
        py_kb_per_event = (cur - base_cur) / n / 1024
        point = {
            "events": n,
            "tracemalloc_current_mb": round(cur / mb, 3),
            "tracemalloc_peak_mb": round(peak / mb, 3),
            "ru_maxrss_mb": round(rss_peak, 3),
            "python_kb_per_event": round(py_kb_per_event, 6),
        }
        points.append(point)
        if print_output:
            print(
                f"  {n:>10,} events: tracemalloc={cur/mb:>6.1f} MB (peak {peak/mb:>6.1f} MB)  "
                f"ru_maxrss={rss_peak:>6.1f} MB (peak)  ~{py_kb_per_event:.2f} KB/event (py)"
            )

    # Force GC and measure again
    del events
    gc.collect()
    cur2, peak2 = tracemalloc.get_traced_memory()
    rss2 = ru_maxrss_mb()
    freed_mb = (last_cur - cur2) / mb
    if print_output:
        print(
            f"  After del+gc: tracemalloc={cur2/mb:>6.1f} MB (peak {peak2/mb:>6.1f} MB)  "
            f"ru_maxrss={rss2:>6.1f} MB (peak)  freed~{freed_mb:.1f} MB (py)"
        )
    after_gc = {
        "tracemalloc_current_mb": round(cur2 / mb, 3),
        "tracemalloc_peak_mb": round(peak2 / mb, 3),
        "ru_maxrss_mb": round(rss2, 3),
        "python_freed_mb": round(freed_mb, 3),
    }
    tracemalloc.stop()
    return {
        "baseline": {
            "tracemalloc_current_mb": round(base_cur / mb, 3),
            "tracemalloc_peak_mb": round(base_peak / mb, 3),
            "ru_maxrss_mb": round(base_rss, 3),
        },
        "points": points,
        "after_gc": after_gc,
    }


# =============================================================================
# BENCH 4: Persistence I/O (JSONL append)
# =============================================================================

def bench_persistence_io(*, print_output: bool = True) -> dict[str, Any]:
    """Measure JSONL append throughput."""
    if print_output:
        print("\n4. Persistence I/O (JSONL append)")
        print("-" * 60)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        tmp_path = Path(f.name)

    try:
        # Measure append throughput
        results: dict[str, Any] = {"batches": {}}
        for batch_label, n in [("1k events", 1000), ("10k events", 10_000), ("100k events", 100_000)]:
            tmp_path.unlink(missing_ok=True)
            events_data = [
                {"pid": f"proc-{i%20}", "kind": "log", "ts": time.time(),
                 "payload": {"message": f"msg-{i}", "level": "info"}}
                for i in range(n)
            ]

            # Per-event open/write/close (baseline worst-case; do not do this in real tools)
            t0 = time.perf_counter()
            for data in events_data:
                with open(tmp_path, "a") as fh:
                    fh.write(json.dumps(data) + "\n")
            t_per_event = time.perf_counter() - t0

            tmp_path.unlink(missing_ok=True)

            # Batched: open once, write all
            t0 = time.perf_counter()
            with open(tmp_path, "a") as fh:
                for data in events_data:
                    fh.write(json.dumps(data) + "\n")
            t_batched = time.perf_counter() - t0

            evts_per_sec_single = n / t_per_event
            evts_per_sec_batch = n / t_batched
            results["batches"][batch_label] = {
                "events": n,
                "per_event_total_ms": round(t_per_event * 1000, 3),
                "per_event_rate_per_sec": round(evts_per_sec_single, 3),
                "batched_total_ms": round(t_batched * 1000, 3),
                "batched_rate_per_sec": round(evts_per_sec_batch, 3),
                "speedup": round(t_per_event / t_batched, 3),
            }
            if print_output:
                print(
                    f"  {batch_label:>12}: per-event={t_per_event*1000:.1f}ms ({evts_per_sec_single:.0f}/s)  "
                    f"batched={t_batched*1000:.1f}ms ({evts_per_sec_batch:.0f}/s)  "
                    f"speedup={t_per_event/t_batched:.1f}x"
                )
    finally:
        tmp_path.unlink(missing_ok=True)
    return results


def run_system_profile(*, print_output: bool = True) -> dict[str, Any]:
    """Run all system-profile benches and return a structured result dict."""
    return {
        "fanout": bench_fanout(print_output=print_output),
        "rich_rendering": bench_rich_rendering(print_output=print_output),
        "memory": bench_memory(print_output=print_output),
        "persistence_io": bench_persistence_io(print_output=print_output),
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("System Profile")
    print("=" * 60)

    run_system_profile(print_output=True)

    print("\n" + "=" * 60)
    print("Summary: Where the time goes at high throughput")
    print("  - Computed: O(n) scan, budget-breaking at ~500k events")
    print("  - Rich: rendering cost scales with visible rows, not total events")
    print("  - Memory: linear growth (see section 3 for KB/event)")
    print("  - I/O: per-event file open is expensive; open once / keep handle open / batch writes")


if __name__ == "__main__":
    main()
