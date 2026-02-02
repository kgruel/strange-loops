"""Proof: SSH -> docker compose ps -> parse -> fold -> tick.

Run: uv run python apps/hlab/proof.py
"""

from __future__ import annotations

import asyncio
import json

from data.source import Source
from data.fact import Fact


async def main():
    # Single source: SSH to infra, get container status
    source = Source(
        command='ssh deploy@192.168.1.30 "cd /opt/infra && docker compose ps --format json"',
        kind="container.status",
        observer="infra",
        format="lines",  # docker compose ps outputs one JSON object per line
    )

    # Collect facts, fold to counts
    healthy = 0
    unhealthy = 0
    containers: list[dict] = []

    async for fact in source.stream():
        if fact.kind == "source.error":
            print(f"ERROR: {fact.payload}")
            return

        # Each fact payload has {"line": "..."} from lines format
        # Parse the JSON from the line
        line = fact.payload.get("line", "")
        if not line:
            continue

        try:
            container = json.loads(line)
            containers.append(container)

            # Docker compose ps JSON shape:
            # {"Name": "...", "State": "running", "Health": "healthy", ...}
            state = container.get("State", "")
            health = container.get("Health", "")

            # Count as healthy if running and (healthy or no health check)
            if state == "running" and health in ("healthy", ""):
                healthy += 1
            else:
                unhealthy += 1

        except json.JSONDecodeError as e:
            print(f"Parse error: {e} for line: {line[:50]}")

    # The tick: summary of what we observed
    tick = {
        "host": "infra",
        "healthy": healthy,
        "unhealthy": unhealthy,
        "total": len(containers),
        "containers": [
            {"name": c.get("Name"), "state": c.get("State"), "health": c.get("Health")}
            for c in containers
        ],
    }

    print()
    print("=== TICK ===")
    print(json.dumps(tick, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
