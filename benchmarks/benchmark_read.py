"""Benchmark: loops read project --static --plain

Measures wall-clock latency of the full read path — imports, store access,
replay, fold evaluation, and lens rendering. Five runs, reports median.
"""

import statistics
import subprocess
import time


def measure_read(n: int = 5) -> list[float]:
    """Run `loops read project --static --plain` n times, return ms per run."""
    times = []
    for _ in range(n):
        start = time.perf_counter()
        result = subprocess.run(
            ["uv", "run", "loops", "read", "project", "--static", "--plain"],
            capture_output=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        if result.returncode != 0:
            print(f"ERROR: read failed: {result.stderr.decode()[:200]}")
            continue
        times.append(elapsed_ms)
    return times


def main():
    times = measure_read(5)
    if not times:
        print("read_ms=ERROR")
        return

    median = statistics.median(times)
    best = min(times)
    worst = max(times)
    print(f"read_ms={median:.1f}")
    print(f"best_ms={best:.1f}")
    print(f"worst_ms={worst:.1f}")
    print(f"runs={len(times)}")


if __name__ == "__main__":
    main()
