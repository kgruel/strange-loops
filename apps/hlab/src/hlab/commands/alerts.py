"""Alerts command — fetch Prometheus alert status.

Fetches alerts from Prometheus running on the infra host via SSH.
Pure data fetch, no rendering knowledge.
"""

from __future__ import annotations

import asyncio
import json
import re
from argparse import ArgumentParser
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..infra import HostConfig, run_ssh, ssh_base_args
from ..inventory import load_inventory, host_config_from_inventory, ANSIBLE_INVENTORY_CACHE
from ..lenses.alerts import AlertsData, FiringAlert, AlertRule, TargetHealth


def _parse_duration(duration: str) -> int:
    """Parse duration string like '4h', '30m', '1d' to seconds."""
    match = re.match(r"^(\d+)([smhd])$", duration.lower())
    if not match:
        raise ValueError(f"Invalid duration format: {duration!r} (use e.g. '4h', '30m', '1d')")
    value, unit = int(match.group(1)), match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers[unit]


async def _fetch_prometheus_api(
    host: HostConfig,
    endpoint: str,
    *,
    connect_timeout_s: float = 5.0,
    cmd_timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Fetch from Prometheus API via SSH + docker exec."""
    ssh_args = ssh_base_args(host, connect_timeout_s=connect_timeout_s)
    remote = f"docker exec prometheus wget -qO- 'http://localhost:9090{endpoint}'"
    cmd = [*ssh_args, f"{host.user}@{host.ip}", remote]

    rc, stdout, stderr = await run_ssh(cmd, timeout_s=cmd_timeout_s)
    if rc != 0:
        return {"status": "error", "error": (stderr or stdout or f"exit {rc}").strip()}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        return {"status": "error", "error": f"JSON decode error: {e}"}


def _parse_alerts_response(data: dict[str, Any]) -> list[FiringAlert]:
    """Parse /api/v1/alerts response."""
    alerts: list[FiringAlert] = []
    if data.get("status") != "success":
        return alerts

    for alert in data.get("data", {}).get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alerts.append(
            FiringAlert(
                alertname=labels.get("alertname", "unknown"),
                state=alert.get("state", "unknown"),
                severity=labels.get("severity"),
                instance=labels.get("instance"),
                summary=annotations.get("summary") or annotations.get("description"),
                labels=labels,
                annotations=annotations,
                active_at=alert.get("activeAt"),
            )
        )
    return alerts


def _parse_rules_response(data: dict[str, Any]) -> list[AlertRule]:
    """Parse /api/v1/rules?type=alert response."""
    rules: list[AlertRule] = []
    if data.get("status") != "success":
        return rules

    for group in data.get("data", {}).get("groups", []):
        group_name = group.get("name", "unknown")
        for rule in group.get("rules", []):
            if rule.get("type") != "alerting":
                continue
            rules.append(
                AlertRule(
                    name=rule.get("name", "unknown"),
                    state=rule.get("state", "unknown"),
                    group=group_name,
                    health=rule.get("health", "unknown"),
                    alerts_count=len(rule.get("alerts", [])),
                    labels=rule.get("labels", {}),
                )
            )
    return rules


def _parse_targets_response(data: dict[str, Any]) -> list[TargetHealth]:
    """Parse /api/v1/targets response."""
    targets: list[TargetHealth] = []
    if data.get("status") != "success":
        return targets

    for target in data.get("data", {}).get("activeTargets", []):
        labels = target.get("labels", {})
        targets.append(
            TargetHealth(
                job=labels.get("job", "unknown"),
                instance=labels.get("instance", "unknown"),
                health=target.get("health", "unknown"),
                scrape_url=target.get("scrapeUrl"),
                last_error=target.get("lastError") or None,
                last_scrape=target.get("lastScrape"),
            )
        )
    return targets


def add_args(parser: ArgumentParser) -> None:
    """Add alerts-specific arguments."""
    parser.add_argument(
        "--targets",
        action="store_true",
        help="Include Prometheus target health (scrape status)",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=None,
        help="Override inventory.yml path",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=5.0,
        help="SSH connection timeout (seconds)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Command timeout (seconds)",
    )


def make_fetcher(args) -> Callable[[], AlertsData]:
    """Create a zero-arg fetcher from parsed CLI args."""
    show_targets = getattr(args, "targets", False)
    inventory = getattr(args, "inventory", None)
    connect_timeout = getattr(args, "connect_timeout", 5.0)
    timeout = getattr(args, "timeout", 30.0)

    def fetch() -> AlertsData:
        return asyncio.run(_fetch_alerts(
            show_targets=show_targets,
            inventory_path=inventory,
            connect_timeout=connect_timeout,
            cmd_timeout=timeout,
        ))

    return fetch


async def _fetch_alerts(
    *,
    show_targets: bool = False,
    inventory_path: Path | None = None,
    connect_timeout: float = 5.0,
    cmd_timeout: float = 30.0,
) -> AlertsData:
    """Fetch alert data from Prometheus."""
    path = inventory_path or ANSIBLE_INVENTORY_CACHE
    inv = load_inventory(path)

    host = host_config_from_inventory(inv, "infra")
    if host.ip is None:
        return AlertsData()

    tasks = [
        _fetch_prometheus_api(host, "/api/v1/alerts", connect_timeout_s=connect_timeout, cmd_timeout_s=cmd_timeout),
        _fetch_prometheus_api(host, "/api/v1/rules?type=alert", connect_timeout_s=connect_timeout, cmd_timeout_s=cmd_timeout),
    ]

    if show_targets:
        tasks.append(
            _fetch_prometheus_api(host, "/api/v1/targets", connect_timeout_s=connect_timeout, cmd_timeout_s=cmd_timeout)
        )

    results = await asyncio.gather(*tasks)
    alerts_data, rules_data = results[0], results[1]
    targets_data = results[2] if show_targets else None

    firing_alerts = _parse_alerts_response(alerts_data)
    alert_rules = _parse_rules_response(rules_data)
    targets = _parse_targets_response(targets_data) if targets_data else []

    return AlertsData(
        firing_alerts=firing_alerts,
        alert_rules=alert_rules,
        targets=targets,
        show_targets=show_targets,
    )


def to_json(data: AlertsData) -> dict[str, Any]:
    """Convert AlertsData to JSON-serializable dict."""
    return {
        "firing_alerts": [asdict(a) for a in data.firing_alerts],
        "alert_rules": [asdict(r) for r in data.alert_rules],
        "targets": [asdict(t) for t in data.targets] if data.show_targets else [],
        "counts": {
            "firing": len(data.firing_alerts),
            "rules": len(data.alert_rules),
            "targets_down": sum(1 for t in data.targets if t.health == "down"),
        },
    }
