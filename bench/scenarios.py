"""Typed event dataclasses and Polyfactory factories for bench scenarios.

Three scenario profiles covering orthogonal performance axes:
- Narrow + high rate: log stream pattern (throughput, memory growth)
- Wide + medium rate: alert/resource pattern (payload size, dict scanning)
- Nested + batch: stack health pattern (entity grouping, child expansion)
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from polyfactory.factories.dataclass_factory import DataclassFactory


# =============================================================================
# NARROW + HIGH RATE (log stream pattern)
# =============================================================================


@dataclass(frozen=True)
class NarrowEvent:
    """Log stream event: small payload, high throughput."""

    source: str
    level: Literal["debug", "info", "warn", "error"]
    message: str
    ts: float = field(default_factory=time.time)


class NarrowEventFactory(DataclassFactory[NarrowEvent]):
    __model__ = NarrowEvent

    @classmethod
    def source(cls) -> str:
        sources = [f"svc-{i}" for i in range(20)]
        return random.choice(sources)

    @classmethod
    def level(cls) -> Literal["debug", "info", "warn", "error"]:
        return random.choices(
            ["debug", "info", "warn", "error"],
            weights=[10, 60, 20, 10],
        )[0]

    @classmethod
    def message(cls) -> str:
        templates = [
            "Request processed",
            "Connection established to upstream",
            "Cache miss for key",
            "Timeout waiting for response from peer",
            "Health check passed",
            "Retrying operation attempt",
            "Queue depth threshold exceeded",
            "Configuration reloaded successfully",
        ]
        base = random.choice(templates)
        # Variable length: 20-120 chars
        padding = "x" * random.randint(0, 80)
        return f"{base} {padding}".strip()

    @classmethod
    def ts(cls) -> float:
        return time.time()


# =============================================================================
# WIDE + MEDIUM RATE (alert/resource pattern)
# =============================================================================


@dataclass(frozen=True)
class WideEvent:
    """Resource event: wide payload, dict-heavy."""

    resource_id: str
    resource_type: Literal["vm", "container", "function", "database", "cache"]
    region: str
    status: Literal["healthy", "degraded", "critical", "unknown"]
    tags: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class WideEventFactory(DataclassFactory[WideEvent]):
    __model__ = WideEvent

    @classmethod
    def resource_id(cls) -> str:
        return f"res-{random.randint(0, 999):04d}"

    @classmethod
    def resource_type(cls) -> Literal["vm", "container", "function", "database", "cache"]:
        return random.choice(["vm", "container", "function", "database", "cache"])

    @classmethod
    def region(cls) -> str:
        return random.choice([
            "us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1",
            "eu-central-1", "ap-northeast-1",
        ])

    @classmethod
    def status(cls) -> Literal["healthy", "degraded", "critical", "unknown"]:
        return random.choices(
            ["healthy", "degraded", "critical", "unknown"],
            weights=[70, 15, 10, 5],
        )[0]

    @classmethod
    def tags(cls) -> dict[str, str]:
        num_tags = random.randint(3, 30)
        return {f"tag-{i}": f"value-{random.randint(0, 100)}" for i in range(num_tags)}

    @classmethod
    def config(cls) -> dict[str, Any]:
        num_keys = random.randint(5, 50)
        config: dict[str, Any] = {}
        for i in range(num_keys):
            kind = random.choice(["str", "int", "bool", "list"])
            if kind == "str":
                config[f"cfg-{i}"] = f"val-{random.randint(0, 1000)}"
            elif kind == "int":
                config[f"cfg-{i}"] = random.randint(0, 10000)
            elif kind == "bool":
                config[f"cfg-{i}"] = random.choice([True, False])
            else:
                config[f"cfg-{i}"] = [random.randint(0, 10) for _ in range(3)]
        return config

    @classmethod
    def metrics(cls) -> dict[str, float]:
        metric_names = ["cpu", "mem", "disk", "net_in", "net_out", "latency_p50",
                        "latency_p99", "error_rate", "throughput", "connections"]
        num_metrics = random.randint(3, len(metric_names))
        chosen = random.sample(metric_names, num_metrics)
        return {name: round(random.uniform(0, 100), 2) for name in chosen}

    @classmethod
    def ts(cls) -> float:
        return time.time()


# =============================================================================
# NESTED + BATCH (stack health pattern)
# =============================================================================


@dataclass(frozen=True)
class NestedEvent:
    """Stack health event: nested child entities, burst arrival."""

    stack: str
    host: str
    status: Literal["healthy", "warning", "critical"]
    services: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ts: float = field(default_factory=time.time)


class NestedEventFactory(DataclassFactory[NestedEvent]):
    __model__ = NestedEvent

    @classmethod
    def stack(cls) -> str:
        return random.choice([f"stack-{i}" for i in range(10)])

    @classmethod
    def host(cls) -> str:
        return f"host-{random.randint(0, 99):03d}"

    @classmethod
    def status(cls) -> Literal["healthy", "warning", "critical"]:
        return random.choices(
            ["healthy", "warning", "critical"],
            weights=[60, 25, 15],
        )[0]

    @classmethod
    def services(cls) -> tuple[dict[str, Any], ...]:
        num_services = random.randint(3, 15)
        svcs = []
        for i in range(num_services):
            svc: dict[str, Any] = {
                "name": f"svc-{i}",
                "status": random.choice(["running", "stopped", "crashed"]),
                "pid": random.randint(1000, 65000),
                "cpu": round(random.uniform(0, 100), 1),
                "mem_mb": round(random.uniform(10, 2048), 1),
                "uptime_sec": random.randint(0, 86400),
            }
            # Some services have extra metadata
            if random.random() > 0.5:
                svc["ports"] = [random.randint(1024, 65535) for _ in range(random.randint(1, 4))]
                svc["dependencies"] = [f"svc-{random.randint(0, num_services-1)}" for _ in range(random.randint(0, 3))]
            svcs.append(svc)
        return tuple(svcs)

    @classmethod
    def ts(cls) -> float:
        return time.time()


# =============================================================================
# SCENARIO REGISTRY
# =============================================================================

SCENARIOS = {
    "narrow": {"event_class": NarrowEvent, "factory": NarrowEventFactory},
    "wide": {"event_class": WideEvent, "factory": WideEventFactory},
    "nested": {"event_class": NestedEvent, "factory": NestedEventFactory},
}
