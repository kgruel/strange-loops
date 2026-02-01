"""Personal Scale: heterogeneous domains through one root vertex.

Demonstrates the loops model at human scale with real data sources:
- infra/disk: real disk usage via df -h
- infra/proc: real process count via ps aux
- personal/calendar: simulated calendar events
- personal/email: simulated email counts

Structure:
    root.vertex
    ├── infra.vertex (disk, proc)
    └── personal.vertex (calendar, email)

Facts flow up, ticks cascade to parent as facts. One root observes all domains.

Run:
    uv run python experiments/personal_scale/main.py
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from data import Fact, Source
from vertex import Vertex, Loop, Tick
from vertex.projection import Projection
from cells import Block, Style, join_vertical, join_horizontal, border, pad
from cells.tui import Surface


# -- Configuration -----------------------------------------------------------

POLL_INTERVAL = 5.0     # Seconds between data collection
MAX_EVENTS = 20         # Events to show in stream


# -- Styles ------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
CYAN = Style(fg="cyan")
CYAN_BOLD = Style(fg="cyan", bold=True)
GREEN = Style(fg="green")
GREEN_BOLD = Style(fg="green", bold=True)
YELLOW = Style(fg="yellow")
YELLOW_BOLD = Style(fg="yellow", bold=True)
MAGENTA = Style(fg="magenta")
MAGENTA_BOLD = Style(fg="magenta", bold=True)
RED = Style(fg="red")
WHITE_BOLD = Style(bold=True)


# -- Event Entry -------------------------------------------------------------

@dataclass(frozen=True)
class EventEntry:
    """An event in the stream display."""
    ts: float
    domain: str
    kind: str
    summary: str
    style: Style = DIM


# -- Folds -------------------------------------------------------------------

def latest_fold(state: Any, payload: dict) -> Any:
    """Keep the latest payload."""
    return payload


def count_fold(state: int, payload: dict) -> int:
    """Count occurrences."""
    return state + 1


def collect_fold(state: list, payload: dict) -> list:
    """Collect payloads, keep last 10."""
    return [*state[-9:], payload]


def by_mount_fold(state: dict, payload: dict) -> dict:
    """Group disk facts by mount point."""
    mount = payload.get("mount", "/")
    result = dict(state)
    result[mount] = {
        "fs": payload.get("fs", "?"),
        "pct": payload.get("pct", 0),
    }
    return result


def infra_summary_fold(state: dict, payload: dict) -> dict:
    """Aggregate infra child ticks."""
    return {
        "updates": state.get("updates", 0) + 1,
        "last_ts": time.time(),
        "disk": payload.get("disk", state.get("disk", {})),
        "proc": payload.get("proc", state.get("proc", 0)),
    }


def personal_summary_fold(state: dict, payload: dict) -> dict:
    """Aggregate personal child ticks."""
    return {
        "updates": state.get("updates", 0) + 1,
        "last_ts": time.time(),
        "calendar": payload.get("calendar", state.get("calendar", {})),
        "email": payload.get("email", state.get("email", {})),
    }


def root_overview_fold(state: dict, payload: dict) -> dict:
    """Aggregate at root level from child vertex ticks."""
    return {
        "snapshots": state.get("snapshots", 0) + 1,
        "last_ts": time.time(),
        "last_source": payload.get("source", "unknown"),
    }


# -- Real Sources ------------------------------------------------------------

def make_disk_source() -> Source:
    """Real disk usage from df -h."""
    from data.parse import Skip, Split, Pick, Rename, Transform, Coerce
    return Source(
        command="df -h",
        kind="disk",
        observer="infra",
        format="lines",
        parse=[
            Skip(startswith="Filesystem"),
            Split(),
            Pick(0, 4, 5),
            Rename({0: "fs", 1: "pct", 2: "mount"}),
            Transform(field="pct", strip="%"),
            Coerce({"pct": int}),
        ],
    )


def make_proc_source() -> Source:
    """Real process count from ps."""
    return Source(
        command="ps aux | wc -l",
        kind="proc",
        observer="infra",
        format="blob",
    )


# -- Simulated Sources -------------------------------------------------------

def simulate_calendar() -> dict:
    """Simulated calendar events."""
    events = [
        {"title": "standup", "time": "09:00"},
        {"title": "lunch", "time": "12:00"},
        {"title": "review", "time": "15:00"},
        {"title": "planning", "time": "16:00"},
    ]
    count = random.randint(1, 4)
    return {"events": events[:count], "count": count}


def simulate_email() -> dict:
    """Simulated email counts."""
    return {
        "inbox": random.randint(10, 100),
        "unread": random.randint(0, 30),
        "flagged": random.randint(0, 5),
    }


# -- Personal Scale App ------------------------------------------------------

class PersonalScaleApp(Surface):
    """Visualization of heterogeneous domains flowing through one root."""

    def __init__(self):
        super().__init__(fps_cap=30, on_emit=self._handle_emit, on_start=self._on_start)
        self._w = 100
        self._h = 40

        self._build_vertices()
        self._sources_task: asyncio.Task | None = None

        # Event stream
        self._events: deque[EventEntry] = deque(maxlen=MAX_EVENTS)

        # Flash states for animation
        self._flashes: dict[str, int] = {}

        # Counters
        self._poll_count = 0
        self._tick_count = 0

    def _build_vertices(self) -> None:
        """Build the nested vertex hierarchy.

        Structure:
          root
          ├── infra (disk, proc)
          └── personal (calendar, email)
        """
        # -- Infra vertex: disk and proc --
        self.infra = Vertex("infra")

        disk_loop = Loop(
            name="disk",
            projection=Projection({}, fold=by_mount_fold),
            boundary_kind="disk.complete",
        )
        self.infra.register_loop(disk_loop)

        proc_loop = Loop(
            name="proc",
            projection=Projection(0, fold=lambda s, p: int(p.get("text", "0").strip())),
            boundary_kind="proc.complete",
        )
        self.infra.register_loop(proc_loop)

        # -- Personal vertex: calendar and email --
        self.personal = Vertex("personal")

        calendar_loop = Loop(
            name="calendar",
            projection=Projection({}, fold=latest_fold),
            boundary_kind="calendar.update",
        )
        self.personal.register_loop(calendar_loop)

        email_loop = Loop(
            name="email",
            projection=Projection({}, fold=latest_fold),
            boundary_kind="email.update",
        )
        self.personal.register_loop(email_loop)

        # -- Root vertex: aggregates all --
        self.root = Vertex("root")

        # Folds for child tick facts
        infra_tick_loop = Loop(
            name="infra.status",
            projection=Projection(
                {"updates": 0, "disk": {}, "proc": 0},
                fold=infra_summary_fold,
            ),
            boundary_kind=None,
        )
        self.root.register_loop(infra_tick_loop)

        personal_tick_loop = Loop(
            name="personal.status",
            projection=Projection(
                {"updates": 0, "calendar": {}, "email": {}},
                fold=personal_summary_fold,
            ),
            boundary_kind=None,
        )
        self.root.register_loop(personal_tick_loop)

        # Overview fold triggered by child updates
        overview_loop = Loop(
            name="overview",
            projection=Projection(
                {"snapshots": 0, "last_ts": 0, "last_source": ""},
                fold=root_overview_fold,
            ),
            boundary_kind="snapshot.trigger",
        )
        self.root.register_loop(overview_loop)

        # Wire nesting
        self.root.add_child(self.infra)
        self.root.add_child(self.personal)

    def _flash(self, node: str, frames: int = 8) -> None:
        """Start flash effect."""
        self._flashes[node] = frames

    def _is_flashing(self, node: str) -> bool:
        """Check if node is flashing."""
        return self._flashes.get(node, 0) > 0

    async def _on_start(self) -> None:
        """Start source polling."""
        self._sources_task = asyncio.create_task(self._poll_sources())

    async def _poll_sources(self) -> None:
        """Poll real and simulated sources."""
        disk_source = make_disk_source()
        proc_source = make_proc_source()

        while True:
            self._poll_count += 1
            now = time.time()

            # -- Disk (real) --
            try:
                async for fact in disk_source.stream():
                    if fact.kind == "disk":
                        self.root.receive(fact)
                        mount = fact.payload.get("mount", "/")
                        pct = fact.payload.get("pct", "?")
                        self._add_event("infra", "disk", f"{mount}: {pct}%", YELLOW)
                        self._flash("disk")
                    elif fact.kind == "disk.complete":
                        # Trigger boundary
                        tick = self.root.receive(fact)
                        if tick:
                            self._handle_tick("infra", "disk", tick)
                    break  # disk_source runs once per iteration
            except Exception as e:
                self._add_event("infra", "disk.error", str(e)[:30], RED)

            # -- Proc (real) --
            try:
                async for fact in proc_source.stream():
                    if fact.kind == "proc":
                        self.root.receive(fact)
                        count = fact.payload.get("text", "0").strip()
                        self._add_event("infra", "proc", f"count={count}", YELLOW)
                        self._flash("proc")
                    elif fact.kind == "proc.complete":
                        tick = self.root.receive(fact)
                        if tick:
                            self._handle_tick("infra", "proc", tick)
                    break
            except Exception as e:
                self._add_event("infra", "proc.error", str(e)[:30], RED)

            # -- Calendar (simulated) --
            cal_data = simulate_calendar()
            cal_fact = Fact.of("calendar", "personal", **cal_data)
            self.root.receive(cal_fact)
            self._add_event("personal", "calendar", f"{cal_data['count']} events", CYAN)
            self._flash("calendar")

            # Trigger calendar boundary
            cal_boundary = Fact.of("calendar.update", "personal")
            tick = self.root.receive(cal_boundary)
            if tick:
                self._handle_tick("personal", "calendar", tick)

            # -- Email (simulated) --
            email_data = simulate_email()
            email_fact = Fact.of("email", "personal", **email_data)
            self.root.receive(email_fact)
            self._add_event(
                "personal", "email",
                f"inbox={email_data['inbox']} unread={email_data['unread']}",
                CYAN
            )
            self._flash("email")

            # Trigger email boundary
            email_boundary = Fact.of("email.update", "personal")
            tick = self.root.receive(email_boundary)
            if tick:
                self._handle_tick("personal", "email", tick)

            # -- Emit infra.status as tick-to-fact for root --
            self._emit_child_tick("infra", {
                "disk": self.infra.state("disk"),
                "proc": self.infra.state("proc"),
            })

            # -- Emit personal.status as tick-to-fact for root --
            self._emit_child_tick("personal", {
                "calendar": self.personal.state("calendar"),
                "email": self.personal.state("email"),
            })

            # -- Trigger root snapshot --
            snapshot_trigger = Fact.of("snapshot.trigger", "system")
            tick = self.root.receive(snapshot_trigger)
            if tick:
                self._tick_count += 1
                self._flash("root")
                self._add_event("root", "snapshot", f"#{self._tick_count}", WHITE_BOLD)

            self.mark_dirty()
            await asyncio.sleep(POLL_INTERVAL)

    def _emit_child_tick(self, child_name: str, payload: dict) -> None:
        """Simulate tick-to-fact from child to root."""
        # This is what happens automatically with nested vertices
        tick_fact = Fact.of(f"{child_name}.status", child_name, **payload, source=child_name)
        self.root.receive(tick_fact)
        self._flash(child_name)
        self._add_event("root", f"{child_name}.status", "tick received", GREEN)

    def _handle_tick(self, domain: str, kind: str, tick: Tick) -> None:
        """Handle a tick from a fold boundary."""
        self._tick_count += 1
        self._add_event(domain, f"{kind}.tick", f"boundary fired", MAGENTA)

    def _add_event(self, domain: str, kind: str, summary: str, style: Style) -> None:
        """Add event to stream."""
        self._events.append(EventEntry(
            ts=time.time(),
            domain=domain,
            kind=kind,
            summary=summary,
            style=style,
        ))

    def _handle_emit(self, kind: str, data: dict) -> None:
        """Handle UI emissions."""
        pass

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def update(self) -> None:
        """Decay flash effects."""
        for node in list(self._flashes.keys()):
            if self._flashes[node] > 0:
                self._flashes[node] -= 1
                self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        content_width = min(self._w - 4, 120)

        # Title
        title = Block.text(
            " PERSONAL SCALE ".center(content_width, "─"),
            WHITE_BOLD,
            width=content_width
        )
        subtitle = Block.text(
            f"polls: {self._poll_count}  ticks: {self._tick_count}".center(content_width),
            DIM,
            width=content_width
        )

        # Hierarchy diagram
        diagram = self._render_hierarchy(content_width)

        # State panels
        panels = self._render_state_panels(content_width)

        # Event stream
        stream = self._render_event_stream(content_width, 10)

        # Help
        help_text = "[q]uit  [r]efresh now"
        help_line = Block.text(help_text.center(content_width), DIM, width=content_width)

        content = join_vertical(
            title,
            subtitle,
            Block.empty(content_width, 1),
            diagram,
            Block.empty(content_width, 1),
            panels,
            Block.empty(content_width, 1),
            stream,
            Block.empty(content_width, 1),
            help_line,
        )

        padded = pad(content, left=2, top=1)
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _render_hierarchy(self, width: int) -> Block:
        """Render the vertex hierarchy."""
        lines = []

        def pulse(name: str, label: str, style: Style) -> Block:
            char = "●" if self._is_flashing(name) else "○"
            s = style if self._is_flashing(name) else DIM
            return Block.text(f"{char} {label}", s)

        # Root
        lines.append(join_horizontal(
            Block.text("         ", DIM),
            pulse("root", "root", WHITE_BOLD),
            Block.text(f"  [{self.root.state('overview').get('snapshots', 0)} snapshots]", DIM),
        ))
        lines.append(Block.text("        ╱ ╲", DIM, width=width))

        # Children
        infra_state = self.root.state("infra.status")
        personal_state = self.root.state("personal.status")

        lines.append(join_horizontal(
            Block.text("      ", DIM),
            pulse("infra", "infra", YELLOW_BOLD),
            Block.text(f" [{infra_state.get('updates', 0)} updates]", DIM),
            Block.text("     ", DIM),
            pulse("personal", "personal", CYAN_BOLD),
            Block.text(f" [{personal_state.get('updates', 0)} updates]", DIM),
        ))
        lines.append(Block.text("      ╱ ╲            ╱ ╲", DIM, width=width))

        # Leaves
        lines.append(join_horizontal(
            Block.text("   ", DIM),
            pulse("disk", "disk", YELLOW),
            Block.text("  ", DIM),
            pulse("proc", "proc", YELLOW),
            Block.text("       ", DIM),
            pulse("calendar", "cal", CYAN),
            Block.text("  ", DIM),
            pulse("email", "email", CYAN),
        ))

        content = join_vertical(*lines)
        return border(content, title="HIERARCHY", style=DIM, title_style=WHITE_BOLD)

    def _render_state_panels(self, width: int) -> Block:
        """Render state for each domain."""
        panel_width = (width - 8) // 2

        # Infra panel
        disk_state = self.infra.state("disk")
        proc_state = self.infra.state("proc")

        infra_lines = [
            Block.text("DISK USAGE", YELLOW_BOLD, width=panel_width - 4),
        ]
        if isinstance(disk_state, dict) and disk_state:
            for mount, data in list(disk_state.items())[:4]:
                pct = data.get("pct", 0) if isinstance(data, dict) else 0
                bar_width = 15
                filled = int(bar_width * pct / 100)
                bar = "█" * filled + "░" * (bar_width - filled)
                pct_style = RED if pct > 80 else YELLOW if pct > 60 else GREEN
                line = f"  {mount[:12]:12s} [{bar}] {pct:3d}%"
                infra_lines.append(Block.text(line, pct_style, width=panel_width - 4))
        else:
            infra_lines.append(Block.text("  (waiting for data)", DIM, width=panel_width - 4))

        infra_lines.append(Block.empty(panel_width - 4, 1))
        infra_lines.append(Block.text("PROCESSES", YELLOW_BOLD, width=panel_width - 4))
        proc_count = proc_state if isinstance(proc_state, int) else 0
        infra_lines.append(Block.text(f"  count: {proc_count}", YELLOW, width=panel_width - 4))

        infra_content = join_vertical(*infra_lines)
        infra_panel = border(
            infra_content,
            title="INFRA",
            style=YELLOW if self._is_flashing("infra") else DIM,
            title_style=YELLOW_BOLD
        )

        # Personal panel
        cal_state = self.personal.state("calendar")
        email_state = self.personal.state("email")

        personal_lines = [
            Block.text("CALENDAR", CYAN_BOLD, width=panel_width - 4),
        ]
        if isinstance(cal_state, dict) and cal_state:
            events = cal_state.get("events", [])
            for ev in events[:3]:
                if isinstance(ev, dict):
                    line = f"  {ev.get('time', '??:??')} {ev.get('title', '?')}"
                    personal_lines.append(Block.text(line, CYAN, width=panel_width - 4))
            count = cal_state.get("count", len(events))
            personal_lines.append(Block.text(f"  ({count} events total)", DIM, width=panel_width - 4))
        else:
            personal_lines.append(Block.text("  (waiting for data)", DIM, width=panel_width - 4))

        personal_lines.append(Block.empty(panel_width - 4, 1))
        personal_lines.append(Block.text("EMAIL", CYAN_BOLD, width=panel_width - 4))
        if isinstance(email_state, dict) and email_state:
            inbox = email_state.get("inbox", 0)
            unread = email_state.get("unread", 0)
            flagged = email_state.get("flagged", 0)
            personal_lines.append(Block.text(f"  inbox: {inbox}", CYAN, width=panel_width - 4))
            unread_style = RED if unread > 20 else YELLOW if unread > 10 else GREEN
            personal_lines.append(Block.text(f"  unread: {unread}", unread_style, width=panel_width - 4))
            personal_lines.append(Block.text(f"  flagged: {flagged}", MAGENTA, width=panel_width - 4))
        else:
            personal_lines.append(Block.text("  (waiting for data)", DIM, width=panel_width - 4))

        personal_content = join_vertical(*personal_lines)
        personal_panel = border(
            personal_content,
            title="PERSONAL",
            style=CYAN if self._is_flashing("personal") else DIM,
            title_style=CYAN_BOLD
        )

        return join_horizontal(infra_panel, Block.empty(4, 1), personal_panel)

    def _render_event_stream(self, width: int, height: int) -> Block:
        """Render scrolling event stream."""
        lines = []

        events = list(self._events)[-height:]
        for event in reversed(events):
            ts_str = datetime.fromtimestamp(event.ts).strftime("%H:%M:%S")
            line = f"{ts_str}  {event.domain:10s} {event.kind:20s} {event.summary}"
            if len(line) > width - 4:
                line = line[:width - 5] + "…"
            lines.append(Block.text(line, event.style, width=width - 4))

        while len(lines) < height:
            lines.append(Block.empty(width - 4, 1))

        content = join_vertical(*lines)
        return border(content, title="EVENT STREAM", style=DIM, title_style=WHITE_BOLD)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self._shutdown()
        elif key == "r":
            # Force immediate refresh by resetting poll timer
            self._add_event("system", "refresh", "manual trigger", GREEN_BOLD)
            self.mark_dirty()

    def _shutdown(self) -> None:
        if self._sources_task and not self._sources_task.done():
            self._sources_task.cancel()
        self.quit()


# -- Main --------------------------------------------------------------------

async def main():
    app = PersonalScaleApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
