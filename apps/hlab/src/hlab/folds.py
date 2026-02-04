"""Fold overrides for hlab — domain computation at fold time.

Each fold override receives (state, payload) where payload is the Fact's
payload dict from the DSL source. For `format: json` sources, the entire
JSON response becomes the payload. For `format: blob` sources, payload
is {"text": "..."}.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Status: health computation
# ---------------------------------------------------------------------------

HEALTH_INITIAL: dict = {"containers": [], "healthy": 0, "total": 0}


def health_fold(state: dict, payload: dict) -> dict:
    """Accumulate containers, compute healthy/total.

    Args:
        state: Current state with containers, healthy, total
        payload: Incoming container dict (Name, State, Health, RunningFor, etc.)

    Returns:
        Updated state with recomputed health metrics
    """
    containers = state.get("containers", []) + [payload]
    containers = containers[-50:]  # cap to match DSL spec

    healthy = sum(
        1 for c in containers
        if c.get("State") == "running"
        and c.get("Health") in ("healthy", "")
    )

    return {
        "containers": containers,
        "healthy": healthy,
        "total": len(containers),
    }


# ---------------------------------------------------------------------------
# Alerts: Prometheus API extraction
# ---------------------------------------------------------------------------

ALERTS_INITIAL: dict[str, Any] = {
    "firing_alerts": [],
    "alert_rules": [],
    "targets": [],
}


def alerts_fold(state: dict, payload: dict) -> dict:
    """Extract firing alerts from Prometheus /api/v1/alerts response.

    Payload is the full JSON response: {"status":"success","data":{"alerts":[...]}}
    """
    if payload.get("status") != "success":
        return state

    alerts = []
    for alert in payload.get("data", {}).get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alerts.append(
            {
                "alertname": labels.get("alertname", "unknown"),
                "state": alert.get("state", "unknown"),
                "severity": labels.get("severity"),
                "instance": labels.get("instance"),
                "summary": annotations.get("summary") or annotations.get("description"),
                "labels": labels,
                "annotations": annotations,
                "active_at": alert.get("activeAt"),
            }
        )

    return {**state, "firing_alerts": alerts}


def rules_fold(state: dict, payload: dict) -> dict:
    """Extract alert rules from Prometheus /api/v1/rules response.

    Payload is the full JSON response: {"status":"success","data":{"groups":[...]}}
    """
    if payload.get("status") != "success":
        return state

    rules = []
    for group in payload.get("data", {}).get("groups", []):
        group_name = group.get("name", "unknown")
        for rule in group.get("rules", []):
            if rule.get("type") != "alerting":
                continue
            rules.append(
                {
                    "name": rule.get("name", "unknown"),
                    "state": rule.get("state", "unknown"),
                    "group": group_name,
                    "health": rule.get("health", "unknown"),
                    "alerts_count": len(rule.get("alerts", [])),
                    "labels": rule.get("labels", {}),
                }
            )

    return {**state, "alert_rules": rules}


def targets_fold(state: dict, payload: dict) -> dict:
    """Extract scrape targets from Prometheus /api/v1/targets response.

    Payload is the full JSON response: {"status":"success","data":{"activeTargets":[...]}}
    """
    if payload.get("status") != "success":
        return state

    targets = []
    for target in payload.get("data", {}).get("activeTargets", []):
        labels = target.get("labels", {})
        targets.append(
            {
                "job": labels.get("job", "unknown"),
                "instance": labels.get("instance", "unknown"),
                "health": target.get("health", "unknown"),
                "scrape_url": target.get("scrapeUrl"),
                "last_error": target.get("lastError") or None,
                "last_scrape": target.get("lastScrape"),
            }
        )

    return {**state, "targets": targets}


# ---------------------------------------------------------------------------
# Media Audit: Radarr API extraction
# ---------------------------------------------------------------------------

MEDIA_AUDIT_INITIAL: dict[str, Any] = {
    "movies": [],
    "quality_defs": [],
}


def movies_fold(state: dict, payload: dict) -> dict:
    """Store raw movie array from Radarr /api/v3/movie response.

    Payload arrives as blob: {"text": "[{movie}, ...]"}
    Radarr returns a JSON array directly, so we parse the text.
    """
    try:
        movies = json.loads(payload.get("text", "[]"))
    except json.JSONDecodeError:
        return state
    return {**state, "movies": movies}


def quality_fold(state: dict, payload: dict) -> dict:
    """Store raw quality definitions from Radarr /api/v3/qualitydefinition.

    Payload arrives as blob: {"text": "[{def}, ...]"}
    Radarr returns a JSON array directly, so we parse the text.
    """
    try:
        defs = json.loads(payload.get("text", "[]"))
    except json.JSONDecodeError:
        return state
    return {**state, "quality_defs": defs}
