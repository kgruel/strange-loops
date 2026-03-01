#!/usr/bin/env python3
"""Disk Space — interactive disk usage visualization.

Region-based layout: layout() computes fixed regions once per resize,
render() fills them. Content never dictates geometry — regions do.

Scans real filesystem data on startup.

Keys:
  ↑/↓  select volume
  q    quit

Run: uv run python demos/examples/disk.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass

from painted import Style
from painted.buffer import BufferView
from painted.region import Region
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


def _put(view: BufferView, x: int, y: int, text: str, style: Style) -> None:
    """put_text clipped to view width."""
    if y >= view.height or x >= view.width:
        return
    view.put_text(x, y, text[: view.width - x], style)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Real filesystem scanning
# ---------------------------------------------------------------------------


def _discover_mounts() -> list[str]:
    """Find mount points: / plus distinct volumes under /Volumes/."""
    mounts = ["/"]
    volumes_dir = "/Volumes"
    if os.path.isdir(volumes_dir):
        for name in sorted(os.listdir(volumes_dir)):
            path = os.path.join(volumes_dir, name)
            if os.path.isdir(path):
                mounts.append(path)
    return mounts


_SIZE_DEPTH = 4  # how deep to recurse for accurate byte counts


def _dir_size(path: str, max_depth: int) -> int:
    """Sum file sizes under path, bounded by depth."""
    total = 0
    if max_depth <= 0:
        return total
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += _dir_size(entry.path, max_depth - 1)
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    return total


def _scan_entries(path: str, depth: int) -> tuple[DirEntry, ...]:
    """Scan directory entries with bounded depth."""
    entries: list[DirEntry] = []
    try:
        for e in os.scandir(path):
            if e.name.startswith(".") and depth > 1:
                continue  # skip hidden at top level only
            try:
                if e.is_dir():
                    size = _dir_size(e.path, max_depth=_SIZE_DEPTH)
                    children = _scan_entries(e.path, depth - 1) if depth > 1 else ()
                    entries.append(DirEntry(e.name, size, children))
                elif e.is_file():
                    entries.append(DirEntry(e.name, e.stat().st_size))
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    return tuple(sorted(entries, key=lambda e: e.size_bytes, reverse=True))


def _scan() -> tuple[Volume, ...]:
    """Scan real filesystem."""
    volumes: list[Volume] = []
    seen_devs: set[int] = set()

    for mount in _discover_mounts():
        try:
            st = os.stat(mount)
            if st.st_dev in seen_devs:
                continue
            seen_devs.add(st.st_dev)
            usage = shutil.disk_usage(mount)
            entries = _scan_entries(mount, depth=2)
            volumes.append(
                Volume(
                    mount=mount,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    entries=entries,
                )
            )
        except (PermissionError, OSError):
            continue

    return tuple(volumes)


# ---------------------------------------------------------------------------
# Rendering helpers (paint into BufferView, not Block composition)
# ---------------------------------------------------------------------------


def _usage_color(pct: float) -> str:
    if pct > 90:
        return "red"
    if pct > 75:
        return "yellow"
    return "green"


def _render_volume_list(
    view: BufferView, volumes: tuple[Volume, ...], selected: int
) -> None:
    """Render the volume list into a fixed-size BufferView."""
    w = view.width
    bar_w = max(4, min(10, w - 20))

    for idx, vol in enumerate(volumes):
        if idx >= view.height:
            break
        is_sel = idx == selected
        marker = ">" if is_sel else " "
        color = _usage_color(vol.used_percent)
        pct_s = f"{vol.used_percent:5.1f}%"

        # marker + space + mount + space + pct + space + bar
        mount_w = max(4, w - 2 - 1 - 6 - 1 - bar_w)
        mount = vol.mount[:mount_w].ljust(mount_w)

        _put(view, 0, idx, f"{marker} {mount} {pct_s} ", Style(bold=is_sel))

        bar_x = 2 + mount_w + 1 + 6 + 1
        bar = progress_bar(
            ProgressState(value=vol.used_bytes / vol.total_bytes if vol.total_bytes else 0.0),
            width=min(bar_w, w - bar_x),
            filled_style=Style(fg=color, bold=is_sel),
            empty_style=Style(dim=True),
        )
        bar.paint(view, bar_x, idx)


def _render_detail_header(view: BufferView, vol: Volume) -> None:
    """Render the volume summary into a fixed-size BufferView."""
    w = view.width
    color = _usage_color(vol.used_percent)

    _put(view, 1, 0, vol.mount, Style(fg=color, bold=True))

    bar_w = max(4, min(24, w - 10))
    bar = progress_bar(
        ProgressState(value=vol.used_bytes / vol.total_bytes if vol.total_bytes else 0.0),
        width=bar_w,
        filled_style=Style(fg=color, bold=True),
        empty_style=Style(dim=True),
    )
    bar.paint(view, 1, 2)
    pct_s = f"{vol.used_percent:5.1f}%"
    _put(view, 1 + bar_w + 1, 2, pct_s, Style(fg=color, bold=True))

    summary = f"{vol.used_human} / {vol.total_human}  ({vol.free_human} free)"
    _put(view, 1, 3, summary, Style(dim=True))


def _render_dir_table(view: BufferView, vol: Volume) -> None:
    """Render the directory breakdown into a fixed-size BufferView."""
    w = view.width
    bar_w = max(4, min(16, w - 22))
    sorted_entries = sorted(vol.entries, key=lambda e: e.size_bytes, reverse=True)

    y = 0
    for entry in sorted_entries[:6]:
        if y >= view.height:
            break
        _render_dir_row(view, y, entry, vol.used_bytes, bar_w, w, indent=0)
        y += 1
        if entry.children:
            for child in sorted(entry.children, key=lambda e: e.size_bytes, reverse=True)[:3]:
                if y >= view.height:
                    break
                _render_dir_row(view, y, child, entry.size_bytes, bar_w, w, indent=1)
                y += 1


def _render_dir_row(
    view: BufferView, y: int, entry: DirEntry, parent_bytes: int,
    bar_w: int, total_w: int, *, indent: int,
) -> None:
    pct = min(1.0, entry.size_bytes / parent_bytes) if parent_bytes > 0 else 0.0
    size_s = entry.size_human.rjust(6)
    pct_s = f"{pct * 100:5.1f}%"
    prefix = "  " * indent
    name_x = 6 + 1 + bar_w + 1 + 6 + 1 + len(prefix)
    name_w = max(0, total_w - name_x)

    _put(view, 0, y, size_s, Style(bold=indent == 0))

    bar = progress_bar(
        ProgressState(value=pct),
        width=bar_w,
        filled_style=Style(fg="cyan" if pct < 0.2 else "yellow"),
        empty_style=Style(dim=True),
    )
    bar.paint(view, 7, y)

    _put(view, 7 + bar_w + 1, y, pct_s, Style(dim=True))
    _put(view, name_x, y, (prefix + entry.name)[:name_w], Style(dim=indent > 0))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class DiskApp(Surface):
    def __init__(self, *, volumes: tuple[Volume, ...]) -> None:
        super().__init__()
        self.volumes = volumes
        self.selected = 0

        # Regions computed in layout()
        self.header_r = Region(0, 0, 0, 0)
        self.list_r = Region(0, 0, 0, 0)
        self.detail_header_r = Region(0, 0, 0, 0)
        self.dir_table_r = Region(0, 0, 0, 0)
        self.footer_r = Region(0, 0, 0, 0)
        self.sep_x = 0

    def layout(self, width: int, height: int) -> None:
        # Fixed split: left list, right detail.
        left_w = max(20, min(34, width * 2 // 5))
        right_w = max(10, width - left_w - 1)
        self.sep_x = left_w

        # Header: row 0
        self.header_r = Region(0, 0, width, 1)

        # Left: volume list (rows 2..height-2)
        list_top = 2
        list_h = max(1, height - 3)
        self.list_r = Region(0, list_top, left_w, list_h)

        # Right: detail header (6 lines) + dir table (rest)
        right_x = left_w + 1
        detail_h = 4
        self.detail_header_r = Region(right_x, list_top, right_w, min(detail_h, list_h))
        dir_top = list_top + detail_h + 1
        dir_h = max(1, height - dir_top - 1)
        self.dir_table_r = Region(right_x, dir_top, right_w, dir_h)

        # Footer: bottom row
        self.footer_r = Region(0, height - 1, width, 1)

    def render(self) -> None:
        buf = self._buf
        buf.fill(0, 0, buf.width, buf.height, " ", Style())

        # Separator
        for y in range(buf.height):
            if self.sep_x < buf.width:
                buf.put_text(self.sep_x, y, "│", Style(dim=True))

        # Header
        hv = self.header_r.view(buf)
        _put(hv, 1, 0, "Disk Space", Style(bold=True))
        _put(hv, 13, 0, "↑/↓ select  q quit", Style(dim=True))

        # Volume list
        lv = self.list_r.view(buf)
        _render_volume_list(lv, self.volumes, self.selected)

        # Detail (right side)
        vol = self.volumes[max(0, min(self.selected, len(self.volumes) - 1))]
        _render_detail_header(self.detail_header_r.view(buf), vol)

        # Directory label
        dir_label_y = self.dir_table_r.y - 1
        if 0 <= dir_label_y < buf.height:
            buf.put_text(self.sep_x + 2, dir_label_y, "Directories", Style(dim=True))

        _render_dir_table(self.dir_table_r.view(buf), vol)

        # Footer
        fv = self.footer_r.view(buf)
        _put(fv, 1, 0, f" {self.selected + 1}/{len(self.volumes)} ", Style(dim=True))

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return
        if key == "up":
            self.selected = max(0, self.selected - 1)
        elif key == "down":
            self.selected = min(len(self.volumes) - 1, self.selected + 1)


async def main() -> None:
    await DiskApp(volumes=_scan()).run()


if __name__ == "__main__":
    asyncio.run(main())
