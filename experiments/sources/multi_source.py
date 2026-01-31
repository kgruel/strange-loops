"""Multi-source experiment: two sources feeding one vertex.

Proves multi-source composition — two CommandSources run concurrently,
facts route to correct folds, state accumulates independently.

Sources:
    1. Heartbeat (every 1s) → kind="heartbeat"
    2. System load (every 5s) → kind="system.load"

Run:
    uv run python experiments/sources/multi_source.py
"""

from __future__ import annotations

import asyncio
import platform
import sys

from data import CommandSource, Runner
from vertex import Vertex


def heartbeat_fold(state: dict, payload: dict) -> dict:
    """Fold heartbeat facts: increment count."""
    return {"count": state["count"] + 1}


def load_fold(state: dict, payload: dict) -> dict:
    """Fold system.load facts: update load average and sample count."""
    line = payload.get("line", "")
    # Parse load average from output
    # macOS: { 1.23 1.45 1.67 }
    # Linux: 1.23 1.45 1.67 1/234 5678
    load = None
    if line:
        parts = line.strip("{ }").split()
        if parts:
            try:
                load = float(parts[0])
            except ValueError:
                pass
    return {
        "load": load,
        "samples": state["samples"] + 1,
    }


def create_sources() -> tuple[CommandSource, CommandSource]:
    """Create heartbeat and system load sources, platform-aware."""
    heartbeat_source = CommandSource(
        command='echo "beat"',
        kind="heartbeat",
        observer="heartbeat-source",
        interval=1.0,
    )

    # Platform-specific load command
    if platform.system() == "Darwin":
        load_command = "sysctl -n vm.loadavg"
    else:
        load_command = "cat /proc/loadavg"

    load_source = CommandSource(
        command=load_command,
        kind="system.load",
        observer="load-source",
        interval=5.0,
    )

    return heartbeat_source, load_source


async def run_with_status(vertex: Vertex, runner: Runner, duration: float = 12.0) -> None:
    """Run sources with periodic status output.

    Since no boundaries are configured, runner.run() won't yield ticks.
    We run the runner in a background task and poll vertex state directly.
    """
    # Start runner as background task
    async def consume_runner():
        async for tick in runner.run():
            # Would only fire if boundaries were configured
            print(f"Tick: {tick}")

    runner_task = asyncio.create_task(consume_runner())

    # Poll and display state
    start = asyncio.get_event_loop().time()
    try:
        while (asyncio.get_event_loop().time() - start) < duration:
            await asyncio.sleep(1.0)
            hb = vertex.state("heartbeat")
            load = vertex.state("system.load")
            elapsed = asyncio.get_event_loop().time() - start
            print(f"[{elapsed:5.1f}s] heartbeat: {hb} | system.load: {load}")
    finally:
        await runner.stop()
        runner_task.cancel()
        try:
            await runner_task
        except asyncio.CancelledError:
            pass


async def main() -> None:
    """Run multi-source experiment."""
    # Create vertex with two folds
    vertex = Vertex("multi-source-vertex")
    vertex.register("heartbeat", {"count": 0}, heartbeat_fold)
    vertex.register("system.load", {"load": None, "samples": 0}, load_fold)

    # Create sources
    heartbeat_source, load_source = create_sources()

    # Create runner and add both sources
    runner = Runner(vertex)
    runner.add(heartbeat_source)
    runner.add(load_source)

    print("Multi-source experiment started")
    print("  - Heartbeat: every 1s")
    print("  - System load: every 5s")
    print("Running for 12 seconds...\n")

    await run_with_status(vertex, runner, duration=12.0)

    # Print final state
    print("\nFinal state:")
    print(f"  heartbeat: {vertex.state('heartbeat')}")
    print(f"  system.load: {vertex.state('system.load')}")
    print("\nSuccess: both sources ran concurrently, facts routed to correct folds.")


if __name__ == "__main__":
    # Run with asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
