"""TUI module — interactive Surface for hlab.

Interactive mode (-i) launches this full TUI with two-panel layout:
- Left panel: stack list with selection
- Right panel: containers for selected stack
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from cells import Block, Style, join_vertical, join_horizontal, border, pad, ROUNDED
from cells.tui import Surface

from data import Runner

from .lenses.status import render_stack_list, render_container_detail, PendingState
from .theme import DEFAULT_THEME


# Styles
DIM = Style(dim=True)
BOLD = Style(bold=True)
RED = Style(fg="red")
CYAN = Style(fg="cyan")


@dataclass(frozen=True)
class TuiState:
    """State for TUI display."""

    selected: int = 0  # Which stack is selected
    pending: frozenset[str] = frozenset()  # Stacks still loading
    stacks: dict[str, dict] | None = None  # Received data (immutable via replacement)
    spinner_frame: int = 0  # For pending animation

    def tick(self) -> "TuiState":
        """Advance spinner frame."""
        return TuiState(
            selected=self.selected,
            pending=self.pending,
            stacks=self.stacks,
            spinner_frame=(self.spinner_frame + 1) % 10,
        )

    def receive(self, name: str, payload: dict) -> "TuiState":
        """Record a received tick."""
        new_stacks = dict(self.stacks) if self.stacks else {}
        new_stacks[name] = payload
        return TuiState(
            selected=self.selected,
            pending=self.pending - {name},
            stacks=new_stacks,
            spinner_frame=self.spinner_frame,
        )

    def select(self, index: int) -> "TuiState":
        """Change selection."""
        return TuiState(
            selected=index,
            pending=self.pending,
            stacks=self.stacks,
            spinner_frame=self.spinner_frame,
        )

    @property
    def all_names(self) -> list[str]:
        """All stack names (received + pending) in sorted order."""
        received = set(self.stacks.keys()) if self.stacks else set()
        return sorted(received | self.pending)

    @property
    def selected_name(self) -> str | None:
        """Name of currently selected stack."""
        names = self.all_names
        if not names or self.selected >= len(names):
            return None
        return names[self.selected]

    @property
    def selected_payload(self) -> dict | None:
        """Payload of currently selected stack."""
        name = self.selected_name
        if name is None or self.stacks is None:
            return None
        return self.stacks.get(name)

    @property
    def selected_is_pending(self) -> bool:
        """Whether selected stack is still loading."""
        name = self.selected_name
        return name is not None and name in self.pending


class HlabApp(Surface):
    """Main TUI for hlab (interactive mode).

    Two-panel layout:
    - Left: stack list with j/k navigation
    - Right: containers for selected stack
    """

    def __init__(self):
        super().__init__(fps_cap=30, on_start=self._on_start)
        self._state = TuiState()
        self._error: str | None = None
        self._w = 80
        self._h = 24
        self._theme = DEFAULT_THEME
        self._expected: list[str] = []

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    async def _on_start(self) -> None:
        asyncio.create_task(self._run())

    async def _spinner_loop(self) -> None:
        """Advance spinner while loading."""
        while self._state.pending:
            await asyncio.sleep(0.1)
            if self._state.pending:  # Check again after sleep
                self._state = self._state.tick()
                self.mark_dirty()

    async def _run(self) -> None:
        try:
            from .commands.status import load_with_expected
            vertex, sources, expected = load_with_expected()

            self._expected = expected
            self._state = TuiState(pending=frozenset(expected), stacks={})

            # Start spinner loop now that state is initialized
            asyncio.create_task(self._spinner_loop())

            runner = Runner(vertex)
            for s in sources:
                runner.add(s)

            async for tick in runner.run():
                self._state = self._state.receive(tick.name, tick.payload)
                self.mark_dirty()
        except Exception as e:
            self._error = str(e)
            self.mark_dirty()

    def on_key(self, key: str) -> None:
        if key in ("q", "Q", "escape"):
            self.quit()
        elif key in ("j", "down"):
            # Move selection down
            names = self._state.all_names
            if names:
                new_sel = min(self._state.selected + 1, len(names) - 1)
                self._state = self._state.select(new_sel)
                self.mark_dirty()
        elif key in ("k", "up"):
            # Move selection up
            new_sel = max(self._state.selected - 1, 0)
            self._state = self._state.select(new_sel)
            self.mark_dirty()
        elif key in ("g", "home"):
            # Jump to top
            self._state = self._state.select(0)
            self.mark_dirty()
        elif key in ("G", "end"):
            # Jump to bottom
            names = self._state.all_names
            if names:
                self._state = self._state.select(len(names) - 1)
                self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        width = self._w - 4
        now = datetime.now().strftime("%H:%M:%S")

        # Header
        stacks = self._state.stacks or {}
        total_healthy = sum(p.get("healthy", 0) for p in stacks.values())
        total_containers = sum(p.get("total", 0) for p in stacks.values())
        n_stacks = len(stacks)
        n_pending = len(self._state.pending)

        if n_pending > 0:
            status = f"{n_stacks}/{n_stacks + n_pending} stacks loaded"
        else:
            status = f"{n_stacks} stacks, {total_healthy}/{total_containers} healthy"

        header = Block.text(
            f"hlab | {now} | {status}",
            BOLD,
            width=width
        )

        # Content
        if self._error:
            content = Block.text(f"Error: {self._error}", RED, width=width)
        else:
            content = self._render_panels(width)

        # Help
        help_line = Block.text("[j/k] navigate  [q]uit", DIM, width=width)

        # Compose
        body = join_vertical(
            header,
            Block.empty(width, 1),
            content,
            Block.empty(width, 1),
            help_line,
        )

        padded = pad(body, left=2, top=1)

        # Paint
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        padded.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _render_panels(self, width: int) -> Block:
        """Render two-panel layout."""
        # Calculate panel dimensions
        # Left panel: ~30% of width, Right panel: ~70%
        left_width = max(25, width // 3)
        right_width = width - left_width - 3  # 3 for gap

        # Panel heights (leave room for header and footer)
        panel_height = max(8, self._h - 8)

        # Create pending state for render functions
        pending_state = PendingState(
            pending=self._state.pending,
            spinner_frame=self._state.spinner_frame,
        )

        # Left panel: stack list
        stacks = self._state.stacks or {}
        left_inner = render_stack_list(
            stacks,
            pending_state,
            self._state.selected,
            left_width - 4,  # Account for border
            panel_height - 2,  # Account for border
            self._theme,
        )
        left_panel = border(
            left_inner,
            title="Stacks",
            style=CYAN,
            chars=ROUNDED,
        )

        # Right panel: container detail
        selected_name = self._state.selected_name
        right_title = f"{selected_name}" if selected_name else "Detail"
        if selected_name and self._state.selected_payload:
            payload = self._state.selected_payload
            healthy = payload.get("healthy", 0)
            total = payload.get("total", 0)
            right_title = f"{selected_name} ({healthy}/{total})"

        right_inner = render_container_detail(
            selected_name,
            self._state.selected_payload,
            self._state.selected_is_pending,
            self._state.spinner_frame,
            right_width - 4,  # Account for border
            panel_height - 2,  # Account for border
            self._theme,
        )
        right_panel = border(
            right_inner,
            title=right_title,
            style=CYAN,
            chars=ROUNDED,
        )

        # Join panels horizontally
        return join_horizontal(left_panel, Block.empty(1, left_panel.height), right_panel)
