"""Alerts command — fetch Prometheus alert status via DSL pipeline.

Uses .loop files for SSH transport and DSL-native parse/fold for domain parsing.
Same pipeline as status: .loop → .vertex → fold → tick → lens → render.
"""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from engine import VertexProgram, load_vertex_program

from ..config import resolve_vars
from ..lenses.alerts import AlertsData, FiringAlert, AlertRule, TargetHealth


HERE = Path(__file__).parent.parent
VERTEX_FILE = HERE / "loops/alerts.vertex"


def _load_program(show_targets: bool = False) -> VertexProgram:
    """Load vertex program, optionally excluding targets sources."""
    program = load_vertex_program(VERTEX_FILE, vars=resolve_vars())
    if not show_targets:
        program = VertexProgram(
            vertex=program.vertex,
            sources=[s for s in program.sources if s.kind != "targets"],
            expected_ticks=program.expected_ticks,
        )
    return program


def load(show_targets: bool = False):
    """Load vertex and sources from DSL files.

    Returns:
        tuple of (vertex, sources)
    """
    program = _load_program(show_targets)
    return program.vertex, program.sources


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
        program = _load_program(show_targets=show_targets)
        results = program.collect(rounds=1)

        firing_alerts = [FiringAlert(**a) for a in results.get("alerts", {}).get("firing_alerts", [])]
        raw_rules = results.get("rules", {}).get("alert_rules", [])
        alert_rules = [
            AlertRule(**{**r, "alerts_count": len(r.pop("alerts", []))})
            for r in raw_rules
        ]
        targets = [TargetHealth(**t) for t in results.get("targets", {}).get("targets", [])]

        return AlertsData(
            firing_alerts=firing_alerts,
            alert_rules=alert_rules,
            targets=targets,
            show_targets=show_targets,
        )

    return fetch


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

