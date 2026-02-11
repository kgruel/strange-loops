"""Post-collect enrichment — docker inspect/stats/logs for collected stacks.

Runs after program.collect() to add detail that the DSL pipeline doesn't
capture (container resource usage, error details, recent logs).

NOTE: Payloads from the DSL fold are frozen (mappingproxy). All enrichment
functions receive a mutable deep copy — see _deep_copy_payload().
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..docker_parse import parse_docker_inspect, parse_docker_stats
from ..infra import HostConfig, run_ssh, ssh_base_args
from ..inventory import (
    ANSIBLE_INVENTORY_CACHE,
    host_config_from_inventory,
    load_inventory,
    stack_name_from_metadata,
    DEFAULT_HOSTS_DIR,
)


def _deep_copy_payload(payload: dict) -> dict:
    """Create a mutable deep copy of a DSL payload.

    DSL fold payloads contain mappingproxy dicts and tuples that cannot be
    mutated. This converts everything to plain dicts/lists.
    """
    containers = payload.get("containers", [])
    return {
        **dict(payload),
        "containers": [dict(c) for c in containers],
    }


async def _run_docker_cmd(host: HostConfig, cmd: str, timeout_s: float = 30.0) -> str:
    """Run a docker command on a remote host via SSH."""
    args = ssh_base_args(host)
    args.extend([f"{host.user}@{host.ip}", cmd])
    rc, stdout, stderr = await run_ssh(args, timeout_s=timeout_s)
    if rc != 0:
        return ""
    return stdout


async def enrich_stats(
    stack_name: str,
    payload: dict,
    host: HostConfig,
    stack_dir_name: str | None = None,
) -> dict:
    """Add CPU/memory stats to each container in the payload.

    Runs `docker stats --no-stream --format json` on the host and merges
    results into the container dicts.
    """
    raw = await _run_docker_cmd(host, "docker stats --no-stream --format json")
    if not raw:
        return payload

    stats = parse_docker_stats(raw)
    stats_by_name = {s["name"]: s for s in stats}

    for c in payload.get("containers", []):
        name = c.get("Name", "")
        if name in stats_by_name:
            s = stats_by_name[name]
            c["cpu_percent"] = s["cpu_percent"]
            c["memory_mb"] = s["memory_mb"]
            c["memory_percent"] = s["memory_percent"]

    return payload


async def enrich_unhealthy(
    stack_name: str,
    payload: dict,
    host: HostConfig,
    stack_dir_name: str | None = None,
) -> dict:
    """Add inspect details for unhealthy containers.

    Runs `docker inspect` on containers that are not running/healthy
    and adds exit_code, restart_count, and error to container dicts.
    """
    containers = payload.get("containers", [])
    unhealthy_names = []
    for c in containers:
        state = c.get("State", "")
        health = c.get("Health", "")
        if state != "running" or health == "unhealthy":
            name = c.get("Name", "")
            if name:
                unhealthy_names.append(name)

    if not unhealthy_names:
        return payload

    names_str = " ".join(unhealthy_names)
    raw = await _run_docker_cmd(host, f"docker inspect {names_str}")
    if not raw:
        return payload

    inspected = parse_docker_inspect(raw)
    inspect_by_name = {i["name"]: i for i in inspected}

    for c in containers:
        name = c.get("Name", "")
        if name in inspect_by_name:
            info = inspect_by_name[name]
            c["exit_code"] = info["exit_code"]
            c["restart_count"] = info["restart_count"]
            c["error"] = info["error"]
            c["oom_killed"] = info["oom_killed"]

    return payload


async def enrich_logs(
    stack_name: str,
    payload: dict,
    host: HostConfig,
    stack_dir_name: str | None = None,
    tail: int = 20,
) -> dict:
    """Add recent logs for unhealthy containers.

    Runs `docker logs --tail N` for each unhealthy container.
    """
    for c in payload.get("containers", []):
        state = c.get("State", "")
        health = c.get("Health", "")
        if state != "running" or health == "unhealthy":
            name = c.get("Name", "")
            if name:
                raw = await _run_docker_cmd(
                    host,
                    f"docker logs --tail {tail} {name} 2>&1",
                    timeout_s=10.0,
                )
                if raw:
                    c["recent_logs"] = raw.strip()

    return payload


async def enrich_stack(
    stack_name: str,
    payload: dict,
    *,
    stats: bool = False,
    logs: bool = False,
    inventory_path: Path | None = None,
) -> dict:
    """Enrich a single stack's payload with docker details.

    Deep-copies the payload first (DSL folds produce frozen mappingproxy dicts).
    Always inspects unhealthy containers. Optionally adds stats and logs.
    """
    inv = load_inventory(inventory_path or ANSIBLE_INVENTORY_CACHE)
    host = host_config_from_inventory(inv, stack_name)
    if not host.ip:
        return payload

    # Deep copy so enrichment functions can mutate container dicts
    payload = _deep_copy_payload(payload)

    stack_dir = stack_name_from_metadata(DEFAULT_HOSTS_DIR, stack_name)

    # Always inspect unhealthy
    payload = await enrich_unhealthy(stack_name, payload, host, stack_dir)

    if stats:
        payload = await enrich_stats(stack_name, payload, host, stack_dir)

    if logs:
        payload = await enrich_logs(stack_name, payload, host, stack_dir)

    return payload


def enrich_all(
    stacks: dict[str, dict],
    *,
    stats: bool = False,
    logs: bool = False,
    inventory_path: Path | None = None,
) -> dict[str, dict]:
    """Enrich all stacks synchronously.

    Runs enrichment for each stack concurrently via asyncio.gather.
    """
    async def _run():
        names = list(stacks.keys())
        coros = [
            enrich_stack(
                name, stacks[name],
                stats=stats,
                logs=logs,
                inventory_path=inventory_path,
            )
            for name in names
        ]
        enriched = await asyncio.gather(*coros, return_exceptions=True)
        results = {}
        for name, result in zip(names, enriched):
            if isinstance(result, Exception):
                # On error, return original payload unchanged
                results[name] = stacks[name]
            else:
                results[name] = result
        return results

    return asyncio.run(_run())
