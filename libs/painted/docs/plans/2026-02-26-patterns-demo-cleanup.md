# Patterns Demo Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate 5 pattern demos into 2 clean, non-redundant runnable examples that teach lens selection and the CLI harness spectrum.

**Architecture:** Delete 4 files (dead code + redundant fidelity demos + dissolved show.py), rewrite 2 survivors with PEP 723 metadata and styled Block headers (no `print()` commentary), rename `fidelity_disk.py` → `fidelity.py`. Update `demos/CLAUDE.md` ladder.

**Tech Stack:** painted primitives (`Block`, `Style`, `show`, `run_cli`), PEP 723 script metadata.

---

### Task 1: Delete dead and redundant files

**Files:**
- Delete: `demos/demo_utils.py`
- Delete: `demos/patterns/show.py`
- Delete: `demos/patterns/fidelity.py`
- Delete: `demos/patterns/fidelity_health.py`

**Step 1: Verify nothing imports demo_utils**

Run: `cd /Users/kaygee/Code/painted && grep -r "demo_utils" demos/`
Expected: No output (nothing imports it).

**Step 2: Delete the four files**

```bash
git rm demos/demo_utils.py
git rm demos/patterns/show.py
git rm demos/patterns/fidelity.py
git rm demos/patterns/fidelity_health.py
```

**Step 3: Verify tests still pass**

Run: `uv run --package painted pytest tests/ -q`
Expected: 622 passed

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete redundant pattern demos and dead demo_utils

demo_utils.py: dead code, nothing imports render_buffer
patterns/show.py: dissolved into primitives/show.py + auto_dispatch.py
patterns/fidelity.py: redundant with fidelity_disk.py
patterns/fidelity_health.py: redundant with fidelity_disk.py"
```

---

### Task 2: Rewrite `auto_dispatch.py`

**Files:**
- Modify: `demos/patterns/auto_dispatch.py`

The demo teaches lens selection strategy: auto → explicit → custom. Three
CLI modes, each showing one approach. Data stays (CONFIG, METRICS, TRAFFIC,
SERVICE) — good shape variety for triggering different dispatch paths.

**Changes from current:**
- Add PEP 723 header
- Replace `_section()` print helper with styled Block header function
- Replace `print()` calls in demo functions with `show()` of styled Blocks
- Drop `--all` mode and its `print("=" * 60)` banners
- Clean up `main()` dispatcher

**Step 1: Write the new file**

Replace the full file with:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Auto-dispatch — shape_lens picks the right strategy for your data.

Three levels of control over how data becomes Blocks:

  1. show(data)              — auto-dispatch, zero config
  2. Explicit lens           — tree_lens / chart_lens directly
  3. Custom render function  — full control, same signature

Run:
    uv run demos/patterns/auto_dispatch.py
    uv run demos/patterns/auto_dispatch.py --explicit
    uv run demos/patterns/auto_dispatch.py --custom
"""

from __future__ import annotations

import sys

from painted import (
    Block,
    Style,
    Zoom,
    border,
    join_vertical,
    pad,
    print_block,
    show,
    ROUNDED,
)


def header(text: str) -> Block:
    """Dim section header — same pattern as primitives demos."""
    return Block.text(f"  {text}", Style(dim=True))


def spacer() -> Block:
    return Block.text("", Style())


# ---------------------------------------------------------------------------
# Sample data — different shapes trigger different strategies
# ---------------------------------------------------------------------------

# Flat key-value (string values) → dict renderer
CONFIG = {
    "host": "api.example.com",
    "port": "8443",
    "env": "production",
    "region": "us-east-1",
}

# All-numeric values → chart_lens (bar chart)
METRICS = {
    "cpu": 67,
    "memory": 82,
    "disk": 45,
    "network": 23,
    "gpu": 91,
}

# Numeric sequence → chart_lens (sparkline)
TRAFFIC = [12, 15, 23, 45, 67, 89, 95, 87, 76, 65, 54, 48, 52, 61, 73, 82]

# Hierarchical (nested dicts/lists) → tree_lens
SERVICE = {
    "api-gateway": {
        "replicas": {"desired": 3, "ready": 2},
        "endpoints": {
            "/health": {"status": 200, "latency_ms": 12},
            "/api/v1/auth": {"status": 503, "latency_ms": 2100},
        },
    },
    "worker": {
        "replicas": {"desired": 5, "ready": 5},
        "queue_depth": 142,
    },
}


# ---------------------------------------------------------------------------
# Level 1: show(data) — shape_lens auto-dispatches
# ---------------------------------------------------------------------------


def demo_auto():
    """Same function, different data → different rendering."""
    print_block(join_vertical(
        spacer(),
        header("flat dict → key-value"),
    ))
    show(CONFIG, zoom=Zoom.DETAILED)

    print_block(join_vertical(
        spacer(),
        header("numeric dict → bar chart"),
    ))
    show(METRICS, zoom=Zoom.DETAILED)

    print_block(join_vertical(
        spacer(),
        header("numeric list → sparkline"),
    ))
    show(TRAFFIC)

    print_block(join_vertical(
        spacer(),
        header("hierarchical dict → tree"),
    ))
    show(SERVICE, zoom=Zoom.DETAILED)


# ---------------------------------------------------------------------------
# Level 2: Explicit lens — bypass auto-dispatch
# ---------------------------------------------------------------------------


def demo_explicit():
    """Call tree_lens / chart_lens directly for full control."""
    from painted.views import tree_lens, chart_lens

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 0 → stats"),
    ))
    block = chart_lens(METRICS, zoom=0, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 1 → sparkline"),
    ))
    block = chart_lens(METRICS, zoom=1, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("chart_lens: zoom 2 → bars"),
    ))
    block = chart_lens(METRICS, zoom=2, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 0 → root + count"),
    ))
    block = tree_lens(SERVICE, zoom=0, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 1 → immediate children"),
    ))
    block = tree_lens(SERVICE, zoom=1, width=60)
    show(block)

    print_block(join_vertical(
        spacer(),
        header("tree_lens: zoom 3 → full expansion"),
    ))
    block = tree_lens(SERVICE, zoom=3, width=60)
    show(block)


# ---------------------------------------------------------------------------
# Level 3: Custom render function — same (data, zoom, width) -> Block
# ---------------------------------------------------------------------------


def demo_custom():
    """Write your own render function. Same signature, full control."""

    def status_card(data: dict, zoom: int, width: int) -> Block:
        """Custom renderer — builds a styled status card."""
        rows = []
        for name, info in data.items():
            replicas = info.get("replicas", {})
            ready = replicas.get("ready", 0)
            desired = replicas.get("desired", 0)
            ok = ready == desired

            color = "green" if ok else "red"
            icon = "+" if ok else "!"
            row = Block.text(
                f" {icon} {name} ({ready}/{desired} ready)",
                Style(fg=color, bold=True),
            )

            if zoom >= 2:
                details = []
                if "endpoints" in info:
                    for path, ep in info["endpoints"].items():
                        status = ep.get("status", "?")
                        latency = ep.get("latency_ms", "?")
                        ep_color = "green" if status == 200 else "red"
                        details.append(Block.text(
                            f"   {path}: {status} ({latency}ms)",
                            Style(fg=ep_color),
                        ))
                if "queue_depth" in info:
                    details.append(Block.text(
                        f"   queue: {info['queue_depth']}",
                        Style(dim=True),
                    ))
                if details:
                    row = join_vertical(row, *details)

            rows.append(row)

        content = join_vertical(*rows)
        if zoom >= 1:
            content = pad(content, left=1, right=1)
            content = border(content, chars=ROUNDED, style=Style(dim=True))
        return content

    print_block(join_vertical(
        spacer(),
        header("custom lens: zoom 1 → bordered card"),
    ))
    show(SERVICE, lens=status_card, zoom=Zoom.SUMMARY)

    print_block(join_vertical(
        spacer(),
        header("custom lens: zoom 2 → card with details"),
    ))
    show(SERVICE, lens=status_card, zoom=Zoom.DETAILED)


def main():
    args = set(sys.argv[1:])

    if "--explicit" in args:
        demo_explicit()
    elif "--custom" in args:
        demo_custom()
    else:
        demo_auto()


if __name__ == "__main__":
    main()
```

**Step 2: Run all three modes and verify no errors**

```bash
uv run --package painted python demos/patterns/auto_dispatch.py
uv run --package painted python demos/patterns/auto_dispatch.py --explicit
uv run --package painted python demos/patterns/auto_dispatch.py --custom
```
Expected: Each produces styled terminal output, no tracebacks.

**Step 3: Run tests to verify nothing broke**

Run: `uv run --package painted pytest tests/ -q`
Expected: 622 passed

**Step 4: Commit**

```bash
git add demos/patterns/auto_dispatch.py
git commit -m "feat: rewrite auto_dispatch demo with PEP 723 + visual treatment

Replace print() section headers with styled Block headers.
Drop --all mode. Same three levels: auto, explicit, custom."
```

---

### Task 3: Rewrite `fidelity_disk.py` → `fidelity.py`

**Files:**
- Rename: `demos/patterns/fidelity_disk.py` → `demos/patterns/fidelity.py`

The demo teaches the CLI harness spectrum — same data rendered at different
zoom levels via `run_cli`. Disk data chosen because hierarchical data maps
naturally to zoom depth.

**Changes from current:**
- Rename file (it's the only fidelity demo now)
- Add PEP 723 header
- `render_standard()` returns `Block` directly (not `str` → `_text_block`)
- Delete `_text_block` helper
- Consolidate `_human_size()` and `DirEntry.size_human` (DirEntry calls the shared function)
- Update docstring run commands to match new filename
- Clean up `=====` comment banners to match primitives style (`# ---`)

**Step 1: Rename the file**

```bash
cd /Users/kaygee/Code/painted
git mv demos/patterns/fidelity_disk.py demos/patterns/fidelity.py
```

**Step 2: Write the updated file**

Full replacement of `demos/patterns/fidelity.py`. Key changes marked inline:

```python
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
    uv run demos/patterns/fidelity.py -vv -i    # interactive tree
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from painted import (
    Block,
    Style,
    CliContext,
    Zoom,
    OutputMode,
    Format,
    border,
    join_vertical,
    join_horizontal,
    ROUNDED,
    print_block,
    run_cli,
)
from painted.tui import Surface


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


def _human_size(size: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            if unit == "B":
                return f"{size}{unit}"
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


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

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


def render_minimal(data: DiskData) -> Block:
    return Block.text(
        f"{data.used_percent:.0f}% used ({data.used_human}/{data.total_human})",
        Style(),
    )


# --- Zoom 1: directory list ---


def render_standard(data: DiskData) -> Block:
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
    return join_vertical(*rows)


# --- Zoom 2+: styled bars ---


def render_styled(data: DiskData, width: int) -> Block:
    sections: list[Block] = []

    # Overall usage bar
    bar_width = min(40, width - 20)
    filled = int(data.used_percent / 100 * bar_width)

    if data.used_percent > 90:
        bar_style = Style(fg="red", bold=True)
    elif data.used_percent > 75:
        bar_style = Style(fg="yellow")
    else:
        bar_style = Style(fg="green")

    bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
    usage_line = join_horizontal(
        Block.text(f"{data.used_percent:5.1f}% ", bar_style),
        Block.text(bar, bar_style),
        Block.text(f" {data.used_human}/{data.total_human}", Style(dim=True)),
    )
    sections.append(border(usage_line, title=f"Disk: {data.mount}", chars=ROUNDED))

    # Directory breakdown
    rows: list[Block] = []
    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)

    for entry in sorted_entries:
        pct = (entry.size_bytes / data.used_bytes) * 100 if data.used_bytes > 0 else 0

        size_block = Block.text(entry.size_human.rjust(6), Style(bold=True))

        entry_bar_width = 20
        entry_filled = int(pct / 100 * entry_bar_width)
        entry_bar_style = Style(fg="yellow") if pct > 20 else Style(fg="cyan")
        entry_bar = "\u2593" * entry_filled + "\u2591" * (entry_bar_width - entry_filled)

        row = join_horizontal(
            size_block,
            Block.text(" ", Style()),
            Block.text(entry_bar, entry_bar_style),
            Block.text(" ", Style()),
            Block.text(f"{pct:5.1f}%", Style(dim=True)),
            Block.text(f"  {entry.name}", Style()),
        )
        rows.append(row)

    sections.append(border(join_vertical(*rows), title="By Directory", chars=ROUNDED))

    free_style = Style(fg="green" if data.used_percent < 75 else "yellow", bold=True)
    sections.append(Block.text(f"  Free: {data.free_human}  ", free_style))

    return join_vertical(*sections, gap=1)


# --- Interactive: TUI tree browser ---


@dataclass
class TreeNode:
    """Mutable tree node for navigation state."""

    entry: DirEntry
    depth: int
    expanded: bool = False
    parent: "TreeNode | None" = None


class DiskSurface(Surface):
    """Interactive TUI with expandable file tree."""

    def __init__(self, data: DiskData):
        super().__init__()
        self._data = data
        self._width = 80
        self._height = 24
        self._nodes: list[TreeNode] = []
        for entry in data.entries:
            self._nodes.append(TreeNode(entry=entry, depth=0))
        self._selected = 0
        self._scroll_offset = 0

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def _visible_nodes(self) -> list[TreeNode]:
        result: list[TreeNode] = []

        def visit(entries: tuple[DirEntry, ...], depth: int, parent: TreeNode | None = None) -> None:
            for entry in sorted(entries, key=lambda e: e.size_bytes, reverse=True):
                node = TreeNode(entry=entry, depth=depth, parent=parent)
                for n in self._nodes:
                    if n.entry.name == entry.name and n.depth == depth:
                        node.expanded = n.expanded
                        break
                result.append(node)
                if node.expanded and entry.children:
                    visit(entry.children, depth + 1, node)

        visit(self._data.entries, 0)
        self._nodes = result
        return result

    def render(self) -> None:
        if self._buf is None:
            return

        self._buf.fill(0, 0, self._width, self._height, " ", Style())

        # Header
        header_text = f" Disk Usage: {self._data.mount} ".center(self._width)
        Block.text(header_text, Style(bold=True, fg="cyan", reverse=True)).paint(self._buf, 0, 0)

        # Usage bar
        bar_width = min(30, self._width - 30)
        filled = int(self._data.used_percent / 100 * bar_width)
        bar_style = Style(
            fg="green" if self._data.used_percent < 75
            else "yellow" if self._data.used_percent < 90
            else "red",
        )
        join_horizontal(
            Block.text(f" {self._data.used_percent:.0f}% ", bar_style),
            Block.text("\u2588" * filled + "\u2591" * (bar_width - filled), bar_style),
            Block.text(f" {self._data.used_human}/{self._data.total_human} ", Style(dim=True)),
        ).paint(self._buf, 0, 1)

        # Tree
        visible = self._visible_nodes()
        tree_height = self._height - 6
        tree_width = self._width - 2
        tree_box = border(
            self._render_tree(visible, tree_width, tree_height),
            title="Files", chars=ROUNDED,
        )
        tree_box.paint(self._buf, 0, 3)

        # Footer
        Block.text(
            " j/k: navigate  Enter: expand/collapse  q: quit ",
            Style(dim=True),
        ).paint(self._buf, 0, self._height - 1)

    def _render_tree(self, nodes: list[TreeNode], width: int, height: int) -> Block:
        if not nodes:
            return Block.text("(empty)", Style(dim=True))

        self._selected = max(0, min(self._selected, len(nodes) - 1))

        if self._selected < self._scroll_offset:
            self._scroll_offset = self._selected
        elif self._selected >= self._scroll_offset + height:
            self._scroll_offset = self._selected - height + 1

        rows: list[Block] = []
        for i in range(self._scroll_offset, min(self._scroll_offset + height, len(nodes))):
            node = nodes[i]
            selected = i == self._selected
            indent = "  " * node.depth

            if node.entry.children:
                expand = "\u25bc " if node.expanded else "\u25b6 "
            else:
                expand = "  "

            icon = ("\U0001f4c2" if node.expanded else "\U0001f4c1") if node.entry.is_dir else "\U0001f4c4"
            size = node.entry.size_human.rjust(6)

            if node.depth == 0:
                pct = (node.entry.size_bytes / self._data.used_bytes) * 100
            elif node.parent:
                pct = (node.entry.size_bytes / node.parent.entry.size_bytes) * 100
            else:
                pct = 0

            name_width = width - len(indent) - 2 - 2 - 6 - 8
            name = node.entry.name[:name_width].ljust(name_width)

            if selected:
                row_style = Style(reverse=True)
                row = join_horizontal(
                    Block.text(indent, row_style),
                    Block.text(expand, row_style),
                    Block.text(icon + " ", row_style),
                    Block.text(name, row_style),
                    Block.text(size, row_style),
                    Block.text(f" {pct:4.1f}%", row_style),
                )
            else:
                size_style = (
                    Style(fg="yellow", bold=True) if pct > 30
                    else Style(bold=True) if pct > 10
                    else Style()
                )
                row = join_horizontal(
                    Block.text(indent, Style()),
                    Block.text(expand, Style()),
                    Block.text(icon + " ", Style()),
                    Block.text(name, Style()),
                    Block.text(size, size_style),
                    Block.text(f" {pct:4.1f}%", Style(dim=True)),
                )
            rows.append(row)

        return join_vertical(*rows)

    def on_key(self, key: str) -> None:
        visible = self._visible_nodes()

        if key == "q":
            self.quit()
        elif key in ("j", "down"):
            if self._selected < len(visible) - 1:
                self._selected += 1
            self.mark_dirty()
        elif key in ("k", "up"):
            if self._selected > 0:
                self._selected -= 1
            self.mark_dirty()
        elif key == "enter":
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.entry.children:
                    node.expanded = not node.expanded
            self.mark_dirty()
        elif key in ("l", "right"):
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.entry.children and not node.expanded:
                    node.expanded = True
            self.mark_dirty()
        elif key in ("h", "left"):
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.expanded:
                    node.expanded = False
                elif node.depth > 0 and node.parent:
                    for i, n in enumerate(visible):
                        if n.entry == node.parent.entry:
                            self._selected = i
                            break
            self.mark_dirty()


# --- run_cli integration ---


def _fetch() -> DiskData:
    return SAMPLE_DISK


def _render(ctx: CliContext, data: DiskData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:
        return render_standard(data)
    return render_styled(data, ctx.width)


def _handle_interactive(ctx: CliContext) -> int:
    data = _fetch()
    if not ctx.is_tty:
        block = _render(ctx, data)
        print_block(block, use_ansi=(ctx.format == Format.ANSI))
        return 0
    surface = DiskSurface(data)
    asyncio.run(surface.run())
    return 0


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        handlers={OutputMode.INTERACTIVE: _handle_interactive},
        description=__doc__,
        prog="fidelity.py",
    )


if __name__ == "__main__":
    sys.exit(main())
```

**Step 3: Run all zoom levels and verify no errors**

```bash
uv run --package painted python demos/patterns/fidelity.py -q
uv run --package painted python demos/patterns/fidelity.py
uv run --package painted python demos/patterns/fidelity.py -v
uv run --package painted python demos/patterns/fidelity.py -vv
```
Expected: Each produces appropriate output, no tracebacks. (Skip `-i` — requires TTY.)

**Step 4: Run tests**

Run: `uv run --package painted pytest tests/ -q`
Expected: 622 passed

**Step 5: Commit**

```bash
git add demos/patterns/fidelity.py
git commit -m "feat: rename fidelity_disk → fidelity, add PEP 723 + cleanup

Now the canonical fidelity demo. render_standard returns Block
directly (removed _text_block helper). Consolidated _human_size."
```

---

### Task 4: Update `demos/CLAUDE.md`

**Files:**
- Modify: `demos/CLAUDE.md`

**Step 1: Update the file**

Replace the full content with:

```markdown
# demos/ — CLAUDE.md

## What We're Doing

Walking back through what we've built to create a progressive set of
educational demos. Many existing demos were stepping stones during API
development — they reference deleted helpers, reach up the stack, or
demonstrate intermediate APIs that no longer exist. We're replacing them
with demos that teach the final API cleanly.

Drop demos that no longer make sense. Don't preserve something just
because it exists.

## Demo Rules

1. **PEP 723** — `# /// script` metadata, runnable via `uv run demos/primitives/foo.py`
2. **Visual, not explanatory** — no `print()` commentary. The output is the lesson. Use styled Block headers (dim) for section labels.
3. **Own layer only** — use exactly the API you're demonstrating. Don't reach up the stack. Output primitives (`print_block`, `join_vertical`, `Block.text()` for headers) are the baseline display mechanism.
4. **`to_X` bridges are fair game** — each demo can use its type's bridge to the next layer (e.g. `Line.to_block()`). The ladder shows the manual version of what the next step automates.
5. **Sections as `join_vertical` groups** — dim header, spacer, content. Consistent visual rhythm.
6. **Real-ish sample text** — terminal output, deploy messages, status lines. Not "Hello world".

### Patterns rule

Patterns demos are **runnable examples** with CLI flags — the invocation IS the lesson.
Visual-not-explanatory still applies (styled Block headers, not `print()`), but CLI arg
modes are allowed because the lesson is the workflow, not just the types.

## Demo Ladder

Each demo uses the API at its level. The code *is* the lesson.

```
primitives/
  cell.py           Style + print_block                        ✓
  span_line.py      Span, Line, to_block()                     ✓
  compose.py        join, border, pad, truncate, Wrap, Align   ✓
  show.py           show() auto-dispatch                       ✓

patterns/
  auto_dispatch.py  Lens selection: auto → explicit → custom   ✓
  fidelity.py       CLI harness: -q → default → -v → -i       ✓
```

Old stepping stones (`block.py`, `buffer.py`, `buffer_view.py`) deleted —
their content is covered by the ladder or belongs at a different level.
Redundant fidelity demos (`fidelity.py`, `fidelity_health.py`) and
dissolved `show.py` deleted — one canonical example per concept.
```

**Step 2: Commit**

```bash
git add demos/CLAUDE.md
git commit -m "docs: update demo ladder with patterns level"
```

---

### Task 5: Final verification

**Step 1: Run all demos in the ladder**

```bash
# Primitives
uv run --package painted python demos/primitives/cell.py
uv run --package painted python demos/primitives/span_line.py
uv run --package painted python demos/primitives/compose.py
uv run --package painted python demos/primitives/show.py

# Patterns
uv run --package painted python demos/patterns/auto_dispatch.py
uv run --package painted python demos/patterns/auto_dispatch.py --explicit
uv run --package painted python demos/patterns/auto_dispatch.py --custom
uv run --package painted python demos/patterns/fidelity.py -q
uv run --package painted python demos/patterns/fidelity.py
uv run --package painted python demos/patterns/fidelity.py -v
uv run --package painted python demos/patterns/fidelity.py -vv
```
Expected: All produce clean output, no tracebacks.

**Step 2: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: 622 passed

**Step 3: Verify no stale references**

```bash
grep -r "fidelity_disk" demos/ docs/ tests/
grep -r "fidelity_health" demos/ docs/ tests/
grep -r "demo_utils" demos/ docs/ tests/
grep -r "patterns/show" demos/ docs/ tests/
```
Expected: No hits (or only the design doc references, which are historical).
