"""Collector registry: maps collector names to implementations.

Collectors are functions that take an SSHSession and return either:
  - list[dict] for poll collectors (mode="collect")
  - AsyncIterator[dict] for stream collectors (mode="stream")

Registry format:
    COLLECTORS = {
        "docker:containers": ("collect", docker.containers),
        "docker:events": ("stream", docker.events),
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Callable

from . import docker

if TYPE_CHECKING:
    from ..ssh_session import SSHSession

# Type aliases
PollCollector = Callable[["SSHSession"], list[dict]]
StreamCollector = Callable[["SSHSession"], AsyncIterator[dict]]

# Registry: name -> (mode, function)
COLLECTORS: dict[str, tuple[str, PollCollector | StreamCollector]] = {
    "docker:containers": ("collect", docker.containers),
    "docker:events": ("stream", docker.events),
    "docker:stats": ("collect", docker.stats),
}


def get_collector(name: str) -> tuple[str, PollCollector | StreamCollector]:
    """Look up a collector by name. Raises KeyError if not found."""
    return COLLECTORS[name]
