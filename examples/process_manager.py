#!/usr/bin/env python3
"""
Process Manager - Interactive CLI for managing simulated processes.

Tests pattern generality with:
- Per-entity state machines (STOPPED → STARTING → RUNNING → STOPPING → STOPPED/CRASHED)
- Async tasks per process (simulators)
- Live durations (uptime computed each render)
- CRUD operations on processes
- Confirmation mode for destructive actions

Run with: uv run examples/process_manager.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rich",
#     "reaktiv",
#     "typing_extensions",
# ]
# ///

from __future__ import annotations

import asyncio
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Literal

from reaktiv import Signal, Computed
from rich.console import Console
from rich.text import Text

# Framework imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from framework import EventStore, BaseApp, Projection, DebugPane, BaseSimulator, SimState, SelectionTracker
from framework.ui import app_layout, focus_panel, event_table, metrics_panel, help_bar, status_parts, ColumnSpec


# =============================================================================
# DATA MODEL
# =============================================================================

# Reuse SimState from framework, aliased for domain clarity
ProcessState = SimState


@dataclass(frozen=True)
class ProcessEvent:
    """Event in the process manager event log."""
    pid: str
    kind: Literal["created", "removed", "state_change", "log"]
    ts: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)
    # created: {"name": str, "crash_prob": float, "log_freq": float}
    # removed: {}
    # state_change: {"from": str, "to": str}
    # log: {"message": str, "level": str}


# =============================================================================
# PERSISTENCE HELPERS
# =============================================================================

EVENTS_PATH = Path(__file__).parent / "process_events.jsonl"


def serialize_event(e: ProcessEvent) -> dict:
    return {"pid": e.pid, "kind": e.kind, "ts": e.ts, "payload": e.payload}


def deserialize_event(d: dict) -> ProcessEvent:
    return ProcessEvent(pid=d["pid"], kind=d["kind"], ts=d["ts"], payload=d["payload"])


# =============================================================================
# MODE
# =============================================================================

class Mode(Enum):
    VIEW = auto()
    FILTER = auto()
    ADD = auto()
    CONFIRM = auto()


# =============================================================================
# STATE COLORS
# =============================================================================

STATE_STYLES = {
    ProcessState.STOPPED: "dim",
    ProcessState.STARTING: "yellow",
    ProcessState.RUNNING: "green",
    ProcessState.STOPPING: "yellow",
    ProcessState.CRASHED: "red bold",
}

LOG_LEVEL_STYLES = {
    "info": "blue",
    "warn": "yellow",
    "error": "red",
    "debug": "dim",
}

# =============================================================================
# SIMULATED LOG MESSAGES
# =============================================================================

LOG_MESSAGES = {
    "web-server": [
        ("info", "Listening on port 8080"),
        ("info", "GET /api/health 200 12ms"),
        ("info", "POST /api/users 201 45ms"),
        ("warn", "Slow query: SELECT * FROM users (320ms)"),
        ("info", "GET /static/app.js 304 2ms"),
        ("error", "Connection pool exhausted"),
        ("info", "WebSocket connection established"),
        ("debug", "Request body parsed: 1.2KB"),
    ],
    "worker": [
        ("info", "Processing job #1042"),
        ("info", "Job #1042 completed in 230ms"),
        ("warn", "Queue depth: 15 items"),
        ("info", "Connecting to message broker"),
        ("error", "Failed to serialize payload"),
        ("info", "Batch processing: 10 items"),
        ("debug", "Heartbeat sent"),
        ("info", "Job #1043 started"),
    ],
    "scheduler": [
        ("info", "Cron job 'cleanup' triggered"),
        ("info", "Next run: cleanup in 60s"),
        ("warn", "Missed schedule for 'report-gen'"),
        ("info", "Task 'db-backup' queued"),
        ("error", "Schedule conflict detected"),
        ("info", "Running periodic health check"),
        ("debug", "Timer tick: 1000ms"),
        ("info", "Cron job 'report-gen' triggered"),
    ],
    "_default": [
        ("info", "Service started successfully"),
        ("info", "Processing request"),
        ("warn", "High memory usage: 85%"),
        ("info", "Connection established"),
        ("error", "Unexpected error in handler"),
        ("info", "Request completed"),
        ("debug", "GC pause: 12ms"),
        ("info", "Health check passed"),
    ],
}


# =============================================================================
# PROCESS SIMULATOR
# =============================================================================

class ProcessSimulator(BaseSimulator):
    """Process-specific simulator that emits ProcessEvents."""

    def __init__(self, pid: str, name: str, crash_prob: float, log_freq: float,
                 store: EventStore, rate_multiplier: Callable[[], float] = lambda: 1.0):
        super().__init__(pid, rate_multiplier=rate_multiplier,
                         crash_prob=crash_prob, event_freq=log_freq)
        self.name = name
        self._store = store

    def emit_event(self, message: str, level: str = "info") -> None:
        self._store.add(ProcessEvent(
            pid=self.entity_id,
            kind="log",
            payload={"message": message, "level": level},
        ))

    def on_state_change(self, from_state: SimState, to_state: SimState) -> None:
        self._store.add(ProcessEvent(
            pid=self.entity_id,
            kind="state_change",
            payload={"from": from_state.value, "to": to_state.value},
        ))

    def generate_message(self) -> tuple[str, str]:
        messages = LOG_MESSAGES.get(self.name, LOG_MESSAGES["_default"])
        return random.choice(messages)


# =============================================================================
# PROCESS MANAGER
# =============================================================================

class ProcessManager:
    """Manages process lifecycle and simulators."""

    def __init__(self, store: EventStore, rate_multiplier: Callable[[], float] = lambda: 1.0):
        self._store = store
        self._rate_multiplier = rate_multiplier
        self._simulators: dict[str, ProcessSimulator] = {}
        self._counter = 0
        self._rebuild_from_events()

    def _rebuild_from_events(self) -> None:
        """Rebuild simulators and counter from replayed events."""
        alive: dict[str, dict] = {}  # pid -> created payload

        for event in self._store.events:
            if event.kind == "created":
                alive[event.pid] = event.payload
            elif event.kind == "removed":
                alive.pop(event.pid, None)

        for pid, payload in alive.items():
            num = int(pid.split("-")[1])
            if num > self._counter:
                self._counter = num
            sim = ProcessSimulator(
                pid, payload["name"], payload["crash_prob"],
                payload["log_freq"], self._store, self._rate_multiplier,
            )
            self._simulators[pid] = sim

    def create(self, name: str, crash_prob: float | None = None,
               log_freq: float | None = None) -> str:
        """Create a new process. Returns pid."""
        self._counter += 1
        pid = f"proc-{self._counter:03d}"

        if crash_prob is None:
            crash_prob = random.uniform(0.0, 0.1)
        if log_freq is None:
            log_freq = random.uniform(0.5, 2.0)

        self._store.add(ProcessEvent(
            pid=pid,
            kind="created",
            payload={"name": name, "crash_prob": crash_prob, "log_freq": log_freq},
        ))

        sim = ProcessSimulator(pid, name, crash_prob, log_freq, self._store, self._rate_multiplier)
        self._simulators[pid] = sim
        return pid

    async def start(self, pid: str) -> None:
        """Start a stopped/crashed process."""
        sim = self._simulators.get(pid)
        if sim:
            await sim.start()

    async def stop(self, pid: str) -> None:
        """Stop a running process."""
        sim = self._simulators.get(pid)
        if sim:
            await sim.stop()

    async def restart(self, pid: str) -> None:
        """Restart a running process."""
        sim = self._simulators.get(pid)
        if sim:
            if sim.is_running:
                await sim.stop()
            await sim.start()

    def remove(self, pid: str) -> None:
        """Remove a stopped process."""
        sim = self._simulators.get(pid)
        if sim:
            self._store.add(ProcessEvent(pid=pid, kind="removed"))
            del self._simulators[pid]

    async def stop_all(self) -> None:
        """Stop all running processes (cleanup)."""
        for sim in self._simulators.values():
            if sim.is_running:
                await sim.stop()


# =============================================================================
# PROCESS FILTER
# =============================================================================

@dataclass
class ProcessFilter:
    """
    Filter for processes:
    - name match (substring, case-insensitive)
    - state=running (exact state match)
    - Combined: "web state=running"
    """
    name_pattern: str = ""
    state_filter: str = ""
    raw: str = ""

    @classmethod
    def parse(cls, query: str) -> "ProcessFilter":
        if not query.strip():
            return cls()

        name_parts = []
        state_filter = ""

        for token in query.strip().split():
            if token.lower().startswith("state="):
                state_filter = token.split("=", 1)[1].lower()
            else:
                name_parts.append(token)

        return cls(
            name_pattern=" ".join(name_parts).lower(),
            state_filter=state_filter,
            raw=query.strip(),
        )

    def matches(self, name: str, state: ProcessState) -> bool:
        if self.name_pattern and self.name_pattern not in name.lower():
            return False
        if self.state_filter and state.value != self.state_filter:
            return False
        return True

    def description(self) -> str:
        return self.raw if (self.name_pattern or self.state_filter) else "all"


# =============================================================================
# PROCESS INFO (derived view)
# =============================================================================

@dataclass
class ProcessInfo:
    """Derived view of a process from events."""
    pid: str
    name: str
    state: ProcessState
    crash_prob: float
    log_freq: float
    start_count: int  # number of times started
    last_started_at: float | None  # timestamp of last RUNNING transition
    created_at: float


# =============================================================================
# PROJECTIONS
# =============================================================================

class ProcessLogsProjection(Projection[dict[str, list[ProcessEvent]], ProcessEvent]):
    """Incrementally accumulates last 50 log events per process."""

    def __init__(self):
        super().__init__({})

    def apply(self, state: dict[str, list[ProcessEvent]], event: ProcessEvent) -> dict[str, list[ProcessEvent]]:
        if event.kind != "log":
            return state
        logs = state.get(event.pid, [])[:]
        logs.append(event)
        if len(logs) > 50:
            logs = logs[-50:]
        state[event.pid] = logs
        return state


# =============================================================================
# PROCESS MONITOR APP
# =============================================================================

class ProcessMonitorApp(BaseApp):
    """Interactive process manager TUI."""

    def __init__(self, store: EventStore, manager: ProcessManager, console: Console):
        super().__init__(console)
        self.store = store
        self.manager = manager

        # Override mode to use our extended Mode enum
        self._mode = Signal(Mode.VIEW)
        self._focused_pane = Signal("list")  # "list", "logs", "detail"

        # Selection
        self._selection = SelectionTracker()

        # Filter
        self._filter = Signal(ProcessFilter())

        # Confirm action
        self._confirm_action: Signal[tuple[str, str] | None] = Signal(None)  # (action, pid)

        # Debug pane (initialized after manager is set via _init_debug)
        self.debug: DebugPane | None = None

        # Tick signal for live durations (bumped every second)
        self._tick = Signal(0)
        self._tick_task: asyncio.Task | None = None

        # Projection: incremental log accumulation
        self._process_logs_projection = ProcessLogsProjection()
        self.register_projection(self._process_logs_projection, store)

        # Computed values
        self.process_list = Computed(lambda: self._compute_process_list())
        self.process_states = Computed(lambda: self._compute_process_states())
        self.filtered_processes = Computed(lambda: self._compute_filtered_processes())
        self.selected_process = Computed(lambda: self._compute_selected_process())

    def init_debug(self) -> None:
        """Initialize debug pane after manager is attached."""
        self.debug = DebugPane(
            self.store,
            actions={
                "B": ("bulk spawn (10)", self._bulk_spawn),
                "S": ("mass stop", self._mass_stop),
                "R": ("mass restart", self._mass_restart),
                "X": ("mass close", self._mass_close),
            },
            extra_metrics=lambda: [("Active sims:", f"{len(self.manager._simulators):>5d}")],
        )

    def _render_dependencies(self) -> None:
        """Read signals that should trigger re-render.

        Only read Signals here, not Computeds. Computeds evaluate lazily
        when render() reads them — avoids per-event recomputation when
        the Effect fires at event rate but renders at frame rate.
        """
        self.store.version()
        self._filter()
        self._selection.index()
        self._confirm_action()
        self._tick()
        if self.debug:
            self.debug.visible()
            self.debug.rate_multiplier()

    # =========================================================================
    # COMPUTED VALUES
    # =========================================================================

    def _compute_process_list(self) -> list[ProcessInfo]:
        """Derive current process list from created/removed events."""
        self.store.version()

        processes: dict[str, ProcessInfo] = {}

        for event in self.store.events:
            if event.kind == "created":
                processes[event.pid] = ProcessInfo(
                    pid=event.pid,
                    name=event.payload["name"],
                    state=ProcessState.STOPPED,
                    crash_prob=event.payload["crash_prob"],
                    log_freq=event.payload["log_freq"],
                    start_count=0,
                    last_started_at=None,
                    created_at=event.ts,
                )
            elif event.kind == "removed":
                processes.pop(event.pid, None)
            elif event.kind == "state_change" and event.pid in processes:
                proc = processes[event.pid]
                new_state = ProcessState(event.payload["to"])
                # Track start count and last started time
                start_count = proc.start_count
                last_started = proc.last_started_at
                if new_state == ProcessState.RUNNING:
                    start_count += 1
                    last_started = event.ts
                processes[event.pid] = ProcessInfo(
                    pid=proc.pid,
                    name=proc.name,
                    state=new_state,
                    crash_prob=proc.crash_prob,
                    log_freq=proc.log_freq,
                    start_count=start_count,
                    last_started_at=last_started,
                    created_at=proc.created_at,
                )

        return list(processes.values())

    def process_logs(self) -> dict[str, list[ProcessEvent]]:
        """Read accumulated logs from the projection."""
        return self._process_logs_projection.state()

    def _compute_process_states(self) -> dict[str, ProcessState]:
        """Map pid → current state."""
        return {p.pid: p.state for p in self.process_list()}

    def _compute_filtered_processes(self) -> list[ProcessInfo]:
        """Apply filter to process list."""
        processes = self.process_list()
        filt = self._filter()
        return [p for p in processes if filt.matches(p.name, p.state)]

    def _compute_selected_process(self) -> ProcessInfo | None:
        """Get currently selected process."""
        idx = self._selection.value
        if idx is None:
            return None
        filtered = self.filtered_processes()
        if 0 <= idx < len(filtered):
            return filtered[idx]
        return None

    # =========================================================================
    # TICK TASK (for live durations)
    # =========================================================================

    async def start_tick(self) -> None:
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def _tick_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                self._tick.update(lambda v: v + 1)
        except asyncio.CancelledError:
            pass

    async def stop_tick(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass

    # =========================================================================
    # KEY HANDLING
    # =========================================================================

    def handle_key(self, key: str) -> bool:
        mode = self._mode()
        if mode == Mode.VIEW:
            return self._handle_view_key(key)
        elif mode == Mode.FILTER:
            return self._handle_filter_key(key)
        elif mode == Mode.ADD:
            return self._handle_add_key(key)
        elif mode == Mode.CONFIRM:
            return self._handle_confirm_key(key)
        return True

    def _handle_view_key(self, key: str) -> bool:
        if key == "q":
            self._running.set(False)
            return False
        elif key == "1":
            self._focused_pane.set("list")
        elif key == "2":
            self._focused_pane.set("logs")
        elif key == "3":
            self._focused_pane.set("detail")
        elif key == "/":
            self._mode.set(Mode.FILTER)
            self._input_buffer.set("")
        elif key == "c":
            self._filter.set(ProcessFilter())
            self._selection.reset()
        elif key == "a":
            self._mode.set(Mode.ADD)
            self._input_buffer.set("")
        elif key == "j" or key == "J":
            self._selection.move(1, len(self.filtered_processes()))
        elif key == "k" or key == "K":
            self._selection.move(-1, len(self.filtered_processes()))
        elif key == "s":
            self._start_selected()
        elif key == "x":
            self._request_stop()
        elif key == "r":
            self._request_restart()
        elif key == "d":
            self._request_remove()
        elif self.debug and self.debug.handle_key(key):
            pass  # consumed by debug pane
        elif key == "h":
            history = self._filter_history()
            if history:
                self._filter.set(ProcessFilter.parse(history[0]))
                self._selection.reset()
        return True

    def _bulk_spawn(self) -> None:
        names = ["web-server", "worker", "scheduler", "api-gateway", "cache", "db-proxy"]
        for _ in range(10):
            self.manager.create(random.choice(names))

    def _mass_stop(self) -> None:
        """Stop all RUNNING processes."""
        for pid, sim in list(self.manager._simulators.items()):
            if sim.is_running:
                asyncio.get_event_loop().create_task(self.manager.stop(pid))

    def _mass_restart(self) -> None:
        """Restart all STOPPED/CRASHED processes."""
        states = self.process_states()
        for pid in list(self.manager._simulators.keys()):
            if states.get(pid) in (ProcessState.STOPPED, ProcessState.CRASHED):
                asyncio.get_event_loop().create_task(self.manager.start(pid))

    def _mass_close(self) -> None:
        """Remove all processes (stop running ones first)."""
        async def _do_mass_close():
            # Stop all running first
            for pid, sim in list(self.manager._simulators.items()):
                if sim.is_running:
                    await self.manager.stop(pid)
            # Remove all
            for pid in list(self.manager._simulators.keys()):
                self.manager.remove(pid)
        asyncio.get_event_loop().create_task(_do_mass_close())

    def _handle_filter_key(self, key: str) -> bool:
        result = super()._handle_filter_key(
            key,
            parse_fn=ProcessFilter.parse,
            filter_signal=self._filter,
            view_mode=Mode.VIEW,
        )
        # Reset selection when filter is applied (Enter key)
        if (key == "\r" or key == "\n") and self._mode() == Mode.VIEW:
            self._selection.reset()
        return result

    def _handle_add_key(self, key: str) -> bool:
        if key == "\r" or key == "\n":
            name = self._input_buffer().strip()
            if name:
                self.manager.create(name)
            self._mode.set(Mode.VIEW)
            self._input_buffer.set("")
        elif key == "\x1b":  # Escape
            self._mode.set(Mode.VIEW)
            self._input_buffer.set("")
        elif key == "\x7f":  # Backspace
            self._input_buffer.update(lambda s: s[:-1])
        elif key.isprintable():
            self._input_buffer.update(lambda s: s + key)
        return True

    def _handle_confirm_key(self, key: str) -> bool:
        if key == "y" or key == "Y":
            action = self._confirm_action()
            if action:
                act, pid = action
                asyncio.get_event_loop().create_task(self._execute_action(act, pid))
            self._confirm_action.set(None)
            self._mode.set(Mode.VIEW)
        elif key == "n" or key == "N" or key == "\x1b":
            self._confirm_action.set(None)
            self._mode.set(Mode.VIEW)
        return True

    async def _execute_action(self, action: str, pid: str) -> None:
        if action == "stop":
            await self.manager.stop(pid)
        elif action == "restart":
            await self.manager.restart(pid)
        elif action == "remove":
            self.manager.remove(pid)

    # =========================================================================
    # SELECTION AND ACTIONS
    # =========================================================================

    def _start_selected(self) -> None:
        proc = self.selected_process()
        if proc and proc.state in (ProcessState.STOPPED, ProcessState.CRASHED):
            asyncio.get_event_loop().create_task(self.manager.start(proc.pid))

    def _request_stop(self) -> None:
        proc = self.selected_process()
        if proc and proc.state == ProcessState.RUNNING:
            self._confirm_action.set(("stop", proc.pid))
            self._mode.set(Mode.CONFIRM)

    def _request_restart(self) -> None:
        proc = self.selected_process()
        if proc and proc.state == ProcessState.RUNNING:
            self._confirm_action.set(("restart", proc.pid))
            self._mode.set(Mode.CONFIRM)

    def _request_remove(self) -> None:
        proc = self.selected_process()
        if proc and proc.state in (ProcessState.STOPPED, ProcessState.CRASHED):
            self._confirm_action.set(("remove", proc.pid))
            self._mode.set(Mode.CONFIRM)

    # =========================================================================
    # RENDER
    # =========================================================================

    def render(self):
        from rich.layout import Layout

        t0 = time.perf_counter()

        pane = self._focused_pane()
        selected = self.selected_process()

        # Build content panes
        content_panes: list[Layout] = []

        if pane == "detail" and selected:
            content_panes.append(Layout(self._render_list_pane(), name="list", ratio=1))
            content_panes.append(Layout(self._render_detail_pane(selected), name="detail", ratio=1))
        elif pane == "logs":
            content_panes.append(Layout(self._render_list_pane(), name="list", ratio=1))
            content_panes.append(Layout(self._render_logs_pane(), name="logs", ratio=2))
        else:
            content_panes.append(Layout(self._render_list_pane(), name="list", ratio=1))
            content_panes.append(Layout(self._render_logs_pane(), name="logs", ratio=1))

        if self.debug and self.debug.visible():
            content_panes.append(Layout(self.debug.render(), name="debug", size=32))

        main = Layout()
        main.split_row(*content_panes)

        result = app_layout(main, self._render_status(), self._render_help())

        # Record render time
        render_ms = (time.perf_counter() - t0) * 1000
        if self.debug:
            self.debug.record_render_time(render_ms)

        return result

    def _render_list_pane(self):
        """Process list with state, uptime, restarts."""
        columns = [
            ColumnSpec("Name", ratio=1),
            ColumnSpec("State"),
            ColumnSpec("Uptime", justify="right"),
            ColumnSpec("Restarts", justify="right"),
        ]

        filtered = self.filtered_processes()
        selected_idx = self._selection.value
        now = time.time()

        rows = []
        for proc in filtered:
            state_style = STATE_STYLES.get(proc.state, "white")

            # Compute uptime for running processes
            uptime_str = ""
            if proc.state == ProcessState.RUNNING and proc.last_started_at:
                elapsed = now - proc.last_started_at
                uptime_str = self._format_duration(elapsed)

            # Restart count (starts - 1, since first start isn't a restart)
            restart_count = max(0, proc.start_count - 1)
            restart_str = str(restart_count) if restart_count > 0 else ""

            rows.append([
                Text(proc.name),
                Text(proc.state.value, style=state_style),
                Text(uptime_str, style="dim"),
                Text(restart_str, style="dim"),
            ])

        table, scroll = event_table(rows, columns, self._available_rows(), selected_idx=selected_idx)

        filt = self._filter()
        title_extra = f" [dim]({filt.description()})[/dim]" if filt.raw else ""
        return focus_panel(
            table,
            title=f"[bold]Processes[/bold]{title_extra}",
            focused=self._focused_pane() == "list",
            subtitle=scroll.subtitle,
        )

    def _render_logs_pane(self):
        """Log output for selected process (or all if none selected)."""
        columns = [
            ColumnSpec("Time", style="dim"),
            ColumnSpec("Process"),
            ColumnSpec("Message", ratio=1),
        ]

        all_logs = self.process_logs()
        selected = self.selected_process()

        # Collect relevant logs
        if selected:
            entries = all_logs.get(selected.pid, [])
            title_proc = selected.name
        else:
            # Merge all logs, sorted by timestamp
            entries = []
            for pid_logs in all_logs.values():
                entries.extend(pid_logs)
            entries.sort(key=lambda e: e.ts)
            title_proc = "all"

        # Get process names for display
        proc_names = {p.pid: p.name for p in self.process_list()}

        rows = []
        for event in entries:
            time_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            level = event.payload.get("level", "info")
            level_style = LOG_LEVEL_STYLES.get(level, "white")
            proc_name = proc_names.get(event.pid, event.pid)
            message = event.payload.get("message", "")

            rows.append([
                Text(time_str, style="dim"),
                Text(proc_name, style="cyan"),
                Text(message, style=level_style),
            ])

        table, scroll = event_table(rows, columns, self._available_rows())

        return focus_panel(
            table,
            title=f"[bold]Logs[/bold] [dim]({title_proc})[/dim]",
            focused=self._focused_pane() == "logs",
            subtitle=scroll.subtitle,
        )

    def _render_detail_pane(self, proc: ProcessInfo):
        """Full detail view for selected process."""
        now = time.time()
        state_style = STATE_STYLES.get(proc.state, "white")

        # Uptime
        if proc.state == ProcessState.RUNNING and proc.last_started_at:
            uptime_str = self._format_duration(now - proc.last_started_at)
        else:
            uptime_str = "-"

        restart_count = max(0, proc.start_count - 1)
        created_str = time.strftime("%H:%M:%S", time.localtime(proc.created_at))

        sections: list[tuple[str, list[tuple[str, str] | tuple[str, str, str]]]] = [
            (f"{proc.name}  [dim]{proc.pid}[/dim]", [
                ("State", proc.state.value, state_style),
                ("Uptime", uptime_str),
            ]),
            ("Configuration", [
                ("Crash probability", f"{proc.crash_prob:.1%}"),
                ("Log frequency", f"{proc.log_freq:.1f} msg/sec"),
            ]),
            ("Statistics", [
                ("Start count", str(proc.start_count)),
                ("Restarts", str(restart_count)),
                ("Created", created_str),
            ]),
        ]

        # Recent logs
        all_logs = self.process_logs()
        proc_logs = all_logs.get(proc.pid, [])
        if proc_logs:
            log_entries: list[tuple[str, str] | tuple[str, str, str]] = []
            for event in proc_logs[-5:]:
                level = event.payload.get("level", "info")
                level_style_log = LOG_LEVEL_STYLES.get(level, "white")
                msg = event.payload.get("message", "")
                log_entries.append(("", msg, level_style_log))
            sections.append(("Recent Logs", log_entries))

        # Available actions
        action_entries: list[tuple[str, str] | tuple[str, str, str]] = []
        if proc.state in (ProcessState.STOPPED, ProcessState.CRASHED):
            action_entries.append(("s", "start", "green"))
            if proc.state == ProcessState.STOPPED:
                action_entries.append(("d", "remove", "red"))
        elif proc.state == ProcessState.RUNNING:
            action_entries.append(("x", "stop", "yellow"))
            action_entries.append(("r", "restart", "yellow"))
        sections.append(("Actions", action_entries))

        return focus_panel(
            metrics_panel(sections),
            title="[bold]Detail[/bold]",
            focused=self._focused_pane() == "detail",
        )

    def _render_status(self) -> Text:
        mode = self._mode()

        if mode == Mode.FILTER:
            history = self._filter_history()
            hist_str = f"  [dim]history: {', '.join(history[:3])}[/dim]" if history else ""
            return Text.from_markup(f"[bold]Filter:[/bold] /{self._input_buffer()}█{hist_str}")

        if mode == Mode.ADD:
            return Text.from_markup(f"[bold]New process name:[/bold] {self._input_buffer()}█")

        if mode == Mode.CONFIRM:
            action = self._confirm_action()
            if action:
                act, pid = action
                proc = next((p for p in self.process_list() if p.pid == pid), None)
                name = proc.name if proc else pid
                return Text.from_markup(
                    f"[bold yellow]{act.title()} process '{name}'? [y/n][/bold yellow]"
                )

        # VIEW mode status
        processes = self.process_list()
        running_count = sum(1 for p in processes if p.state == ProcessState.RUNNING)
        crashed_count = sum(1 for p in processes if p.state == ProcessState.CRASHED)

        selected_idx = self._selection.value
        filtered = self.filtered_processes()
        sel_part = f"[cyan]Selected: {selected_idx + 1}/{len(filtered)}[/cyan]" if selected_idx is not None and filtered else None
        crashed_part = f"[red]Crashed: {crashed_count}[/red]" if crashed_count > 0 else None

        return status_parts(
            f"[bold]Focus:[/bold] {self._focused_pane()}",
            "|",
            f"[bold]Total:[/bold] {len(processes)}  [green]Running: {running_count}[/green]",
            crashed_part,
            sel_part,
        )

    def _render_help(self) -> Text:
        mode = self._mode()

        if mode == Mode.FILTER:
            return help_bar([
                ("Enter", "apply"), ("Esc", "cancel"), ("|", ""),
                ("", "Syntax: [cyan]name[/cyan]  [cyan]state=[/cyan]running|stopped|crashed"),
            ])

        if mode == Mode.ADD:
            return help_bar([("Enter", "create"), ("Esc", "cancel")])

        if mode == Mode.CONFIRM:
            return help_bar([("y", "confirm"), ("n/Esc", "cancel")])

        # VIEW mode
        history = self._filter_history()
        bindings: list[tuple[str, str]] = [
            ("1", "list"), ("2", "logs"), ("3", "detail"), ("|", ""),
            ("j/k", "nav"), ("s", "start"), ("x", "stop"),
            ("r", "restart"), ("d", "remove"), ("|", ""),
            ("/", "filter"), ("a", "add"), ("c", "clear"),
        ]
        if history:
            bindings.append(("h", "last"))
        bindings.extend([("|", ""), ("D", "debug"), ("q", "quit")])
        return help_bar(bindings)

    def _format_duration(self, seconds: float) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            m = int(seconds // 60)
            s = int(seconds % 60)
            return f"{m}m{s:02d}s"
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h{m:02d}m"


# =============================================================================
# MAIN
# =============================================================================

async def run_manager(duration: float | None = None):
    console = Console()

    console.print("\n[bold]Process Manager[/bold]")
    console.print("Manage and monitor simulated processes")
    if duration:
        console.print(f"[dim]Running for {duration}s...[/dim]")
    console.print()
    await asyncio.sleep(0.5)

    store: EventStore[ProcessEvent] = EventStore(
        path=EVENTS_PATH,
        serialize=serialize_event,
        deserialize=deserialize_event,
    )

    app = ProcessMonitorApp(store, None, console)  # type: ignore[arg-type]
    app.init_debug()
    manager = ProcessManager(store, rate_multiplier=app.debug.rate_multiplier)
    app.manager = manager

    # Pre-seed processes only on first run (no existing events)
    if store.total == 0:
        manager.create("web-server", crash_prob=0.02, log_freq=1.5)
        manager.create("worker", crash_prob=0.08, log_freq=1.0)
        manager.create("scheduler", crash_prob=0.15, log_freq=0.7)
    await app.start_tick()

    try:
        await app.run(duration=duration)
    finally:
        await app.stop_tick()
        await manager.stop_all()
        store.close()

    processes = app.process_list()
    console.print(f"\n[bold]Done![/bold] {len(processes)} processes managed")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Interactive Process Manager")
    parser.add_argument("--duration", "-d", type=float, default=None,
                        help="Run for N seconds (default: until quit)")
    args = parser.parse_args()

    try:
        asyncio.run(run_manager(duration=args.duration))
    except KeyboardInterrupt:
        print("\nInterrupted")


if __name__ == "__main__":
    main()
