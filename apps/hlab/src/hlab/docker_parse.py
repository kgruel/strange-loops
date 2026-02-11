"""Docker output parsing — pure functions for docker CLI JSON output.

Parses JSON output from docker inspect, docker stats, and docker compose logs.
"""

from __future__ import annotations

import json


def parse_docker_inspect(raw: str) -> list[dict]:
    """Parse docker inspect JSON output.

    Returns list of dicts with:
        name, exit_code, restart_count, error, started_at, finished_at
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, list):
        data = [data]

    results = []
    for container in data:
        state = container.get("State", {})
        name = container.get("Name", "").lstrip("/")
        results.append({
            "name": name,
            "exit_code": state.get("ExitCode", 0),
            "restart_count": container.get("RestartCount", 0),
            "error": state.get("Error", ""),
            "started_at": state.get("StartedAt", ""),
            "finished_at": state.get("FinishedAt", ""),
            "oom_killed": state.get("OOMKilled", False),
        })
    return results


def parse_docker_stats(raw: str) -> list[dict]:
    """Parse docker stats --no-stream --format json output.

    Returns list of dicts with:
        name, cpu_percent, memory_mb, memory_percent
    """
    results = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        cpu_str = data.get("CPUPerc", "0%").rstrip("%")
        mem_str = data.get("MemPerc", "0%").rstrip("%")

        try:
            cpu_pct = float(cpu_str)
        except ValueError:
            cpu_pct = 0.0

        try:
            mem_pct = float(mem_str)
        except ValueError:
            mem_pct = 0.0

        # Parse memory usage (e.g., "123.4MiB / 1GiB")
        mem_usage = data.get("MemUsage", "")
        mem_mb = _parse_mem_to_mb(mem_usage.split("/")[0].strip()) if "/" in mem_usage else 0.0

        results.append({
            "name": data.get("Name", ""),
            "cpu_percent": cpu_pct,
            "memory_mb": mem_mb,
            "memory_percent": mem_pct,
        })
    return results


def _parse_mem_to_mb(s: str) -> float:
    """Parse memory string like '123.4MiB' or '1.2GiB' to MB."""
    s = s.strip()
    try:
        if s.endswith("GiB"):
            return float(s[:-3]) * 1024
        if s.endswith("MiB"):
            return float(s[:-3])
        if s.endswith("KiB"):
            return float(s[:-3]) / 1024
        if s.endswith("B"):
            return float(s[:-1]) / (1024 * 1024)
    except ValueError:
        pass
    return 0.0
