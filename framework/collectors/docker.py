"""Docker collectors: containers, events, stats.

Each collector takes an SSHSession and returns events as dicts.
Poll collectors return list[dict], stream collectors yield dict.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from ..ssh_session import SSHSession


async def containers(ssh: "SSHSession") -> list[dict]:
    """Poll running containers. Returns one event per container."""
    output = await ssh.run("docker ps --format json")
    events = []
    for line in output.strip().split("\n"):
        if line:
            data = json.loads(line)
            events.append({
                "type": "container",
                "id": data.get("ID", ""),
                "name": data.get("Names", ""),
                "image": data.get("Image", ""),
                "status": data.get("Status", ""),
                "state": data.get("State", ""),
            })
    return events


async def events(ssh: "SSHSession") -> AsyncIterator[dict]:
    """Stream docker events. Yields one event per docker event."""
    async for line in ssh.stream("docker events --format json"):
        if line:
            data = json.loads(line)
            yield {
                "type": "docker_event",
                "action": data.get("Action", ""),
                "actor_id": data.get("Actor", {}).get("ID", ""),
                "actor_name": data.get("Actor", {}).get("Attributes", {}).get("name", ""),
                "time": data.get("time", 0),
            }


async def stats(ssh: "SSHSession") -> list[dict]:
    """Poll container stats. Returns one event per container."""
    output = await ssh.run("docker stats --no-stream --format json")
    events = []
    for line in output.strip().split("\n"):
        if line:
            data = json.loads(line)
            events.append({
                "type": "container_stats",
                "id": data.get("ID", ""),
                "name": data.get("Name", ""),
                "cpu_percent": data.get("CPUPerc", ""),
                "mem_usage": data.get("MemUsage", ""),
                "mem_percent": data.get("MemPerc", ""),
                "net_io": data.get("NetIO", ""),
                "block_io": data.get("BlockIO", ""),
            })
    return events
