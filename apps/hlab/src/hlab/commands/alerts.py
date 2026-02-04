"""Alerts command — fetch Prometheus alert status via DSL pipeline.

Uses .loop files for SSH transport and fold overrides for domain parsing.
Same pipeline as status: .loop → .vertex → fold → tick → lens → render.
"""

from __future__ import annotations

import asyncio
from argparse import ArgumentParser
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dsl import load_vertex_program
from data import Runner

from ..folds import ALERTS_INITIAL, alerts_fold, rules_fold, targets_fold
from ..lenses.alerts import AlertsData, FiringAlert, AlertRule, TargetHealth


HERE = Path(__file__).parent.parent
VERTEX_FILE = HERE / "loops/alerts.vertex"


def load(show_targets: bool = False):
    """Load vertex and sources from DSL files.

    Returns:
        tuple of (vertex, sources)
    """
    fold_overrides = {
        "alerts": (ALERTS_INITIAL, alerts_fold),
        "rules": (ALERTS_INITIAL, rules_fold),
    }
    if show_targets:
        fold_overrides["targets"] = (ALERTS_INITIAL, targets_fold)

    program = load_vertex_program(VERTEX_FILE, fold_overrides=fold_overrides)
    sources = program.sources
    if not show_targets:
        sources = [s for s in sources if s.kind != "targets"]

    return program.vertex, sources


def add_args(parser: ArgumentParser) -> None:
    """Add alerts-specific arguments."""
    parser.add_argument(
        "--targets",
        action="store_true",
        help="Include Prometheus target health (scrape status)",
    )


def make_fetcher(args) -> Callable[[], AlertsData]:
    """Create a zero-arg fetcher from parsed CLI args."""
    show_targets = getattr(args, "targets", False)

    def fetch() -> AlertsData:
        return asyncio.run(_fetch_alerts(show_targets=show_targets))

    return fetch


async def _fetch_alerts(*, show_targets: bool = False) -> AlertsData:
    """Fetch alert data from Prometheus via DSL pipeline."""
    vertex, sources = load(show_targets=show_targets)
    runner = Runner(vertex)
    for s in sources:
        runner.add(s)

    firing_alerts: list[FiringAlert] = []
    alert_rules: list[AlertRule] = []
    targets: list[TargetHealth] = []

    async for tick in runner.run():
        payload = tick.payload
        if tick.name == "alerts":
            firing_alerts = [FiringAlert(**a) for a in payload.get("firing_alerts", [])]
        elif tick.name == "rules":
            alert_rules = [AlertRule(**r) for r in payload.get("alert_rules", [])]
        elif tick.name == "targets":
            targets = [TargetHealth(**t) for t in payload.get("targets", [])]

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

