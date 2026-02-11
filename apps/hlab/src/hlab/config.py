"""Config resolution — inventory + environment to vertex vars.

Reads Ansible inventory and environment variables to produce the vars dict
that load_vertex_program() uses to resolve ${var} references in .vertex files.
"""

from __future__ import annotations

import os
from pathlib import Path

from .inventory import (
    ANSIBLE_INVENTORY_CACHE,
    host_config_from_inventory,
    load_inventory,
)

# Radarr API port (appended to media host IP)
_RADARR_PORT = "7878"


def resolve_vars(inventory_path: Path | None = None) -> dict[str, str]:
    """Resolve vertex vars from Ansible inventory + environment.

    Reads host IPs from inventory and API keys from environment.

    Args:
        inventory_path: Override path to inventory.yml

    Returns:
        Dict of variable name → value for vertex var substitution.
    """
    inv = load_inventory(inventory_path or ANSIBLE_INVENTORY_CACHE)
    vars: dict[str, str] = {}

    # Stack host IPs
    for stack in ("infra", "media", "dev", "minecraft"):
        cfg = host_config_from_inventory(inv, stack)
        if cfg.ip:
            vars[f"{stack}_host"] = cfg.ip

    # Radarr: media IP with port
    media_cfg = host_config_from_inventory(inv, "media")
    if media_cfg.ip:
        vars["radarr_host"] = f"{media_cfg.ip}:{_RADARR_PORT}"

    # API keys from environment
    vars["radarr_apikey"] = os.environ.get("RADARR_API_KEY", "")

    return vars
