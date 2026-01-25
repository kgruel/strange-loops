"""Producer: simulates container health events, writes to JSONL.

Run: uv run python apps/producer.py [--path /tmp/events.jsonl]

Writes a container health event every 0.5-2s. Simulates 3 stacks
with occasional unhealthy/error states. Ctrl-C to stop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from rill import FileWriter


@dataclass(frozen=True)
class ContainerEvent:
    ts: float
    stack: str
    container: str
    status: str  # "healthy", "unhealthy", "error"
    message: str = ""


STACKS = {
    "media": ["jellyfin", "radarr", "sonarr", "prowlarr"],
    "infra": ["traefik", "authelia", "loki", "prometheus"],
    "home": ["homeassistant", "mosquitto", "zigbee2mqtt"],
}


def serialize(e: ContainerEvent) -> dict:
    return asdict(e)


async def produce(path: Path) -> None:
    writer: FileWriter[ContainerEvent] = FileWriter(path, serialize)
    print(f"Producing events to: {path}")
    print("Ctrl-C to stop\n")

    try:
        while True:
            stack = random.choice(list(STACKS.keys()))
            container = random.choice(STACKS[stack])

            # 80% healthy, 15% unhealthy, 5% error
            roll = random.random()
            if roll < 0.80:
                status = "healthy"
                message = ""
            elif roll < 0.95:
                status = "unhealthy"
                message = random.choice([
                    "high memory usage",
                    "connection timeout",
                    "health check failed",
                    "slow response",
                ])
            else:
                status = "error"
                message = random.choice([
                    "container restarting",
                    "OOM killed",
                    "port bind failed",
                    "image pull error",
                ])

            event = ContainerEvent(
                ts=time.time(),
                stack=stack,
                container=container,
                status=status,
                message=message,
            )
            await writer.consume(event)

            symbol = {"healthy": ".", "unhealthy": "!", "error": "X"}[status]
            print(symbol, end="", flush=True)

            await asyncio.sleep(random.uniform(0.5, 2.0))
    except asyncio.CancelledError:
        pass
    finally:
        writer.close()
        print("\nDone.")


def main():
    parser = argparse.ArgumentParser(description="Produce simulated container events")
    parser.add_argument("--path", type=Path, default=Path("/tmp/events.jsonl"))
    args = parser.parse_args()

    try:
        asyncio.run(produce(args.path))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
