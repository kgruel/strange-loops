#!/usr/bin/env python3
"""Bench harness: run scenario+profile combinations through the reactive pipeline.

Measures framework performance (EventStore + Computed + Effect) with realistic
data shapes. Generation cost is excluded from timing — only pipeline processing
is measured.

Usage:
    uv run bench/harness.py --scenario narrow --profile narrow_high_rate
    uv run bench/harness.py --scenario wide --profile wide_medium_rate --save baseline
    uv run bench/harness.py --scenario wide --profile wide_medium_rate --compare baseline
    uv run bench/harness.py --scenario narrow --sweep num_entities 10,50,100,500
    uv run bench/harness.py --scenario wide --profile wide_medium_rate --seed 0 --save baseline
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reaktiv",
#     "typing_extensions",
#     "rich",
#     "polyfactory",
# ]
# ///

import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from subprocess import DEVNULL, CalledProcessError, check_output

from reaktiv import Signal, Computed, Effect

sys.path.insert(0, str(Path(__file__).parent.parent))
from framework import EventStore, metrics

from scenarios import NarrowEvent, WideEvent, NestedEvent, SCENARIOS
from profiles import EventProfile, PRESETS


# =============================================================================
# REPRODUCIBILITY + ENVIRONMENT
# =============================================================================


def _git_head_sha(repo_root: Path) -> str | None:
    try:
        out = check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=DEVNULL,
            text=True,
        ).strip()
        return out or None
    except (FileNotFoundError, CalledProcessError):
        return None


def collect_environment(repo_root: Path) -> dict[str, Any]:
    """Collect lightweight environment metadata for result comparability."""
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": _git_head_sha(repo_root),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }


def derive_run_seed(
    base_seed: int | None,
    *,
    scenario: str,
    profile_name: str,
    profile: EventProfile,
) -> int | None:
    """Derive a stable per-run seed so sweeps are deterministic regardless of order."""
    if base_seed is None or base_seed < 0:
        return None
    salt = json.dumps(
        {"scenario": scenario, "profile_name": profile_name, "profile": asdict(profile)},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(salt.encode("utf-8")).digest()
    salt_int = int.from_bytes(digest[:4], "big")
    return (int(base_seed) + salt_int) % (2**32)


# =============================================================================
# REACTIVE PIPELINE (mirrors integration.py pattern)
# =============================================================================


class BenchPipeline:
    """Reactive pipeline for benchmarking: store + computeds + effect.

    Adapts Computed logic to the event shape being tested. The computeds
    perform realistic work: scanning events, grouping, filtering — the same
    patterns the production app uses.
    """

    def __init__(self, scenario: str):
        self.store: EventStore = EventStore()
        self.scenario = scenario
        self.render_count = 0
        self._render_dirty = False

        # Wire up scenario-specific computeds
        if scenario == "narrow":
            self.computed_a = Computed(lambda: self._compute_by_source())
            self.computed_b = Computed(lambda: self._compute_filtered_logs())
        elif scenario == "wide":
            self.computed_a = Computed(lambda: self._compute_resource_states())
            self.computed_b = Computed(lambda: self._compute_metric_aggregates())
        elif scenario == "nested":
            self.computed_a = Computed(lambda: self._compute_stack_summary())
            self.computed_b = Computed(lambda: self._compute_service_counts())

        self._effect = Effect(lambda: self._on_change())

    def _on_change(self):
        self.store.version()
        self._render_dirty = True
        metrics.count("effect_fires")

    # --- Narrow scenario computeds ---

    def _compute_by_source(self) -> dict[str, list]:
        """Group events by source, keep last 50 per source."""
        self.store.version()
        with metrics.time("computed_a"):
            groups: dict[str, list] = {}
            for event in self.store.events:
                src = event.source
                if src not in groups:
                    groups[src] = []
                groups[src].append(event)
                if len(groups[src]) > 50:
                    groups[src] = groups[src][-50:]
            return groups

    def _compute_filtered_logs(self) -> dict[str, int]:
        """Count events by level (filter-style scan)."""
        self.store.version()
        with metrics.time("computed_b"):
            counts: dict[str, int] = {}
            for event in self.store.events:
                lvl = event.level
                counts[lvl] = counts.get(lvl, 0) + 1
            return counts

    # --- Wide scenario computeds ---

    def _compute_resource_states(self) -> dict[str, dict]:
        """Build resource state map from events (dict scanning)."""
        self.store.version()
        with metrics.time("computed_a"):
            resources: dict[str, dict] = {}
            for event in self.store.events:
                resources[event.resource_id] = {
                    "type": event.resource_type,
                    "status": event.status,
                    "region": event.region,
                    "tag_count": len(event.tags),
                    "config_keys": len(event.config),
                }
            return resources

    def _compute_metric_aggregates(self) -> dict[str, float]:
        """Aggregate numeric metrics across all events."""
        self.store.version()
        with metrics.time("computed_b"):
            totals: dict[str, float] = {}
            counts: dict[str, int] = {}
            for event in self.store.events:
                for k, v in event.metrics.items():
                    totals[k] = totals.get(k, 0.0) + v
                    counts[k] = counts.get(k, 0) + 1
            return {k: totals[k] / counts[k] for k in totals}

    # --- Nested scenario computeds ---

    def _compute_stack_summary(self) -> dict[str, dict]:
        """Group by stack, track latest status + host count."""
        self.store.version()
        with metrics.time("computed_a"):
            stacks: dict[str, dict] = {}
            for event in self.store.events:
                if event.stack not in stacks:
                    stacks[event.stack] = {"hosts": set(), "status": "unknown", "events": 0}
                stacks[event.stack]["hosts"].add(event.host)
                stacks[event.stack]["status"] = event.status
                stacks[event.stack]["events"] += 1
            # Convert sets for serialization
            return {k: {**v, "hosts": len(v["hosts"])} for k, v in stacks.items()}

    def _compute_service_counts(self) -> dict[str, int]:
        """Count total child services per stack."""
        self.store.version()
        with metrics.time("computed_b"):
            counts: dict[str, int] = {}
            for event in self.store.events:
                counts[event.stack] = counts.get(event.stack, 0) + len(event.services)
            return counts

    # --- Render ---

    def do_render(self):
        """Simulate debounced render: evaluate computeds."""
        if self._render_dirty:
            self._render_dirty = False
            with metrics.time("render"):
                _ = self.computed_a()
                _ = self.computed_b()
            self.render_count += 1
            metrics.count("frames_rendered")


# =============================================================================
# EVENT GENERATION (pre-generated, cost excluded from timing)
# =============================================================================


def generate_events(scenario: str, profile: EventProfile) -> list:
    """Pre-generate all events. Cost is NOT included in pipeline timing."""
    factory_cls = SCENARIOS[scenario]["factory"]
    event_count = profile.event_count

    # Apply profile overrides to factory behavior
    events = []
    for i in range(event_count):
        # Entity distribution: round-robin across num_entities
        entity_idx = i % profile.num_entities

        if scenario == "narrow":
            source = f"svc-{entity_idx}"
            event = factory_cls.build(source=source, ts=float(i))
        elif scenario == "wide":
            resource_id = f"res-{entity_idx:04d}"
            # Respect payload_fields for tag/config width
            tags = {f"tag-{j}": f"v-{random.randint(0,100)}" for j in range(min(profile.payload_fields, 30))}
            config = {f"cfg-{j}": random.randint(0, 1000) for j in range(profile.payload_fields)}
            event = factory_cls.build(resource_id=resource_id, tags=tags, config=config, ts=float(i))
        elif scenario == "nested":
            stack = f"stack-{entity_idx}"
            # Respect child_entities for service count
            services = tuple(
                {
                    "name": f"svc-{j}",
                    "status": random.choice(["running", "stopped", "crashed"]),
                    "pid": random.randint(1000, 65000),
                    "cpu": round(random.uniform(0, 100), 1),
                    "mem_mb": round(random.uniform(10, 2048), 1),
                }
                for j in range(profile.child_entities)
            )
            event = factory_cls.build(stack=stack, services=services, ts=float(i))
        else:
            event = factory_cls.build(ts=float(i))

        events.append(event)

    # Apply burst_factor: reorder events into bursts
    if profile.burst_factor > 1.0:
        events = _apply_bursts(events, profile.burst_factor)

    return events


def _apply_bursts(events: list, burst_factor: float) -> list:
    """Reorder events to simulate bursty arrival.

    burst_factor controls how clustered same-entity events are.
    Higher = more temporal locality (events from same entity arrive together).
    """
    # Group by entity, then interleave with burst clustering
    from collections import defaultdict
    by_entity: dict[str, list] = defaultdict(list)

    for event in events:
        # Extract entity key based on event type
        if hasattr(event, "source"):
            key = event.source
        elif hasattr(event, "resource_id"):
            key = event.resource_id
        elif hasattr(event, "stack"):
            key = event.stack
        else:
            key = "default"
        by_entity[key].append(event)

    # Emit in bursts: pick a random entity, emit burst_factor events from it
    result = []
    entities = list(by_entity.keys())
    burst_size = max(1, int(burst_factor))

    while any(by_entity[e] for e in entities):
        entity = random.choice(entities)
        for _ in range(burst_size):
            if by_entity[entity]:
                result.append(by_entity[entity].pop(0))
        # Remove exhausted entities
        entities = [e for e in entities if by_entity[e]]

    return result


# =============================================================================
# HARNESS: RUN + MEASURE
# =============================================================================


@dataclass
class RunResult:
    """Result of a single harness run."""
    scenario: str
    profile_name: str
    profile: dict
    base_seed: int | None
    seed: int | None
    environment: dict
    iteration_times_ms: list[float]
    median_ms: float
    p95_ms: float
    max_ms: float
    events_per_sec: float
    total_events: int
    frames_rendered: int
    framework_metrics: dict
    timestamp: str


def run_iteration(pipeline: BenchPipeline, events: list) -> float:
    """Push all events through pipeline, render at 20fps. Returns elapsed ms.

    Events are pre-generated — this measures only pipeline cost.
    """
    metrics.reset()
    metrics.enable()

    # Reset pipeline state
    pipeline.store.events.clear()
    pipeline.store.version.set(0)
    pipeline.render_count = 0
    pipeline._render_dirty = False

    render_interval = 0.05  # 20fps
    last_render = time.perf_counter()
    start = time.perf_counter()

    for event in events:
        pipeline.store.add(event)

        # Render at frame rate
        now = time.perf_counter()
        if now - last_render >= render_interval:
            pipeline.do_render()
            last_render = now

    # Final render
    pipeline.do_render()

    elapsed_ms = (time.perf_counter() - start) * 1000
    metrics.disable()
    return elapsed_ms


def run_harness(
    scenario: str,
    profile: EventProfile,
    profile_name: str,
    *,
    base_seed: int | None,
    environment: dict[str, Any],
) -> RunResult:
    """Run warmup + measurement iterations, collect stats."""
    run_seed = derive_run_seed(base_seed, scenario=scenario, profile_name=profile_name, profile=profile)
    if run_seed is not None:
        random.seed(run_seed)

    # Pre-generate events (excluded from timing)
    print(f"  Generating {profile.event_count:,} events...", end=" ", flush=True)
    gen_start = time.perf_counter()
    events = generate_events(scenario, profile)
    gen_ms = (time.perf_counter() - gen_start) * 1000
    print(f"done ({gen_ms:.0f}ms)")

    pipeline = BenchPipeline(scenario)

    # Warmup
    print(f"  Warmup ({profile.warmup_iterations} iterations)...", end=" ", flush=True)
    for _ in range(profile.warmup_iterations):
        run_iteration(pipeline, events)
    print("done")

    # Measurement
    print(f"  Measuring ({profile.measure_iterations} iterations)...", end=" ", flush=True)
    times: list[float] = []
    for _ in range(profile.measure_iterations):
        elapsed = run_iteration(pipeline, events)
        times.append(elapsed)
    print("done")

    # Collect final framework metrics (from last iteration)
    metrics.enable()
    # Re-run once more to get clean metrics snapshot
    final_elapsed = run_iteration(pipeline, events)
    snap = metrics.snapshot()
    metrics.disable()

    sorted_times = sorted(times)
    median = statistics.median(sorted_times)
    p95_idx = min(int(len(sorted_times) * 0.95), len(sorted_times) - 1)
    p95 = sorted_times[p95_idx]

    return RunResult(
        scenario=scenario,
        profile_name=profile_name,
        profile=asdict(profile) if hasattr(profile, "__dataclass_fields__") else {},
        base_seed=base_seed,
        seed=run_seed,
        environment=environment,
        iteration_times_ms=times,
        median_ms=round(median, 2),
        p95_ms=round(p95, 2),
        max_ms=round(max(times), 2),
        events_per_sec=round(profile.event_count / (median / 1000), 0),
        total_events=profile.event_count,
        frames_rendered=pipeline.render_count,
        framework_metrics=snap,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


# =============================================================================
# SAVE / COMPARE
# =============================================================================

RESULTS_DIR = Path(__file__).parent / "results"


def save_result(result: RunResult, name: str) -> Path:
    """Save result as JSON."""
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"

    data = {
        "scenario": result.scenario,
        "profile_name": result.profile_name,
        "profile": result.profile,
        "base_seed": result.base_seed,
        "seed": result.seed,
        "environment": result.environment,
        "iteration_times_ms": result.iteration_times_ms,
        "median_ms": result.median_ms,
        "p95_ms": result.p95_ms,
        "max_ms": result.max_ms,
        "events_per_sec": result.events_per_sec,
        "total_events": result.total_events,
        "frames_rendered": result.frames_rendered,
        "framework_metrics": result.framework_metrics,
        "timestamp": result.timestamp,
    }

    path.write_text(json.dumps(data, indent=2))
    return path


def load_result(name: str) -> dict | None:
    """Load a saved result by name."""
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def compare_results(current: RunResult, baseline: dict) -> None:
    """Print delta comparison between current run and saved baseline."""
    print("\n  Comparison vs baseline:")
    print(f"  {'Metric':<24} {'Baseline':>12} {'Current':>12} {'Delta':>10} {'%':>8}")
    print(f"  {'-'*70}")

    comparisons = [
        ("median_ms", baseline["median_ms"], current.median_ms, "ms"),
        ("p95_ms", baseline["p95_ms"], current.p95_ms, "ms"),
        ("max_ms", baseline["max_ms"], current.max_ms, "ms"),
        ("events_per_sec", baseline["events_per_sec"], current.events_per_sec, "/s"),
    ]

    for label, base_val, curr_val, unit in comparisons:
        delta = curr_val - base_val
        pct = (delta / base_val * 100) if base_val != 0 else 0
        direction = "+" if delta > 0 else ""
        # For timing: lower is better. For throughput: higher is better.
        if "sec" in label:
            indicator = " *" if pct > 5 else " !" if pct < -5 else ""
        else:
            indicator = " !" if pct > 5 else " *" if pct < -5 else ""
        print(f"  {label:<24} {base_val:>10.1f}{unit:>2} {curr_val:>10.1f}{unit:>2} "
              f"{direction}{delta:>8.1f} {pct:>+7.1f}%{indicator}")

    # Compare framework timing breakdowns
    base_timings = baseline.get("framework_metrics", {}).get("timings", {})
    curr_timings = current.framework_metrics.get("timings", {})
    if base_timings and curr_timings:
        print(f"\n  {'Computed timing':<24} {'Base avg':>12} {'Curr avg':>12} {'Delta':>10}")
        print(f"  {'-'*60}")
        for key in sorted(set(base_timings) | set(curr_timings)):
            if key in base_timings and key in curr_timings:
                b = base_timings[key]["avg_ms"]
                c = curr_timings[key]["avg_ms"]
                delta = c - b
                print(f"  {key:<24} {b:>10.2f}ms {c:>10.2f}ms {delta:>+9.2f}ms")


# =============================================================================
# CLI
# =============================================================================


def print_result(result: RunResult) -> None:
    """Print formatted result summary."""
    print(f"\n  Results:")
    if result.seed is not None:
        print(f"    Seed:            {result.seed} (base={result.base_seed})")
    git_sha = result.environment.get("git_sha") if isinstance(result.environment, dict) else None
    if git_sha:
        print(f"    Git SHA:         {git_sha}")
    print(f"    Median:          {result.median_ms:>10.2f} ms")
    print(f"    P95:             {result.p95_ms:>10.2f} ms")
    print(f"    Max:             {result.max_ms:>10.2f} ms")
    print(f"    Throughput:      {result.events_per_sec:>10,.0f} events/sec")
    print(f"    Events:          {result.total_events:>10,}")
    print(f"    Frames rendered: {result.frames_rendered:>10}")

    # Timing breakdown from framework metrics
    timings = result.framework_metrics.get("timings", {})
    if timings:
        print(f"\n  Framework timings (last iteration):")
        for name in sorted(timings):
            t = timings[name]
            print(f"    {name:<20} avg={t['avg_ms']:>7.2f}ms  "
                  f"p95={t['p95_ms']:>7.2f}ms  max={t['max_ms']:>7.2f}ms  n={t['count']}")

    counters = result.framework_metrics.get("counters", {})
    if counters:
        print(f"\n  Counters:")
        for name, val in sorted(counters.items()):
            print(f"    {name:<24} {val:>10,}")


def run_sweep(scenario: str, profile: EventProfile, profile_name: str,
              param: str, values: list[int], *, base_seed: int | None, environment: dict[str, Any]) -> None:
    """Sweep a single parameter across values."""
    print(f"\n  Sweep: {param} = {values}")
    print(f"  {'Value':>8} {'Median ms':>12} {'P95 ms':>10} {'Events/sec':>12}")
    print(f"  {'-'*50}")

    for val in values:
        swept_profile = EventProfile(**{**asdict(profile), param: val})
        result = run_harness(
            scenario,
            swept_profile,
            f"{profile_name}_{param}_{val}",
            base_seed=base_seed,
            environment=environment,
        )
        print(f"  {val:>8} {result.median_ms:>12.2f} {result.p95_ms:>10.2f} "
              f"{result.events_per_sec:>12,.0f}")


def main():
    parser = argparse.ArgumentParser(
        description="Bench harness: measure framework performance with realistic data shapes"
    )
    parser.add_argument("--scenario", required=True, choices=list(SCENARIOS.keys()),
                        help="Event shape scenario")
    parser.add_argument("--profile", default=None,
                        help=f"Named preset ({', '.join(PRESETS.keys())}) or use defaults")
    parser.add_argument("--save", metavar="NAME",
                        help="Save results as JSON to bench/results/NAME.json")
    parser.add_argument("--compare", metavar="NAME",
                        help="Compare against saved baseline NAME")
    parser.add_argument("--sweep", nargs=2, metavar=("PARAM", "VALUES"),
                        help="Sweep a profile parameter (e.g. --sweep num_entities 10,50,100)")
    parser.add_argument("--event-count", type=int, default=None,
                        help="Override event count")
    parser.add_argument("--warmup", type=int, default=None,
                        help="Override warmup iterations")
    parser.add_argument("--iterations", type=int, default=None,
                        help="Override measurement iterations")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Base RNG seed (default: 0). Each run derives a stable per-scenario seed; use -1 to disable seeding.",
    )

    args = parser.parse_args()
    repo_root = Path(__file__).parent.parent
    environment = collect_environment(repo_root)

    # Resolve profile
    if args.profile and args.profile in PRESETS:
        profile = PRESETS[args.profile]
        profile_name = args.profile
    elif args.profile:
        parser.error(f"Unknown profile: {args.profile}. Available: {', '.join(PRESETS.keys())}")
        return
    else:
        profile = EventProfile()
        profile_name = "default"

    # Apply overrides
    if args.event_count is not None:
        profile = EventProfile(**{**asdict(profile), "event_count": args.event_count})
    if args.warmup is not None:
        profile = EventProfile(**{**asdict(profile), "warmup_iterations": args.warmup})
    if args.iterations is not None:
        profile = EventProfile(**{**asdict(profile), "measure_iterations": args.iterations})

    print(f"Bench Harness: scenario={args.scenario}, profile={profile_name}, base_seed={args.seed}")
    print(f"  {profile}")
    print()

    # Sweep mode
    if args.sweep:
        param, values_str = args.sweep
        if not hasattr(profile, param):
            parser.error(f"Unknown sweep parameter: {param}. "
                         f"Available: {list(EventProfile.__dataclass_fields__.keys())}")
            return
        values = [int(v) for v in values_str.split(",")]
        run_sweep(
            args.scenario,
            profile,
            profile_name,
            param,
            values,
            base_seed=args.seed,
            environment=environment,
        )
        return

    # Normal run
    result = run_harness(
        args.scenario,
        profile,
        profile_name,
        base_seed=args.seed,
        environment=environment,
    )
    print_result(result)

    # Save
    if args.save:
        path = save_result(result, args.save)
        print(f"\n  Saved to: {path}")

    # Compare
    if args.compare:
        baseline = load_result(args.compare)
        if baseline is None:
            print(f"\n  Error: baseline '{args.compare}' not found in {RESULTS_DIR}")
        else:
            compare_results(result, baseline)

    print()


if __name__ == "__main__":
    main()
