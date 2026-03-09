"""Discover Claude Code JSONL session files and emit raw records.

Thin discovery script — finds session files, tracks which have been
processed (manifest), and emits raw NDJSON records to stdout. All
filtering and field extraction is handled by the vertex parse pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LOCATIONS = ["~/.claude/projects", "~/.config/claude/projects"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover and emit Claude Code session records")
    parser.add_argument("--data-dir", default=None, help="Data directory for manifest (cursor state)")
    args = parser.parse_args(argv)

    manifest_path = Path(args.data_dir).expanduser() / ".manifest-v2" if args.data_dir else None
    manifest = _load_manifest(manifest_path)

    paths: list[Path] = []
    for loc in LOCATIONS:
        base = Path(loc).expanduser()
        if base.exists():
            paths.extend(base.glob("**/*.jsonl"))
    paths.sort(key=lambda p: p.stat().st_mtime)

    for path in paths:
        key = str(path)
        size = path.stat().st_size
        if size == manifest.get(key, {}).get("size", -1):
            continue  # unchanged since last sync

        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Pre-filter: only emit user/assistant records.
                    # Avoids piping megabyte-sized progress records through
                    # the ndjson parser just to drop them in the where filter.
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if record.get("type") in ("user", "assistant"):
                        sys.stdout.write(line)
                        sys.stdout.write("\n")
        except (OSError, UnicodeDecodeError):
            continue

        manifest[key] = {"size": size}

    _save_manifest(manifest, manifest_path)
    return 0


def _load_manifest(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_manifest(manifest: dict, path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.rename(path)


if __name__ == "__main__":
    sys.exit(main())
