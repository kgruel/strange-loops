"""Collector registry: maps collector names to implementations.

Collectors are functions that take an SSHSession and return either:
  - list[dict] for poll collectors (mode="collect")
  - AsyncIterator[dict] for stream collectors (mode="stream")

Two paths to registration:
  1. Discovery: scans collectors/ directory for .collector (KDL) and .py files
  2. Manual: hardcoded COLLECTORS dict for built-in collectors

Discovery naming: collectors/docker/containers.collector → docker.containers
Manual naming: uses colon separator → docker:containers

Registry format:
    COLLECTORS = {
        "docker:containers": ("collect", docker.containers),
        "docker:events": ("stream", docker.events),
    }
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Callable

from . import docker
from .discovery import discover_and_register
from .spec import CollectorSpec, parse_collector_spec

if TYPE_CHECKING:
    from ..ssh_session import SSHSession

logger = logging.getLogger(__name__)

# Type aliases
PollCollector = Callable[["SSHSession"], list[dict]]
StreamCollector = Callable[["SSHSession"], AsyncIterator[dict]]

# Built-in collectors (manual registration)
_BUILTIN_COLLECTORS: dict[str, tuple[str, PollCollector | StreamCollector]] = {
    "docker:containers": ("collect", docker.containers),
    "docker:events": ("stream", docker.events),
    "docker:stats": ("collect", docker.stats),
}

# Discovered collectors (populated on first access)
_discovered: dict[str, tuple[str, PollCollector | StreamCollector]] | None = None


def _ensure_discovered() -> dict[str, tuple[str, PollCollector | StreamCollector]]:
    """Lazily discover collectors from collectors/ directory."""
    global _discovered
    if _discovered is None:
        # Look for collectors/ in common locations
        candidates = [
            Path("collectors"),  # Current directory
            Path(__file__).parent.parent.parent / "collectors",  # Project root
        ]
        _discovered = {}
        for base in candidates:
            if base.exists():
                _discovered.update(discover_and_register(base, separator="."))
                logger.debug(f"Discovered {len(_discovered)} collectors from {base}")
                break
    return _discovered


def get_registry() -> dict[str, tuple[str, PollCollector | StreamCollector]]:
    """Get the combined collector registry (built-in + discovered).

    Built-in collectors use colon separator (docker:containers).
    Discovered collectors use dot separator (docker.containers).
    """
    discovered = _ensure_discovered()
    return {**discovered, **_BUILTIN_COLLECTORS}


def get_collector(name: str) -> tuple[str, PollCollector | StreamCollector]:
    """Look up a collector by name. Raises KeyError if not found."""
    registry = get_registry()
    return registry[name]


def reset_discovery() -> None:
    """Reset discovered collectors (for testing)."""
    global _discovered
    _discovered = None


def __getattr__(name: str):
    """Module-level __getattr__ for lazy COLLECTORS access."""
    if name == "COLLECTORS":
        return get_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "COLLECTORS",
    "PollCollector",
    "StreamCollector",
    "CollectorSpec",
    "get_collector",
    "get_registry",
    "parse_collector_spec",
    "reset_discovery",
]
