"""Homelab event infrastructure.

Core primitives (Stream, Projection, EventStore, etc.) live in rill package.
This layer adds:
  - KDL spec parsing (ProjectionSpec, AppSpec)
  - SSH collection (SSHSession, SSHConnectionManager)
  - Docker collectors
  - Orchestration
"""

from .sim import BaseSimulator, SimState
from .instrument import metrics
from .spec import ProjectionSpec, SpecProjection, ValidationError, parse_projection_spec
from .app_spec import AppSpec, VMInfo, parse_app_spec
from .ssh import SSHConnectionManager
from .watcher import SpecWatcher

__all__ = [
    "BaseSimulator",
    "SimState",
    "metrics",
    "ProjectionSpec",
    "SpecProjection",
    "ValidationError",
    "parse_projection_spec",
    "AppSpec",
    "VMInfo",
    "parse_app_spec",
    "SSHConnectionManager",
    "SpecWatcher",
]
