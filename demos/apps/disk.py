#!/usr/bin/env python3
"""Disk Space — interactive disk usage visualization.

Interactive version of the fidelity pattern disk demo.

Keys:
  ↑/↓  select volume
  q    quit
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from painted import (
    Block,
    ROUNDED,
    Style,
    Wrap,
    border,
    join_horizontal,
    join_vertical,
    pad,
    truncate,
    vslice,
)
from painted.tui import Surface
from painted.views import ProgressState, progress_bar


def _human_size(n: int) -> str:
    size: float = n
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}P"


@dataclass(frozen=True, slots=True)
class DirEntry:
    name: str
    size_bytes: int
    children: tuple["DirEntry", ...] = ()

    @property
    def size_human(self) -> str:
        return _human_size(self.size_bytes)


@dataclass(frozen=True, slots=True)
class Volume:
    mount: str
    device: str
    fstype: str
    total_bytes: int
    used_bytes: int
    entries: tuple[DirEntry, ...]

    @property
    def free_bytes(self) -> int:
        return max(0, self.total_bytes - self.used_bytes)

    @property
    def used_percent(self) -> float:
        return (self.used_bytes / self.total_bytes) * 100 if self.total_bytes > 0 else 0.0

    @property
    def total_human(self) -> str:
        return _human_size(self.total_bytes)

    @property
    def used_human(self) -> str:
        return _human_size(self.used_bytes)

    @property
    def free_human(self) -> str:
        return _human_size(self.free_bytes)


SAMPLE_VOLUMES: tuple[Volume, ...] = (
    Volume(
        mount="/",
        device="/dev/nvme0n1p2",
        fstype="ext4",
        total_bytes=512 * 1024**3,
        used_bytes=318 * 1024**3,
        entries=(
            DirEntry(
                "usr",
                140 * 1024**3,
                children=(
                    DirEntry("lib", 52 * 1024**3),
                    DirEntry("share", 45 * 1024**3),
                    DirEntry("bin", 12 * 1024**3),
                    DirEntry("local", 31 * 1024**3),
                ),
            ),
            DirEntry(
                "var",
                58 * 1024**3,
                children=(
                    DirEntry("lib", 30 * 1024**3),
                    DirEntry("log", 6 * 1024**3),
                    DirEntry("cache", 18 * 1024**3),
                    DirEntry("tmp", 4 * 1024**3),
                ),
            ),
            DirEntry("home", 82 * 1024**3),
            DirEntry("opt", 22 * 1024**3),
            DirEntry("snap", 14 * 1024**3),
        ),
    ),
    Volume(
        mount="/home",
        device="/dev/nvme0n1p3",
        fstype="ext4",
        total_bytes=200 * 1024**3,
        used_bytes=134 * 1024**3,
        entries=(
            DirEntry(
                "projects",
                45 * 1024**3,
                children=(
                    DirEntry(
                        "prism",
                        12 * 1024**3,
                        children=(
                            DirEntry("libs", 3 * 1024**3),
                            DirEntry("experiments", 2 * 1024**3),
                            DirEntry(".venv", 5 * 1024**3),
                            DirEntry("node_modules", 2 * 1024**3),
                        ),
                    ),
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
    ),
    Volume(
        mount="/var",
        device="/dev/nvme0n1p4",
        fstype="ext4",
        total_bytes=96 * 1024**3,
        used_bytes=63 * 1024**3,
        entries=(
            DirEntry(
                "lib",
                34 * 1024**3,
                children=(
                    DirEntry("docker", 14 * 1024**3),
                    DirEntry("postgres", 9 * 1024**3),
                    DirEntry("apt", 3 * 1024**3),
                    DirEntry("snapd", 8 * 1024**3),
                ),
            ),
            DirEntry("log", 7 * 1024**3),
            DirEntry("cache", 16 * 1024**3),
            DirEntry("spool", 3 * 1024**3),
            DirEntry("tmp", 3 * 1024**3),
        ),
    ),
    Volume(
        mount="/mnt/data",
        device="/dev/sda1",
        fstype="xfs",
        total_bytes=2 * 1024**4,
        used_bytes=1670 * 1024**3,
        entries=(
            DirEntry(
                "datasets",
                740 * 1024**3,
                children=(
                    DirEntry("images", 220 * 1024**3),
                    DirEntry("audio", 85 * 1024**3),
                    DirEntry("nlp", 140 * 1024**3),
                    DirEntry("video", 295 * 1024**3),
                ),
            ),
            DirEntry(
                "backups",
                520 * 1024**3,
                children=(
                    DirEntry("laptops", 180 * 1024**3),
                    DirEntry("servers", 240 * 1024**3),
                    DirEntry("phones", 100 * 1024**3),
                ),
            ),
            DirEntry("vm-images", 260 * 1024**3),
            DirEntry("media", 120 * 1024**3),
            DirEntry("scratch", 30 * 1024**3),
        ),
    ),
)


def _usage_color(pct: float) -> str:
    if pct > 90:
        return "red"
    if pct > 75:
        return "yellow"
    return "green"


def _usage_bar(used: int, total: int, width: int) -> Block:
    value = (used / total) if total > 0 else 0.0
    pct = value * 100
    bar = progress_bar(
        ProgressState(value=value),
        width=width,
        filled_style=Style(fg=_usage_color(pct), bold=True),
        empty_style=Style(dim=True),
    )
    return join_horizontal(
        Block.text(f"{pct:5.1f}% ", Style(fg=_usage_color(pct), bold=True)),
        bar,
    )


def _volume_list(volumes: tuple[Volume, ...], selected: int, width: int) -> Block:
    rows: list[Block] = []
    for idx, vol in enumerate(volumes):
        is_sel = idx == selected
        marker = ">" if is_sel else " "
        marker_style = Style(bold=is_sel)

        bar_width = max(8, min(18, width - 26))
        name_width = max(10, width - (2 + 1 + 6 + 1 + bar_width + 1))

        name = Block.text(vol.mount, Style(bold=is_sel), width=name_width, wrap=Wrap.ELLIPSIS)
        pct = Block.text(f"{vol.used_percent:5.1f}%", Style(dim=not is_sel))
        bar = progress_bar(
            ProgressState(value=(vol.used_bytes / vol.total_bytes) if vol.total_bytes else 0.0),
            width=bar_width,
            filled_style=Style(fg=_usage_color(vol.used_percent), bold=is_sel),
            empty_style=Style(dim=True),
        )

        line1 = join_horizontal(
            Block.text(marker, marker_style),
            Block.text(" ", Style()),
            name,
            Block.text(" ", Style()),
            pct,
            Block.text(" ", Style()),
            bar,
        )
        rows.append(truncate(line1, width))

        if is_sel:
            detail = f"  {vol.used_human}/{vol.total_human}  free {vol.free_human}  {vol.fstype}  {vol.device}"
            rows.append(Block.text(detail, Style(dim=True), width=width, wrap=Wrap.ELLIPSIS))

    if not rows:
        return Block.text("(no volumes)", Style(dim=True), width=width)
    return truncate(join_vertical(*rows), width)


def _dir_row(entry: DirEntry, parent_bytes: int, bar_width: int, *, indent: int = 0) -> Block:
    pct = (entry.size_bytes / parent_bytes) if parent_bytes > 0 else 0.0
    size = Block.text(entry.size_human.rjust(6), Style(bold=indent == 0))
    bar = progress_bar(
        ProgressState(value=pct),
        width=bar_width,
        filled_style=Style(fg="cyan" if pct < 0.2 else "yellow"),
        empty_style=Style(dim=True),
    )
    name_prefix = "  " + "  " * indent
    name_style = Style() if indent == 0 else Style(dim=True)
    return join_horizontal(
        size,
        Block.text(" ", Style()),
        bar,
        Block.text(" ", Style()),
        Block.text(f"{pct * 100:5.1f}%", Style(dim=True)),
        Block.text(f"{name_prefix}{entry.name}", name_style),
    )


def _volume_detail(vol: Volume, width: int, height: int) -> Block:
    bar_w = max(8, min(28, width - 10))
    usage = _usage_bar(vol.used_bytes, vol.total_bytes, bar_w)
    usage = pad(usage, right=max(0, width - usage.width))

    meta = Block.text(
        f"{vol.used_human} used • {vol.free_human} free • {vol.total_human} total",
        Style(dim=True),
        width=width,
        wrap=Wrap.ELLIPSIS,
    )

    rows: list[Block] = [border(join_vertical(usage, meta), title=f"Disk: {vol.mount}", chars=ROUNDED)]

    sorted_entries = sorted(vol.entries, key=lambda e: e.size_bytes, reverse=True)
    bar_width = max(10, min(24, width - 28))

    dir_rows: list[Block] = []
    for entry in sorted_entries[:8]:
        dir_rows.append(_dir_row(entry, vol.used_bytes, bar_width))
        if entry.children:
            for child in sorted(entry.children, key=lambda e: e.size_bytes, reverse=True)[:4]:
                dir_rows.append(_dir_row(child, entry.size_bytes, bar_width, indent=1))

    table = truncate(join_vertical(*dir_rows) if dir_rows else Block.text("(no entries)", Style(dim=True)), width)
    rows.append(Block.text("", Style()))
    rows.append(border(table, title="By Directory", chars=ROUNDED))

    detail = join_vertical(*rows)
    if detail.height > height:
        return vslice(detail, 0, height)
    return detail


def _render(width: int, height: int, volumes: tuple[Volume, ...], selected: int) -> Block:
    title = Block.text("Disk Space", Style(bold=True))
    subtitle = Block.text("↑/↓ select • q quit", Style(dim=True))
    header = join_horizontal(title, Block.text("  ", Style()), subtitle)

    if width < 60:
        list_w = max(20, width - 2)
        details_w = list_w
        vol_list = border(_volume_list(volumes, selected, list_w - 2), title="Volumes", chars=ROUNDED)
        details = _volume_detail(volumes[selected], details_w - 2, max(3, height - vol_list.height - 6))
        content = join_vertical(vol_list, Block.text("", Style()), details)
    else:
        left_w = max(26, min(36, width // 2))
        right_w = max(20, width - left_w - 1)
        vol_list = border(_volume_list(volumes, selected, left_w - 2), title="Volumes", chars=ROUNDED)
        details = _volume_detail(volumes[selected], right_w - 2, max(3, height - 4))
        content = join_horizontal(vol_list, Block.text(" ", Style()), details)

    footer = Block.text("Sample data (deterministic for goldens)", Style(dim=True))
    root = join_vertical(header, Block.text("", Style()), content, Block.text("", Style()), footer)
    root = truncate(root, width)
    if root.height > height:
        root = vslice(root, 0, height)
    return root


class DiskApp(Surface):
    def __init__(self, *, volumes: tuple[Volume, ...] = SAMPLE_VOLUMES) -> None:
        super().__init__()
        self.volumes = volumes
        self.selected = 0

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        if not self.volumes:
            Block.text("No volumes", Style(dim=True)).paint(self._buf, 0, 0)
            return
        selected = max(0, min(self.selected, len(self.volumes) - 1))
        ui = _render(self._buf.width, self._buf.height, self.volumes, selected)
        ui.paint(self._buf, 0, 0)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return
        if key == "up":
            self.selected = max(0, self.selected - 1)
        elif key == "down":
            self.selected = min(len(self.volumes) - 1, self.selected + 1)


async def main() -> None:
    await DiskApp().run()


if __name__ == "__main__":
    asyncio.run(main())
