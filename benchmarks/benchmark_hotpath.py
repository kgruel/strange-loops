"""Monorepo Benchmark Suite: Cross-Layer Hot-Path Verification.

Measures latency and throughput across raw store, engine admission, and CLI cold paths.
Supports recording baselines and comparing candidate runs against baseline JSON.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

from atoms import Fact
from engine import open_vertex, vertex_read
from engine.handle import WriteCredentials
from engine.jsonl_store import JsonlStore
from engine.sqlite_store import SqliteStore
from engine.store_reader import StoreReader


class BenchCreds:
    """Mock CredentialProvider for benchmark runs."""

    def for_write(self, vertex: Path) -> WriteCredentials:
        return WriteCredentials()


def measure_store_write(n_facts: int = 1000, runs: int = 3) -> dict[str, float]:
    """Measure raw SqliteStore append throughput (median over multiple runs)."""
    totals = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "bench.db"
            store = SqliteStore(
                path=store_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )
            facts = [
                Fact(
                    kind="note",
                    ts=1700000000.0 + i,
                    payload={"index": i, "content": f"Fact payload {i}"},
                    observer="bench",
                    origin="bench",
                )
                for i in range(n_facts)
            ]

            start = time.perf_counter()
            for f in facts:
                store.append(f)
            elapsed_sec = time.perf_counter() - start
            totals.append(elapsed_sec)

    median_sec = statistics.median(totals)
    ops_per_sec = n_facts / median_sec if median_sec > 0 else 0
    ms_per_op = (median_sec / n_facts) * 1000

    return {
        "store_write_total_ms": round(median_sec * 1000, 2),
        "store_write_ms_per_op": round(ms_per_op, 4),
        "store_write_ops_per_sec": round(ops_per_sec, 1),
    }


def measure_store_read(n_facts: int = 1000, runs: int = 3) -> dict[str, float]:
    """Measure raw SqliteStore scan and query latency (median over multiple runs)."""
    totals = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "bench.db"
            store = SqliteStore(
                path=store_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            )
            for i in range(n_facts):
                store.append(
                    Fact(
                        kind="note",
                        ts=1700000000.0 + i,
                        payload={"index": i},
                        observer="bench",
                        origin="bench",
                    )
                )

            start = time.perf_counter()
            read_facts = store.since(0)
            elapsed_sec = time.perf_counter() - start

            assert len(read_facts) == n_facts
            totals.append(elapsed_sec)

    median_sec = statistics.median(totals)
    return {
        "store_read_since_1k_ms": round(median_sec * 1000, 2),
    }


def measure_engine_emit(n_facts: int = 500, runs: int = 3) -> dict[str, float]:
    """Measure engine.handle.receive throughput (median over multiple runs)."""
    totals = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "bench.db"
            vertex_path = Path(tmpdir) / "bench.vertex"
            vertex_path.write_text(
                f'name "bench"\n'
                f'store "{store_path}"\n'
                f'loops {{\n'
                f'  note {{\n'
                f'    fold {{ items "collect" 100 }}\n'
                f'  }}\n'
                f'}}\n'
            )
            SqliteStore(
                path=store_path,
                serialize=lambda f: f.to_dict(),
                deserialize=Fact.from_dict,
            ).close()

            with open_vertex(vertex_path, credentials=BenchCreds()) as handle:
                facts = [
                    Fact(
                        kind="note",
                        ts=1700000000.0 + i,
                        payload={"index": i, "title": f"Bench note {i}"},
                        observer="bench",
                        origin="bench",
                    )
                    for i in range(n_facts)
                ]

                start = time.perf_counter()
                for f in facts:
                    handle.receive(f)
                elapsed_sec = time.perf_counter() - start
                totals.append(elapsed_sec)

    median_sec = statistics.median(totals)
    ms_per_op = (median_sec / n_facts) * 1000
    ops_per_sec = n_facts / median_sec if median_sec > 0 else 0

    return {
        "engine_emit_total_ms": round(median_sec * 1000, 2),
        "engine_emit_ms_per_op": round(ms_per_op, 4),
        "engine_emit_ops_per_sec": round(ops_per_sec, 1),
    }


def measure_engine_summary_and_replay(n_facts: int = 500) -> dict[str, float]:
    """Measure engine reader summary and state replay over pre-populated vertex."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "bench.db"
        vertex_path = Path(tmpdir) / "bench.vertex"
        vertex_path.write_text(
            f'name "bench"\n'
            f'store "{store_path}"\n'
            f'loops {{\n'
            f'  note {{\n'
            f'    fold {{ items "collect" 100 }}\n'
            f'  }}\n'
            f'}}\n'
        )
        SqliteStore(
            path=store_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        ).close()

        with open_vertex(vertex_path, credentials=BenchCreds()) as handle:
            for i in range(n_facts):
                handle.receive(
                    Fact(
                        kind="note",
                        ts=1700000000.0 + i,
                        payload={"index": i, "val": i * 2},
                        observer="bench",
                        origin="bench",
                    )
                )

            reader = StoreReader(store_path)
            # Measure summary latency (repeated 10 times)
            summary_times = []
            for _ in range(10):
                start = time.perf_counter()
                summary = reader.summary()
                summary_times.append((time.perf_counter() - start) * 1000)
                assert summary["facts"]["total"] == n_facts

            # Measure fold state replay latency (repeated 10 times)
            replay_times = []
            for _ in range(10):
                start = time.perf_counter()
                state = vertex_read(vertex_path)
                replay_times.append((time.perf_counter() - start) * 1000)
                assert "note" in state

        return {
            "engine_summary_ms": round(statistics.median(summary_times), 3),
            "engine_replay_fold_ms": round(statistics.median(replay_times), 3),
        }


def measure_cli_cold_invocation(runs: int = 5) -> dict[str, float]:
    """Measure cold CLI startup & execution latency via subprocess."""
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        res = subprocess.run(
            ["uv", "run", "loops", "--version"],
            capture_output=True,
            text=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        if res.returncode == 0:
            times.append(elapsed_ms)

    median_cli = statistics.median(times) if times else 0.0
    return {
        "cli_cold_version_ms": round(median_cli, 2),
    }


def measure_sdk_operations(n_facts: int = 500) -> dict[str, float]:
    """Measure sdk.emit_fact, sdk.read_facts, and sdk.read_summary apex composition latency."""
    try:
        from sdk import emit_fact, init_vertex, read_facts, read_summary, search_facts
    except ImportError:
        return {}

    with tempfile.TemporaryDirectory() as tmpdir:
        vertex_path = Path(tmpdir) / "bench_sdk.vertex"
        init_vertex(vertex_path, name="bench_sdk", store_type="sqlite")

        # Measure sdk.emit_fact throughput (500 facts)
        start = time.perf_counter()
        for i in range(n_facts):
            emit_fact(
                vertex_path,
                kind_or_fact="note",
                payload={"index": i, "content": f"SDK Fact {i}"},
                observer="bench",
                admit_undeclared=True,
            )
        emit_elapsed = time.perf_counter() - start
        sdk_emit_ms_per_op = (emit_elapsed / n_facts) * 1000
        sdk_emit_ops_sec = n_facts / emit_elapsed if emit_elapsed > 0 else 0

        # Measure sdk.read_summary latency (10 runs)
        summary_times = []
        for _ in range(10):
            t0 = time.perf_counter()
            summary = read_summary(vertex_path)
            summary_times.append((time.perf_counter() - t0) * 1000)
            assert summary.fact_total == n_facts

        # Measure sdk.read_facts pagination latency (10 runs)
        read_times = []
        for _ in range(10):
            t0 = time.perf_counter()
            page = read_facts(vertex_path, limit=100)
            read_times.append((time.perf_counter() - t0) * 1000)
            assert len(page.items) == 100

        # Measure sdk.search_facts latency (10 runs)
        search_times = []
        for _ in range(10):
            t0 = time.perf_counter()
            s_res = search_facts(vertex_path, query="Fact 42")
            search_times.append((time.perf_counter() - t0) * 1000)

        return {
            "sdk_emit_total_ms": round(emit_elapsed * 1000, 2),
            "sdk_emit_ms_per_op": round(sdk_emit_ms_per_op, 4),
            "sdk_emit_ops_per_sec": round(sdk_emit_ops_sec, 1),
            "sdk_summary_ms": round(statistics.median(summary_times), 3),
            "sdk_read_page_100_ms": round(statistics.median(read_times), 3),
            "sdk_search_ms": round(statistics.median(search_times), 3),
        }


def run_all_benchmarks() -> dict[str, Any]:
    """Run all benchmark suites and compile metrics."""
    metrics: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
    }

    print("Running Store Write Benchmark (1,000 facts)...")
    metrics.update(measure_store_write(1000))

    print("Running Store Read Scan Benchmark (1,000 facts)...")
    metrics.update(measure_store_read(1000))

    print("Running Engine Emit Benchmark (500 facts)...")
    metrics.update(measure_engine_emit(500))

    print("Running Engine Summary & Replay Benchmark (500 facts)...")
    metrics.update(measure_engine_summary_and_replay(500))

    print("Running CLI Cold Invocation Benchmark (5 runs)...")
    metrics.update(measure_cli_cold_invocation(5))

    sdk_metrics = measure_sdk_operations(500)
    if sdk_metrics:
        print("Running SDK Apex Composition Benchmarks (500 facts)...")
        metrics.update(sdk_metrics)

    return metrics


def compare_with_baseline(
    current: dict[str, Any], baseline_path: Path, max_regression_pct: float = 10.0
) -> tuple[bool, str]:
    """Compare current benchmark results against baseline JSON."""
    if not baseline_path.exists():
        return True, f"Baseline file not found at {baseline_path} (skipping comparison)"

    with open(baseline_path) as f:
        baseline = json.load(f)

    lines = []
    lines.append("| Metric | Baseline | Current | Delta (%) | Status |")
    lines.append("| :--- | ---: | ---: | ---: | :--- |")

    has_severe_regression = False

    for key, curr_val in current.items():
        if key in ("timestamp", "python_version") or not isinstance(
            curr_val, (int, float)
        ):
            continue

        base_val = baseline.get(key)
        if base_val is None or not isinstance(base_val, (int, float)):
            lines.append(f"| `{key}` | N/A | `{curr_val}` | N/A | NEW |")
            continue

        # Higher is better for ops_per_sec; Lower is better for latency (ms)
        is_throughput = "ops_per_sec" in key
        if base_val == 0:
            pct_delta = 0.0
        else:
            pct_delta = ((curr_val - base_val) / base_val) * 100.0

        if is_throughput:
            # Drop in ops/sec is regression
            is_regression = pct_delta < -max_regression_pct
            status = "🚨 SLOWDOWN" if is_regression else ("⚡ FASTER" if pct_delta > max_regression_pct else "✅ STABLE")
        else:
            # Increase in latency is regression
            is_regression = pct_delta > max_regression_pct
            status = "🚨 SLOWDOWN" if is_regression else ("⚡ FASTER" if pct_delta < -max_regression_pct else "✅ STABLE")

        if is_regression:
            has_severe_regression = True

        lines.append(
            f"| `{key}` | {base_val} | {curr_val} | {pct_delta:+.1f}% | {status} |"
        )

    report = "\n".join(lines)
    return (not has_severe_regression), report


def main() -> None:
    parser = argparse.ArgumentParser(description="Loops Monorepo Benchmark Suite")
    parser.add_argument("--record", type=str, help="Record benchmark results to specified JSON path")
    parser.add_argument("--compare", type=str, help="Compare results against specified baseline JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        help="Max allowed regression percentage before exit code 1 (default: 10%%)",
    )
    args = parser.parse_args()

    results = run_all_benchmarks()

    print("\n=== Benchmark Results ===")
    for k, v in results.items():
        print(f"  {k}: {v}")

    if args.record:
        out_path = Path(args.record)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved benchmark baseline to: {out_path}")

    if args.compare:
        passed, report = compare_with_baseline(
            results, Path(args.compare), max_regression_pct=args.threshold
        )
        print("\n=== Baseline Comparison Report ===")
        print(report)
        if not passed:
            print(f"\n❌ FAILED: Performance regressed by more than {args.threshold}%.")
            sys.exit(1)
        else:
            print(f"\n✅ PASSED: All metrics within {args.threshold}% performance budget.")


if __name__ == "__main__":
    main()
