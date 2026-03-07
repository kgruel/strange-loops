#!/usr/bin/env python3
"""Ingest LOG.md entries into the project vertex store as development log facts.

Each ## header becomes a fact with kind="log", date as ts, title and body as payload.
Uses loops emit directly so the full pipeline is exercised.
"""

import re
import subprocess
import sys
from pathlib import Path


def parse_log(path: Path) -> list[dict]:
    """Split LOG.md into entries by ## headers."""
    text = path.read_text()
    # Split on ## YYYY-MM-DD — Title
    pattern = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+)$", re.MULTILINE)

    entries = []
    matches = list(pattern.finditer(text))

    for i, match in enumerate(matches):
        date = match.group(1)
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip().rstrip("-").strip()
        entries.append({"date": date, "title": title, "body": body})

    return entries


def emit(entry: dict, dry_run: bool = False) -> None:
    """Emit a log entry as a fact via loops emit."""
    # Truncate body for payload — full text as the trailing message
    # Use explicit vertex path to avoid resolution ambiguity
    # ("project" as positional gets parsed as kind, not vertex name)
    vertex_path = str(Path(__file__).parent.parent / ".loops" / "project.vertex")
    cmd = [
        "uv", "run", "loops", "emit", vertex_path, "log",
        "--observer", "kyle",
        f"date={entry['date']}",
        f"title={entry['title']}",
        entry["body"],
    ]
    if dry_run:
        cmd.insert(cmd.index("log") + 1, "--dry-run")

    result = subprocess.run(cmd, capture_output=True, text=True)
    status = "ok" if result.returncode == 0 else "FAIL"
    print(f"  [{status}] {entry['date']} — {entry['title'][:60]}")
    if result.returncode != 0:
        print(f"    stderr: {result.stderr.strip()}")


def main():
    log_path = Path(__file__).parent.parent / "LOG.md"
    if not log_path.exists():
        print(f"LOG.md not found at {log_path}")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    entries = parse_log(log_path)
    print(f"Parsed {len(entries)} log entries from LOG.md")

    if dry_run:
        print("(dry run — no facts will be stored)\n")
    else:
        print()

    for entry in entries:
        emit(entry, dry_run=dry_run)

    print(f"\nDone. {'Would emit' if dry_run else 'Emitted'} {len(entries)} facts.")
    if not dry_run:
        print("Query with: loops read project --facts --kind log")


if __name__ == "__main__":
    main()
