"""Sync uptime-kuma command — sync monitors from config to Uptime Kuma.

Bidirectional sync that:
1. Reads monitors from hosts/infra/uptime-kuma-monitors.json
2. Creates/updates monitors to match the config
3. Deletes monitors not in config (orphan cleanup)
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from argparse import ArgumentParser
from pathlib import Path

from cells.fidelity import CliContext

from ..config import resolve_vars
from ..inventory import GRUEL_NETWORK_ROOT
from ..theme import DEFAULT_THEME


def add_args(parser: ArgumentParser) -> None:
    """Add sync-uptime-kuma specific arguments."""
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    parser.add_argument("--config", type=Path, help="Override monitors config path")
    parser.add_argument("--url", help="Uptime Kuma URL (default: from UPTIME_KUMA_URL env or http://192.168.1.30:3001)")


def _get_monitor_type(type_str: str):
    """Convert string type to MonitorType enum."""
    from uptime_kuma_api import MonitorType

    type_map = {
        "http": MonitorType.HTTP,
        "port": MonitorType.PORT,
        "ping": MonitorType.PING,
        "keyword": MonitorType.KEYWORD,
        "dns": MonitorType.DNS,
        "docker": MonitorType.DOCKER,
        "push": MonitorType.PUSH,
    }
    return type_map.get(type_str.lower(), MonitorType.HTTP)


def _build_monitor_params(m: dict, existing_tags: dict[str, int]) -> dict:
    """Build monitor parameters from config."""
    from uptime_kuma_api import MonitorType

    monitor_type = _get_monitor_type(m["type"])

    params = {
        "type": monitor_type,
        "name": m["name"],
        "interval": m.get("interval", 60),
        "retryInterval": m.get("retryInterval", 30),
        "maxretries": m.get("maxretries", 3),
        "description": m.get("description", ""),
    }

    # Type-specific params
    if monitor_type == MonitorType.HTTP:
        params["url"] = m["url"]
        if m.get("ignoreTls"):
            params["ignoreTls"] = True
        if m.get("accepted_statuscodes"):
            params["accepted_statuscodes"] = m["accepted_statuscodes"]
    elif monitor_type == MonitorType.PORT:
        params["hostname"] = m["hostname"]
        params["port"] = m["port"]
    elif monitor_type == MonitorType.PING:
        params["hostname"] = m["hostname"]

    return params


def _monitors_differ(existing: dict, desired_params: dict) -> list[str]:
    """Check if existing monitor differs from desired config."""
    differences = []

    key_mapping = {
        "type": "type",
        "url": "url",
        "hostname": "hostname",
        "port": "port",
        "interval": "interval",
        "retryInterval": "retryInterval",
        "maxretries": "maxretries",
        "description": "description",
        "ignoreTls": "ignoreTls",
        "accepted_statuscodes": "accepted_statuscodes",
    }

    for config_key, existing_key in key_mapping.items():
        if config_key not in desired_params:
            continue

        desired_value = desired_params[config_key]
        existing_value = existing.get(existing_key)

        if config_key == "type":
            if existing_value != desired_value:
                differences.append(f"type: {existing_value} -> {desired_value}")
            continue

        if config_key == "accepted_statuscodes":
            existing_codes = existing.get("accepted_statuscodes", ["200-299"])
            if set(existing_codes) != set(desired_value):
                differences.append(f"accepted_statuscodes: {existing_codes} -> {desired_value}")
            continue

        if existing_value != desired_value:
            differences.append(f"{config_key}: {existing_value!r} -> {desired_value!r}")

    return differences


def run_sync(ctx: CliContext, args) -> int:
    """Run sync command."""
    theme = DEFAULT_THEME

    try:
        from uptime_kuma_api import UptimeKumaApi, MonitorType
    except ImportError:
        print("Error: uptime-kuma-api not installed", file=sys.stderr)
        print("Install with: uv pip install uptime-kuma-api", file=sys.stderr)
        return 1

    # Load config
    config_path = getattr(args, "config", None) or (GRUEL_NETWORK_ROOT / "hosts/infra/uptime-kuma-monitors.json")
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        return 1

    with config_path.open() as f:
        config = json.load(f)

    monitors = config.get("monitors", [])
    print(f"Loaded {len(monitors)} monitors from config", file=sys.stderr)

    # Dry run mode
    dry_run = getattr(args, "dry_run", False)
    if dry_run:
        print("\n[DRY RUN] Would sync the following monitors:", file=sys.stderr)
        for m in monitors:
            name = m.get("name", "")
            target = m.get("url") or m.get("hostname") or "N/A"
            print(f"  {name} ({m.get('type')}) -> {target}", file=sys.stderr)
        print(f"\nDry run: {len(monitors)} monitors would be synced", file=sys.stderr)
        return 0

    # Get credentials
    vars = resolve_vars()
    infra_host = vars.get("infra_host", "192.168.1.30")
    url = getattr(args, "url", None) or os.environ.get("UPTIME_KUMA_URL", f"http://{infra_host}:3001")
    username = os.environ.get("UPTIME_KUMA_USERNAME")
    password = os.environ.get("UPTIME_KUMA_PASSWORD")

    if not username:
        username = input("Uptime Kuma username: ")
    if not password:
        password = getpass.getpass("Uptime Kuma password: ")

    # Connect
    print(f"Connecting to {url}...", file=sys.stderr)
    api = UptimeKumaApi(url)

    try:
        api.login(username, password)
        print(f"{theme.icons.healthy} Logged in", file=sys.stderr)

        # Get existing state
        existing = {m["name"]: m for m in api.get_monitors()}
        existing_tags = {t["name"]: t["id"] for t in api.get_tags()}
        print(f"Found {len(existing)} existing monitors", file=sys.stderr)

        # Create missing tags
        all_tags = set()
        for m in monitors:
            all_tags.update(m.get("tags", []))

        for tag_name in all_tags:
            if tag_name not in existing_tags:
                print(f"Creating tag: {tag_name}", file=sys.stderr)
                tag_result = api.add_tag(name=tag_name, color="#3498db")
                existing_tags[tag_name] = tag_result["id"]

        # Sync monitors
        created = 0
        updated = 0
        skipped = 0
        config_names = {m["name"] for m in monitors}

        for m in monitors:
            name = m["name"]
            params = _build_monitor_params(m, existing_tags)
            tag_ids = [existing_tags[t] for t in m.get("tags", []) if t in existing_tags]

            if name in existing:
                differences = _monitors_differ(existing[name], params)
                if differences:
                    monitor_id = existing[name]["id"]
                    api.edit_monitor(monitor_id, **params)
                    print(f"  {theme.icons.healthy} Updated: {name}", file=sys.stderr)
                    for diff in differences:
                        print(f"      {diff}", file=sys.stderr)
                    updated += 1
                else:
                    print(f"  - Unchanged: {name}", file=sys.stderr)
                    skipped += 1
            else:
                create_result = api.add_monitor(**params)
                monitor_id = create_result["monitorID"]

                for tag_id in tag_ids:
                    api.add_monitor_tag(tag_id=tag_id, monitor_id=monitor_id)

                print(f"  {theme.icons.healthy} Created: {name}", file=sys.stderr)
                created += 1

            # Log push URL for push monitors
            monitor = api.get_monitor(existing[name]["id"] if name in existing else monitor_id)
            if monitor["type"] == MonitorType.PUSH:
                push_token = monitor.get("pushToken")
                if push_token:
                    push_url = f"{url.rstrip('/')}/api/push/{push_token}?status=up&msg=OK&ping="
                    print(f"      Push URL: {push_url}", file=sys.stderr)

        # Delete orphans
        deleted = 0
        for name, monitor in existing.items():
            if name not in config_names:
                api.delete_monitor(monitor["id"])
                print(f"  {theme.icons.unhealthy} Deleted: {name}", file=sys.stderr)
                deleted += 1

        # Summary
        print(f"\n{created} created, {updated} updated, {skipped} unchanged, {deleted} deleted", file=sys.stderr)
        return 0

    except Exception as e:
        print(f"{theme.icons.unhealthy} Sync failed: {e}", file=sys.stderr)
        return 1

    finally:
        try:
            api.disconnect()
        except Exception:
            pass
