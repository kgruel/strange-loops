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
import resource
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Literal

from reaktiv import Signal, Computed, Effect
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Framework imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from cli_framework import EventStore, KeyboardInput, FilterHistory, BaseApp


# =============================================================================
# DATA MODEL
# =============================================================================

class ProcessState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


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

class ProcessSimulator:
    """Per-process async task that simulates execution lifecycle."""

    def __init__(self, pid: str, name: str, crash_prob: float, log_freq: float,
                 store: EventStore, rate_multiplier: Callable[[], float] = lambda: 1.0):
        self.pid = pid
        self.name = name
        self.crash_prob = crash_prob
        self.log_freq = log_freq
        self._store = store
        self._rate_multiplier = rate_multiplier
        self._task: asyncio.Task | None = None
        self._stop_requested = False

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the process simulation."""
        self._stop_requested = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Request graceful stop."""
        self._stop_requested = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        """Process lifecycle: starting → running (with logs/crashes) → stopped.

        On crash, auto-restarts after a short delay to sustain event throughput.
        """
        prev_state = ProcessState.STOPPED

        while not self._stop_requested:
            # STARTING phase
            self._emit_state_change(prev_state, ProcessState.STARTING)
            start_delay = random.uniform(0.5, 2.0)
            await asyncio.sleep(start_delay / self._rate_multiplier())

            # Transition to RUNNING
            self._emit_state_change(ProcessState.STARTING, ProcessState.RUNNING)

            # RUNNING phase - emit logs, may crash
            messages = LOG_MESSAGES.get(self.name, LOG_MESSAGES["_default"])
            crashed = False
            try:
                while not self._stop_requested:
                    # Emit a log message
                    level, message = random.choice(messages)
                    self._emit_log(message, level)

                    # Check for crash (scale probability by rate so per-second crash rate is constant)
                    effective_crash_prob = self.crash_prob / self._rate_multiplier()
                    if random.random() < effective_crash_prob:
                        self._emit_log("Fatal error: process terminated unexpectedly", "error")
                        self._emit_state_change(ProcessState.RUNNING, ProcessState.CRASHED)
                        crashed = True
                        break

                    # Wait before next log (scaled by rate multiplier)
                    base_delay = 1.0 / self.log_freq
                    delay = base_delay / self._rate_multiplier() + random.uniform(-0.2, 0.5)
                    await asyncio.sleep(max(0.01, delay))

            except asyncio.CancelledError:
                break

            if crashed:
                # Auto-restart after a short delay
                restart_delay = random.uniform(2.0, 3.0) / self._rate_multiplier()
                await asyncio.sleep(restart_delay)
                prev_state = ProcessState.CRASHED
                continue

            # If we exit the inner loop without crash or cancel, it's a stop request
            break

        # STOPPING phase (graceful shutdown)
        if self._stop_requested:
            self._emit_state_change(ProcessState.RUNNING, ProcessState.STOPPING)
            await asyncio.sleep(random.uniform(0.3, 1.0))
            self._emit_state_change(ProcessState.STOPPING, ProcessState.STOPPED)

    def _emit_state_change(self, from_state: ProcessState, to_state: ProcessState) -> None:
        self._store.add(ProcessEvent(
            pid=self.pid,
            kind="state_change",
            payload={"from": from_state.value, "to": to_state.value},
        ))

    def _emit_log(self, message: str, level: str) -> None:
        self._store.add(ProcessEvent(
            pid=self.pid,
            kind="log",
            payload={"message": message, "level": level},
        ))


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
        self._selected_index: Signal[int | None] = Signal(None)

        # Filter
        self._filter = Signal(ProcessFilter())
        self._filter_history = FilterHistory()

        # Confirm action
        self._confirm_action: Signal[tuple[str, str] | None] = Signal(None)  # (action, pid)

        # Debug pane
        self._debug_visible = Signal(False)
        self._rate_multiplier: Signal[float] = Signal(1.0)
        self._render_time_ms: float = 0.0
        self._last_event_count = 0
        self._last_event_time = time.time()
        self._events_per_sec = 0.0

        # Tick signal for live durations (bumped every second)
        self._tick = Signal(0)
        self._tick_task: asyncio.Task | None = None

        # Computed values
        self.process_list = Computed(lambda: self._compute_process_list())
        self.process_states = Computed(lambda: self._compute_process_states())
        self.process_logs = Computed(lambda: self._compute_process_logs())
        self.filtered_processes = Computed(lambda: self._compute_filtered_processes())
        self.selected_process = Computed(lambda: self._compute_selected_process())

    def _render_dependencies(self) -> None:
        """Read signals that should trigger re-render."""
        self.store.version()
        self._filter()
        self._selected_index()
        self._confirm_action()
        self._tick()
        self._debug_visible()
        self._rate_multiplier()
        self.process_list()
        self.process_states()
        self.filtered_processes()
        self.selected_process()

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

    def _compute_process_states(self) -> dict[str, ProcessState]:
        """Map pid → current state."""
        return {p.pid: p.state for p in self.process_list()}

    def _compute_process_logs(self) -> dict[str, list[ProcessEvent]]:
        """Collect last 50 log events per process."""
        self.store.version()

        logs: dict[str, list[ProcessEvent]] = {}
        for event in self.store.events:
            if event.kind == "log":
                if event.pid not in logs:
                    logs[event.pid] = []
                logs[event.pid].append(event)
                # Keep last 50
                if len(logs[event.pid]) > 50:
                    logs[event.pid] = logs[event.pid][-50:]

        return logs

    def _compute_filtered_processes(self) -> list[ProcessInfo]:
        """Apply filter to process list."""
        processes = self.process_list()
        filt = self._filter()
        return [p for p in processes if filt.matches(p.name, p.state)]

    def _compute_selected_process(self) -> ProcessInfo | None:
        """Get currently selected process."""
        idx = self._selected_index()
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
            self._selected_index.set(None)
        elif key == "a":
            self._mode.set(Mode.ADD)
            self._input_buffer.set("")
        elif key == "j" or key == "J":
            self._move_selection(1)
        elif key == "k" or key == "K":
            self._move_selection(-1)
        elif key == "s":
            self._start_selected()
        elif key == "x":
            self._request_stop()
        elif key == "r":
            self._request_restart()
        elif key == "d":
            self._request_remove()
        elif key == "D":
            self._debug_visible.update(lambda v: not v)
        elif key == "+" and self._debug_visible():
            self._cycle_rate_multiplier(up=True)
        elif key == "-" and self._debug_visible():
            self._cycle_rate_multiplier(up=False)
        elif key == "B" and self._debug_visible():
            self._bulk_spawn()
        elif key == "S" and self._debug_visible():
            self._mass_stop()
        elif key == "R" and self._debug_visible():
            self._mass_restart()
        elif key == "X" and self._debug_visible():
            self._mass_close()
        elif key == "h":
            latest = self._filter_history.latest
            if latest:
                self._filter.set(ProcessFilter.parse(latest))
                self._selected_index.set(None)
        return True

    _RATE_STEPS = [1.0, 2.0, 5.0, 10.0, 50.0, 100.0]

    def _cycle_rate_multiplier(self, up: bool) -> None:
        current = self._rate_multiplier()
        try:
            idx = self._RATE_STEPS.index(current)
        except ValueError:
            idx = 0
        if up:
            idx = min(idx + 1, len(self._RATE_STEPS) - 1)
        else:
            idx = max(idx - 1, 0)
        self._rate_multiplier.set(self._RATE_STEPS[idx])

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
        if key == "\r" or key == "\n":
            raw = self._input_buffer()
            if raw.strip():
                self._filter_history.push(raw)
            self._filter.set(ProcessFilter.parse(raw))
            self._selected_index.set(None)
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

    def _move_selection(self, delta: int) -> None:
        filtered = self.filtered_processes()
        if not filtered:
            return
        current = self._selected_index()
        if current is None:
            new_idx = 0 if delta > 0 else len(filtered) - 1
        else:
            new_idx = max(0, min(len(filtered) - 1, current + delta))
        self._selected_index.set(new_idx)

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

    def render(self) -> Layout:
        t0 = time.perf_counter()

        # Compute events/sec
        now = time.time()
        current_total = self.store.total
        dt = now - self._last_event_time
        if dt > 0:
            self._events_per_sec = (current_total - self._last_event_count) / dt
        self._last_event_count = current_total
        self._last_event_time = now

        layout = Layout()

        layout.split_column(
            Layout(name="main", ratio=1),
            Layout(self._render_status(), name="status", size=1),
            Layout(self._render_help(), name="help", size=1),
        )

        pane = self._focused_pane()
        selected = self.selected_process()
        debug_visible = self._debug_visible()

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

        if debug_visible:
            content_panes.append(Layout(self._render_debug_pane(), name="debug", size=32))

        layout["main"].split_row(*content_panes)

        # Record render time
        self._render_time_ms = (time.perf_counter() - t0) * 1000

        return layout

    def _render_list_pane(self) -> Panel:
        """Process list with state, uptime, restarts."""
        table = Table(
            show_header=True,
            header_style="bold",
            expand=True,
            box=None,
            padding=(0, 1),
        )
        table.add_column("", no_wrap=True, width=1)  # Selection indicator
        table.add_column("Name", ratio=1)
        table.add_column("State", no_wrap=True)
        table.add_column("Uptime", no_wrap=True, justify="right")
        table.add_column("Restarts", no_wrap=True, justify="right")

        filtered = self.filtered_processes()
        selected_idx = self._selected_index()
        max_rows = self._available_rows()
        now = time.time()

        start_idx = 0
        if selected_idx is not None and selected_idx >= max_rows:
            start_idx = selected_idx - max_rows + 1
        end_idx = min(len(filtered), start_idx + max_rows)

        for i in range(start_idx, end_idx):
            proc = filtered[i]
            is_selected = (i == selected_idx)

            indicator = "▶" if is_selected else ""
            state_style = STATE_STYLES.get(proc.state, "white")

            # Compute uptime for running processes
            uptime_str = ""
            if proc.state == ProcessState.RUNNING and proc.last_started_at:
                elapsed = now - proc.last_started_at
                uptime_str = self._format_duration(elapsed)

            # Restart count (starts - 1, since first start isn't a restart)
            restart_count = max(0, proc.start_count - 1)
            restart_str = str(restart_count) if restart_count > 0 else ""

            row_style = "reverse" if is_selected else None
            table.add_row(
                Text(indicator, style="cyan bold"),
                Text(proc.name, style="" if not is_selected else "reverse"),
                Text(proc.state.value, style=state_style if not is_selected else f"{state_style} reverse"),
                Text(uptime_str, style="dim" if not is_selected else "dim reverse"),
                Text(restart_str, style="dim" if not is_selected else "dim reverse"),
                style=row_style,
            )

        if not filtered:
            table.add_row("", Text("No processes", style="dim"), "", "", "")

        border_style = "green" if self._focused_pane() == "list" else "dim"
        filt = self._filter()
        title_extra = f" [dim]({filt.description()})[/dim]" if filt.raw else ""
        return Panel(table, title=f"[bold]Processes[/bold]{title_extra}",
                     border_style=border_style)

    def _render_logs_pane(self) -> Panel:
        """Log output for selected process (or all if none selected)."""
        table = Table(
            show_header=True,
            header_style="bold",
            expand=True,
            box=None,
            padding=(0, 1),
        )
        table.add_column("Time", no_wrap=True, style="dim")
        table.add_column("Process", no_wrap=True)
        table.add_column("Message", ratio=1)

        all_logs = self.process_logs()
        selected = self.selected_process()
        max_rows = self._available_rows()

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

        # Show last N
        visible = entries[-max_rows:]

        # Get process names for display
        proc_names = {p.pid: p.name for p in self.process_list()}

        for event in visible:
            time_str = time.strftime("%H:%M:%S", time.localtime(event.ts))
            level = event.payload.get("level", "info")
            level_style = LOG_LEVEL_STYLES.get(level, "white")
            proc_name = proc_names.get(event.pid, event.pid)
            message = event.payload.get("message", "")

            table.add_row(
                time_str,
                Text(proc_name, style="cyan"),
                Text(f"[{level_style}]{message}[/{level_style}]"),
            )

        if not visible:
            table.add_row("", "", Text("No logs yet", style="dim"))

        border_style = "green" if self._focused_pane() == "logs" else "dim"
        return Panel(table, title=f"[bold]Logs[/bold] [dim]({title_proc})[/dim]",
                     border_style=border_style)

    def _render_detail_pane(self, proc: ProcessInfo) -> Panel:
        """Full detail view for selected process."""
        lines = []
        now = time.time()

        lines.append(f"[bold]{proc.name}[/bold]  [dim]{proc.pid}[/dim]")
        lines.append("")

        # State
        state_style = STATE_STYLES.get(proc.state, "white")
        lines.append(f"[bold]State:[/bold]  [{state_style}]{proc.state.value}[/{state_style}]")
        lines.append("")

        # Uptime
        if proc.state == ProcessState.RUNNING and proc.last_started_at:
            elapsed = now - proc.last_started_at
            lines.append(f"[bold]Uptime:[/bold] {self._format_duration(elapsed)}")
        else:
            lines.append("[bold]Uptime:[/bold] -")
        lines.append("")

        # Config
        lines.append("[bold underline]Configuration[/bold underline]")
        lines.append(f"  Crash probability: {proc.crash_prob:.1%}")
        lines.append(f"  Log frequency:     {proc.log_freq:.1f} msg/sec")
        lines.append("")

        # Stats
        lines.append("[bold underline]Statistics[/bold underline]")
        lines.append(f"  Start count:  {proc.start_count}")
        restart_count = max(0, proc.start_count - 1)
        lines.append(f"  Restarts:     {restart_count}")
        created_str = time.strftime("%H:%M:%S", time.localtime(proc.created_at))
        lines.append(f"  Created:      {created_str}")
        lines.append("")

        # Recent logs
        all_logs = self.process_logs()
        proc_logs = all_logs.get(proc.pid, [])
        if proc_logs:
            lines.append("[bold underline]Recent Logs[/bold underline]")
            for event in proc_logs[-5:]:
                level = event.payload.get("level", "info")
                level_style = LOG_LEVEL_STYLES.get(level, "white")
                msg = event.payload.get("message", "")
                lines.append(f"  [{level_style}]{msg}[/{level_style}]")
        else:
            lines.append("[dim]No logs yet[/dim]")

        # Available actions
        lines.append("")
        lines.append("[bold underline]Actions[/bold underline]")
        if proc.state in (ProcessState.STOPPED, ProcessState.CRASHED):
            lines.append("  [green]s[/green] = start")
            if proc.state == ProcessState.STOPPED:
                lines.append("  [red]d[/red] = remove")
        elif proc.state == ProcessState.RUNNING:
            lines.append("  [yellow]x[/yellow] = stop")
            lines.append("  [yellow]r[/yellow] = restart")

        border_style = "green" if self._focused_pane() == "detail" else "dim"
        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold]Detail[/bold]",
            border_style=border_style,
        )

    def _render_debug_pane(self) -> Panel:
        """Debug pane with system metrics and sim controls."""
        lines = []

        # Metrics
        lines.append("[bold underline]Metrics[/bold underline]")
        lines.append(f"  Events/sec:     {self._events_per_sec:>8.1f}")
        lines.append(f"  Total events:   {self.store.total:>8d}")
        lines.append(f"  Render time:    {self._render_time_ms:>7.2f} ms")

        # Memory RSS (macOS: ru_maxrss is bytes)
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = rss_bytes / 1048576
        lines.append(f"  Memory (RSS):   {rss_mb:>7.1f} MB")

        lines.append(f"  Active sims:    {len(self.manager._simulators):>8d}")
        lines.append("")

        # Controls
        lines.append("[bold underline]Controls[/bold underline]")
        rate = self._rate_multiplier()
        rate_str = f"{rate:.0f}x" if rate == int(rate) else f"{rate}x"
        lines.append(f"  Rate multiplier: [bold cyan]{rate_str:>5}[/bold cyan]")
        lines.append("    [dim]+/-[/dim] to adjust")
        lines.append("")
        lines.append("  [dim]B[/dim] = bulk spawn (10)")
        lines.append("  [dim]S[/dim] = mass stop")
        lines.append("  [dim]R[/dim] = mass restart")
        lines.append("  [dim]X[/dim] = mass close")
        lines.append("  [dim]D[/dim] = hide debug pane")

        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold]Debug[/bold]",
            border_style="magenta",
        )

    def _render_status(self) -> Text:
        mode = self._mode()

        if mode == Mode.FILTER:
            entries = self._filter_history.entries()
            hist_str = f"  [dim]history: {', '.join(entries[:3])}[/dim]" if entries else ""
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

        selected_idx = self._selected_index()
        filtered = self.filtered_processes()
        sel_part = ""
        if selected_idx is not None and filtered:
            sel_part = f"  [cyan]Selected: {selected_idx + 1}/{len(filtered)}[/cyan]"

        crashed_part = f"  [red]Crashed: {crashed_count}[/red]" if crashed_count > 0 else ""

        return Text.from_markup(
            f"[bold]Focus:[/bold] {self._focused_pane()}  |  "
            f"[bold]Total:[/bold] {len(processes)}  "
            f"[green]Running: {running_count}[/green]{crashed_part}{sel_part}"
        )

    def _render_help(self) -> Text:
        mode = self._mode()

        if mode == Mode.FILTER:
            return Text.from_markup(
                "[dim]Enter[/dim]=apply  [dim]Esc[/dim]=cancel  |  "
                "Syntax: [cyan]name[/cyan]  [cyan]state=[/cyan]running|stopped|crashed"
            )

        if mode == Mode.ADD:
            return Text.from_markup(
                "[dim]Enter[/dim]=create  [dim]Esc[/dim]=cancel"
            )

        if mode == Mode.CONFIRM:
            return Text.from_markup(
                "[dim]y[/dim]=confirm  [dim]n/Esc[/dim]=cancel"
            )

        # VIEW mode
        history = self._filter_history.entries()
        h_key = "  [dim]h[/dim]=last" if history else ""
        return Text.from_markup(
            "[dim]1[/dim]=list  [dim]2[/dim]=logs  [dim]3[/dim]=detail  |  "
            "[dim]j/k[/dim]=nav  [dim]s[/dim]=start  [dim]x[/dim]=stop  "
            "[dim]r[/dim]=restart  [dim]d[/dim]=remove  |  "
            f"[dim]/[/dim]=filter  [dim]a[/dim]=add  [dim]c[/dim]=clear{h_key}  |  "
            "[dim]D[/dim]=debug  [dim]q[/dim]=quit"
        )

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

    # Create app first so manager can reference the rate_multiplier signal
    app = ProcessMonitorApp(store, None, console)  # type: ignore[arg-type]
    manager = ProcessManager(store, rate_multiplier=app._rate_multiplier)
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
