#!/usr/bin/env python3
"""Bench snapshot: run the full bench suite and write a single report file.

This ties together:
- harness presets (reactive pipeline cost across event-shape scenarios)
- system_profile (fanout, Rich rendering, memory, persistence I/O)
- computed_scaling (full-scan projection scaling)

Usage:
    uv run bench/snapshot.py --name baseline --seed 0
    uv run bench/snapshot.py --name current --seed 0 --compare baseline
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

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
import time
from contextlib import redirect_stdout
from dataclasses import asdict as dataclass_asdict
from pathlib import Path
from typing import Any


SNAPSHOT_DIR = Path(__file__).parent / "results" / "snapshots"


def _stable_seed(base_seed: int | None, *, namespace: str) -> int | None:
    """Derive a stable component seed from a base seed + namespace."""
    if base_seed is None or base_seed < 0:
        return None
    digest = hashlib.sha256(f"{base_seed}:{namespace}".encode("utf-8")).digest()
    salt_int = int.from_bytes(digest[:4], "big")
    return (int(base_seed) + salt_int) % (2**32)


def _fmt(value: float | int | None, unit: str = "", digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}{unit}"
    return f"{value:.{digits}f}{unit}"


def _pct_delta(base: float | None, curr: float | None) -> float | None:
    if base is None or curr is None or base == 0:
        return None
    return (curr - base) / base * 100.0


def _delta_cell(base: float | None, curr: float | None, unit: str = "", digits: int = 2) -> str:
    if base is None or curr is None:
        return "—"
    delta = curr - base
    pct = _pct_delta(base, curr)
    pct_s = "" if pct is None else f" ({pct:+.{digits}f}%)"
    return f"{delta:+.{digits}f}{unit}{pct_s}"


def _get_timing_avg_ms(result: dict[str, Any], name: str) -> float | None:
    try:
        return float(result["framework_metrics"]["timings"][name]["avg_ms"])
    except Exception:
        return None


def _get_counter(result: dict[str, Any], name: str) -> int | None:
    try:
        return int(result["framework_metrics"]["counters"].get(name))
    except Exception:
        return None


def load_snapshot(name: str) -> dict[str, Any] | None:
    path = SNAPSHOT_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_snapshot(snapshot: dict[str, Any], name: str, *, baseline: dict[str, Any] | None) -> tuple[Path, Path]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = SNAPSHOT_DIR / f"{name}.json"
    md_path = SNAPSHOT_DIR / f"{name}.md"
    json_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    md_path.write_text(render_markdown(snapshot, name=name, baseline=baseline))
    return json_path, md_path


def render_markdown(snapshot: dict[str, Any], *, name: str, baseline: dict[str, Any] | None) -> str:
    meta = snapshot.get("meta", {})
    env = meta.get("environment", {})
    base_seed = meta.get("base_seed")
    baseline_name = snapshot.get("meta", {}).get("baseline_name")

    lines: list[str] = []
    lines.append(f"# Bench Snapshot: {name}")
    lines.append("")
    lines.append(f"- Created (UTC): `{meta.get('timestamp_utc', 'unknown')}`")
    lines.append(f"- Base seed: `{base_seed}`")
    if env.get("git_sha"):
        lines.append(f"- Git SHA: `{env['git_sha']}`")
    if env.get("python_version"):
        lines.append(f"- Python: `{env.get('python_implementation', 'Python')} {env['python_version']}`")
    if env.get("platform"):
        lines.append(f"- Platform: `{env['platform']}`")
    if baseline_name:
        lines.append(f"- Compared against: `{baseline_name}`")
    lines.append("")

    # ---------------------------------------------------------------------
    # Harness suite
    # ---------------------------------------------------------------------
    lines.append("## Harness Suite (Reactive Pipeline)")
    lines.append("")
    harness = snapshot.get("harness_suite", {})
    harness_base = (baseline or {}).get("harness_suite", {}) if baseline else {}

    for scenario in ("narrow", "wide", "nested"):
        curr = harness.get(scenario)
        if not curr:
            continue
        base = harness_base.get(scenario) if baseline else None

        profile_name = curr.get("profile_name", "unknown")
        lines.append(f"### {scenario} / {profile_name}")
        lines.append("")
        lines.append("| Metric | Baseline | Current | Delta |")
        lines.append("|---|---:|---:|---:|")

        def row(metric: str, base_val: float | int | None, curr_val: float | int | None, unit: str = "", digits: int = 2):
            b = _fmt(base_val, unit=unit, digits=digits) if baseline else "—"
            c = _fmt(curr_val, unit=unit, digits=digits)
            d = _delta_cell(float(base_val) if baseline and base_val is not None else None,
                            float(curr_val) if curr_val is not None else None,
                            unit=unit, digits=digits) if baseline else "—"
            lines.append(f"| `{metric}` | {b} | {c} | {d} |")

        row("median_ms", base.get("median_ms") if base else None, curr.get("median_ms"), unit=" ms", digits=2)
        row("p95_ms", base.get("p95_ms") if base else None, curr.get("p95_ms"), unit=" ms", digits=2)
        row("events_per_sec", base.get("events_per_sec") if base else None, curr.get("events_per_sec"), unit=" /s", digits=0)
        row("frames_rendered", base.get("frames_rendered") if base else None, curr.get("frames_rendered"), unit="", digits=0)

        base_effects = _get_counter(base, "effect_fires") if base else None
        curr_effects = _get_counter(curr, "effect_fires")
        row("effect_fires", base_effects, curr_effects, unit="", digits=0)

        def ratio(effects: int | None, frames: int | None) -> float | None:
            if effects is None or frames is None or frames == 0:
                return None
            return effects / frames

        row(
            "effect_per_frame",
            ratio(base_effects, int(base.get("frames_rendered")) if base else None) if base else None,
            ratio(curr_effects, int(curr.get("frames_rendered"))),
            unit="",
            digits=2,
        )

        # Timing breakdown (avg ms)
        lines.append("")
        lines.append("| Timing (avg) | Baseline | Current | Delta |")
        lines.append("|---|---:|---:|---:|")
        for timing in ("computed_a", "computed_b", "render"):
            row(
                timing,
                _get_timing_avg_ms(base, timing) if base else None,
                _get_timing_avg_ms(curr, timing),
                unit=" ms",
                digits=2,
            )
        lines.append("")

    # ---------------------------------------------------------------------
    # System profile
    # ---------------------------------------------------------------------
    lines.append("## System Profile (Components)")
    lines.append("")
    sys_prof = snapshot.get("system_profile", {})
    sys_base = (baseline or {}).get("system_profile", {}) if baseline else {}

    # Fanout
    fan = sys_prof.get("fanout", {})
    fan_b = sys_base.get("fanout", {}) if baseline else {}
    if fan:
        lines.append("### Fanout")
        lines.append("")
        lines.append("| Metric | Baseline | Current | Delta |")
        lines.append("|---|---:|---:|---:|")
        for key in ("events_added", "effect_renders"):
            row = (
                f"| `{key}` | {_fmt(fan_b.get(key), digits=0) if baseline else '—'} | {_fmt(fan.get(key), digits=0)} | "
                f"{_delta_cell(float(fan_b.get(key)) if baseline and fan_b.get(key) is not None else None, float(fan.get(key)) if fan.get(key) is not None else None, digits=0) if baseline else '—'} |"
            )
            lines.append(row)
        lines.append("")

        computed = fan.get("computed_evals", {}) or {}
        computed_b = fan_b.get("computed_evals", {}) or {}
        if computed:
            lines.append("| Computed | Baseline | Current | Delta |")
            lines.append("|---|---:|---:|---:|")
            for k in sorted(computed.keys()):
                b = computed_b.get(k) if baseline else None
                c = computed.get(k)
                lines.append(
                    f"| `{k}` | {_fmt(b, digits=0) if baseline else '—'} | {_fmt(c, digits=0)} | "
                    f"{_delta_cell(float(b) if baseline and b is not None else None, float(c) if c is not None else None, digits=0) if baseline else '—'} |"
                )
            lines.append("")

    # Rich rendering
    rich = sys_prof.get("rich_rendering", {})
    rich_b = sys_base.get("rich_rendering", {}) if baseline else {}
    rows = rich.get("rows", {}) or {}
    if rows:
        lines.append("### Rich Rendering")
        lines.append("")
        lines.append("| Rows | Metric | Baseline | Current | Delta |")
        lines.append("|---:|---|---:|---:|---:|")
        for row_count in sorted(rows.keys(), key=lambda s: int(s)):
            curr_row = rows[row_count]
            base_row = (rich_b.get("rows", {}) or {}).get(row_count, {}) if baseline else {}
            for metric in ("build_median_ms", "render_median_ms", "total_median_ms"):
                b = base_row.get(metric) if baseline else None
                c = curr_row.get(metric)
                lines.append(
                    f"| {row_count} | `{metric}` | {_fmt(b, unit=' ms', digits=2) if baseline else '—'} | "
                    f"{_fmt(c, unit=' ms', digits=2)} | "
                    f"{_delta_cell(float(b) if baseline and b is not None else None, float(c) if c is not None else None, unit=' ms', digits=2) if baseline else '—'} |"
                )
        lines.append("")

    # Memory
    mem = sys_prof.get("memory", {})
    mem_b = sys_base.get("memory", {}) if baseline else {}
    points = mem.get("points", []) or []
    if points:
        lines.append("### Memory (tracemalloc)")
        lines.append("")
        lines.append("| Events | KB/event (py) | Baseline KB/event | Delta |")
        lines.append("|---:|---:|---:|---:|")
        base_points_by_n = {p.get("events"): p for p in (mem_b.get("points", []) or [])} if baseline else {}
        for p in points:
            n = p.get("events")
            c = p.get("python_kb_per_event")
            b = base_points_by_n.get(n, {}).get("python_kb_per_event") if baseline else None
            lines.append(
                f"| {n:,} | {_fmt(c, unit=' KB', digits=3)} | {_fmt(b, unit=' KB', digits=3) if baseline else '—'} | "
                f"{_delta_cell(float(b) if baseline and b is not None else None, float(c) if c is not None else None, unit=' KB', digits=3) if baseline else '—'} |"
            )
        lines.append("")

    # Persistence I/O
    io = sys_prof.get("persistence_io", {})
    io_b = sys_base.get("persistence_io", {}) if baseline else {}
    batches = io.get("batches", {}) or {}
    if batches:
        lines.append("### Persistence I/O")
        lines.append("")
        lines.append("| Batch | Metric | Baseline | Current | Delta |")
        lines.append("|---|---|---:|---:|---:|")
        base_batches = io_b.get("batches", {}) if baseline else {}
        for batch_label in ("1k events", "10k events", "100k events"):
            curr_b = batches.get(batch_label)
            if not curr_b:
                continue
            base_b = base_batches.get(batch_label, {}) if baseline else {}
            for metric, unit, digits in (
                ("per_event_rate_per_sec", " /s", 0),
                ("batched_rate_per_sec", " /s", 0),
                ("speedup", "x", 2),
            ):
                b = base_b.get(metric) if baseline else None
                c = curr_b.get(metric)
                unit_str = "x" if unit == "x" else unit
                lines.append(
                    f"| {batch_label} | `{metric}` | {_fmt(b, unit=unit_str, digits=digits) if baseline else '—'} | "
                    f"{_fmt(c, unit=unit_str, digits=digits)} | "
                    f"{_delta_cell(float(b) if baseline and b is not None else None, float(c) if c is not None else None, unit=unit_str, digits=digits) if baseline else '—'} |"
                )
        lines.append("")

    # ---------------------------------------------------------------------
    # Computed scaling
    # ---------------------------------------------------------------------
    lines.append("## Computed Scaling (Full-scan Projections)")
    lines.append("")
    cs = snapshot.get("computed_scaling", {})
    cs_b = (baseline or {}).get("computed_scaling", {}) if baseline else {}
    rows = cs.get("rows", []) or []
    if rows:
        lines.append(f"- Seed: `{cs.get('seed')}` warmup=`{cs.get('warmup')}` runs=`{cs.get('runs')}`")
        lines.append("")
        lines.append("| N events | Combined ms | Baseline combined ms | Delta |")
        lines.append("|---:|---:|---:|---:|")
        base_by_n = {int(r["n_events"]): r for r in (cs_b.get("rows", []) or [])} if baseline else {}
        for r in rows:
            n = int(r["n_events"])
            c = float(r["combined_ms"])
            b = float(base_by_n.get(n, {}).get("combined_ms")) if baseline and n in base_by_n else None
            lines.append(
                f"| {n:,} | {_fmt(c, unit=' ms', digits=2)} | {_fmt(b, unit=' ms', digits=2) if baseline else '—'} | "
                f"{_delta_cell(b, c, unit=' ms', digits=2) if baseline else '—'} |"
            )
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(f"Raw JSON: `{(SNAPSHOT_DIR / f'{name}.json').as_posix()}`")
    if baseline_name:
        lines.append(f"Baseline JSON: `{(SNAPSHOT_DIR / f'{baseline_name}.json').as_posix()}`")
    lines.append("")
    return "\n".join(lines)


def run_snapshot(*, name: str, base_seed: int, compare: str | None, verbose: bool, scaling_warmup: int, scaling_runs: int) -> dict[str, Any]:
    # Local imports so `uv run` script deps apply cleanly.
    import harness
    import system_profile
    import computed_scaling
    from profiles import PRESETS

    repo_root = Path(__file__).parent.parent
    environment = harness.collect_environment(repo_root)

    harness_pairs = [
        ("narrow", "narrow_high_rate"),
        ("wide", "wide_medium_rate"),
        ("nested", "nested_batch"),
    ]

    harness_suite: dict[str, Any] = {}
    for scenario, preset in harness_pairs:
        profile = PRESETS[preset]
        if verbose:
            result = harness.run_harness(
                scenario,
                profile,
                preset,
                base_seed=base_seed,
                environment=environment,
            )
        else:
            with redirect_stdout(io.StringIO()):
                result = harness.run_harness(
                    scenario,
                    profile,
                    preset,
                    base_seed=base_seed,
                    environment=environment,
                )
        harness_suite[scenario] = dataclass_asdict(result)

    sys_prof = system_profile.run_system_profile(print_output=verbose)

    cs_seed = _stable_seed(base_seed, namespace="computed_scaling")
    if cs_seed is not None:
        random.seed(cs_seed)
    counts = [100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000, 1_000_000]
    cs_rows: list[dict[str, Any]] = []
    for n in counts:
        events = computed_scaling.generate_events(n, num_processes=min(n // 5, 200))
        t_list = computed_scaling.bench_one(
            events, computed_scaling.compute_process_list, warmup=scaling_warmup, runs=scaling_runs
        )
        t_logs = computed_scaling.bench_one(
            events, computed_scaling.compute_process_logs, warmup=scaling_warmup, runs=scaling_runs
        )
        cs_rows.append(
            {
                "n_events": n,
                "process_list_ms": round(t_list, 3),
                "process_logs_ms": round(t_logs, 3),
                "combined_ms": round(t_list + t_logs, 3),
            }
        )

    snapshot = {
        "schema_version": 1,
        "meta": {
            "name": name,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_seed": base_seed,
            "baseline_name": compare,
            "argv": list(sys.argv),
            "environment": environment,
        },
        "harness_suite": harness_suite,
        "system_profile": sys_prof,
        "computed_scaling": {
            "seed": cs_seed,
            "warmup": scaling_warmup,
            "runs": scaling_runs,
            "rows": cs_rows,
        },
    }
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a full benchmark snapshot and write a single report file.")
    parser.add_argument("--name", required=True, help="Snapshot name (saved as bench/results/snapshots/<name>.*)")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Base RNG seed (default: 0). Use -1 to disable seeding (not recommended for comparisons).",
    )
    parser.add_argument("--compare", default=None, help="Baseline snapshot name to compare against")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output while running")
    parser.add_argument("--scaling-warmup", type=int, default=3, help="Warmup runs for computed_scaling")
    parser.add_argument("--scaling-runs", type=int, default=10, help="Measured runs for computed_scaling")
    args = parser.parse_args()

    baseline = load_snapshot(args.compare) if args.compare else None
    if args.compare and baseline is None:
        print(f"Error: baseline snapshot '{args.compare}' not found in {SNAPSHOT_DIR}", file=sys.stderr)
        return 2

    snapshot = run_snapshot(
        name=args.name,
        base_seed=args.seed,
        compare=args.compare,
        verbose=not args.quiet,
        scaling_warmup=args.scaling_warmup,
        scaling_runs=args.scaling_runs,
    )
    json_path, md_path = save_snapshot(snapshot, args.name, baseline=baseline)
    print(f"Wrote snapshot: {md_path}")
    print(f"Wrote raw JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
