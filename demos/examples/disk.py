#!/usr/bin/env python3
"""Disk Space — interactive disk usage visualization.

Region-based layout: layout() computes fixed regions once per resize,
render() fills them. Content never dictates geometry — regions do.

Scans real filesystem data on startup.

Keys:
  ↑/↓        navigate (volumes or directories)
  enter      drill into directory
  backspace  go back up
  tab        switch focus (volumes / directories)
  v          cycle view (tree / bars / chart / flame)
  q          quit

Run: uv run python demos/examples/disk.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
import time
from dataclasses import dataclass

from painted import Block, Style
from painted._components.spinner import SpinnerState
from painted.inplace import InPlaceRenderer
from painted.buffer import BufferView
from painted.region import Region
from painted.tui import Surface
from painted.views import ProgressState, chart_lens, flame_lens, progress_bar, tree_lens


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
    is_dir: bool = False
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
                    entries.append(DirEntry(e.name, size, is_dir=True, children=children))
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
    view: BufferView, volumes: tuple[Volume, ...], selected: int,
    *, focused: bool = True,
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

        _put(view, 0, idx, f"{marker} {mount} {pct_s} ", Style(bold=is_sel and focused))

        bar_x = 2 + mount_w + 1 + 6 + 1
        bar = progress_bar(
            ProgressState(value=vol.used_bytes / vol.total_bytes if vol.total_bytes else 0.0),
            width=min(bar_w, w - bar_x),
            filled_style=Style(fg=color, bold=is_sel and focused),
            empty_style=Style(dim=True),
        )
        bar.paint(view, bar_x, idx)


def _render_detail_header(view: BufferView, vol: Volume, breadcrumb: str) -> None:
    """Render the volume summary into a fixed-size BufferView."""
    w = view.width
    color = _usage_color(vol.used_percent)

    _put(view, 1, 0, breadcrumb, Style(fg=color, bold=True))

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


def _render_dir_table(
    view: BufferView, entries: tuple[DirEntry, ...], parent_bytes: int,
    selected: int, *, focused: bool = True,
) -> None:
    """Render the directory breakdown into a fixed-size BufferView."""
    w = view.width
    bar_w = max(4, min(16, w - 24))

    y = 0
    for idx, entry in enumerate(entries):
        if y >= view.height:
            break
        is_sel = idx == selected
        if is_sel:
            style = Style(bold=True, fg="cyan") if focused else Style(dim=True)
            _put(view, 0, y, ">", style)
        _render_dir_row(view, y, entry, parent_bytes, bar_w, w, indent=0, x_offset=2)
        y += 1
        if entry.children:
            for child in sorted(entry.children, key=lambda e: e.size_bytes, reverse=True)[:3]:
                if y >= view.height:
                    break
                _render_dir_row(view, y, child, entry.size_bytes, bar_w, w, indent=1, x_offset=2)
                y += 1


def _render_dir_row(
    view: BufferView, y: int, entry: DirEntry, parent_bytes: int,
    bar_w: int, total_w: int, *, indent: int, x_offset: int = 0,
) -> None:
    pct = min(1.0, entry.size_bytes / parent_bytes) if parent_bytes > 0 else 0.0
    size_s = entry.size_human.rjust(6)
    pct_s = f"{pct * 100:5.1f}%"
    prefix = "  " * indent
    name_x = x_offset + 6 + 1 + bar_w + 1 + 6 + 1 + len(prefix)
    name_w = max(0, total_w - name_x)

    _put(view, x_offset, y, size_s, Style(bold=indent == 0))

    bar = progress_bar(
        ProgressState(value=pct),
        width=bar_w,
        filled_style=Style(fg="cyan" if pct < 0.2 else "yellow"),
        empty_style=Style(dim=True),
    )
    bar.paint(view, x_offset + 7, y)

    _put(view, x_offset + 7 + bar_w + 1, y, pct_s, Style(dim=True))
    _put(view, name_x, y, (prefix + entry.name)[:name_w], Style(dim=indent > 0))


# ---------------------------------------------------------------------------
# View modes — lens-based rendering of directory entries
# ---------------------------------------------------------------------------

_VIEW_MODES = ("bars", "tree", "chart", "flame")


def _entries_to_tree(entries: tuple[DirEntry, ...]) -> dict[str, object]:
    """Convert DirEntry list to nested dict for tree_lens."""
    result: dict[str, object] = {}
    for e in entries:
        if e.children:
            result[e.name] = _entries_to_tree(e.children)
        else:
            result[e.name] = e.size_bytes
    return result


def _tree_node_renderer(key: str, value: object, depth: int) -> Block:
    """Show entry name with human-readable size."""
    if isinstance(value, dict):
        total = sum(v for v in value.values() if isinstance(v, (int, float)))
        return Block.text(f"{key}  {_human_size(int(total))}", Style())
    if isinstance(value, (int, float)):
        return Block.text(f"{key}  {_human_size(int(value))}", Style())
    return Block.text(key, Style())


def _entries_to_chart(entries: tuple[DirEntry, ...]) -> dict[str, float]:
    """Convert DirEntry list to {name: size} for chart_lens."""
    return {e.name: float(e.size_bytes) for e in entries[:20]}


def _entries_to_flame(entries: tuple[DirEntry, ...]) -> dict[str, object]:
    """Convert DirEntry list to nested dict for flame_lens."""
    result: dict[str, object] = {}
    for e in entries:
        if e.children:
            result[e.name] = {c.name: c.size_bytes for c in e.children}
        else:
            result[e.name] = e.size_bytes
    return result


def _render_lens_view(
    view: BufferView,
    entries: tuple[DirEntry, ...],
    mode: str,
) -> None:
    """Render entries using a lens into the given BufferView."""
    w, h = view.width, view.height
    if not entries or w <= 0 or h <= 0:
        return
    if mode == "tree":
        data = _entries_to_tree(entries)
        block = tree_lens(data, zoom=3, width=w, node_renderer=_tree_node_renderer)
    elif mode == "chart":
        data = _entries_to_chart(entries)
        block = chart_lens(data, zoom=3, width=w)
    else:  # flame
        data = _entries_to_flame(entries)
        block = flame_lens(data, zoom=2, width=w)
    block.paint(view, 0, 0)


# ---------------------------------------------------------------------------
# Interactive tree view
# ---------------------------------------------------------------------------

# Row tuple: (entry, depth, path, is_expanded, is_last)
type TreeRow = tuple[DirEntry, int, tuple[str, ...], bool, bool]


def _flatten_tree(
    entries: tuple[DirEntry, ...],
    expanded: set[tuple[str, ...]],
    lazy_children: dict[tuple[str, ...], tuple[DirEntry, ...]] | None = None,
    path_prefix: tuple[str, ...] = (),
) -> list[TreeRow]:
    """Depth-first flatten of entries respecting expanded set.

    Children come from lazy_children (on-demand scans) first, then
    entry.children (pre-scanned). Any directory is expandable.
    """
    rows: list[TreeRow] = []
    for i, entry in enumerate(entries):
        path = (*path_prefix, entry.name)
        is_last = i == len(entries) - 1
        is_expanded = path in expanded and entry.is_dir
        rows.append((entry, len(path_prefix), path, is_expanded, is_last))
        if is_expanded:
            children = (
                (lazy_children or {}).get(path)
                or entry.children
            )
            if children:
                sorted_children = tuple(
                    sorted(children, key=lambda e: e.size_bytes, reverse=True)
                )
                rows.extend(_flatten_tree(sorted_children, expanded, lazy_children, path))
    return rows


def _render_tree_view(
    view: BufferView,
    rows: list[TreeRow],
    selected: int,
    *,
    focused: bool = True,
) -> None:
    """Render flattened tree rows into a BufferView."""
    w = view.width
    if not rows or w <= 0:
        return

    # Track which depths have a continuing vertical line
    # (ancestor is not the last sibling at that depth)
    continuing: set[int] = set()

    for idx, (entry, depth, _path, is_expanded, is_last) in enumerate(rows):
        if idx >= view.height:
            break
        is_sel = idx == selected

        # Cursor marker
        if is_sel:
            style = Style(bold=True, fg="cyan") if focused else Style(dim=True)
            _put(view, 0, idx, ">", style)

        # Build tree prefix: "│  " for continuing ancestors, "   " otherwise
        x = 2
        for d in range(depth):
            if d in continuing:
                _put(view, x, idx, "│", Style(dim=True))
            x += 3

        # Branch character for non-root entries
        if depth > 0:
            branch = "└── " if is_last else "├── "
            _put(view, x - 3, idx, branch, Style(dim=True))

        # Expand/collapse indicator for directories
        if entry.is_dir:
            indicator = "▼ " if is_expanded else "▶ "
            _put(view, x, idx, indicator, Style(fg="cyan" if is_sel else "white"))
            x += 2

        # Entry name + size — dirs get trailing /, files are dim
        suffix = "/" if entry.is_dir else ""
        size_s = f"  {entry.size_human}"
        name_w = max(0, w - x - len(suffix) - len(size_s))
        name = entry.name[:name_w]
        if is_sel:
            name_style = Style(bold=True, fg="cyan") if focused else Style(dim=True)
        elif entry.is_dir:
            name_style = Style()
        else:
            name_style = Style(dim=True)
        _put(view, x, idx, name + suffix, name_style)
        _put(view, x + len(name) + len(suffix), idx, size_s, Style(dim=True))

        # Update continuing set for children that follow
        if is_last:
            continuing.discard(depth)
        else:
            continuing.add(depth)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class DiskApp(Surface):
    def __init__(self, *, volumes: tuple[Volume, ...]) -> None:
        super().__init__()
        self.volumes = volumes
        self.selected = 0
        self.focus = "volumes"  # "volumes" or "dirs"
        self.nav_stack: list[str] = []  # relative path components from mount
        self.dir_selected = 0
        self.view_mode = 0  # index into _VIEW_MODES
        self.tree_expanded: set[tuple[str, ...]] = set()
        self.tree_children: dict[tuple[str, ...], tuple[DirEntry, ...]] = {}
        self.current_entries: tuple[DirEntry, ...] = ()
        if volumes:
            self.current_entries = volumes[0].entries

        # Regions computed in layout()
        self.header_r = Region(0, 0, 0, 0)
        self.list_r = Region(0, 0, 0, 0)
        self.detail_header_r = Region(0, 0, 0, 0)
        self.dir_table_r = Region(0, 0, 0, 0)
        self.footer_r = Region(0, 0, 0, 0)
        self.sep_x = 0

    def _current_vol(self) -> Volume:
        return self.volumes[max(0, min(self.selected, len(self.volumes) - 1))]

    def _current_path(self) -> str:
        vol = self._current_vol()
        if not self.nav_stack:
            return vol.mount
        return os.path.join(vol.mount, *self.nav_stack)

    def _breadcrumb(self) -> str:
        vol = self._current_vol()
        if not self.nav_stack:
            return vol.mount
        parts = [vol.mount] + list(self.nav_stack)
        return " > ".join(parts)

    def _sync_entries(self) -> None:
        """Refresh directory entries for the current navigation path."""
        if not self.nav_stack:
            self.current_entries = self._current_vol().entries
        else:
            self.current_entries = _scan_entries(self._current_path(), depth=2)
        self.dir_selected = 0
        self.tree_expanded = set()
        self.tree_children = {}

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
        _put(hv, 13, 0, "↑↓ nav  ⏎ enter  ⌫ back  tab focus  v view  q quit", Style(dim=True))

        # Volume list
        lv = self.list_r.view(buf)
        _render_volume_list(lv, self.volumes, self.selected, focused=self.focus == "volumes")

        # Detail (right side)
        vol = self._current_vol()
        _render_detail_header(self.detail_header_r.view(buf), vol, self._breadcrumb())

        # Directory label
        dir_label_y = self.dir_table_r.y - 1
        if 0 <= dir_label_y < buf.height:
            label = "Directories"
            if self.nav_stack:
                label = self.nav_stack[-1]
            buf.put_text(self.sep_x + 2, dir_label_y, label, Style(dim=True))

        # Directory table / lens view
        mode = _VIEW_MODES[self.view_mode]
        if mode == "bars":
            # Clamp selection to valid range
            if self.current_entries:
                self.dir_selected = min(self.dir_selected, len(self.current_entries) - 1)
            parent_bytes = vol.used_bytes if not self.nav_stack else (
                sum(e.size_bytes for e in self.current_entries) or 1
            )
            _render_dir_table(
                self.dir_table_r.view(buf),
                self.current_entries,
                parent_bytes,
                self.dir_selected,
                focused=self.focus == "dirs",
            )
        elif mode == "tree":
            rows = _flatten_tree(
                self.current_entries, self.tree_expanded, self.tree_children,
            )
            if rows:
                self.dir_selected = min(self.dir_selected, len(rows) - 1)
            _render_tree_view(
                self.dir_table_r.view(buf),
                rows,
                self.dir_selected,
                focused=self.focus == "dirs",
            )
        else:
            _render_lens_view(
                self.dir_table_r.view(buf),
                self.current_entries,
                mode,
            )

        # Footer
        fv = self.footer_r.view(buf)
        vol_info = f" {self.selected + 1}/{len(self.volumes)} "
        if self.nav_stack:
            vol_info += f" depth:{len(self.nav_stack)} "
        _put(fv, 1, 0, vol_info, Style(dim=True))
        view_label = f"[{mode}]"
        _put(fv, fv.width - len(view_label) - 1, 0, view_label, Style(fg="cyan"))

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return
        if key == "tab":
            self.focus = "dirs" if self.focus == "volumes" else "volumes"
            return
        if key == "v":
            self.view_mode = (self.view_mode + 1) % len(_VIEW_MODES)
            return

        if self.focus == "volumes":
            if key == "enter":
                # Drill into the selected volume's directory pane
                self.focus = "dirs"
                return
            old = self.selected
            if key == "up":
                self.selected = max(0, self.selected - 1)
            elif key == "down":
                self.selected = min(len(self.volumes) - 1, self.selected + 1)
            if self.selected != old:
                self.nav_stack.clear()
                self._sync_entries()
        elif self.focus == "dirs":
            mode = _VIEW_MODES[self.view_mode]
            if mode == "tree":
                self._on_key_tree(key)
            elif mode == "bars":
                self._on_key_bars(key)
            else:
                # chart/flame: only backspace
                if key == "backspace":
                    self._nav_back()

    def _nav_back(self) -> None:
        """Pop nav_stack or return focus to volumes."""
        if self.nav_stack:
            self.nav_stack.pop()
            self._sync_entries()
        else:
            self.focus = "volumes"

    def _on_key_bars(self, key: str) -> None:
        if key == "up":
            self.dir_selected = max(0, self.dir_selected - 1)
        elif key == "down":
            if self.current_entries:
                self.dir_selected = min(
                    len(self.current_entries) - 1, self.dir_selected + 1
                )
        elif key == "enter":
            if (
                self.current_entries
                and self.dir_selected < len(self.current_entries)
            ):
                entry = self.current_entries[self.dir_selected]
                if entry.is_dir:
                    self.nav_stack.append(entry.name)
                    self._sync_entries()
        elif key == "backspace":
            self._nav_back()

    def _on_key_tree(self, key: str) -> None:
        rows = _flatten_tree(
            self.current_entries, self.tree_expanded, self.tree_children,
        )
        if key == "up":
            self.dir_selected = max(0, self.dir_selected - 1)
        elif key == "down":
            if rows:
                self.dir_selected = min(len(rows) - 1, self.dir_selected + 1)
        elif key == "enter":
            if rows and self.dir_selected < len(rows):
                entry, _depth, path, is_expanded, _is_last = rows[self.dir_selected]
                if entry.is_dir:
                    if is_expanded:
                        self.tree_expanded.discard(path)
                    else:
                        self.tree_expanded.add(path)
                        # Lazy-scan: if no children available, scan the filesystem
                        if not entry.children and path not in self.tree_children:
                            fs_path = os.path.join(self._current_path(), *path)
                            self.tree_children[path] = _scan_entries(fs_path, depth=2)
        elif key == "backspace":
            self._nav_back()


async def main() -> None:
    # Scan with a loading spinner
    result: list[tuple[Volume, ...]] = []

    def _do_scan() -> None:
        result.append(_scan())

    thread = threading.Thread(target=_do_scan)
    thread.start()

    with InPlaceRenderer() as renderer:
        ss = SpinnerState()
        while thread.is_alive():
            char = ss.frames.frames[ss.frame]
            frame = Block.text(f" {char} Scanning volumes…", Style(dim=True))
            renderer.render(frame)
            ss = ss.tick()
            time.sleep(0.08)
        renderer.clear()

    await DiskApp(volumes=result[0]).run()


if __name__ == "__main__":
    asyncio.run(main())
