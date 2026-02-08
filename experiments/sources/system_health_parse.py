"""System health experiment: parse-enabled sources producing structured facts.

Proves parse integration with CommandSource. Real system commands (df, ps)
are parsed declaratively — no wiring layer code, just pipeline composition.

Sources:
    1. Disk usage (df -h) → kind="disk" with structured payload
    2. Top processes (ps) → kind="process" with structured payload

The key insight: Source takes responsibility for structured data.
Spec stays focused on folding. Clean separation.

Run:
    uv run python experiments/sources/system_health_parse.py
"""

from __future__ import annotations

import asyncio
import platform
import sys

from atoms import CommandSource, Runner
from atoms import Coerce, Pick, Rename, Skip, Split, Transform
from vertex import Vertex


# Parse pipelines — declarative transformation from raw text to structured dict
DISK_PARSE = [
    Skip(startswith="Filesystem"),  # Skip header
    Skip(contains="/System/Volumes"),  # Skip macOS system volumes
    Split(),
    Pick(0, 1, 4, 8),  # fs, size, pct, mount
    Rename({0: "fs", 1: "size", 2: "pct", 3: "mount"}),
    Transform("pct", strip="%"),
    Coerce({"pct": int}),
]

PS_PARSE = [
    Skip(startswith="UID"),  # Skip header
    Split(),
    Pick(0, 1, 2, 3),  # uid, pid, cpu, mem
    Rename({0: "uid", 1: "pid", 2: "cpu", 3: "mem"}),
    Coerce({"uid": int, "pid": int, "cpu": float, "mem": float}),
    Skip(predicate=lambda x: x.get("cpu", 0) == 0),  # Skip idle processes
]


def disk_fold(state: dict, payload: dict) -> dict:
    """Fold disk facts: track per-mount usage."""
    disks = dict(state.get("disks", {}))
    mount = payload.get("mount", "unknown")
    disks[mount] = {
        "fs": payload.get("fs"),
        "size": payload.get("size"),
        "pct": payload.get("pct"),
    }
    return {"disks": disks, "count": state.get("count", 0) + 1}


def process_fold(state: dict, payload: dict) -> dict:
    """Fold process facts: track top CPU consumers."""
    top = list(state.get("top", []))
    entry = {
        "pid": payload.get("pid"),
        "cpu": payload.get("cpu"),
        "mem": payload.get("mem"),
    }
    # Keep top 5 by CPU
    top.append(entry)
    top.sort(key=lambda x: x.get("cpu", 0), reverse=True)
    top = top[:5]
    return {"top": top, "samples": state.get("samples", 0) + 1}


def create_sources() -> tuple[CommandSource, CommandSource]:
    """Create disk and process sources with parse pipelines."""
    disk_source = CommandSource(
        command="df -h",
        kind="disk",
        observer="df-source",
        interval=5.0,
        parse=DISK_PARSE,
    )

    # Platform-specific ps command
    if platform.system() == "Darwin":
        ps_command = "ps -A -o uid,pid,%cpu,%mem"
    else:
        ps_command = "ps -eo uid,pid,%cpu,%mem"

    process_source = CommandSource(
        command=ps_command,
        kind="process",
        observer="ps-source",
        interval=3.0,
        parse=PS_PARSE,
    )

    return disk_source, process_source


async def run_with_status(vertex: Vertex, runner: Runner, duration: float = 15.0) -> None:
    """Run sources with periodic status output."""

    async def consume_runner():
        async for tick in runner.run():
            print(f"Tick: {tick}")

    runner_task = asyncio.create_task(consume_runner())

    start = asyncio.get_event_loop().time()
    try:
        while (asyncio.get_event_loop().time() - start) < duration:
            await asyncio.sleep(2.0)
            disk = vertex.state("disk")
            proc = vertex.state("process")
            elapsed = asyncio.get_event_loop().time() - start
            print(f"\n[{elapsed:5.1f}s] State snapshot:")
            print(f"  disk samples: {disk.get('count', 0)}")
            if disk.get("disks"):
                for mount, info in disk["disks"].items():
                    print(f"    {mount}: {info['pct']}% used ({info['size']})")
            print(f"  process samples: {proc.get('samples', 0)}")
            if proc.get("top"):
                print("  top processes by CPU:")
                for p in proc["top"][:3]:
                    print(f"    pid={p['pid']} cpu={p['cpu']:.1f}% mem={p['mem']:.1f}%")
    finally:
        await runner.stop()
        runner_task.cancel()
        try:
            await runner_task
        except asyncio.CancelledError:
            pass


async def main() -> None:
    """Run system health experiment with parse-enabled sources."""
    # Create vertex
    vertex = Vertex("system-health")
    vertex.register("disk", {"disks": {}, "count": 0}, disk_fold)
    vertex.register("process", {"top": [], "samples": 0}, process_fold)

    # Create sources with parse pipelines
    disk_source, process_source = create_sources()

    # Create runner
    runner = Runner(vertex)
    runner.add(disk_source)
    runner.add(process_source)

    print("System health experiment (parse-enabled sources)")
    print("=" * 50)
    print("Proves: Source produces structured data via parse pipeline")
    print("  - df output → disk facts with {fs, size, pct, mount}")
    print("  - ps output → process facts with {pid, cpu, mem}")
    print("  - Skip filters headers and idle processes")
    print("  - Transform strips %, Coerce converts to int/float")
    print("=" * 50)
    print(f"\nRunning for 15 seconds...\n")

    await run_with_status(vertex, runner, duration=15.0)

    # Print final state
    disk = vertex.state("disk")
    proc = vertex.state("process")
    print("\n" + "=" * 50)
    print("Final state:")
    print(f"  disk: {disk.get('count', 0)} samples, {len(disk.get('disks', {}))} mounts")
    print(f"  process: {proc.get('samples', 0)} samples, tracking top 5")
    print("\nKey insight: No wiring-layer parse code.")
    print("Parse pipeline is declarative, attached to Source.")
    print("Fact payloads arrive structured. Fold just accumulates.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
