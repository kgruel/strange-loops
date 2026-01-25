"""Consumer dashboard: tails a JSONL file, renders live state.

Run: uv run python apps/tail_dashboard.py [--path /tmp/events.jsonl]

Tails the event file (created by apps.producer), projects into
summary state, and renders a live terminal dashboard. Replays
existing events on startup, then follows the tail.

This is the "personal Kafka consumer" — a Projection driven by
a file tailer rather than an in-process Stream.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from cells import (
    RenderApp, Block, Style,
    join_horizontal, join_vertical, pad, border,
    Region,
)

from rill import Tailer, Projection


# --- Event type (matches producer) ---


@dataclass(frozen=True)
class ContainerEvent:
    ts: float
    stack: str
    container: str
    status: str
    message: str = ""


def deserialize(d: dict) -> ContainerEvent:
    return ContainerEvent(**d)


# --- Projection: fold events into dashboard state ---


@dataclass
class DashboardState:
    total: int = 0
    healthy: int = 0
    unhealthy: int = 0
    errors: int = 0
    stacks: dict[str, dict[str, str]] = None  # stack -> {container: status}
    recent: deque[ContainerEvent] = None
    first_ts: float = 0.0
    last_ts: float = 0.0

    def __post_init__(self):
        if self.stacks is None:
            self.stacks = {}
        if self.recent is None:
            self.recent = deque(maxlen=20)


class DashboardProjection(Projection[DashboardState, ContainerEvent]):
    def apply(self, state: DashboardState, event: ContainerEvent) -> DashboardState:
        state.total += 1
        if event.status == "healthy":
            state.healthy += 1
        elif event.status == "unhealthy":
            state.unhealthy += 1
        elif event.status == "error":
            state.errors += 1

        # Track per-container status
        if event.stack not in state.stacks:
            state.stacks[event.stack] = {}
        state.stacks[event.stack][event.container] = event.status

        state.recent.append(event)

        if state.first_ts == 0.0:
            state.first_ts = event.ts
        state.last_ts = event.ts

        return state


# --- Dashboard App ---


class TailDashboard(RenderApp):
    def __init__(self, path: Path):
        super().__init__(fps_cap=15)
        self._tailer: Tailer[ContainerEvent] = Tailer(path, deserialize)
        self._proj = DashboardProjection(initial=DashboardState())
        self._path = path
        self._region = Region(0, 0, 80, 24)
        self._last_version = -1

    def layout(self, width: int, height: int) -> None:
        self._region = Region(0, 0, width, height)

    def update(self) -> None:
        # Poll for new events and feed to projection
        events = self._tailer.poll()
        for event in events:
            self._proj._state = self._proj.apply(self._proj._state, event)
            self._proj._version += 1

        if self._proj.version != self._last_version:
            self._last_version = self._proj.version
            self.mark_dirty()

    def _styled_line(self, *parts: tuple[str, Style]) -> Block:
        """Build a single-row Block from multiple styled text segments."""
        blocks = [Block.text(text, style) for text, style in parts]
        return join_horizontal(*blocks)

    def render(self) -> None:
        state = self._proj.state

        # --- Header: counts ---
        elapsed = (state.last_ts - state.first_ts) if state.first_ts else 0
        rate = f"{state.total / elapsed:.1f}/s" if elapsed > 1 else "..."

        header_block = self._styled_line(
            (f" Events: {state.total} ", Style(bold=True)),
            (f" Rate: {rate} ", Style(dim=True)),
            (f" OK:{state.healthy} ", Style(fg="green")),
            (f" WARN:{state.unhealthy} ", Style(fg="yellow")),
            (f" ERR:{state.errors} ", Style(fg="red")),
        )

        # --- File info ---
        info_block = Block.text(
            f" Tailing: {self._path}  offset: {self._tailer.offset}",
            Style(dim=True),
        )

        # --- Stack summary ---
        stack_rows: list[Block] = []
        for stack_name in sorted(state.stacks.keys()):
            containers = state.stacks[stack_name]
            healthy = sum(1 for s in containers.values() if s == "healthy")
            total = len(containers)
            if healthy == total:
                row = self._styled_line(
                    (f"  {stack_name}: ", Style(fg="green")),
                    (f"{healthy}/{total} healthy", Style(dim=True)),
                )
            else:
                unhealthy = [
                    f"{c}({s})" for c, s in containers.items() if s != "healthy"
                ]
                row = self._styled_line(
                    (f"  {stack_name}: ", Style(fg="yellow")),
                    (f"{healthy}/{total} healthy  [{', '.join(unhealthy)}]", Style(fg="yellow")),
                )
            stack_rows.append(row)

        stack_content = (
            join_vertical(*stack_rows) if stack_rows
            else Block.text("  Waiting for events...", Style(dim=True))
        )
        stack_block = border(stack_content, title="Stacks")

        # --- Recent events ---
        max_events = max(5, self._region.height - 12)
        recent = list(state.recent)[-max_events:]
        event_rows: list[Block] = []
        for event in recent:
            ts_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            status_style = {
                "healthy": Style(fg="green"),
                "unhealthy": Style(fg="yellow"),
                "error": Style(fg="red", bold=True),
            }.get(event.status, Style())

            parts: list[tuple[str, Style]] = [
                (f"  {ts_str} ", Style(dim=True)),
                (f"[{event.status:>9}] ", status_style),
                (f"{event.stack}/{event.container}", Style()),
            ]
            if event.message:
                parts.append((f"  {event.message}", Style(dim=True)))
            event_rows.append(self._styled_line(*parts))

        events_content = (
            join_vertical(*event_rows) if event_rows
            else Block.text("  No events yet...", Style(dim=True))
        )
        events_block = border(events_content, title="Recent Events")

        # --- Compose ---
        composed = join_vertical(
            header_block,
            info_block,
            pad(stack_block, top=1),
            pad(events_block, top=1),
        )

        # Paint
        if self._buf is not None:
            self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
            view = self._region.view(self._buf)
            composed.paint(view, x=0, y=0)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()


async def main():
    parser = argparse.ArgumentParser(description="Tail JSONL and render dashboard")
    parser.add_argument("--path", type=Path, default=Path("/tmp/events.jsonl"))
    args = parser.parse_args()

    print(f"Tailing: {args.path}")
    print("Start the producer in another terminal: uv run python -m apps.producer")
    print("Press any key to start (q to quit)...\n")

    app = TailDashboard(args.path)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
