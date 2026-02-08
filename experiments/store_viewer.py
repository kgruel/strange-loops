"""Store Viewer — generic TUI for browsing any SqliteStore.

Usage:
    uv run python experiments/store_viewer.py <path-to-store.db>
    uv run python experiments/store_viewer.py --demo   # generate synthetic data

Navigation:
    j/k or arrows  — move cursor
    Enter          — drill into selected item
    Backspace      — go back
    +/-            — adjust zoom level
    f              — fidelity drill (on a tick: show contributing facts)
    a              — toggle fidelity filter (all kinds / single kind)
    Tab            — switch between facts/ticks panels
    q              — quit

Findings from this experiment:

1. Fidelity traversal is cross-cutting. store.between(tick.since, tick.ts)
   returns ALL fact kinds in the window, not just those the spec consumed.
   This is a feature: it surfaces correlations across independent streams
   that no single vertex would show.

2. The complement vertex (HANDOFF.md) dissolves. The manual version is
   this viewer's unfiltered fidelity view — store.between() + kind set
   difference. The automated version ("fire when ignored volume exceeds
   threshold") is a boundary condition on an existing spec, not a new atom.

3. The store is spec-blind. Ticks carry origin (vertex name) but not which
   kinds/folds produced them. Open question: should Tick carry a `spec` or
   `kinds_consumed` field for provenance?

4. This is a store tool, not a cells widget. The interesting behavior is
   queries (fidelity, cross-kind correlation). The TUI adds navigation
   ergonomics but not essence. Graduates to apps/, not cells.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

# Prism imports
sys.path.insert(0, str(Path(__file__).parent.parent / "libs" / "cells" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "libs" / "vertex" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "libs" / "data" / "src"))

from cells import Block, Style, join_vertical, join_horizontal, border, pad, ROUNDED
from cells.tui import Surface
from cells.lens import shape_lens

from engine.store_reader import StoreReader
from engine.tick import Tick


# ── Styles ──────────────────────────────────────────────────────────

DIM = Style(dim=True)
BOLD = Style(bold=True)
CYAN = Style(fg="cyan")
GREEN = Style(fg="green")
YELLOW = Style(fg="yellow")
RED = Style(fg="red")
REVERSE = Style(reverse=True)


# ── View State ──────────────────────────────────────────────────────

class View(Enum):
    OVERVIEW = auto()
    FACT_LIST = auto()
    TICK_LIST = auto()
    FACT_DETAIL = auto()
    TICK_DETAIL = auto()
    FIDELITY = auto()  # facts that produced a tick


class Panel(Enum):
    FACTS = auto()
    TICKS = auto()


@dataclass(frozen=True)
class ViewerState:
    """Immutable state for the store viewer."""

    view: View = View.OVERVIEW
    panel: Panel = Panel.FACTS
    zoom: int = 1

    # Overview cursor
    fact_cursor: int = 0
    tick_cursor: int = 0

    # List view cursor (when drilled into a kind/name)
    list_cursor: int = 0
    selected_kind: str | None = None
    selected_tick_name: str | None = None

    # Detail view
    detail_index: int = 0

    # Fidelity drill
    fidelity_cursor: int = 0
    fidelity_tick: Tick | None = None
    fidelity_filtered: bool = False  # False = all facts in window (truthful), True = single kind

    def move_cursor(self, delta: int, max_idx: int) -> ViewerState:
        """Move the active cursor by delta, clamped to [0, max_idx]."""
        if self.view == View.OVERVIEW:
            if self.panel == Panel.FACTS:
                new = max(0, min(max_idx, self.fact_cursor + delta))
                return replace(self, fact_cursor=new)
            else:
                new = max(0, min(max_idx, self.tick_cursor + delta))
                return replace(self, tick_cursor=new)
        elif self.view in (View.FACT_LIST, View.TICK_LIST):
            new = max(0, min(max_idx, self.list_cursor + delta))
            return replace(self, list_cursor=new)
        elif self.view == View.FIDELITY:
            new = max(0, min(max_idx, self.fidelity_cursor + delta))
            return replace(self, fidelity_cursor=new)
        return self


# ── Store Viewer App ────────────────────────────────────────────────

class StoreViewerApp(Surface):
    """Generic TUI for browsing any SqliteStore."""

    def __init__(self, store_path: Path):
        super().__init__(fps_cap=30)
        self._reader = StoreReader(store_path)
        self._state = ViewerState()
        self._w = 80
        self._h = 24

        # Cache store metadata
        self._fact_stats: dict[str, dict] = {}
        self._tick_stats: dict[str, dict] = {}
        self._fact_kinds: list[str] = []
        self._tick_names: list[str] = []

        # Cache for list/detail views
        self._cached_facts: list[dict] = []
        self._cached_ticks: list[Tick] = []
        self._cached_fidelity: list[dict] = []

        self._refresh_stats()

    def _refresh_stats(self) -> None:
        self._fact_stats = self._reader.fact_kind_stats()
        self._tick_stats = self._reader.tick_name_stats()
        self._fact_kinds = sorted(self._fact_stats.keys())
        self._tick_names = sorted(self._tick_stats.keys())

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def on_key(self, key: str) -> None:
        s = self._state

        if key in ("q", "Q"):
            self.quit()
            return

        # Navigation
        if key in ("j", "down"):
            self._move(1)
        elif key in ("k", "up"):
            self._move(-1)
        elif key in ("g", "home"):
            self._move(-9999)
        elif key in ("G", "end"):
            self._move(9999)

        # Drill in
        elif key in ("enter", "l", "right"):
            self._drill_in()

        # Go back
        elif key in ("backspace", "h", "left"):
            self._drill_out()

        # Fidelity drill
        elif key == "f":
            self._fidelity_drill()

        # Toggle fidelity filter (in fidelity view)
        elif key == "a" and s.view == View.FIDELITY:
            self._toggle_fidelity_filter()

        # Zoom
        elif key in ("+", "="):
            self._state = replace(self._state, zoom=min(3, s.zoom + 1))
        elif key in ("-", "_"):
            self._state = replace(self._state, zoom=max(0, s.zoom - 1))

        # Panel switch
        elif key == "tab":
            new_panel = Panel.TICKS if s.panel == Panel.FACTS else Panel.FACTS
            self._state = replace(self._state, panel=new_panel)

        self.mark_dirty()

    def _move(self, delta: int) -> None:
        s = self._state
        if s.view == View.OVERVIEW:
            if s.panel == Panel.FACTS:
                max_idx = max(0, len(self._fact_kinds) - 1)
            else:
                max_idx = max(0, len(self._tick_names) - 1)
        elif s.view in (View.FACT_LIST, View.TICK_LIST):
            max_idx = max(0, len(self._cached_facts if s.view == View.FACT_LIST else self._cached_ticks) - 1)
        elif s.view == View.FIDELITY:
            max_idx = max(0, len(self._cached_fidelity) - 1)
        else:
            max_idx = 0
        self._state = s.move_cursor(delta, max_idx)

    def _drill_in(self) -> None:
        s = self._state

        if s.view == View.OVERVIEW:
            if s.panel == Panel.FACTS and self._fact_kinds:
                kind = self._fact_kinds[s.fact_cursor]
                self._cached_facts = self._reader.recent_facts(kind, 50)
                self._state = replace(s, view=View.FACT_LIST, selected_kind=kind, list_cursor=0)
            elif s.panel == Panel.TICKS and self._tick_names:
                name = self._tick_names[s.tick_cursor]
                self._cached_ticks = self._reader.recent_ticks(name, 50)
                self._state = replace(s, view=View.TICK_LIST, selected_tick_name=name, list_cursor=0)

        elif s.view == View.FACT_LIST and self._cached_facts:
            self._state = replace(s, view=View.FACT_DETAIL, detail_index=s.list_cursor)

        elif s.view == View.TICK_LIST and self._cached_ticks:
            self._state = replace(s, view=View.TICK_DETAIL, detail_index=s.list_cursor)

    def _drill_out(self) -> None:
        s = self._state

        if s.view in (View.FACT_LIST, View.TICK_LIST):
            self._state = replace(s, view=View.OVERVIEW, list_cursor=0)
        elif s.view in (View.FACT_DETAIL, View.TICK_DETAIL):
            prev = View.FACT_LIST if s.view == View.FACT_DETAIL else View.TICK_LIST
            self._state = replace(s, view=prev)
        elif s.view == View.FIDELITY:
            self._state = replace(s, view=View.TICK_DETAIL, fidelity_cursor=0)

    def _fidelity_drill(self) -> None:
        s = self._state

        if s.view == View.TICK_DETAIL and self._cached_ticks:
            tick = self._cached_ticks[s.detail_index]
            if tick.since is not None:
                self._load_fidelity_facts(tick, kind=None)
                self._state = replace(s, view=View.FIDELITY, fidelity_tick=tick,
                                      fidelity_cursor=0, fidelity_filtered=False)

    def _toggle_fidelity_filter(self) -> None:
        """Toggle between all facts in the window and a specific kind.

        When toggling to filtered, cycles through the kinds present in
        the current (unfiltered) result set rather than inferring from
        the tick name. The store is spec-blind — we show what's there.

        Open question (surfaced by this experiment): should Tick carry a
        `spec` or `kinds_consumed` field so downstream tools can
        reconstruct a fold's input set without heuristics?
        """
        s = self._state
        if s.fidelity_tick is None or s.fidelity_tick.since is None:
            return

        if not s.fidelity_filtered:
            # Switch to filtered: pick the most common kind in the window
            kind_counts: dict[str, int] = {}
            for f in self._cached_fidelity:
                kind_counts[f["kind"]] = kind_counts.get(f["kind"], 0) + 1
            if kind_counts:
                # Start with the kind matching tick origin, fall back to most common
                origin_kind = None
                for k in kind_counts:
                    if s.fidelity_tick.origin and s.fidelity_tick.origin.split(".")[-1] in k:
                        origin_kind = k
                        break
                first_kind = origin_kind or max(kind_counts, key=kind_counts.get)
                self._load_fidelity_facts(s.fidelity_tick, kind=first_kind)
                self._state = replace(s, fidelity_filtered=True, fidelity_cursor=0)
        else:
            # Back to unfiltered
            self._load_fidelity_facts(s.fidelity_tick, kind=None)
            self._state = replace(s, fidelity_filtered=False, fidelity_cursor=0)

    def _load_fidelity_facts(self, tick: Tick, *, kind: str | None) -> None:
        since_ts = tick.since.timestamp()
        ts = tick.ts.timestamp()
        self._cached_fidelity = self._reader.facts_between(since_ts, ts, kind=kind)

    # ── Rendering ───────────────────────────────────────────────────

    def render(self) -> None:
        if self._buf is None:
            return

        s = self._state
        width = self._w - 4  # padding
        height = self._h

        # Header
        header = self._render_header(width)

        # Body
        body_height = height - 4  # header + help + padding
        if s.view == View.OVERVIEW:
            body = self._render_overview(width, body_height)
        elif s.view == View.FACT_LIST:
            body = self._render_fact_list(width, body_height)
        elif s.view == View.TICK_LIST:
            body = self._render_tick_list(width, body_height)
        elif s.view == View.FACT_DETAIL:
            body = self._render_fact_detail(width, body_height)
        elif s.view == View.TICK_DETAIL:
            body = self._render_tick_detail(width, body_height)
        elif s.view == View.FIDELITY:
            body = self._render_fidelity(width, body_height)
        else:
            body = Block.empty(width, body_height)

        # Help
        help_line = self._render_help(width)

        # Compose
        full = join_vertical(header, Block.empty(width, 1), body, Block.empty(width, 1), help_line)
        padded = pad(full, left=2, top=1)

        # Paint
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _render_header(self, width: int) -> Block:
        s = self._state
        freshness = self._reader.freshness
        fresh_str = freshness.strftime("%H:%M:%S") if freshness else "empty"

        title = f"store viewer | {self._reader._path.name}"
        stats = f"{self._reader.fact_total} facts, {self._reader.tick_total} ticks | fresh: {fresh_str}"
        zoom_str = f"zoom:{s.zoom}"
        view_str = s.view.name.lower().replace("_", " ")

        line = f"{title} | {stats} | {view_str} | {zoom_str}"
        if len(line) > width:
            line = line[:width]

        return Block.text(line, BOLD, width=width)

    def _render_help(self, width: int) -> Block:
        s = self._state
        parts = ["[j/k] move", "[q]uit", "[+/-] zoom", "[tab] panel"]

        if s.view == View.OVERVIEW:
            parts.insert(1, "[enter] drill")
        elif s.view in (View.FACT_LIST, View.TICK_LIST):
            parts.insert(1, "[enter] detail")
            parts.insert(2, "[bksp] back")
        elif s.view == View.TICK_DETAIL:
            parts.insert(1, "[f] fidelity")
            parts.insert(2, "[bksp] back")
        elif s.view == View.FIDELITY:
            filter_label = "all" if s.fidelity_filtered else "filtered"
            parts.insert(1, f"[a] {filter_label}")
            parts.insert(2, "[bksp] back")
        elif s.view == View.FACT_DETAIL:
            parts.insert(1, "[bksp] back")

        text = "  ".join(parts)
        return Block.text(text[:width], DIM, width=width)

    def _render_overview(self, width: int, height: int) -> Block:
        s = self._state

        # Two panels: facts and ticks
        left_width = max(20, width // 2 - 1)
        right_width = width - left_width - 1

        # Facts panel
        fact_rows: list[Block] = []
        for i, kind in enumerate(self._fact_kinds):
            stats = self._fact_stats[kind]
            count = stats["count"]
            latest = stats["latest"].strftime("%H:%M:%S")
            line = f"{kind} ({count}) {latest}"
            if len(line) > left_width - 4:
                line = line[:left_width - 5] + "…"
            line = line.ljust(left_width - 4)

            is_cursor = s.panel == Panel.FACTS and i == s.fact_cursor
            style = REVERSE if is_cursor else Style()
            fact_rows.append(Block.text(line, style, width=left_width - 4))

        if not fact_rows:
            fact_rows.append(Block.text("(no facts)", DIM, width=left_width - 4))

        # Pad to fill
        while len(fact_rows) < height - 2:
            fact_rows.append(Block.empty(left_width - 4, 1))

        facts_inner = join_vertical(*fact_rows[:height - 2])
        fact_title = "Facts" if s.panel == Panel.FACTS else "Facts"
        fact_border_style = CYAN if s.panel == Panel.FACTS else DIM
        facts_panel = border(facts_inner, title=fact_title, style=fact_border_style, chars=ROUNDED)

        # Ticks panel
        tick_rows: list[Block] = []
        for i, name in enumerate(self._tick_names):
            stats = self._tick_stats[name]
            count = stats["count"]
            latest = stats["latest"].strftime("%H:%M:%S")
            line = f"{name} ({count}) {latest}"
            if len(line) > right_width - 4:
                line = line[:right_width - 5] + "…"
            line = line.ljust(right_width - 4)

            is_cursor = s.panel == Panel.TICKS and i == s.tick_cursor
            style = REVERSE if is_cursor else Style()
            tick_rows.append(Block.text(line, style, width=right_width - 4))

        if not tick_rows:
            tick_rows.append(Block.text("(no ticks)", DIM, width=right_width - 4))

        while len(tick_rows) < height - 2:
            tick_rows.append(Block.empty(right_width - 4, 1))

        ticks_inner = join_vertical(*tick_rows[:height - 2])
        tick_border_style = CYAN if s.panel == Panel.TICKS else DIM
        ticks_panel = border(ticks_inner, title="Ticks", style=tick_border_style, chars=ROUNDED)

        return join_horizontal(facts_panel, Block.empty(1, facts_panel.height), ticks_panel)

    def _render_fact_list(self, width: int, height: int) -> Block:
        s = self._state
        inner_w = width - 4

        title = f"Facts: {s.selected_kind} ({len(self._cached_facts)})"
        rows: list[Block] = []

        for i, fact in enumerate(self._cached_facts):
            ts = fact["ts"].strftime("%H:%M:%S")
            obs = fact["observer"]
            payload_preview = _payload_one_liner(fact["payload"], inner_w - 25)
            line = f"{ts} {obs:>10} {payload_preview}"
            if len(line) > inner_w:
                line = line[:inner_w - 1] + "…"
            line = line.ljust(inner_w)

            is_cursor = i == s.list_cursor
            style = REVERSE if is_cursor else Style()
            rows.append(Block.text(line, style, width=inner_w))

        if not rows:
            rows.append(Block.text("(no facts)", DIM, width=inner_w))

        while len(rows) < height - 2:
            rows.append(Block.empty(inner_w, 1))

        inner = join_vertical(*rows[:height - 2])
        return border(inner, title=title, style=CYAN, chars=ROUNDED)

    def _render_tick_list(self, width: int, height: int) -> Block:
        s = self._state
        inner_w = width - 4

        title = f"Ticks: {s.selected_tick_name} ({len(self._cached_ticks)})"
        rows: list[Block] = []

        for i, tick in enumerate(self._cached_ticks):
            ts = tick.ts.strftime("%H:%M:%S")
            origin = tick.origin or "?"
            has_since = "F" if tick.since else " "  # F = fidelity traversal available
            payload_preview = _payload_one_liner(tick.payload, inner_w - 25)
            line = f"{ts} [{has_since}] {origin:>10} {payload_preview}"
            if len(line) > inner_w:
                line = line[:inner_w - 1] + "…"
            line = line.ljust(inner_w)

            is_cursor = i == s.list_cursor
            style = REVERSE if is_cursor else Style()
            rows.append(Block.text(line, style, width=inner_w))

        if not rows:
            rows.append(Block.text("(no ticks)", DIM, width=inner_w))

        while len(rows) < height - 2:
            rows.append(Block.empty(inner_w, 1))

        inner = join_vertical(*rows[:height - 2])
        return border(inner, title=title, style=CYAN, chars=ROUNDED)

    def _render_fact_detail(self, width: int, height: int) -> Block:
        s = self._state
        inner_w = width - 4

        if not self._cached_facts or s.detail_index >= len(self._cached_facts):
            return border(Block.text("(no selection)", DIM, width=inner_w), title="Detail", style=CYAN, chars=ROUNDED)

        fact = self._cached_facts[s.detail_index]
        content = {
            "kind": fact["kind"],
            "ts": str(fact["ts"]),
            "observer": fact["observer"],
            "payload": fact["payload"],
        }

        rendered = shape_lens(content, s.zoom, inner_w)

        # Pad to fill
        rows = [rendered]
        total_h = rendered.height
        if total_h < height - 2:
            rows.append(Block.empty(inner_w, height - 2 - total_h))

        inner = join_vertical(*rows)
        title = f"Fact: {fact['kind']} @ {fact['ts'].strftime('%H:%M:%S')}"
        return border(inner, title=title, style=GREEN, chars=ROUNDED)

    def _render_tick_detail(self, width: int, height: int) -> Block:
        s = self._state
        inner_w = width - 4

        if not self._cached_ticks or s.detail_index >= len(self._cached_ticks):
            return border(Block.text("(no selection)", DIM, width=inner_w), title="Detail", style=CYAN, chars=ROUNDED)

        tick = self._cached_ticks[s.detail_index]
        content = {
            "name": tick.name,
            "ts": str(tick.ts),
            "origin": tick.origin,
            "since": str(tick.since) if tick.since else None,
            "payload": tick.payload,
        }

        rendered = shape_lens(content, s.zoom, inner_w)

        fidelity_hint = ""
        if tick.since:
            fidelity_hint = " [f: drill into contributing facts]"

        rows = [rendered]
        total_h = rendered.height
        if fidelity_hint:
            hint_block = Block.text(fidelity_hint, YELLOW, width=inner_w)
            rows.append(hint_block)
            total_h += 1
        if total_h < height - 2:
            rows.append(Block.empty(inner_w, height - 2 - total_h))

        inner = join_vertical(*rows)
        title = f"Tick: {tick.name} @ {tick.ts.strftime('%H:%M:%S')}"
        return border(inner, title=title, style=GREEN, chars=ROUNDED)

    def _render_fidelity(self, width: int, height: int) -> Block:
        s = self._state
        inner_w = width - 4

        tick = s.fidelity_tick
        if tick is None:
            return border(Block.text("(no tick)", DIM, width=inner_w), title="Fidelity", style=CYAN, chars=ROUNDED)

        period = f"{tick.since.strftime('%H:%M:%S')} → {tick.ts.strftime('%H:%M:%S')}" if tick.since else "?"
        if s.fidelity_filtered and self._cached_fidelity:
            filter_tag = self._cached_fidelity[0]["kind"]
        else:
            # Count distinct kinds to show what's in the window
            distinct = len({f["kind"] for f in self._cached_fidelity}) if self._cached_fidelity else 0
            filter_tag = f"all {distinct} kinds"
        title = f"Fidelity: {tick.name} [{period}] ({len(self._cached_fidelity)} facts, {filter_tag})"

        rows: list[Block] = []
        for i, fact in enumerate(self._cached_fidelity):
            ts = fact["ts"].strftime("%H:%M:%S")
            kind = fact["kind"]
            obs = fact["observer"]
            payload_preview = _payload_one_liner(fact["payload"], inner_w - 30)
            line = f"{ts} {kind:>12} {obs:>8} {payload_preview}"
            if len(line) > inner_w:
                line = line[:inner_w - 1] + "…"
            line = line.ljust(inner_w)

            is_cursor = i == s.fidelity_cursor
            style = REVERSE if is_cursor else Style()
            rows.append(Block.text(line, style, width=inner_w))

        if not rows:
            rows.append(Block.text("(no facts in period)", DIM, width=inner_w))

        while len(rows) < height - 2:
            rows.append(Block.empty(inner_w, 1))

        inner = join_vertical(*rows[:height - 2])
        return border(inner, title=title, style=YELLOW, chars=ROUNDED)

    def close(self) -> None:
        self._reader.close()


# ── Helpers ─────────────────────────────────────────────────────────

def _payload_one_liner(payload: Any, max_width: int) -> str:
    """Compress a payload dict into a short one-line preview."""
    if isinstance(payload, dict):
        parts = []
        for k, v in payload.items():
            if isinstance(v, str) and len(v) > 15:
                v = v[:12] + "…"
            parts.append(f"{k}={v}")
        line = " ".join(parts)
    elif isinstance(payload, list):
        line = f"[{len(payload)} items]"
    else:
        line = str(payload)

    if len(line) > max_width:
        line = line[:max_width - 1] + "…"
    return line


# ── Synthetic Data Generator ────────────────────────────────────────

def generate_demo_store(path: Path) -> None:
    """Create a SqliteStore with synthetic homelab-like data."""
    from engine.sqlite_store import SqliteStore
    from atoms import Fact

    store = SqliteStore(
        path=path,
        serialize=lambda f: f.to_dict(),
        deserialize=lambda d: Fact.from_dict(d),
    )

    observers = ["hlab", "cron", "manual"]
    stacks = ["infra", "media", "monitoring"]
    containers = {
        "infra": ["traefik", "portainer", "watchtower", "pihole"],
        "media": ["plex", "sonarr", "radarr", "jackett", "overseerr"],
        "monitoring": ["prometheus", "grafana", "alertmanager", "node-exporter"],
    }
    statuses = ["running", "running", "running", "running", "stopped", "restarting"]

    now = time.time()
    base = now - 3600  # start 1 hour ago

    # Generate facts over the last hour
    for i in range(200):
        ts = base + (i * 18)  # ~every 18 seconds
        stack = random.choice(stacks)
        container = random.choice(containers[stack])
        status = random.choice(statuses)
        observer = random.choice(observers)

        fact = Fact.of(
            f"container.{stack}",
            observer,
            name=container,
            status=status,
            cpu=round(random.uniform(0.1, 45.0), 1),
            memory_mb=random.randint(32, 2048),
            uptime_hours=random.randint(1, 720),
        )
        # Override ts for spread
        fact = Fact(kind=fact.kind, ts=ts, payload=fact.payload, observer=fact.observer)
        store.append(fact)

    # Generate ticks (boundary snapshots)
    # Every ~5 minutes, a health check boundary fires
    tick_interval = 300
    for i in range(12):
        tick_ts = base + (i * tick_interval) + tick_interval
        since_ts = base + (i * tick_interval)

        for stack in stacks:
            stack_containers = containers[stack]
            healthy = random.randint(len(stack_containers) - 1, len(stack_containers))
            total = len(stack_containers)

            tick = Tick(
                name=f"health.{stack}",
                ts=datetime.fromtimestamp(tick_ts, tz=timezone.utc),
                payload={
                    "healthy": healthy,
                    "total": total,
                    "containers": {
                        c: random.choice(["running", "running", "running", "stopped"])
                        for c in stack_containers
                    },
                },
                origin=f"vertex.{stack}",
                since=datetime.fromtimestamp(since_ts, tz=timezone.utc),
            )
            store.append_tick(tick)

    store.close()
    print(f"Generated demo store: {path}")
    print(f"  {store.total if hasattr(store, 'total') else '?'} facts, 36 ticks")


# ── Main ────────────────────────────────────────────────────────────

async def _run_app(path: Path) -> None:
    app = StoreViewerApp(path)
    try:
        await app.run()
    finally:
        app.close()


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--demo":
        demo_path = Path(__file__).parent / "data" / "demo_store.db"
        demo_path.parent.mkdir(exist_ok=True)
        # Remove old demo store if exists
        if demo_path.exists():
            demo_path.unlink()
        generate_demo_store(demo_path)
        print(f"\nRun the viewer:\n  uv run python experiments/store_viewer.py {demo_path}")
        return

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Store not found: {path}")
        sys.exit(1)

    asyncio.run(_run_app(path))


if __name__ == "__main__":
    main()
