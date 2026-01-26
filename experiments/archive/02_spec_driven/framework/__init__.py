"""Homelab event infrastructure.

Core primitives (Stream, Projection, EventStore, etc.) live in rill package.
This layer adds:
  - KDL spec parsing (ProjectionSpec, AppSpec)
  - SSH collection (SSHSession, sources)
  - Docker collectors
  - Source bindings (wiring sources to streams and projections)
"""

from .sim import BaseSimulator, SimState
from .instrument import metrics
from .spec import ProjectionSpec, SpecProjection, ValidationError, parse_projection_spec
from .app_spec import AppSpec, VMInfo, DataSourceSpec, parse_app_spec
from .watcher import SpecWatcher
from .binding import (
    SourceBinding,
    run_source,
    bind_data_source,
    start_binding,
    stop_binding,
    create_binding_for_poll,
    create_binding_for_stream,
    create_binding_for_tailer,
)
from .sources import TailerSource, PollSource, StreamSource

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
    "DataSourceSpec",
    "parse_app_spec",
    "SpecWatcher",
    # Binding
    "SourceBinding",
    "run_source",
    "bind_data_source",
    "start_binding",
    "stop_binding",
    "create_binding_for_poll",
    "create_binding_for_stream",
    "create_binding_for_tailer",
    # Sources
    "TailerSource",
    "PollSource",
    "StreamSource",
]
