"""Collector discovery: scan collectors/ directory for .collector and .py files.

Discovery scans a directory tree and loads collectors from:
- .collector files: parsed as KDL specs
- .py files: imported, reads __collector__ metadata and collect/stream functions

Naming convention: path determines name.
    collectors/docker/containers.collector → docker.containers
    collectors/proxmox/vms.py → proxmox.vms
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Callable

from .spec import (
    CollectorSpec,
    build_poll_collector,
    build_stream_collector,
    parse_collector_spec,
)

if TYPE_CHECKING:
    from ..ssh_session import SSHSession

logger = logging.getLogger(__name__)


# Type aliases for collector functions
PollCollector = Callable[["SSHSession"], list[dict]]
StreamCollector = Callable[["SSHSession"], AsyncIterator[dict]]
CollectorFn = PollCollector | StreamCollector

# Registry entry: (mode, collector_function, spec_or_none)
RegistryEntry = tuple[str, CollectorFn, CollectorSpec | None]


def derive_name(path: Path, base_dir: Path) -> str:
    """Derive collector name from path relative to base directory.

    collectors/docker/containers.collector → docker.containers
    collectors/system/uptime.collector → system.uptime
    """
    relative = path.relative_to(base_dir)
    parts = list(relative.parts)
    # Remove file extension from last part
    parts[-1] = path.stem
    return ".".join(parts)


def discover_collectors(
    base_dir: Path,
    *,
    separator: str = ".",
) -> dict[str, RegistryEntry]:
    """Discover collectors from a directory tree.

    Args:
        base_dir: Root directory to scan (e.g., Path("collectors"))
        separator: Separator for name parts (default: ".")

    Returns:
        Dict mapping collector names to (mode, function, spec) tuples.
        spec is CollectorSpec for .collector files, None for .py files.
    """
    registry: dict[str, RegistryEntry] = {}

    if not base_dir.exists():
        logger.debug(f"Collector directory does not exist: {base_dir}")
        return registry

    # Find all .collector and .py files
    for path in sorted(base_dir.rglob("*")):
        if path.is_file():
            name = derive_name(path, base_dir)
            if separator != ".":
                name = name.replace(".", separator)

            if path.suffix == ".collector":
                entry = _load_collector_spec(path, name)
                if entry:
                    registry[name] = entry
            elif path.suffix == ".py" and not path.name.startswith("_"):
                entry = _load_python_collector(path, name)
                if entry:
                    registry[name] = entry

    return registry


def _load_collector_spec(path: Path, name: str) -> RegistryEntry | None:
    """Load a .collector KDL file."""
    try:
        spec = parse_collector_spec(path, name)
        if spec.mode == "stream":
            fn = build_stream_collector(spec)
        else:
            fn = build_poll_collector(spec)
        return (spec.mode, fn, spec)
    except Exception as e:
        logger.warning(f"Failed to load collector spec {path}: {e}")
        return None


def _load_python_collector(path: Path, name: str) -> RegistryEntry | None:
    """Load a Python collector module.

    Expects:
        __collector__ = {"mode": "collect" | "stream"}
        async def collect(ssh) -> list[dict]   # for mode="collect"
        async def stream(ssh) -> AsyncIterator[dict]  # for mode="stream"
    """
    try:
        # Create a unique module name to avoid conflicts
        module_name = f"_collectors_.{name.replace('.', '_')}"

        # Load the module from file
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning(f"Could not load module spec from {path}")
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Read __collector__ metadata
        metadata = getattr(module, "__collector__", None)
        if metadata is None:
            logger.debug(f"No __collector__ metadata in {path}, skipping")
            return None

        mode = metadata.get("mode", "collect")

        # Get the collector function
        if mode == "stream":
            fn = getattr(module, "stream", None)
            if fn is None:
                logger.warning(f"stream mode but no stream() function in {path}")
                return None
        else:
            fn = getattr(module, "collect", None)
            if fn is None:
                logger.warning(f"collect mode but no collect() function in {path}")
                return None

        return (mode, fn, None)

    except Exception as e:
        logger.warning(f"Failed to load Python collector {path}: {e}")
        return None


def discover_and_register(
    base_dir: Path,
    *,
    separator: str = ".",
) -> dict[str, tuple[str, CollectorFn]]:
    """Discover collectors and return simplified registry (mode, function only).

    This is the interface expected by the existing COLLECTORS dict.
    """
    full_registry = discover_collectors(base_dir, separator=separator)
    return {name: (mode, fn) for name, (mode, fn, _) in full_registry.items()}
