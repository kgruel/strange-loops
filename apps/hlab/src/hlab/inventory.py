"""Inventory loading — parse Ansible inventory and host metadata.

Provides functions to discover stacks from the hosts directory and
extract SSH connection details from Ansible inventory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .infra import HostConfig

# Default paths relative to gruel.network repo
GRUEL_NETWORK_ROOT = Path.home() / "Code" / "gruel.network"
DEFAULT_HOSTS_DIR = GRUEL_NETWORK_ROOT / "hosts"
ANSIBLE_INVENTORY_CACHE = GRUEL_NETWORK_ROOT / "ansible" / "inventory.yml"


class InventoryError(Exception):
    """Error loading or parsing inventory."""

    def __init__(self, message: str, suggestion: str | None = None) -> None:
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)


def load_inventory(path: Path | None = None) -> dict[str, Any]:
    """Load Ansible inventory YAML file.

    Args:
        path: Path to inventory.yml (defaults to ANSIBLE_INVENTORY_CACHE)

    Returns:
        Parsed inventory dictionary

    Raises:
        InventoryError: If file not found or invalid YAML
    """
    inventory_path = path or ANSIBLE_INVENTORY_CACHE
    try:
        data = yaml.safe_load(inventory_path.read_text())
    except FileNotFoundError as e:
        raise InventoryError(
            f"Missing file: {inventory_path}",
            suggestion="Check that gruel.network repo is at ~/Code/gruel.network",
        ) from e
    except Exception as e:
        raise InventoryError(f"Failed to parse YAML: {inventory_path}", suggestion=str(e)) from e

    if not isinstance(data, dict):
        raise InventoryError(f"Invalid YAML (expected mapping): {inventory_path}")
    return data


def list_stacks(hosts_dir: Path | None = None, *, include_homeassistant: bool = False) -> list[str]:
    """List available stack names from hosts directory.

    Each subdirectory in hosts/ (excluding those starting with _) is a stack.

    Args:
        hosts_dir: Path to hosts directory (defaults to DEFAULT_HOSTS_DIR)
        include_homeassistant: Whether to include homeassistant stack

    Returns:
        Sorted list of stack names

    Raises:
        InventoryError: If hosts directory not found
    """
    dir_path = hosts_dir or DEFAULT_HOSTS_DIR
    try:
        entries = list(dir_path.iterdir())
    except FileNotFoundError as e:
        raise InventoryError(
            f"Missing hosts directory: {dir_path}",
            suggestion="Check that gruel.network repo is at ~/Code/gruel.network",
        ) from e

    stacks: list[str] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith("_"):
            continue
        if not include_homeassistant and name == "homeassistant":
            continue
        stacks.append(name)
    return sorted(stacks)


def stack_name_from_metadata(hosts_dir: Path | None, stack: str) -> str:
    """Get the stack name (directory name on host) from metadata.

    Some stacks have a different name on the host than their directory name.
    The metadata.yml file can specify stack-name to override.

    Args:
        hosts_dir: Path to hosts directory
        stack: Stack directory name

    Returns:
        Stack name to use on the host (e.g., /opt/{stack_name})
    """
    dir_path = hosts_dir or DEFAULT_HOSTS_DIR
    meta = dir_path / stack / "metadata.yml"
    if not meta.exists():
        return stack
    try:
        data = yaml.safe_load(meta.read_text())
        if isinstance(data, dict):
            return str(data.get("stack-name") or stack)
    except Exception:
        pass
    return stack


def host_config_from_inventory(inventory: dict[str, Any], stack: str) -> HostConfig:
    """Extract host configuration for a stack from Ansible inventory.

    Args:
        inventory: Parsed inventory dictionary
        stack: Stack name (e.g., "infra", "media")

    Returns:
        HostConfig with SSH connection details
    """
    children = inventory.get("all", {}).get("children", {})
    vars_ = inventory.get("all", {}).get("vars", {})
    common_args = str(vars_.get("ansible_ssh_common_args") or "").strip()

    # Match legacy behavior: runner maps to runner-01 under runner_vms
    if stack == "runner":
        host = children.get("runner_vms", {}).get("hosts", {}).get("runner-01", {})
    else:
        host = children.get("vms", {}).get("hosts", {}).get(stack, {})

    ip = host.get("ansible_host")
    user = host.get("ansible_user") or "deploy"
    key = host.get("ansible_ssh_private_key_file")
    key_file = Path(str(key)).expanduser() if key else None

    return HostConfig(
        ip=str(ip) if ip else None,
        user=str(user),
        key_file=key_file,
        common_args=common_args,
    )
