"""System health: real machine data through the loop.

Purpose: "Is my system healthy?" — disk space + process resources

Flow:
    CommandSource(df) ──→ Fact("disk") ──┐
                                         ├──→ Vertex ──→ Folds ──→ Consumer (health report)
    CommandSource(ps) ──→ Fact("proc") ──┘

This proves:
    - Multiple sources feed one vertex
    - Real machine data (not synthetic)
    - Parsing happens in fold (payload is raw line)
    - Consumer gives meaning: health dashboard
"""

import asyncio
import re
from datetime import datetime, timezone

from engine import Vertex
from atoms import CommandSource, Runner


def now_ts() -> float:
    """Current timestamp."""
    return datetime.now(timezone.utc).timestamp()


def parse_df_line(line: str) -> dict | None:
    """Parse a df output line into structured data.

    Example line: '/dev/disk1s1   466Gi  123Gi  340Gi    27%   12345 4294954940    0%   /'
    """
    # Skip header line
    if line.startswith("Filesystem") or not line.strip():
        return None

    parts = line.split()
    if len(parts) < 9:
        return None

    # macOS df -h format: Filesystem Size Used Avail Capacity iused ifree %iused Mounted
    try:
        return {
            "filesystem": parts[0],
            "size": parts[1],
            "used": parts[2],
            "avail": parts[3],
            "capacity": int(parts[4].rstrip("%")),
            "mount": parts[8] if len(parts) > 8 else parts[-1],
        }
    except (ValueError, IndexError):
        return None


def parse_ps_line(line: str) -> dict | None:
    """Parse a ps output line into structured data.

    Using: ps -eo pcpu,pmem,pid,comm
    Example: ' 12.3  4.5 12345 /usr/bin/python'
    """
    # Skip header
    if "CPU" in line and "MEM" in line:
        return None

    parts = line.split(None, 3)  # Split into 4 parts max
    if len(parts) < 4:
        return None

    try:
        cpu = float(parts[0])
        mem = float(parts[1])
        pid = int(parts[2])
        cmd = parts[3] if len(parts) > 3 else "unknown"

        # Skip idle processes
        if cpu == 0.0 and mem == 0.0:
            return None

        return {
            "cpu": cpu,
            "mem": mem,
            "pid": pid,
            "cmd": cmd.split("/")[-1][:20],  # Short command name
        }
    except (ValueError, IndexError):
        return None


async def main():
    vertex = Vertex("system")

    # Disk fold: track capacity per mount point
    def fold_disk(state: dict, payload: dict) -> dict:
        parsed = parse_df_line(payload["line"])
        if parsed is None:
            return state

        disks = dict(state["disks"])
        disks[parsed["mount"]] = {
            "capacity": parsed["capacity"],
            "size": parsed["size"],
            "avail": parsed["avail"],
        }
        return {
            "disks": disks,
            "updated": now_ts(),
        }

    vertex.register(
        "disk",
        initial={"disks": {}, "updated": None},
        fold=fold_disk,
    )

    # Process fold: track top processes by CPU
    def fold_proc(state: dict, payload: dict) -> dict:
        parsed = parse_ps_line(payload["line"])
        if parsed is None:
            return state

        procs = list(state["procs"])

        # Add or update process
        existing = next((p for p in procs if p["pid"] == parsed["pid"]), None)
        if existing:
            procs.remove(existing)
        procs.append(parsed)

        # Keep top 10 by CPU
        procs.sort(key=lambda p: p["cpu"], reverse=True)
        procs = procs[:10]

        return {
            "procs": procs,
            "updated": now_ts(),
        }

    vertex.register(
        "proc",
        initial={"procs": [], "updated": None},
        fold=fold_proc,
    )

    # Sources: real machine data
    disk_source = CommandSource(
        command="df -h",
        kind="disk",
        observer="df",
        interval=5.0,  # Check disk every 5s
    )

    proc_source = CommandSource(
        command="ps -eo pcpu,pmem,pid,comm -r | head -20",  # Top 20 by CPU
        kind="proc",
        observer="ps",
        interval=2.0,  # Check processes every 2s
    )

    runner = Runner(vertex)
    runner.add(disk_source)
    runner.add(proc_source)

    print("System Health Monitor")
    print("=" * 60)
    print("Sources: df (5s interval), ps (2s interval)")
    print("Consumer: health report every 3s")
    print()

    # Consumer: periodic health report
    async def health_report():
        disk_threshold = 80  # Alert above 80%

        while True:
            await asyncio.sleep(3.0)

            disk_state = vertex.state("disk")
            proc_state = vertex.state("proc")

            print("-" * 60)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Health Report")
            print()

            # Disk health
            print("DISK USAGE:")
            if disk_state["disks"]:
                for mount, info in sorted(disk_state["disks"].items()):
                    cap = info["capacity"]
                    status = "ALERT!" if cap >= disk_threshold else "ok"
                    bar = "#" * (cap // 5) + "." * (20 - cap // 5)
                    print(f"  {mount:20} [{bar}] {cap:3}% {status}")
            else:
                print("  (no data yet)")
            print()

            # Process health
            print("TOP PROCESSES (by CPU):")
            if proc_state["procs"]:
                for p in proc_state["procs"][:5]:
                    print(f"  {p['cmd']:20} CPU:{p['cpu']:5.1f}%  MEM:{p['mem']:5.1f}%")
            else:
                print("  (no data yet)")
            print()

    report_task = asyncio.create_task(health_report())

    try:
        # Run for 15 seconds
        await asyncio.wait_for(runner.run().__anext__(), timeout=15.0)
    except (asyncio.TimeoutError, StopAsyncIteration):
        pass

    report_task.cancel()

    print("=" * 60)
    print("Final state:")
    print(f"  Disks tracked: {list(vertex.state('disk')['disks'].keys())}")
    print(f"  Processes tracked: {len(vertex.state('proc')['procs'])}")


if __name__ == "__main__":
    asyncio.run(main())
