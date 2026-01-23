#!/usr/bin/env python3
"""
HTTP Request Logger - Interactive CLI for monitoring HTTP traffic.

Tests pattern generality with:
- Correlated events (request → response pairs)
- Derived latency from two events
- Status code filtering, path patterns

Run with: uv run examples/http_logger.py
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
import fnmatch
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from reaktiv import Signal, Computed, LinkedSignal, batch
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Framework imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from framework import EventStore, BaseApp, Mode


# =============================================================================
# EVENTS
# =============================================================================

@dataclass(frozen=True)
class HttpEvent:
    """HTTP request or response event."""
    request_id: str
    kind: Literal["request", "response"]
    method: str
    path: str
    status: int | None  # None for requests
    ts: float = field(default_factory=time.time)
    headers: dict = field(default_factory=dict)
    body_size: int = 0


@dataclass
class CompletedRequest:
    """A matched request-response pair with computed latency."""
    request_id: str
    method: str
    path: str
    status: int
    request_ts: float
    response_ts: float
    latency_ms: float
    request_size: int
    response_size: int


# =============================================================================
# FILTER QUERY (extended for HTTP)
# =============================================================================

@dataclass
class HttpFilter:
    """
    HTTP-specific filter supporting:
    - status=200           (exact)
    - status=2xx           (glob pattern for status class)
    - status=4xx,5xx       (OR multiple patterns)
    - path=/api/*          (glob pattern)
    - method=GET,POST      (OR)
    - latency>500          (comparison - only on completed requests)
    """
    conditions: list[tuple[str, str, str]] = field(default_factory=list)
    raw: str = ""

    @classmethod
    def parse(cls, query: str) -> "HttpFilter":
        if not query.strip():
            return cls(raw=query)

        conditions = []
        # Match: field op value (op can be =, >, <, >=, <=)
        pattern = r'(\w+)\s*(>=|<=|>|<|=)\s*(\S+)'
        for match in re.finditer(pattern, query):
            field, op, value = match.groups()
            conditions.append((field, op, value))
        return cls(conditions=conditions, raw=query)

    def matches_event(self, event: HttpEvent) -> bool:
        """Match against raw HttpEvent (for pending requests view)."""
        for field, op, value in self.conditions:
            if field == "latency":
                continue  # Can't filter events by latency

            if field == "status":
                if event.status is None:
                    continue  # Requests don't have status yet
                if not self._match_status(event.status, value):
                    return False
            elif field == "path":
                if not self._match_glob(event.path, value):
                    return False
            elif field == "method":
                if not self._match_or(event.method, value):
                    return False
        return True

    def matches_completed(self, req: CompletedRequest) -> bool:
        """Match against CompletedRequest (has latency)."""
        for field, op, value in self.conditions:
            if field == "status":
                if not self._match_status(req.status, value):
                    return False
            elif field == "path":
                if not self._match_glob(req.path, value):
                    return False
            elif field == "method":
                if not self._match_or(req.method, value):
                    return False
            elif field == "latency":
                if not self._match_comparison(req.latency_ms, op, value):
                    return False
        return True

    def _match_status(self, status: int, pattern: str) -> bool:
        """Match status with glob support (2xx, 4xx, etc)."""
        # Support comma-separated OR
        patterns = [p.strip() for p in pattern.split(",")]
        for p in patterns:
            if "x" in p.lower():
                # Convert 2xx to 2* for fnmatch
                glob = p.lower().replace("x", "?")
                if fnmatch.fnmatch(str(status), glob):
                    return True
            elif str(status) == p:
                return True
        return False

    def _match_glob(self, value: str, pattern: str) -> bool:
        """Match with glob support."""
        patterns = [p.strip() for p in pattern.split(",")]
        return any(fnmatch.fnmatch(value, p) for p in patterns)

    def _match_or(self, value: str, pattern: str) -> bool:
        """Match against comma-separated values."""
        values = [v.strip().upper() for v in pattern.split(",")]
        return value.upper() in values

    def _match_comparison(self, value: float, op: str, threshold: str) -> bool:
        """Match numeric comparison."""
        try:
            thresh = float(threshold)
        except ValueError:
            return True  # Invalid threshold, skip filter

        if op == ">":
            return value > thresh
        elif op == ">=":
            return value >= thresh
        elif op == "<":
            return value < thresh
        elif op == "<=":
            return value <= thresh
        elif op == "=":
            return abs(value - thresh) < 0.001
        return True

    def description(self) -> str:
        return self.raw if self.conditions else "all"


# =============================================================================
# TRAFFIC SIMULATOR
# =============================================================================

PATHS = [
    "/api/users",
    "/api/users/{id}",
    "/api/orders",
    "/api/orders/{id}",
    "/api/products",
    "/api/health",
    "/static/app.js",
    "/static/style.css",
]

METHODS = ["GET", "GET", "GET", "POST", "PUT", "DELETE"]  # Weighted toward GET


class TrafficSimulator:
    """Generates simulated HTTP traffic."""

    def __init__(self, store: EventStore):
        self._store = store
        self._pending: dict[str, HttpEvent] = {}  # request_id -> request
        self._request_counter = 0
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        while True:
            await asyncio.sleep(random.uniform(0.1, 0.3))

            # More requests than responses to build up pending queue
            if random.random() < 0.7 or not self._pending:
                await self._send_request()
            else:
                await self._send_response()

    async def _send_request(self):
        self._request_counter += 1
        request_id = f"req-{self._request_counter:04d}"

        path = random.choice(PATHS)
        if "{id}" in path:
            path = path.replace("{id}", str(random.randint(1, 100)))

        request = HttpEvent(
            request_id=request_id,
            kind="request",
            method=random.choice(METHODS),
            path=path,
            status=None,
            body_size=random.randint(0, 1000),
        )

        self._store.add(request)
        self._pending[request_id] = request

    async def _send_response(self):
        if not self._pending:
            return

        # Pick a pending request (older ones more likely to respond)
        request_id = random.choice(list(self._pending.keys()))
        request = self._pending.pop(request_id)

        # Simulate latency (some requests are slow)
        latency = random.uniform(10, 200)
        if random.random() < 0.1:  # 10% slow requests
            latency = random.uniform(500, 2000)

        # Determine status code
        status = self._pick_status(request.method)

        response = HttpEvent(
            request_id=request_id,
            kind="response",
            method=request.method,
            path=request.path,
            status=status,
            ts=request.ts + (latency / 1000),  # Add latency
            body_size=random.randint(100, 50000) if status == 200 else random.randint(50, 500),
        )

        self._store.add(response)

    def _pick_status(self, method: str) -> int:
        """Pick status code with realistic distribution."""
        r = random.random()
        if r < 0.85:
            return 200 if method != "POST" else random.choice([200, 201])
        elif r < 0.92:
            return random.choice([301, 304])
        elif r < 0.97:
            return random.choice([400, 401, 403, 404])
        else:
            return random.choice([500, 502, 503])


# =============================================================================
# HTTP LOGGER (main dashboard)
# =============================================================================

STATUS_STYLES = {
    2: "green",
    3: "cyan",
    4: "yellow",
    5: "red bold",
}

METHOD_STYLES = {
    "GET": "cyan",
    "POST": "green",
    "PUT": "yellow",
    "DELETE": "red",
}


class HttpLogger(BaseApp):
    def __init__(self, store: EventStore, console: Console):
        super().__init__(console)
        self.store = store

        # Domain-specific signals
        self._focused_pane = Signal("requests")  # "requests", "pending", "detail", or "metrics"
        self._filter = Signal(HttpFilter())
        self._filter_history: Signal[list[str]] = Signal([])
        self._show_pending = Signal(True)  # Toggle pending pane visibility
        self._pending_threshold = Signal(500.0)  # ms - highlight "stuck" requests

        # LinkedSignal: selection resets to None whenever filter changes
        self._selected_index: LinkedSignal[int | None] = LinkedSignal(
            lambda: None, source=self._filter
        )

        # Computed: correlation (request → response pairs)
        self.completed_requests = Computed(lambda: self._compute_completed())
        self.pending_requests = Computed(lambda: self._compute_pending())

        # Computed: metrics
        self.total_requests = Computed(lambda: len(self.completed_requests()))
        self.pending_count = Computed(lambda: len(self.pending_requests()))
        self.avg_latency = Computed(lambda: self._compute_avg_latency())
        self.p95_latency = Computed(lambda: self._compute_p95_latency())
        self.status_counts = Computed(lambda: self._compute_status_counts())
        self.error_rate = Computed(lambda: self._compute_error_rate())

        # Computed: filtered
        self.filtered_completed = Computed(lambda: self._compute_filtered_completed())

        # Computed: selected request (depends on selection index and filtered list)
        self.selected_request = Computed(lambda: self._compute_selected_request())

    def _render_dependencies(self) -> None:
        """Read signals that should trigger re-render.

        Only Signals here — Computeds evaluate lazily in render().
        """
        self.store.version()
        self._filter()
        self._filter_history()
        self._show_pending()
        self._pending_threshold()
        self._selected_index()

    def _compute_completed(self) -> list[CompletedRequest]:
        """Match requests to responses, compute latency."""
        self.store.version()  # Dependency

        requests: dict[str, HttpEvent] = {}
        completed: list[CompletedRequest] = []

        for event in self.store.events:
            if event.kind == "request":
                requests[event.request_id] = event
            elif event.kind == "response" and event.request_id in requests:
                req = requests.pop(event.request_id)
                completed.append(CompletedRequest(
                    request_id=event.request_id,
                    method=req.method,
                    path=req.path,
                    status=event.status,
                    request_ts=req.ts,
                    response_ts=event.ts,
                    latency_ms=(event.ts - req.ts) * 1000,
                    request_size=req.body_size,
                    response_size=event.body_size,
                ))

        return completed

    def _compute_pending(self) -> list[HttpEvent]:
        """Requests without responses."""
        self.store.version()

        responded: set[str] = set()
        for event in self.store.events:
            if event.kind == "response":
                responded.add(event.request_id)

        return [e for e in self.store.events
                if e.kind == "request" and e.request_id not in responded]

    def _compute_avg_latency(self) -> float:
        completed = self.completed_requests()
        if not completed:
            return 0.0
        return sum(r.latency_ms for r in completed) / len(completed)

    def _compute_p95_latency(self) -> float:
        completed = self.completed_requests()
        if not completed:
            return 0.0
        latencies = sorted(r.latency_ms for r in completed)
        idx = int(len(latencies) * 0.95)
        return latencies[min(idx, len(latencies) - 1)]

    def _compute_status_counts(self) -> dict[int, int]:
        completed = self.completed_requests()
        counts: dict[int, int] = {}
        for req in completed:
            counts[req.status] = counts.get(req.status, 0) + 1
        return counts

    def _compute_error_rate(self) -> float:
        completed = self.completed_requests()
        if not completed:
            return 0.0
        errors = sum(1 for r in completed if r.status >= 400)
        return (errors / len(completed)) * 100

    def _compute_filtered_completed(self) -> list[CompletedRequest]:
        completed = self.completed_requests()
        filt = self._filter()
        return [r for r in completed if filt.matches_completed(r)]

    def _compute_selected_request(self) -> CompletedRequest | None:
        idx = self._selected_index()
        if idx is None:
            return None
        filtered = self.filtered_completed()
        if 0 <= idx < len(filtered):
            return filtered[idx]
        return None

    # =========================================================================
    # KEY HANDLING
    # =========================================================================

    def handle_key(self, key: str) -> bool:
        if self._mode() == Mode.VIEW:
            return self._handle_view_key(key)
        elif self._mode() == Mode.FILTER:
            return self._handle_filter_key(key)
        return True

    def _handle_view_key(self, key: str) -> bool:
        if key == "q":
            self._running.set(False)
            return False
        elif key == "1":
            self._focused_pane.set("requests")
        elif key == "2":
            if self._selected_index() is not None:
                self._focused_pane.set("detail")
            else:
                self._focused_pane.set("pending")
                if not self._show_pending():
                    self._show_pending.set(True)
        elif key == "3":
            self._focused_pane.set("metrics")
        elif key == "/" and self._focused_pane() == "requests":
            with batch():
                self._mode.set(Mode.FILTER)
                self._input_buffer.set("")
        elif key == "c":
            # LinkedSignal auto-resets _selected_index when filter changes
            self._filter.set(HttpFilter())
        elif key == "e":  # Errors shortcut
            self._filter.set(HttpFilter.parse("status=4xx,5xx"))
        elif key == "s":  # Slow requests shortcut
            self._filter.set(HttpFilter.parse("latency>500"))
        elif key == "p":  # Toggle pending pane
            with batch():
                self._selected_index.set(None)
                self._show_pending.update(lambda v: not v)
        elif key == "h":
            history = self._filter_history()
            if history:
                self._filter.set(HttpFilter.parse(history[0]))
        elif key == "\x1b":  # Escape - clear selection
            self._selected_index.set(None)
        elif key == "j" or key == "J":  # Down / select next
            self._move_selection(1)
        elif key == "k" or key == "K":  # Up / select previous
            self._move_selection(-1)
        elif key == "\r" or key == "\n":  # Enter - focus detail pane
            if self._selected_index() is not None:
                self._focused_pane.set("detail")
        return True

    def _move_selection(self, delta: int) -> None:
        """Move selection up or down in the filtered list."""
        filtered = self.filtered_completed()
        if not filtered:
            return

        current = self._selected_index()
        if current is None:
            # Start at end (most recent) for down, start for up
            new_idx = len(filtered) - 1 if delta > 0 else 0
        else:
            new_idx = current + delta
            # Clamp to valid range
            new_idx = max(0, min(len(filtered) - 1, new_idx))

        self._selected_index.set(new_idx)

    def _handle_filter_key(self, key: str) -> bool:
        if key == "\r" or key == "\n":
            raw = self._input_buffer()
            if raw.strip():
                self._filter_history.update(lambda h:
                    ([raw] + [x for x in h if x != raw])[:5]
                )
            with batch():
                self._filter.set(HttpFilter.parse(raw))
                self._mode.set(Mode.VIEW)
                self._input_buffer.set("")
        elif key == "\x1b":  # Escape
            with batch():
                self._mode.set(Mode.VIEW)
                self._input_buffer.set("")
        elif key == "\x7f":  # Backspace
            self._input_buffer.update(lambda s: s[:-1])
        elif key.isprintable():
            self._input_buffer.update(lambda s: s + key)
        return True

    # =========================================================================
    # RENDER
    # =========================================================================

    def render(self) -> Layout:
        layout = Layout()

        layout.split_column(
            Layout(name="main", ratio=1),
            Layout(self._render_status(), name="status", size=1),
            Layout(self._render_help(), name="help", size=1),
        )

        selected = self.selected_request()

        if selected is not None:
            # Show detail pane when request is selected
            layout["main"].split_row(
                Layout(self._render_requests_pane(), name="requests", ratio=2),
                Layout(self._render_detail_pane(selected), name="detail", ratio=1),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=35),
            )
        elif self._show_pending():
            layout["main"].split_row(
                Layout(self._render_requests_pane(), name="requests", ratio=2),
                Layout(self._render_pending_pane(), name="pending", ratio=1),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=35),
            )
        else:
            layout["main"].split_row(
                Layout(self._render_requests_pane(), name="requests", ratio=2),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=35),
            )

        return layout

    def _render_requests_pane(self) -> Panel:
        """Completed requests with latency."""
        table = Table(
            show_header=True,
            header_style="bold",
            expand=True,
            box=None,
            padding=(0, 1),
        )
        table.add_column("", no_wrap=True, width=1)  # Selection indicator
        table.add_column("Time", no_wrap=True, style="dim")
        table.add_column("Method", no_wrap=True)
        table.add_column("Path", ratio=1)
        table.add_column("Status", no_wrap=True)
        table.add_column("Latency", no_wrap=True, justify="right")

        filtered = self.filtered_completed()
        max_rows = self._available_rows()
        selected_idx = self._selected_index()

        # Calculate which slice of requests to show
        # If selected, try to keep selection visible
        start_idx = max(0, len(filtered) - max_rows)
        if selected_idx is not None and selected_idx < start_idx:
            start_idx = selected_idx
        end_idx = min(len(filtered), start_idx + max_rows)

        for i in range(start_idx, end_idx):
            req = filtered[i]
            is_selected = (i == selected_idx)

            time_str = time.strftime("%H:%M:%S", time.localtime(req.request_ts))
            method_style = METHOD_STYLES.get(req.method, "white")
            status_style = STATUS_STYLES.get(req.status // 100, "white")

            # Latency coloring
            latency_style = "green"
            if req.latency_ms > 500:
                latency_style = "yellow"
            if req.latency_ms > 1000:
                latency_style = "red"

            # Selection indicator and row styling
            indicator = "▶" if is_selected else ""
            row_style = "reverse" if is_selected else None

            table.add_row(
                Text(indicator, style="cyan bold"),
                Text(time_str, style="dim" if not is_selected else "dim reverse"),
                Text(req.method, style=method_style if not is_selected else f"{method_style} reverse"),
                Text(req.path, style="" if not is_selected else "reverse"),
                Text(str(req.status), style=status_style if not is_selected else f"{status_style} reverse"),
                Text(f"{req.latency_ms:.0f}ms", style=latency_style if not is_selected else f"{latency_style} reverse"),
            )

        border_style = "green" if self._focused_pane() == "requests" else "dim"
        filt = self._filter()
        title = f"[bold]Requests[/bold] [dim]({filt.description()})[/dim]"
        return Panel(table, title=title, border_style=border_style)

    def _render_pending_pane(self) -> Panel:
        """Pending requests with live age tracking."""
        table = Table(
            show_header=True,
            header_style="bold",
            expand=True,
            box=None,
            padding=(0, 1),
        )
        table.add_column("Age", no_wrap=True, justify="right")
        table.add_column("Method", no_wrap=True)
        table.add_column("Path", ratio=1)
        table.add_column("ID", no_wrap=True, style="dim")

        pending = self.pending_requests()
        threshold = self._pending_threshold()
        now = time.time()
        max_rows = self._available_rows()

        # Sort by age (oldest first)
        sorted_pending = sorted(pending, key=lambda e: e.ts)

        for event in sorted_pending[:max_rows]:
            age_ms = (now - event.ts) * 1000
            method_style = METHOD_STYLES.get(event.method, "white")

            # Age styling: green < threshold, yellow < 2x, red >= 2x
            if age_ms >= threshold * 2:
                age_style = "red bold"
                age_indicator = "!"
            elif age_ms >= threshold:
                age_style = "yellow"
                age_indicator = ""
            else:
                age_style = "green"
                age_indicator = ""

            # Format age nicely
            if age_ms < 1000:
                age_str = f"{age_ms:.0f}ms"
            else:
                age_str = f"{age_ms/1000:.1f}s"

            table.add_row(
                Text(f"{age_indicator}{age_str}", style=age_style),
                Text(event.method, style=method_style),
                event.path,
                event.request_id[-4:],  # Last 4 chars of ID
            )

        if not pending:
            table.add_row("", "", Text("No pending requests", style="dim"), "")

        border_style = "green" if self._focused_pane() == "pending" else "dim"
        stuck_count = sum(1 for e in pending if (now - e.ts) * 1000 >= threshold)
        stuck_str = f" [red]{stuck_count} stuck[/red]" if stuck_count > 0 else ""
        title = f"[bold]Pending[/bold] [dim]({len(pending)})[/dim]{stuck_str}"
        return Panel(table, title=title, border_style=border_style)

    def _render_detail_pane(self, req: CompletedRequest) -> Panel:
        """Detail view for selected request."""
        lines = []

        # Request info
        method_style = METHOD_STYLES.get(req.method, "white")
        status_style = STATUS_STYLES.get(req.status // 100, "white")

        lines.append(f"[bold]{req.request_id}[/bold]")
        lines.append("")
        lines.append(f"[{method_style}]{req.method}[/{method_style}] {req.path}")
        lines.append("")

        # Status with description
        status_desc = {
            200: "OK", 201: "Created", 204: "No Content",
            301: "Moved", 304: "Not Modified",
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
            500: "Internal Error", 502: "Bad Gateway", 503: "Unavailable",
        }.get(req.status, "")
        lines.append(f"[bold]Status:[/bold] [{status_style}]{req.status} {status_desc}[/{status_style}]")
        lines.append("")

        # Timing
        lines.append("[bold underline]Timing[/bold underline]")
        request_time = time.strftime("%H:%M:%S", time.localtime(req.request_ts))
        response_time = time.strftime("%H:%M:%S", time.localtime(req.response_ts))
        lines.append(f"  Request:  {request_time}")
        lines.append(f"  Response: {response_time}")

        # Latency with styling
        latency_style = "green"
        if req.latency_ms > 500:
            latency_style = "yellow"
        if req.latency_ms > 1000:
            latency_style = "red"
        lines.append(f"  Latency:  [{latency_style}]{req.latency_ms:.1f}ms[/{latency_style}]")
        lines.append("")

        # Size
        lines.append("[bold underline]Size[/bold underline]")
        lines.append(f"  Request:  {req.request_size:,} bytes")
        lines.append(f"  Response: {req.response_size:,} bytes")
        lines.append("")

        # Percentile context
        completed = self.completed_requests()
        if completed:
            latencies = sorted(r.latency_ms for r in completed)
            rank = sum(1 for l in latencies if l <= req.latency_ms)
            percentile = (rank / len(latencies)) * 100
            lines.append(f"[dim]Faster than {100 - percentile:.0f}% of requests[/dim]")

        border_style = "green" if self._focused_pane() == "detail" else "dim"
        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold]Detail[/bold]",
            border_style=border_style,
        )

    def _render_metrics_pane(self) -> Panel:
        """Latency stats and status distribution."""
        filt = self._filter()
        has_filter = bool(filt.conditions)

        # Overall metrics
        total = self.total_requests()
        pending = self.pending_count()
        avg_lat = self.avg_latency()
        p95_lat = self.p95_latency()
        error_rate = self.error_rate()
        status_counts = self.status_counts()

        lines = ["[bold underline]Overview[/bold underline]"]
        lines.append(f"  Completed: {total}  Pending: {pending}")
        lines.append("")
        lines.append("[bold underline]Latency[/bold underline]")
        lines.append(f"  Avg: {avg_lat:.0f}ms  P95: {p95_lat:.0f}ms")
        lines.append("")
        lines.append("[bold underline]Status Codes[/bold underline]")

        for status in sorted(status_counts.keys()):
            count = status_counts[status]
            style = STATUS_STYLES.get(status // 100, "white")
            lines.append(f"  [{style}]{status}[/{style}]: {count}")

        lines.append("")
        error_style = "red" if error_rate > 5 else "yellow" if error_rate > 1 else "green"
        lines.append(f"  Error rate: [{error_style}]{error_rate:.1f}%[/{error_style}]")

        if has_filter:
            filtered = self.filtered_completed()
            lines.append("")
            lines.append(f"[bold underline]Filtered ({filt.raw})[/bold underline]")
            lines.append(f"  Showing: {len(filtered)} requests")

        border_style = "green" if self._focused_pane() == "metrics" else "dim"
        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold]Metrics[/bold]",
            border_style=border_style,
        )

    def _render_status(self) -> Text:
        if self._mode() == Mode.FILTER:
            history = self._filter_history()
            hist_str = f"  [dim]history: {', '.join(history[:3])}[/dim]" if history else ""
            return Text.from_markup(f"[bold]Filter:[/bold] /{self._input_buffer()}█{hist_str}")

        history = self._filter_history()
        hist_part = f"  [dim]h={history[0]}[/dim]" if history else ""

        pending = self.pending_count()
        pending_part = f"  [yellow]Pending: {pending}[/yellow]" if pending > 0 else ""

        selected_idx = self._selected_index()
        filtered = self.filtered_completed()
        if selected_idx is not None and filtered:
            selected_part = f"  [cyan]Selected: {selected_idx + 1}/{len(filtered)}[/cyan]"
        else:
            selected_part = ""

        return Text.from_markup(
            f"[bold]Focus:[/bold] {self._focused_pane()}  |  "
            f"[bold]Completed:[/bold] {self.total_requests()}{pending_part}{selected_part}{hist_part}"
        )

    def _render_help(self) -> Text:
        if self._mode() == Mode.FILTER:
            return Text.from_markup(
                "[dim]Enter[/dim]=apply  [dim]Esc[/dim]=cancel  |  "
                "Fields: [cyan]status[/cyan]=200,4xx  [cyan]path[/cyan]=/api/*  "
                "[cyan]method[/cyan]=GET  [cyan]latency[/cyan]>500"
            )

        selected = self._selected_index() is not None
        pane2 = "detail" if selected else "pending"
        pane_keys = f"[dim]1[/dim]=requests  [dim]2[/dim]={pane2}  [dim]3[/dim]=metrics"

        if self._focused_pane() == "requests":
            history = self._filter_history()
            h_key = "  [dim]h[/dim]=last" if history else ""
            nav_keys = "[dim]j/k[/dim]=select  " if not selected else "[dim]j/k[/dim]=nav  [dim]Esc[/dim]=deselect  "
            return Text.from_markup(
                f"{pane_keys}  |  {nav_keys}"
                f"[dim]/[/dim]=filter  [dim]e[/dim]=errors  [dim]s[/dim]=slow{h_key}  |  "
                "[dim]q[/dim]=quit"
            )
        elif self._focused_pane() == "detail":
            return Text.from_markup(
                f"{pane_keys}  |  [dim]j/k[/dim]=nav  [dim]Esc[/dim]=back  |  [dim]q[/dim]=quit"
            )
        else:
            return Text.from_markup(
                f"{pane_keys}  |  [dim]q[/dim]=quit"
            )


# =============================================================================
# MAIN
# =============================================================================

async def run_logger(duration: float | None = None):
    console = Console()

    console.print("\n[bold]HTTP Request Logger[/bold]")
    console.print("Monitors request/response pairs with latency tracking")
    if duration:
        console.print(f"[dim]Running for {duration}s...[/dim]")
    console.print()
    await asyncio.sleep(0.5)

    store: EventStore[HttpEvent] = EventStore()
    simulator = TrafficSimulator(store)
    app = HttpLogger(store, console)

    await simulator.start()

    try:
        await app.run(duration=duration)
    finally:
        await simulator.stop()

    console.print(f"\n[bold]Done![/bold] {app.total_requests()} completed requests")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", "-d", type=float, default=None,
                        help="Run for N seconds (default: until quit)")
    args = parser.parse_args()

    try:
        asyncio.run(run_logger(duration=args.duration))
    except KeyboardInterrupt:
        print("\nInterrupted")


if __name__ == "__main__":
    main()
