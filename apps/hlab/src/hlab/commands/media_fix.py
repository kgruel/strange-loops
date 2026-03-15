"""Media fix command — fix corrupt/truncated media files.

Interactive command that:
1. Identifies corrupt files (runs audit if needed)
2. Confirms with user before action
3. Deletes the corrupt file from Radarr
4. Triggers a new search for the movie
"""

from __future__ import annotations

import asyncio
import sys
from argparse import ArgumentParser
from pathlib import Path

from painted.cli import CliContext

from ..config import resolve_vars
from ..radarr import RadarrClient, RadarrError, format_size
from ..lenses.media import AuditResult
from ..theme import DEFAULT_THEME
from .media_audit import _fetch_audit


def add_args(parser: ArgumentParser) -> None:
    """Add media fix-specific arguments."""
    parser.add_argument("title", nargs="?", help="Movie title to fix (optional, prompts if not provided)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--all-corrupt", action="store_true", help="Fix all corrupt/truncated files")
    parser.add_argument("--deep", "-d", action="store_true", help="Run deep scan first to identify truly corrupt files")
    parser.add_argument("--inventory", type=Path, default=None, help="Override inventory.yml path")
    parser.add_argument("--connect-timeout", type=float, default=5.0, help="SSH connection timeout (seconds)")


def _confirm(message: str, *, skip: bool = False) -> bool:
    """Ask user for confirmation."""
    if skip:
        return True
    try:
        response = input(f"{message} [y/N] ").strip().lower()
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


async def _fix_movie(client: RadarrClient, result: AuditResult, *, skip_confirm: bool = False) -> bool:
    """Fix a single corrupt movie by deleting and re-searching.

    Returns True if successful.
    """
    theme = DEFAULT_THEME

    print(f"\nProcessing: {result.title} ({result.year})", file=sys.stderr)
    print(f"  Quality: {result.quality}", file=sys.stderr)
    print(f"  Status: {result.status.upper()}", file=sys.stderr)
    print(f"  Size: {format_size(result.actual_size_bytes)}", file=sys.stderr)
    if result.reason:
        print(f"  Reason: {result.reason}", file=sys.stderr)

    # Get current movie state from Radarr
    movie = await client.get_movie(result.movie_id)
    if not movie:
        print(f"  {theme.icons.unhealthy} Movie not found in Radarr", file=sys.stderr)
        return False

    if not movie.movie_file:
        print(f"  {theme.icons.unhealthy} No file to delete", file=sys.stderr)
        return False

    movie_file_id = movie.movie_file.id

    # Confirm deletion
    if not _confirm(f"  Delete file and search for new copy?", skip=skip_confirm):
        print(f"  Skipped", file=sys.stderr)
        return False

    # Delete the file
    try:
        print(f"  Deleting file...", file=sys.stderr)
        await client.delete_movie_file(movie_file_id)
        print(f"  {theme.icons.healthy} File deleted", file=sys.stderr)
    except RadarrError as e:
        print(f"  {theme.icons.unhealthy} Delete failed: {e.message}", file=sys.stderr)
        return False

    # Trigger search
    try:
        print(f"  Triggering search...", file=sys.stderr)
        await client.search_movie(result.movie_id)
        print(f"  {theme.icons.healthy} Search triggered", file=sys.stderr)
    except RadarrError as e:
        print(f"  {theme.icons.unhealthy} Search failed: {e.message}", file=sys.stderr)
        return False

    return True


async def _run_fix_async(ctx: CliContext, args) -> int:
    """Run media fix command."""
    theme = DEFAULT_THEME

    title = getattr(args, "title", None)
    yes = getattr(args, "yes", False)
    all_corrupt = getattr(args, "all_corrupt", False)
    deep = getattr(args, "deep", False)
    inventory = getattr(args, "inventory", None)
    connect_timeout = getattr(args, "connect_timeout", 5.0)

    # Run audit first
    print("Scanning media library...", file=sys.stderr)
    data = await _fetch_audit(
        show_all=False,
        quality=None,
        deep=deep,
        inventory_path=inventory,
        connect_timeout=connect_timeout,
    )

    if not data.results:
        print(f"{theme.icons.healthy} No files to audit", file=sys.stderr)
        return 0

    # Filter to fixable files
    if all_corrupt:
        to_fix = [r for r in data.results if r.status in ("corrupt", "truncated")]
        if not to_fix:
            print(f"{theme.icons.healthy} No corrupt files found", file=sys.stderr)
            return 0
        print(f"\nFound {len(to_fix)} corrupt files to fix", file=sys.stderr)

    elif title:
        title_search = title.lower()
        matches = [
            r for r in data.results
            if title_search in r.title.lower() and r.status in ("corrupt", "truncated", "suspicious")
        ]

        if not matches:
            print(f"{theme.icons.unhealthy} No matching corrupt/suspicious files found for '{title}'", file=sys.stderr)
            return 1

        if len(matches) > 1:
            print(f"Multiple matches found:", file=sys.stderr)
            for i, r in enumerate(matches):
                print(f"  [{i + 1}] {r.title} ({r.year}) - {r.status.upper()}", file=sys.stderr)

            try:
                choice = input("Enter number to fix (or 'all'): ").strip().lower()
                if choice == "all":
                    to_fix = matches
                else:
                    idx = int(choice) - 1
                    if 0 <= idx < len(matches):
                        to_fix = [matches[idx]]
                    else:
                        print("Invalid selection", file=sys.stderr)
                        return 1
            except (ValueError, EOFError, KeyboardInterrupt):
                return 1
        else:
            to_fix = matches

    else:
        corrupt = [r for r in data.results if r.status in ("corrupt", "truncated")]
        suspicious = [r for r in data.results if r.status == "suspicious"]

        if not corrupt and not suspicious:
            print(f"{theme.icons.healthy} No issues found", file=sys.stderr)
            return 0

        print(f"\nCorrupt/truncated files ({len(corrupt)}):", file=sys.stderr)
        for r in corrupt[:10]:
            print(f"  {theme.icons.unhealthy} {r.title} ({r.year}) - {r.quality}", file=sys.stderr)
        if len(corrupt) > 10:
            print(f"  ... and {len(corrupt) - 10} more", file=sys.stderr)

        if suspicious:
            print(f"\nSuspicious files ({len(suspicious)}):", file=sys.stderr)
            print("  (Use --deep to verify before fixing)", file=sys.stderr)

        if not corrupt:
            print("\nNo confirmed corrupt files. Use --deep to scan suspicious files.", file=sys.stderr)
            return 0

        if not _confirm(f"\nFix all {len(corrupt)} corrupt files?", skip=yes):
            return 0

        to_fix = corrupt

    vars = resolve_vars()
    client = RadarrClient(
        host=vars.get("radarr_host", ""),
        api_key=vars.get("radarr_apikey", ""),
    )
    fixed = 0
    failed = 0

    for result in to_fix:
        success = await _fix_movie(client, result, skip_confirm=yes)
        if success:
            fixed += 1
        else:
            failed += 1

    print(f"\n{'=' * 40}", file=sys.stderr)
    print(f"Fixed: {fixed}", file=sys.stderr)
    if failed:
        print(f"Failed: {failed}", file=sys.stderr)

    return 0 if failed == 0 else 1


def run_fix(ctx: CliContext, args) -> int:
    """Run media fix command (sync wrapper)."""
    try:
        return asyncio.run(_run_fix_async(ctx, args))
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        return 130
