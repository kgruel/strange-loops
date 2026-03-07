#!/usr/bin/env python3
"""Compute a mechanical session delta summary.

Finds the observer's most recent session-open timestamp, counts facts
emitted since then (excluding session markers), and prints a one-line
summary. Exits silently if no facts were emitted.

Usage: session-delta.py <loops-binary> <observer>
"""
import json
import subprocess
import sys
from datetime import datetime


def main() -> None:
    if len(sys.argv) < 3:
        return
    loops = sys.argv[1]
    observer = sys.argv[2]

    # Find session open timestamp
    result = subprocess.run(
        [loops, "read", "project", "--facts", "--kind", "session", "--json"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return

    data = json.loads(result.stdout)
    open_ts = None
    # Facts returns newest-first — first match is most recent open
    for f in data.get("facts", []):
        p = f.get("payload", {})
        if p.get("name") == observer and p.get("status") == "open":
            open_ts = datetime.fromisoformat(f["ts"])
            break
    if open_ts is None:
        return

    # Get facts since session open
    result = subprocess.run(
        [loops, "read", "project", "--facts", "--since", "30d", "--json"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return

    data = json.loads(result.stdout)
    facts = [
        f for f in data.get("facts", [])
        if f["kind"] != "session"
        and datetime.fromisoformat(f["ts"]) >= open_ts
    ]
    if not facts:
        return

    kinds: dict[str, int] = {}
    for f in facts:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    parts = [f"{v} {k}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])]
    print(f"Session: {len(facts)} facts. {', '.join(parts)}.")


if __name__ == "__main__":
    main()
