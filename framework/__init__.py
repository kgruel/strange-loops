"""Homelab event infrastructure.

Core primitives (Stream, Projection, EventStore, etc.) live in rill package.
This layer adds:
  - KDL spec parsing (ProjectionSpec, AppSpec)
  - SSH collection (SSHSession, SSHConnectionManager)
  - Docker collectors
  - Orchestration
"""

# Re-export rill primitives for convenience
from rill import Stream, Tap, Consumer, EventStore, Projection, FileWriter, Tailer, Forward
from .sim import BaseSimulator, SimState
from .instrument import metrics
from .spec import ProjectionSpec, SpecProjection, parse_projection_spec
from .app_spec import AppSpec, VMInfo, parse_app_spec
from .ssh import SSHConnectionManager
from .watcher import SpecWatcher

__all__ = [
    "Stream",
    "Tap",
    "Consumer",
    "EventStore",
    "Projection",
    "FileWriter",
    "Tailer",
    "Forward",
    "BaseSimulator",
    "SimState",
    "metrics",
    "ProjectionSpec",
    "SpecProjection",
    "parse_projection_spec",
    "AppSpec",
    "VMInfo",
    "parse_app_spec",
    "SSHConnectionManager",
    "SpecWatcher",
]
