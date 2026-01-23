#!/usr/bin/env python3
"""Benchmark: Computed scaling vs event count.

Measures the two expensive full-scan Computed patterns from process_manager:
1. process_list — scans all events, builds entity state dict
2. process_logs — scans all events, collects last 50 logs per entity

Usage: uv run bench/computed_scaling.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import argparse
import random
import time
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ProcessEvent:
    pid: str
    kind: Literal["created", "removed", "state_change", "log"]
    ts: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)


def generate_events(n: int, num_processes: int = 20) -> list[ProcessEvent]:
    """Generate a realistic mix of events."""
    events = []
    ts = 0.0
    # Create processes first
    for i in range(num_processes):
        if len(events) >= n:
            break
        events.append(
            ProcessEvent(
                pid=f"proc-{i}",
                kind="created",
                ts=ts,
                payload={"name": f"worker-{i}", "crash_prob": 0.05, "log_freq": 1.0},
            )
        )
        ts += 1.0
        if len(events) >= n:
            break
        events.append(
            ProcessEvent(
                pid=f"proc-{i}",
                kind="state_change",
                ts=ts,
                payload={"from": "stopped", "to": "running"},
            )
        )
        ts += 1.0

    # Fill remaining with ~90% log events, ~10% state changes
    remaining = n - len(events)
    for _ in range(remaining):
        pid = f"proc-{random.randint(0, num_processes - 1)}"
        if random.random() < 0.9:
            events.append(
                ProcessEvent(
                    pid=pid,
                    kind="log",
                    ts=ts,
                    payload={"message": "Processing request", "level": "info"},
                )
            )
        else:
            events.append(
                ProcessEvent(
                    pid=pid,
                    kind="state_change",
                    ts=ts,
                    payload={"from": "running", "to": "running"},
                )
            )
        ts += 1.0
    return events


def compute_process_list(events: list[ProcessEvent]) -> int:
    """Mirrors _compute_process_list: scan all events, build entity state."""
    processes = {}
    for event in events:
        if event.kind == "created":
            processes[event.pid] = {
                "pid": event.pid,
                "name": event.payload["name"],
                "state": "stopped",
                "start_count": 0,
            }
        elif event.kind == "removed":
            processes.pop(event.pid, None)
        elif event.kind == "state_change" and event.pid in processes:
            processes[event.pid]["state"] = event.payload["to"]
            if event.payload["to"] == "running":
                processes[event.pid]["start_count"] += 1
    return len(processes)


def compute_process_logs(events: list[ProcessEvent]) -> int:
    """Mirrors _compute_process_logs: scan all events, collect last 50 logs per entity."""
    logs: dict[str, list] = {}
    for event in events:
        if event.kind == "log":
            if event.pid not in logs:
                logs[event.pid] = []
            logs[event.pid].append(event)
            if len(logs[event.pid]) > 50:
                logs[event.pid] = logs[event.pid][-50:]
    return sum(len(v) for v in logs.values())


def bench_one(events: list[ProcessEvent], func, warmup: int = 3, runs: int = 10) -> float:
    """Time a Computed function, return median ms."""
    # Warmup
    for _ in range(warmup):
        func(events)
    # Measure
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        func(events)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return times[len(times) // 2]  # median


def main():
    parser = argparse.ArgumentParser(description="Benchmark full-scan projection cost vs event count")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for event generation (default: 0). Use -1 to disable seeding.",
    )
    parser.add_argument("--warmup", type=int, default=3, help="Warmup runs per measurement")
    parser.add_argument("--runs", type=int, default=10, help="Measured runs per measurement")
    args = parser.parse_args()

    if args.seed >= 0:
        random.seed(args.seed)

    print("Computed Scaling Benchmark")
    print("=" * 60)
    if args.seed >= 0:
        print(f"seed={args.seed} warmup={args.warmup} runs={args.runs}")
    print(f"{'N events':>10} {'process_list':>14} {'process_logs':>14} {'combined':>14}")
    print(f"{'':>10} {'(ms)':>14} {'(ms)':>14} {'(ms)':>14}")
    print("-" * 60)

    for n in [100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000, 1_000_000]:
        events = generate_events(n, num_processes=min(n // 5, 200))
        t_list = bench_one(events, compute_process_list, warmup=args.warmup, runs=args.runs)
        t_logs = bench_one(events, compute_process_logs, warmup=args.warmup, runs=args.runs)
        combined = t_list + t_logs
        print(f"{n:>10,} {t_list:>12.2f}ms {t_logs:>12.2f}ms {combined:>12.2f}ms")

        # At 10fps, budget is 100ms. Flag if over.
        if combined > 100:
            print(f"{'':>10} ^^^ EXCEEDS 100ms render budget at 10fps")

    print()
    print("Notes:")
    print("- Both Computed functions do full O(n) scans of the event list")
    print("- Whether this breaks you depends on evaluation frequency:")
    print("  - debounced render loop: evaluated at frame rate")
    print("  - naive loop: evaluated per event/version bump")


if __name__ == "__main__":
    main()
