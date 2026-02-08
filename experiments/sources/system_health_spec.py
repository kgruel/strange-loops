"""System health: spec-driven version.

Separates concerns:
    1. Source — raw data ingress (CommandSource emits lines)
    2. Parser — transforms raw lines into structured payloads
    3. Spec — declarative fold rules over structured payloads
    4. Consumer — queries state, gives meaning

This surfaces the seams that a .loop file format would capture.
"""

import asyncio
from datetime import datetime, timezone
from typing import Callable

from vertex import Vertex
from atoms import CommandSource, Runner
from atoms import Spec, Facet, Fold


# =============================================================================
# PARSERS — Raw line → Structured payload
# =============================================================================
# These are the "missing piece" between Source and Spec.
# Source emits {"line": "..."}, Parser produces {"mount": "/", "capacity": 22}.


def parse_disk(raw: dict) -> dict | None:
    """Parse df -h output line into structured payload.

    Input:  {"line": "/dev/disk1s1   466Gi  123Gi  340Gi    27%   ...   /"}
    Output: {"mount": "/", "capacity": 27, "size": "466Gi", "avail": "340Gi"}
    """
    line = raw.get("line", "")

    # Skip headers and empty
    if line.startswith("Filesystem") or not line.strip():
        return None

    parts = line.split()
    if len(parts) < 9:
        return None

    # Skip virtual filesystems
    mount = parts[8] if len(parts) > 8 else parts[-1]
    if mount.startswith("/System/Volumes") or mount == "/dev":
        return None

    try:
        return {
            "mount": mount,
            "capacity": int(parts[4].rstrip("%")),
            "size": parts[1],
            "avail": parts[3],
        }
    except (ValueError, IndexError):
        return None


def parse_proc(raw: dict) -> dict | None:
    """Parse ps output line into structured payload.

    Input:  {"line": " 12.3  4.5 12345 /usr/bin/python"}
    Output: {"pid": 12345, "cpu": 12.3, "mem": 4.5, "cmd": "python"}
    """
    line = raw.get("line", "")

    # Skip header
    if "CPU" in line and "MEM" in line:
        return None

    parts = line.split(None, 3)
    if len(parts) < 4:
        return None

    try:
        cpu = float(parts[0])
        mem = float(parts[1])

        # Skip idle processes
        if cpu == 0.0 and mem == 0.0:
            return None

        return {
            "pid": int(parts[2]),
            "cpu": cpu,
            "mem": mem,
            "cmd": parts[3].split("/")[-1][:20],
        }
    except (ValueError, IndexError):
        return None


# =============================================================================
# SPECS — Declarative fold rules
# =============================================================================
# Specs describe HOW structured payloads become state.
# They don't know about raw lines — parsers handle that.


disk_spec = Spec(
    name="disk",
    about="Disk usage by mount point",
    input_facets=(
        Facet("mount", "str"),
        Facet("capacity", "int"),
        Facet("size", "str"),
        Facet("avail", "str"),
    ),
    state_facets=(
        Facet("disks", "dict"),  # mount -> {capacity, size, avail}
        Facet("updated", "float"),
    ),
    folds=(
        Fold("upsert", "disks", {"key": "mount"}),
        Fold("latest", "updated"),
    ),
)


proc_spec = Spec(
    name="proc",
    about="Top processes by CPU usage",
    input_facets=(
        Facet("pid", "int"),
        Facet("cpu", "float"),
        Facet("mem", "float"),
        Facet("cmd", "str"),
    ),
    state_facets=(
        Facet("procs", "list"),  # Recent process snapshots
        Facet("updated", "float"),
    ),
    folds=(
        Fold("collect", "procs", {"max": 50}),  # Keep last 50, we'll sort in consumer
        Fold("latest", "updated"),
    ),
)


# =============================================================================
# WIRING — Source + Parser + Spec → Vertex
# =============================================================================
# This is the composition layer. Could be driven by a .loop file.


def register_with_parser(
    vertex: Vertex,
    spec: Spec,
    parser: Callable[[dict], dict | None],
) -> None:
    """Register a spec with a parser that transforms raw payloads.

    The fold function:
    1. Parses raw payload via parser
    2. If parse succeeds, applies spec
    3. If parse fails (returns None), returns state unchanged
    """

    def fold_with_parse(state: dict, payload: dict) -> dict:
        parsed = parser(payload)
        if parsed is None:
            return state
        return spec.apply(state, parsed)

    vertex.register(
        spec.name,
        initial=spec.initial_state(),
        fold=fold_with_parse,
    )


# =============================================================================
# CONSUMER — Queries state, gives meaning
# =============================================================================


def top_procs(state: dict, n: int = 5) -> list[dict]:
    """Extract top N processes by CPU from collected snapshots."""
    # Dedupe by pid, keeping most recent
    by_pid = {}
    for p in state["procs"]:
        by_pid[p["pid"]] = p

    # Sort by CPU descending
    return sorted(by_pid.values(), key=lambda p: p["cpu"], reverse=True)[:n]


async def main():
    vertex = Vertex("system")

    # Wire specs with parsers
    register_with_parser(vertex, disk_spec, parse_disk)
    register_with_parser(vertex, proc_spec, parse_proc)

    # Sources
    disk_source = CommandSource(
        command="df -h",
        kind="disk",
        observer="df",
        interval=5.0,
    )

    proc_source = CommandSource(
        command="ps -eo pcpu,pmem,pid,comm -r | head -20",
        kind="proc",
        observer="ps",
        interval=2.0,
    )

    runner = Runner(vertex)
    runner.add(disk_source)
    runner.add(proc_source)

    print("System Health Monitor (spec-driven)")
    print("=" * 60)
    print()
    print("Structure:")
    print("  Source → raw lines")
    print("  Parser → structured payloads")
    print("  Spec   → declarative folds (upsert, collect, latest)")
    print()
    print(f"Specs registered:")
    print(f"  disk: {disk_spec.about}")
    print(f"    folds: {[f.op for f in disk_spec.folds]}")
    print(f"  proc: {proc_spec.about}")
    print(f"    folds: {[f.op for f in proc_spec.folds]}")
    print()

    # Consumer: health report
    async def health_report():
        threshold = 80

        while True:
            await asyncio.sleep(3.0)

            disk_state = vertex.state("disk")
            proc_state = vertex.state("proc")

            print("-" * 60)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Health Report")
            print()

            # Disk: query upserted dict
            print("DISK (upsert by mount):")
            if disk_state["disks"]:
                for mount, info in sorted(disk_state["disks"].items()):
                    cap = info["capacity"]
                    status = "ALERT!" if cap >= threshold else "ok"
                    bar = "#" * (cap // 5) + "." * (20 - cap // 5)
                    print(f"  {mount:20} [{bar}] {cap:3}% {status}")
            else:
                print("  (no data)")
            print()

            # Procs: query collected list, sort/dedupe
            print("PROCESSES (collect → sort by cpu):")
            top = top_procs(proc_state)
            if top:
                for p in top:
                    print(f"  {p['cmd']:20} CPU:{p['cpu']:5.1f}%  MEM:{p['mem']:5.1f}%")
            else:
                print("  (no data)")
            print()

    report_task = asyncio.create_task(health_report())

    try:
        await asyncio.wait_for(runner.run().__anext__(), timeout=12.0)
    except (asyncio.TimeoutError, StopAsyncIteration):
        pass

    report_task.cancel()

    print("=" * 60)
    print("Final state via Spec:")
    print(f"  disk_spec.state_facets: {[f.name for f in disk_spec.state_facets]}")
    print(f"  proc_spec.state_facets: {[f.name for f in proc_spec.state_facets]}")


if __name__ == "__main__":
    asyncio.run(main())
