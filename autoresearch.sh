#!/bin/bash
set -euo pipefail
uv run --python 3.13 python - <<'PY'
from __future__ import annotations

import io
import os
import shutil
import statistics
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atoms import Fact
from engine import SqliteStore
from loops.main import main

ROOT = Path.cwd()
HOME = ROOT / ".bench_autoresearch" / "home"
VERTEX_DIR = HOME / "bench"
VERTEX_PATH = VERTEX_DIR / "bench.vertex"
DB_PATH = VERTEX_DIR / "data" / "bench.db"


def ensure_benchmark_data() -> None:
    if DB_PATH.exists() and VERTEX_PATH.exists():
        return
    if HOME.exists():
        shutil.rmtree(HOME)
    (VERTEX_DIR / "data").mkdir(parents=True, exist_ok=True)
    VERTEX_PATH.write_text(
        'name "bench"\n'
        'store "./data/bench.db"\n\n'
        'loops {\n'
        '  task {\n'
        '    fold {\n'
        '      items "by" "name"\n'
        '    }\n'
        '  }\n'
        '  decision {\n'
        '    fold {\n'
        '      items "by" "topic"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SqliteStore(path=DB_PATH, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        for i in range(2500):
            ts = base + timedelta(seconds=i)
            store.append(Fact(kind="task", ts=ts, observer="bench", payload={
                "name": f"task-{i % 800}",
                "status": "open" if i % 3 else "completed",
                "summary": f"Task summary {i}",
            }))
        for i in range(1800):
            ts = base + timedelta(seconds=5000 + i)
            store.append(Fact(kind="decision", ts=ts, observer="bench", payload={
                "topic": f"topic/{i % 600}",
                "message": f"Decision message {i}",
            }))


def run_cli(args: list[str]) -> float:
    buf = io.StringIO()
    started = time.perf_counter()
    with redirect_stdout(buf):
        rc = main(args)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if rc != 0:
        sys.stderr.write(buf.getvalue())
        raise SystemExit(rc)
    return elapsed_ms


ensure_benchmark_data()
os.environ["LOOPS_HOME"] = str(HOME)

# Warm imports / SQLite page cache / parser paths.
run_cli(["read", "bench", "--plain"])
run_cli(["read", "bench", "--facts", "--kind", "task", "--plain"])

fold_runs = [run_cli(["read", "bench", "--plain"]) for _ in range(7)]
stream_runs = [run_cli(["read", "bench", "--facts", "--kind", "task", "--plain"]) for _ in range(7)]
fold_ms = statistics.mean(fold_runs)
stream_ms = statistics.mean(stream_runs)
total_ms = fold_ms + stream_ms
print(f"METRIC total_ms={total_ms:.3f}")
print(f"METRIC fold_ms={fold_ms:.3f}")
print(f"METRIC stream_ms={stream_ms:.3f}")
PY
