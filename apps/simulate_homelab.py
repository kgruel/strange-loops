"""Simulated homelab producer: writes fake VM events to JSONL.

Run:
    uv run python apps/simulate_homelab.py                        # all VMs
    uv run python apps/simulate_homelab.py --vms media infra      # specific VMs
    uv run python apps/simulate_homelab.py --output /tmp/homelab  # custom output dir

Generates container health, log, and resource events. Pair with:
    uv run python apps/homelab.py --source <output-dir>

Ctrl-C to stop.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import asyncio
import random
from datetime import datetime, timezone

from rill import FileWriter

from framework import parse_app_spec

SPECS_DIR = Path(__file__).parent.parent / "specs"
APP_SPEC = SPECS_DIR / "homelab.app.kdl"
DEFAULT_OUTPUT = Path("/tmp/homelab")


CONTAINERS = ["nginx", "postgres", "redis", "app", "worker"]
LOG_LEVELS = ["info", "info", "info", "warn", "error", "debug"]
LOG_MESSAGES = [
    "Request processed",
    "Connection established",
    "Health check passed",
    "Slow query detected",
    "Connection timeout",
    "Cache miss",
    "Worker started",
    "Memory usage high",
]


async def simulate_vm(vm_name: str, projection_names: list[str], output: Path) -> None:
    """Produce events for a single VM until cancelled."""
    writers: dict[str, FileWriter] = {}
    for name in projection_names:
        path = output / vm_name / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        writers[name] = FileWriter(path, serialize=lambda e: e)

    try:
        while True:
            container = random.choice(CONTAINERS)
            ts = datetime.now(timezone.utc).isoformat()

            if "vm-health" in writers:
                healthy = random.random() > 0.15
                await writers["vm-health"].consume({
                    "_ts": ts,
                    "container": container,
                    "service": container,
                    "state": "running" if healthy else "restarting",
                    "health": "healthy" if healthy else "unhealthy",
                    "healthy": healthy,
                })

            if "vm-events" in writers:
                await writers["vm-events"].consume({
                    "_ts": ts,
                    "source": random.choice(CONTAINERS),
                    "message": random.choice(LOG_MESSAGES),
                    "level": random.choice(LOG_LEVELS),
                })

            if "vm-resources" in writers:
                await writers["vm-resources"].consume({
                    "_ts": ts,
                    "container": container,
                    "cpu_pct": round(random.uniform(0.0, 85.0), 1),
                    "mem_pct": round(random.uniform(1.0, 60.0), 1),
                    "mem_usage": f"{random.randint(10, 512)}MiB / 2GiB",
                    "net_io": f"{random.randint(1, 500)}kB / {random.randint(1, 200)}kB",
                    "pids": random.randint(1, 30),
                })

            await asyncio.sleep(random.uniform(0.3, 1.5))
    except asyncio.CancelledError:
        pass
    finally:
        for w in writers.values():
            w.close()


async def run(vm_names: list[str], projection_names: list[str], output: Path) -> None:
    print(f"Simulating: {vm_names}")
    print(f"Projections: {projection_names}")
    print(f"Output: {output}")
    print("Ctrl-C to stop\n")

    tasks = [
        asyncio.create_task(simulate_vm(name, projection_names, output))
        for name in vm_names
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="Simulate homelab VM events")
    parser.add_argument("--vms", nargs="*", help="VM names to simulate (default: all)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, metavar="DIR",
                        help=f"Output directory (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()

    app_spec = parse_app_spec(APP_SPEC, specs_dir=SPECS_DIR)
    projection_names = [p.name for p in app_spec.projections]

    if args.vms:
        vm_names = args.vms
    else:
        vm_names = [vm.name for vm in app_spec.vms]

    try:
        asyncio.run(run(vm_names, projection_names, args.output))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
