"""EventProfile and named presets for bench harness parameterization.

Profiles control performance-relevant dimensions of generated data,
independent of the scenario (event shape). This separation lets you
sweep one axis while holding others fixed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EventProfile:
    """Controls performance-relevant dimensions of generated data."""

    num_entities: int = 20  # cardinality (distinct sources/resources/stacks)
    payload_fields: int = 5  # width (for wide scenario: tag/config key count)
    event_count: int = 10_000  # total events to generate
    burst_factor: float = 1.0  # 1.0=uniform, >1=bursty arrival
    child_entities: int = 5  # for nested scenario: services per event
    warmup_iterations: int = 2  # iterations before measurement
    measure_iterations: int = 5  # measurement iterations


PRESETS: dict[str, EventProfile] = {
    "narrow_high_rate": EventProfile(
        num_entities=15,
        event_count=50_000,
        payload_fields=3,
        warmup_iterations=2,
        measure_iterations=5,
    ),
    "wide_medium_rate": EventProfile(
        num_entities=200,
        event_count=10_000,
        payload_fields=25,
        warmup_iterations=2,
        measure_iterations=3,
    ),
    "nested_batch": EventProfile(
        num_entities=25,
        event_count=5_000,
        child_entities=10,
        burst_factor=5.0,
        warmup_iterations=2,
        measure_iterations=3,
    ),
}
