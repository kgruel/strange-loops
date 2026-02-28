#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Fidelity spectrum — same data, four presentations.

Disk usage rendered at every zoom level through run_cli.
The flags drive the output — the code doesn't switch on modes.

    uv run demos/patterns/fidelity.py -q        # one line
    uv run demos/patterns/fidelity.py           # directory list
    uv run demos/patterns/fidelity.py -v        # styled bars
    uv run demos/patterns/fidelity.py -vv       # full detail
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from painted import (
    Block,
    Style,
    CliContext,
    Zoom,
    border,
    join_vertical,
    join_horizontal,
    pad,
    truncate,
    ROUNDED,
    run_cli,
)


# --- Data model ---


def _human_size(n: int) -> str:
    """Format byte count as human-readable string."""
    size: float = n
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}P"


@dataclass(frozen=True)
class DirEntry:
    """A directory or file with its size."""

    name: str
    size_bytes: int
    is_dir: bool = True
    children: tuple["DirEntry", ...] = ()

    @property
    def size_human(self) -> str:
        return _human_size(self.size_bytes)


@dataclass(frozen=True)
class DiskData:
    """Disk usage summary."""

    mount: str
    total_bytes: int
    used_bytes: int
    entries: tuple[DirEntry, ...]
    timestamp: str = ""

    @property
    def free_bytes(self) -> int:
        return self.total_bytes - self.used_bytes

    @property
    def used_percent(self) -> float:
        return (self.used_bytes / self.total_bytes) * 100 if self.total_bytes > 0 else 0

    @property
    def total_human(self) -> str:
        return _human_size(self.total_bytes)

    @property
    def used_human(self) -> str:
        return _human_size(self.used_bytes)

    @property
    def free_human(self) -> str:
        return _human_size(self.free_bytes)


# --- Sample data ---

SAMPLE_DISK = DiskData(
    mount="/home",
    total_bytes=200 * 1024**3,
    used_bytes=134 * 1024**3,
    entries=(
        DirEntry(
            "projects",
            45 * 1024**3,
            children=(
                DirEntry("prism", 12 * 1024**3, children=(
                    DirEntry("libs", 3 * 1024**3),
                    DirEntry("experiments", 2 * 1024**3),
                    DirEntry(".venv", 5 * 1024**3),
                    DirEntry("node_modules", 2 * 1024**3),
                )),
                DirEntry("website", 8 * 1024**3),
                DirEntry("ml-research", 15 * 1024**3),
                DirEntry("archive", 10 * 1024**3),
            ),
        ),
        DirEntry(
            "downloads",
            28 * 1024**3,
            children=(
                DirEntry("installers", 12 * 1024**3),
                DirEntry("datasets", 10 * 1024**3),
                DirEntry("misc", 6 * 1024**3),
            ),
        ),
        DirEntry(
            ".cache",
            22 * 1024**3,
            children=(
                DirEntry("pip", 8 * 1024**3),
                DirEntry("huggingface", 10 * 1024**3),
                DirEntry("uv", 4 * 1024**3),
            ),
        ),
        DirEntry("documents", 18 * 1024**3),
        DirEntry("pictures", 12 * 1024**3),
        DirEntry(".local", 9 * 1024**3),
    ),
)


# --- Zoom 0: one-line summary ---


def render_minimal(data: DiskData, width: int) -> Block:
    ts = f"  [{data.timestamp}]" if data.timestamp else ""
    result = Block.text(
        f"{data.used_percent:.0f}% used ({data.used_human}/{data.total_human}){ts}",
        Style(),
    )
    return truncate(result, width)


# --- Zoom 1: directory list ---


def render_standard(data: DiskData, width: int) -> Block:
    rows: list[Block] = [
        Block.text(f"Disk usage: {data.mount}", Style(bold=True)),
        Block.text(
            f"  {data.used_human} / {data.total_human} ({data.used_percent:.1f}% used)",
            Style(),
        ),
        Block.text("", Style()),
        Block.text("Top directories:", Style()),
    ]

    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)
    for entry in sorted_entries[:8]:
        pct = (entry.size_bytes / data.used_bytes) * 100 if data.used_bytes > 0 else 0
        rows.append(Block.text(
            f"  {entry.size_human:>6}  {pct:4.1f}%  {entry.name}", Style(),
        ))

    rows.append(Block.text("", Style()))
    rows.append(Block.text(f"Free: {data.free_human}", Style()))
    if data.timestamp:
        rows.append(Block.text(f"  {data.timestamp}", Style(dim=True)))
    return truncate(join_vertical(*rows), width)


# --- Zoom 2: styled bars ---


def _usage_bar(data: DiskData, bar_width: int) -> Block:
    """Overall disk usage bar."""
    filled = int(data.used_percent / 100 * bar_width)

    if data.used_percent > 90:
        bar_style = Style(fg="red", bold=True)
    elif data.used_percent > 75:
        bar_style = Style(fg="yellow")
    else:
        bar_style = Style(fg="green")

    bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
    return join_horizontal(
        Block.text(f"{data.used_percent:5.1f}% ", bar_style),
        Block.text(bar, bar_style),
        Block.text(f" {data.used_human}/{data.total_human}", Style(dim=True)),
    )


def _dir_row(entry: DirEntry, parent_bytes: int, bar_width: int, indent: int = 0) -> Block:
    """Single directory row with size bar."""
    pct = (entry.size_bytes / parent_bytes) * 100 if parent_bytes > 0 else 0

    size_block = Block.text(entry.size_human.rjust(6), Style(bold=True if indent == 0 else False))

    filled = int(pct / 100 * bar_width)
    bar_style = Style(fg="yellow") if pct > 20 else Style(fg="cyan")
    bar = "\u2593" * filled + "\u2591" * (bar_width - filled)

    name_prefix = "  " + "  " * indent
    name_style = Style() if indent == 0 else Style(dim=True)

    return join_horizontal(
        size_block,
        Block.text(" ", Style()),
        Block.text(bar, bar_style),
        Block.text(" ", Style()),
        Block.text(f"{pct:5.1f}%", Style(dim=True)),
        Block.text(f"{name_prefix}{entry.name}", name_style),
    )


def render_styled(data: DiskData, width: int) -> Block:
    """Zoom 2: styled bars, top-level directories only."""
    # Shared bar width for consistent alignment
    bar_width = min(30, width - 30)

    usage = _usage_bar(data, bar_width)
    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)
    rows = [_dir_row(e, data.used_bytes, bar_width) for e in sorted_entries]
    dir_table = join_vertical(*rows)

    # Pad narrower block so both boxes match width
    content_width = max(usage.width, dir_table.width)
    usage_padded = pad(usage, right=content_width - usage.width)
    dir_padded = pad(dir_table, right=content_width - dir_table.width)

    free_style = Style(fg="green" if data.used_percent < 75 else "yellow", bold=True)
    blocks = [
        border(usage_padded, title=f"Disk: {data.mount}", chars=ROUNDED),
        Block.text("", Style()),
        border(dir_padded, title="By Directory", chars=ROUNDED),
        Block.text("", Style()),
        Block.text(f"  Free: {data.free_human}  ", free_style),
    ]
    if data.timestamp:
        blocks.append(Block.text(f"  {data.timestamp}", Style(dim=True)))
    return join_vertical(*blocks)


# --- Zoom 3: full detail with children ---


def render_full(data: DiskData, width: int) -> Block:
    """Zoom 3: styled bars with subdirectories expanded."""
    bar_width = min(30, width - 30)

    usage = _usage_bar(data, bar_width)
    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)

    rows: list[Block] = []
    for entry in sorted_entries:
        rows.append(_dir_row(entry, data.used_bytes, bar_width))
        if entry.children:
            sorted_children = sorted(entry.children, key=lambda e: e.size_bytes, reverse=True)
            for child in sorted_children:
                rows.append(_dir_row(child, entry.size_bytes, bar_width, indent=1))

    dir_table = join_vertical(*rows)

    content_width = max(usage.width, dir_table.width)
    usage_padded = pad(usage, right=content_width - usage.width)
    dir_padded = pad(dir_table, right=content_width - dir_table.width)

    free_style = Style(fg="green" if data.used_percent < 75 else "yellow", bold=True)
    blocks = [
        border(usage_padded, title=f"Disk: {data.mount}", chars=ROUNDED),
        Block.text("", Style()),
        border(dir_padded, title="By Directory", chars=ROUNDED),
        Block.text("", Style()),
        Block.text(f"  Free: {data.free_human}  ", free_style),
    ]
    if data.timestamp:
        blocks.append(Block.text(f"  {data.timestamp}", Style(dim=True)))
    return join_vertical(*blocks)


# --- run_cli integration ---


def _fetch() -> DiskData:
    """Real disk stats for home directory, sample subdirectories."""
    home = Path.home()
    try:
        usage = shutil.disk_usage(home)
    except OSError:
        return SAMPLE_DISK
    return DiskData(
        mount=str(home),
        total_bytes=usage.total,
        used_bytes=usage.used,
        entries=SAMPLE_DISK.entries,
        timestamp=datetime.now().isoformat(timespec="seconds"),
    )


def _render(ctx: CliContext, data: DiskData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return render_minimal(data, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return render_standard(data, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return render_full(data, ctx.width)
    return render_styled(data, ctx.width)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="fidelity.py",
    )


if __name__ == "__main__":
    sys.exit(main())
