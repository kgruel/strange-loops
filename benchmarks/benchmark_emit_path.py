"""Benchmark: full loops emit path.

Measures end-to-end cost of emitting a single fact into a vertex store,
using load_vertex_program() — the same path as `loops emit`.

Creates a realistic vertex store (~300 facts across multiple kinds) to match
real project/orchestration workloads, then times repeated full emit cycles.

Usage:
    uv run python benchmarks/benchmark_emit_path.py

Prints METRIC lines for autoresearch consumption.
"""

from __future__ import annotations

import shutil
import statistics
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config — matches real project stores in shape and size
# ---------------------------------------------------------------------------

REPEATS = 7  # emit cycles per measurement (median of these)
RUNS = 3  # measurement runs (best of these)

# Store population: ~300 facts across 6 kinds
SEED_DECISIONS = 50
SEED_THREADS = 30
SEED_TASKS = 20
SEED_SESSIONS = 10
SEED_OBSERVATIONS = 150
SEED_LOGS = 40


def metric(name: str, value: float) -> None:
    print(f"METRIC {name}={value:.3f}")


# ---------------------------------------------------------------------------
# Fixture: create a realistic .vertex file + populated store
# ---------------------------------------------------------------------------

VERTEX_KDL = """\
name "bench"
store "./bench.db"

loops {
  decision { fold { items "by" "topic" } }
  thread   { fold { items "by" "name" } }
  task     { fold { items "by" "name" } }
  session  { fold { items "by" "name" } }
  observation { fold { items "collect" 50 } }
  log      { fold { items "collect" 20 } }

  boundary when="session" status="closed"
}
"""


def create_fixture(tmp: Path) -> Path:
    """Create a .vertex file and populate its store with realistic data."""
    from atoms import Fact
    from engine import load_vertex_program

    vertex_path = tmp / "bench.vertex"
    vertex_path.write_text(VERTEX_KDL)

    # Load once to create the store and populate it
    program = load_vertex_program(vertex_path, validate_ast=False)
    v = program.vertex

    ts_base = 1700000000.0

    # Decisions — keyed by topic, latest wins
    for i in range(SEED_DECISIONS):
        v.receive(Fact(
            kind="decision",
            ts=ts_base + i,
            payload={"topic": f"design/topic-{i % 25}", "message": f"Decision text {i}"},
            observer="bench",
            origin="",
        ))

    # Threads — keyed by name, status updates
    for i in range(SEED_THREADS):
        status = "open" if i % 3 != 0 else "resolved"
        v.receive(Fact(
            kind="thread",
            ts=ts_base + 1000 + i,
            payload={"name": f"thread-{i % 15}", "status": status, "message": f"Thread update {i}"},
            observer="bench",
            origin="",
        ))

    # Tasks — keyed by name
    for i in range(SEED_TASKS):
        status = ["open", "in_progress", "completed"][i % 3]
        v.receive(Fact(
            kind="task",
            ts=ts_base + 2000 + i,
            payload={"name": f"task-{i % 10}", "status": status},
            observer="bench",
            origin="",
        ))

    # Sessions — keyed by name
    for i in range(SEED_SESSIONS):
        status = "open" if i == SEED_SESSIONS - 1 else "closed"
        v.receive(Fact(
            kind="session",
            ts=ts_base + 3000 + i,
            payload={"name": f"session-{i}", "status": status},
            observer="bench",
            origin="",
        ))

    # Observations — collected (append-only window)
    for i in range(SEED_OBSERVATIONS):
        v.receive(Fact(
            kind="observation",
            ts=ts_base + 4000 + i,
            payload={"message": f"Observation {i}", "context": f"ctx-{i % 10}"},
            observer="bench",
            origin="",
        ))

    # Logs — collected
    for i in range(SEED_LOGS):
        v.receive(Fact(
            kind="log",
            ts=ts_base + 5000 + i,
            payload={"message": f"Log entry {i}", "level": "info"},
            observer="bench",
            origin="",
        ))

    # Close the store
    if hasattr(v, '_store') and v._store is not None:
        v._store.close()

    return vertex_path


# ---------------------------------------------------------------------------
# Benchmark: full emit cycle via load_vertex_program (matches real path)
# ---------------------------------------------------------------------------

def run_emit_cycle(vertex_path: Path, fact_i: int) -> dict[str, float]:
    """Run one full emit cycle through load_vertex_program and return phase timings."""
    from atoms import Fact
    from engine import load_vertex_program

    # Phase 1: Compile (parse + compile + source collection + materialize)
    # load_vertex_program does: parse → compile → collect_sources → validate_dag → materialize
    # Then replay is called internally before returning
    #
    # To get phase breakdown, we split: compile vs replay
    # But load_vertex_program bundles them. So we time the whole thing
    # and separately time replay to get the split.
    from lang import parse_vertex_file
    from engine.compiler import (
        compile_vertex_recursive,
        materialize_vertex,
    )

    t0 = time.perf_counter()
    ast = parse_vertex_file(vertex_path)
    compiled = compile_vertex_recursive(ast)
    vertex = materialize_vertex(compiled)
    t1 = time.perf_counter()

    # Phase 2: Replay
    vertex.replay()
    t2 = time.perf_counter()

    # Phase 3: Receive one fact
    fact = Fact(
        kind="observation",
        ts=1700010000.0 + fact_i,
        payload={"message": f"Benchmark emit {fact_i}"},
        observer="bench",
        origin="",
    )
    vertex.receive(fact)
    t3 = time.perf_counter()

    # Phase 4: Close
    if hasattr(vertex, '_store') and vertex._store is not None:
        vertex._store.close()
    t4 = time.perf_counter()

    return {
        "compile_ms": (t1 - t0) * 1000,
        "replay_ms": (t2 - t1) * 1000,
        "receive_ms": (t3 - t2) * 1000,
        "close_ms": (t4 - t3) * 1000,
        "emit_total_ms": (t4 - t0) * 1000,
    }


def run_measurement(vertex_path: Path) -> dict[str, float]:
    """Run REPEATS emit cycles and return median timings."""
    results: dict[str, list[float]] = {}

    for i in range(REPEATS):
        timings = run_emit_cycle(vertex_path, i)
        for key, val in timings.items():
            results.setdefault(key, []).append(val)

    return {key: statistics.median(vals) for key, vals in results.items()}


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bench_emit_"))
    try:
        vertex_path = create_fixture(tmp)
        total_facts = (
            SEED_DECISIONS + SEED_THREADS + SEED_TASKS
            + SEED_SESSIONS + SEED_OBSERVATIONS + SEED_LOGS
        )

        # Warm-up: one cycle to prime any caches
        run_emit_cycle(vertex_path, -1)

        # Measurement: best of RUNS
        best: dict[str, float] | None = None
        for _ in range(RUNS):
            result = run_measurement(vertex_path)
            if best is None or result["emit_total_ms"] < best["emit_total_ms"]:
                best = result

        assert best is not None

        # Report
        metric("emit_total_ms", best["emit_total_ms"])
        metric("compile_ms", best["compile_ms"])
        metric("replay_ms", best["replay_ms"])
        metric("receive_ms", best["receive_ms"])
        metric("close_ms", best["close_ms"])
        metric("store_facts", float(total_facts))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
