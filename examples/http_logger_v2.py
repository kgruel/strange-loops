#!/usr/bin/env python3
"""
HTTP Request Logger v2 - Enhanced Interactive CLI for monitoring HTTP traffic.

Improvements over v1:
- Latency histogram pane (l key)
- Endpoint breakdown pane (b key)
- Sliding window metrics (w key toggle)
- Enhanced percentiles (p50, p90, p99)
- Request rate calculation
- Filter enhancements (age>N, id=*pattern*)
- Scroll indicators for viewport
- Keyboard shortcuts help overlay (? key)

Run with: uv run examples/http_logger_v2.py
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
import termios
import time
import tty
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Literal

from reaktiv import Signal, Computed, Effect
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


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
# EVENT STORE (same pattern as v1)
# =============================================================================

class EventStore:
    """Append-only event store with version signal."""

    def __init__(self):
        self._events: list[HttpEvent] = []
        self.version = Signal(0)

    def add(self, event: HttpEvent) -> None:
        self._events.append(event)
        self.version.update(lambda v: v + 1)

    @property
    def events(self) -> list[HttpEvent]:
        return self._events

    @property
    def total(self) -> int:
        return len(self._events)


# =============================================================================
# FILTER QUERY (extended for v2)
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
    - age>1000             (filter pending by age in ms) [v2]
    - id=*0042*            (request ID matching) [v2]
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

    def matches_event(self, event: HttpEvent, now: float | None = None) -> bool:
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
            elif field == "id":
                if not self._match_glob(event.request_id, value):
                    return False
            elif field == "age" and now is not None:
                # Filter pending requests by age in ms
                age_ms = (now - event.ts) * 1000
                if not self._match_comparison(age_ms, op, value):
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
            elif field == "id":
                if not self._match_glob(req.request_id, value):
                    return False
            # age filter doesn't apply to completed requests
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

    def has_age_filter(self) -> bool:
        """Check if filter includes age condition (for pending pane)."""
        return any(f == "age" for f, _, _ in self.conditions)

    def description(self) -> str:
        return self.raw if self.conditions else "all"


# =============================================================================
# MODE & MIDDLE PANE MODE
# =============================================================================

class Mode(Enum):
    VIEW = auto()
    FILTER = auto()


class MiddlePaneMode(Enum):
    PENDING = auto()      # Default: pending requests
    HISTOGRAM = auto()    # Latency histogram (l key)
    BREAKDOWN = auto()    # Endpoint breakdown (b key)


# =============================================================================
# KEYBOARD INPUT (same as v1)
# =============================================================================

class KeyboardInput:
    def __init__(self):
        self._old_settings = None
        self._available = True

    def __enter__(self):
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, OSError):
            self._available = False
        return self

    def __exit__(self, *args):
        if self._old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            except (termios.error, OSError):
                pass

    def get_key(self) -> str | None:
        if not self._available:
            return None
        import select
        try:
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1)
        except (OSError, ValueError):
            self._available = False
        return None


# =============================================================================
# TRAFFIC SIMULATOR (same as v1)
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
# PATH PATTERN NORMALIZATION (for endpoint breakdown)
# =============================================================================

def normalize_path(path: str) -> str:
    """
    Collapse numeric IDs in paths to {id} pattern.
    /api/users/123 -> /api/users/{id}
    /api/orders/456/items/789 -> /api/orders/{id}/items/{id}
    """
    parts = path.split("/")
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append("{id}")
        else:
            normalized.append(part)
    return "/".join(normalized)


# =============================================================================
# LATENCY HISTOGRAM BUCKETS
# =============================================================================

LATENCY_BUCKETS = [
    (0, 50, "0-50ms"),
    (50, 100, "50-100ms"),
    (100, 200, "100-200ms"),
    (200, 500, "200-500ms"),
    (500, 1000, "500ms-1s"),
    (1000, float("inf"), "1s+"),
]


def bucket_latency(latency_ms: float) -> int:
    """Return bucket index for a latency value."""
    for i, (low, high, _) in enumerate(LATENCY_BUCKETS):
        if low <= latency_ms < high:
            return i
    return len(LATENCY_BUCKETS) - 1  # Last bucket for anything >= 1s


# =============================================================================
# HTTP LOGGER V2 (main dashboard)
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


@dataclass
class EndpointStats:
    """Stats for a single endpoint pattern."""
    pattern: str
    count: int
    total_latency: float
    error_count: int

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.count if self.count else 0

    @property
    def error_rate(self) -> float:
        return (self.error_count / self.count * 100) if self.count else 0


class HttpLogger:
    def __init__(self, store: EventStore, console: Console):
        self.store = store
        self._console = console
        self._live: Live | None = None

        # UI state as Signals
        self._running = Signal(True)
        self._focused_pane = Signal("requests")  # "requests", "pending", "detail", "metrics", "histogram", "breakdown"
        self._mode = Signal(Mode.VIEW)
        self._filter = Signal(HttpFilter())
        self._input_buffer = Signal("")
        self._filter_history: Signal[list[str]] = Signal([])
        self._middle_pane_mode = Signal(MiddlePaneMode.PENDING)
        self._pending_threshold = Signal(500.0)  # ms - highlight "stuck" requests

        # v2: Sliding window toggle
        self._use_sliding_window = Signal(False)  # False = all time, True = last 60s
        self._window_duration = 60.0  # seconds

        # v2: Help overlay toggle
        self._show_help = Signal(False)

        # v2: Request rate tracking (completion timestamps for last 10s)
        self._completion_times: deque[float] = deque()
        self._rate_window = 10.0  # seconds

        # Selection state for request detail view
        self._selected_index: Signal[int | None] = Signal(None)  # Index into filtered_completed

        # Computed: correlation (request → response pairs)
        self.completed_requests = Computed(lambda: self._compute_completed())
        self.pending_requests = Computed(lambda: self._compute_pending())

        # Computed: metrics (all time)
        self.total_requests = Computed(lambda: len(self.completed_requests()))
        self.pending_count = Computed(lambda: len(self.pending_requests()))

        # Computed: windowed metrics
        self.windowed_completed = Computed(lambda: self._compute_windowed_completed())
        self.avg_latency = Computed(lambda: self._compute_avg_latency())
        self.percentiles = Computed(lambda: self._compute_percentiles())
        self.status_counts = Computed(lambda: self._compute_status_counts())
        self.error_rate = Computed(lambda: self._compute_error_rate())
        self.request_rate = Computed(lambda: self._compute_request_rate())

        # Computed: latency histogram
        self.latency_histogram = Computed(lambda: self._compute_histogram())

        # Computed: endpoint breakdown
        self.endpoint_stats = Computed(lambda: self._compute_endpoint_stats())

        # Computed: filtered
        self.filtered_completed = Computed(lambda: self._compute_filtered_completed())

        # Computed: selected request (depends on selection index and filtered list)
        self.selected_request = Computed(lambda: self._compute_selected_request())

        # Effect: render
        self._render_effect = Effect(lambda: self._do_render())

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
                # Track completion time for rate calculation
                self._completion_times.append(event.ts)

        # Prune old completion times
        cutoff = time.time() - self._rate_window
        while self._completion_times and self._completion_times[0] < cutoff:
            self._completion_times.popleft()

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

    def _compute_windowed_completed(self) -> list[CompletedRequest]:
        """Get completed requests, filtered by window if enabled."""
        completed = self.completed_requests()
        if not self._use_sliding_window():
            return completed

        cutoff = time.time() - self._window_duration
        return [r for r in completed if r.response_ts >= cutoff]

    def _compute_avg_latency(self) -> float:
        completed = self.windowed_completed()
        if not completed:
            return 0.0
        return sum(r.latency_ms for r in completed) / len(completed)

    def _compute_percentiles(self) -> dict[str, float]:
        """Compute p50, p90, p95, p99."""
        completed = self.windowed_completed()
        if not completed:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}

        latencies = sorted(r.latency_ms for r in completed)
        n = len(latencies)

        def percentile(p: float) -> float:
            idx = int(n * p)
            return latencies[min(idx, n - 1)]

        return {
            "p50": percentile(0.50),
            "p90": percentile(0.90),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
        }

    def _compute_status_counts(self) -> dict[int, int]:
        completed = self.windowed_completed()
        counts: dict[int, int] = {}
        for req in completed:
            counts[req.status] = counts.get(req.status, 0) + 1
        return counts

    def _compute_error_rate(self) -> float:
        completed = self.windowed_completed()
        if not completed:
            return 0.0
        errors = sum(1 for r in completed if r.status >= 400)
        return (errors / len(completed)) * 100

    def _compute_request_rate(self) -> float:
        """Compute requests per second over last 10s window."""
        now = time.time()
        cutoff = now - self._rate_window

        # Prune old times
        while self._completion_times and self._completion_times[0] < cutoff:
            self._completion_times.popleft()

        count = len(self._completion_times)
        return count / self._rate_window

    def _compute_histogram(self) -> list[int]:
        """Compute latency histogram bucket counts."""
        completed = self.windowed_completed()
        counts = [0] * len(LATENCY_BUCKETS)
        for req in completed:
            idx = bucket_latency(req.latency_ms)
            counts[idx] += 1
        return counts

    def _compute_endpoint_stats(self) -> list[EndpointStats]:
        """Compute per-endpoint statistics."""
        completed = self.windowed_completed()
        stats: dict[str, EndpointStats] = {}

        for req in completed:
            pattern = normalize_path(req.path)
            if pattern not in stats:
                stats[pattern] = EndpointStats(
                    pattern=pattern,
                    count=0,
                    total_latency=0.0,
                    error_count=0,
                )
            s = stats[pattern]
            s.count += 1
            s.total_latency += req.latency_ms
            if req.status >= 400:
                s.error_count += 1

        # Sort by count descending
        return sorted(stats.values(), key=lambda s: s.count, reverse=True)

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

    def _do_render(self) -> None:
        """Effect: read dependencies, update Live."""
        # Establish dependencies
        self.store.version()
        self._focused_pane()
        self._mode()
        self._filter()
        self._input_buffer()
        self._filter_history()
        self._middle_pane_mode()
        self._pending_threshold()
        self._selected_index()
        self._use_sliding_window()
        self._show_help()
        self.completed_requests()
        self.pending_requests()
        self.selected_request()
        self.windowed_completed()
        self.latency_histogram()
        self.endpoint_stats()
        self.request_rate()

        if self._live:
            self._live.update(self.render())

    def set_live(self, live: Live) -> None:
        self._live = live
        self._live.update(self.render())

    def _available_rows(self) -> int:
        height = self._console.size.height
        return max(5, height - 8)

    @property
    def running(self) -> bool:
        return self._running()

    def handle_key(self, key: str) -> bool:
        # Help overlay has priority
        if self._show_help():
            if key in ("?", "\x1b", "q"):  # ? or Escape or q closes help
                self._show_help.set(False)
            return True

        if self._mode() == Mode.VIEW:
            return self._handle_view_key(key)
        elif self._mode() == Mode.FILTER:
            return self._handle_filter_key(key)
        return True

    def _handle_view_key(self, key: str) -> bool:
        if key == "q":
            self._running.set(False)
            return False
        elif key == "?":
            self._show_help.set(True)
        elif key == "1":
            self._focused_pane.set("requests")
        elif key == "2":
            if self._selected_index() is not None:
                self._focused_pane.set("detail")
            else:
                middle_mode = self._middle_pane_mode()
                if middle_mode == MiddlePaneMode.PENDING:
                    self._focused_pane.set("pending")
                elif middle_mode == MiddlePaneMode.HISTOGRAM:
                    self._focused_pane.set("histogram")
                elif middle_mode == MiddlePaneMode.BREAKDOWN:
                    self._focused_pane.set("breakdown")
        elif key == "3":
            self._focused_pane.set("metrics")
        elif key == "/" and self._focused_pane() == "requests":
            self._mode.set(Mode.FILTER)
            self._input_buffer.set("")
        elif key == "c":
            self._filter.set(HttpFilter())
            self._selected_index.set(None)  # Clear selection on filter clear
        elif key == "e":  # Errors shortcut
            self._filter.set(HttpFilter.parse("status=4xx,5xx"))
            self._selected_index.set(None)
        elif key == "s":  # Slow requests shortcut
            self._filter.set(HttpFilter.parse("latency>500"))
            self._selected_index.set(None)
        elif key == "p":  # Toggle pending pane (clears selection, switches to pending mode)
            self._selected_index.set(None)
            self._middle_pane_mode.set(MiddlePaneMode.PENDING)
            self._focused_pane.set("pending")
        elif key == "l":  # Toggle latency histogram
            self._selected_index.set(None)
            self._middle_pane_mode.set(MiddlePaneMode.HISTOGRAM)
            self._focused_pane.set("histogram")
        elif key == "b":  # Toggle endpoint breakdown
            self._selected_index.set(None)
            self._middle_pane_mode.set(MiddlePaneMode.BREAKDOWN)
            self._focused_pane.set("breakdown")
        elif key == "w":  # Toggle sliding window
            self._use_sliding_window.update(lambda v: not v)
        elif key == "h":
            history = self._filter_history()
            if history:
                self._filter.set(HttpFilter.parse(history[0]))
                self._selected_index.set(None)
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
            self._filter.set(HttpFilter.parse(raw))
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

    def render(self) -> Layout:
        # Help overlay takes precedence
        if self._show_help():
            return self._render_help_overlay()

        layout = Layout()

        layout.split_column(
            Layout(name="main", ratio=1),
            Layout(self._render_status(), name="status", size=1),
            Layout(self._render_help(), name="help", size=1),
        )

        selected = self.selected_request()
        middle_mode = self._middle_pane_mode()

        if selected is not None:
            # Show detail pane when request is selected
            layout["main"].split_row(
                Layout(self._render_requests_pane(), name="requests", ratio=2),
                Layout(self._render_detail_pane(selected), name="detail", ratio=1),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=35),
            )
        elif middle_mode == MiddlePaneMode.HISTOGRAM:
            layout["main"].split_row(
                Layout(self._render_requests_pane(), name="requests", ratio=2),
                Layout(self._render_histogram_pane(), name="histogram", ratio=1),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=35),
            )
        elif middle_mode == MiddlePaneMode.BREAKDOWN:
            layout["main"].split_row(
                Layout(self._render_requests_pane(), name="requests", ratio=2),
                Layout(self._render_breakdown_pane(), name="breakdown", ratio=1),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=35),
            )
        else:
            # Default: pending pane
            layout["main"].split_row(
                Layout(self._render_requests_pane(), name="requests", ratio=2),
                Layout(self._render_pending_pane(), name="pending", ratio=1),
                Layout(self._render_metrics_pane(), name="metrics", minimum_size=35),
            )

        return layout

    def _render_requests_pane(self) -> Panel:
        """Completed requests with latency and scroll indicators."""
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
        if selected_idx is not None and selected_idx >= start_idx + max_rows:
            start_idx = selected_idx - max_rows + 1
        end_idx = min(len(filtered), start_idx + max_rows)

        # Calculate scroll indicators
        above_count = start_idx
        below_count = len(filtered) - end_idx

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

        # Build subtitle with scroll indicators
        scroll_parts = []
        if above_count > 0:
            scroll_parts.append(f"↑ {above_count} more")
        if below_count > 0:
            scroll_parts.append(f"↓ {below_count} more")
        subtitle = "  ".join(scroll_parts) if scroll_parts else None

        return Panel(table, title=title, subtitle=subtitle, border_style=border_style)

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
        filt = self._filter()

        # Sort by age (oldest first)
        sorted_pending = sorted(pending, key=lambda e: e.ts)

        # Apply filter if it has age condition
        if filt.has_age_filter():
            sorted_pending = [e for e in sorted_pending if filt.matches_event(e, now)]

        # Scroll indicators
        above_count = 0
        below_count = max(0, len(sorted_pending) - max_rows)

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

        if not sorted_pending:
            table.add_row("", "", Text("No pending requests", style="dim"), "")

        border_style = "green" if self._focused_pane() == "pending" else "dim"
        stuck_count = sum(1 for e in pending if (now - e.ts) * 1000 >= threshold)
        stuck_str = f" [red]{stuck_count} stuck[/red]" if stuck_count > 0 else ""
        title = f"[bold]Pending[/bold] [dim]({len(sorted_pending)})[/dim]{stuck_str}"

        # Subtitle with scroll indicator
        subtitle = f"↓ {below_count} more" if below_count > 0 else None

        return Panel(table, title=title, subtitle=subtitle, border_style=border_style)

    def _render_histogram_pane(self) -> Panel:
        """Latency histogram as ASCII bar chart."""
        histogram = self.latency_histogram()
        total = sum(histogram)

        lines = []
        max_count = max(histogram) if histogram else 1
        bar_width = 20  # Max bar width

        for i, (low, high, label) in enumerate(LATENCY_BUCKETS):
            count = histogram[i]
            pct = (count / total * 100) if total else 0

            # Calculate bar length
            bar_len = int((count / max_count) * bar_width) if max_count else 0

            # Color based on bucket
            if i <= 1:  # 0-100ms
                style = "green"
            elif i <= 3:  # 100-500ms
                style = "yellow"
            else:  # 500ms+
                style = "red"

            bar = "█" * bar_len + "░" * (bar_width - bar_len)
            lines.append(f"[dim]{label:>10}[/dim] [{style}]{bar}[/{style}] {count:>4} ({pct:>5.1f}%)")

        border_style = "green" if self._focused_pane() == "histogram" else "dim"
        window_indicator = " [cyan](60s)[/cyan]" if self._use_sliding_window() else ""
        title = f"[bold]Latency Histogram[/bold]{window_indicator}"

        return Panel(
            Text.from_markup("\n".join(lines)),
            title=title,
            border_style=border_style,
        )

    def _render_breakdown_pane(self) -> Panel:
        """Endpoint breakdown with stats per path pattern."""
        stats = self.endpoint_stats()
        max_rows = self._available_rows()

        table = Table(
            show_header=True,
            header_style="bold",
            expand=True,
            box=None,
            padding=(0, 1),
        )
        table.add_column("Endpoint", ratio=1)
        table.add_column("Count", no_wrap=True, justify="right")
        table.add_column("Avg", no_wrap=True, justify="right")
        table.add_column("Err%", no_wrap=True, justify="right")

        # Scroll indicators
        below_count = max(0, len(stats) - max_rows)

        for stat in stats[:max_rows]:
            # Color avg latency
            avg_style = "green"
            if stat.avg_latency > 500:
                avg_style = "yellow"
            if stat.avg_latency > 1000:
                avg_style = "red"

            # Color error rate
            err_style = "green" if stat.error_rate < 1 else "yellow" if stat.error_rate < 5 else "red"

            table.add_row(
                Text(stat.pattern, style="dim" if "/static/" in stat.pattern else ""),
                str(stat.count),
                Text(f"{stat.avg_latency:.0f}ms", style=avg_style),
                Text(f"{stat.error_rate:.1f}%", style=err_style),
            )

        if not stats:
            table.add_row(Text("No data", style="dim"), "", "", "")

        border_style = "green" if self._focused_pane() == "breakdown" else "dim"
        window_indicator = " [cyan](60s)[/cyan]" if self._use_sliding_window() else ""
        title = f"[bold]Endpoints[/bold]{window_indicator}"

        subtitle = f"↓ {below_count} more" if below_count > 0 else None

        return Panel(table, title=title, subtitle=subtitle, border_style=border_style)

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
            rank = sum(1 for lat in latencies if lat <= req.latency_ms)
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
        use_window = self._use_sliding_window()

        # Metrics (windowed or all time based on toggle)
        total = self.total_requests()
        windowed_total = len(self.windowed_completed())
        pending = self.pending_count()
        avg_lat = self.avg_latency()
        percentiles = self.percentiles()
        error_rate = self.error_rate()
        status_counts = self.status_counts()
        rate = self.request_rate()

        lines = ["[bold underline]Overview[/bold underline]"]
        lines.append(f"  Completed: {total}  Pending: {pending}")
        lines.append(f"  Rate: {rate:.1f} req/s")
        lines.append("")

        lines.append("[bold underline]Latency[/bold underline]")
        lines.append(f"  Avg: {avg_lat:.0f}ms")
        lines.append(f"  p50: {percentiles['p50']:.0f}ms  p90: {percentiles['p90']:.0f}ms")
        lines.append(f"  p95: {percentiles['p95']:.0f}ms  p99: {percentiles['p99']:.0f}ms")
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
        window_indicator = " [cyan](60s)[/cyan]" if use_window else ""
        title = f"[bold]Metrics[/bold]{window_indicator}"
        return Panel(
            Text.from_markup("\n".join(lines)),
            title=title,
            border_style=border_style,
        )

    def _render_help_overlay(self) -> Layout:
        """Full-screen help overlay showing all keyboard shortcuts."""
        help_text = """
[bold cyan]HTTP Logger v2 - Keyboard Shortcuts[/bold cyan]

[bold underline]Navigation[/bold underline]
  [yellow]1[/yellow]         Focus requests pane
  [yellow]2[/yellow]         Focus middle pane (pending/histogram/breakdown/detail)
  [yellow]3[/yellow]         Focus metrics pane
  [yellow]j/k[/yellow]       Select next/previous request
  [yellow]Enter[/yellow]     View selected request detail
  [yellow]Esc[/yellow]       Clear selection / Close overlay

[bold underline]Pane Toggles[/bold underline]
  [yellow]p[/yellow]         Show pending requests pane
  [yellow]l[/yellow]         Show latency histogram pane
  [yellow]b[/yellow]         Show endpoint breakdown pane

[bold underline]Filtering[/bold underline]
  [yellow]/[/yellow]         Enter filter mode (in requests pane)
  [yellow]c[/yellow]         Clear filter
  [yellow]e[/yellow]         Quick filter: errors (status=4xx,5xx)
  [yellow]s[/yellow]         Quick filter: slow requests (latency>500)
  [yellow]h[/yellow]         Apply last filter from history

[bold underline]Filter Syntax[/bold underline]
  [dim]status=200[/dim]      Exact status code
  [dim]status=2xx,4xx[/dim]  Status class patterns (OR)
  [dim]path=/api/*[/dim]     Path glob pattern
  [dim]method=GET,POST[/dim] Method filter (OR)
  [dim]latency>500[/dim]     Latency comparison (ms)
  [dim]age>1000[/dim]        Pending age filter (ms)
  [dim]id=*0042*[/dim]       Request ID pattern

[bold underline]Metrics[/bold underline]
  [yellow]w[/yellow]         Toggle sliding window (all time / last 60s)

[bold underline]Other[/bold underline]
  [yellow]?[/yellow]         Toggle this help overlay
  [yellow]q[/yellow]         Quit

[dim]Press ? or Esc to close this help[/dim]
"""
        return Layout(Panel(
            Text.from_markup(help_text.strip()),
            title="[bold]Help[/bold]",
            border_style="cyan",
        ))

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

        window_part = "  [cyan]Window: 60s[/cyan]" if self._use_sliding_window() else ""

        return Text.from_markup(
            f"[bold]Focus:[/bold] {self._focused_pane()}  |  "
            f"[bold]Completed:[/bold] {self.total_requests()}{pending_part}{selected_part}{window_part}{hist_part}"
        )

    def _render_help(self) -> Text:
        if self._mode() == Mode.FILTER:
            return Text.from_markup(
                "[dim]Enter[/dim]=apply  [dim]Esc[/dim]=cancel  |  "
                "Fields: [cyan]status[/cyan]=200,4xx  [cyan]path[/cyan]=/api/*  "
                "[cyan]method[/cyan]=GET  [cyan]latency[/cyan]>500  [cyan]age[/cyan]>1000  [cyan]id[/cyan]=*pattern*"
            )

        selected = self._selected_index() is not None
        middle_mode = self._middle_pane_mode()
        pane2_name = {
            MiddlePaneMode.PENDING: "pending",
            MiddlePaneMode.HISTOGRAM: "histogram",
            MiddlePaneMode.BREAKDOWN: "breakdown",
        }.get(middle_mode, "pending")
        if selected:
            pane2_name = "detail"
        pane_keys = f"[dim]1[/dim]=requests  [dim]2[/dim]={pane2_name}  [dim]3[/dim]=metrics"

        if self._focused_pane() == "requests":
            history = self._filter_history()
            h_key = "  [dim]h[/dim]=last" if history else ""
            nav_keys = "[dim]j/k[/dim]=select  " if not selected else "[dim]j/k[/dim]=nav  [dim]Esc[/dim]=deselect  "
            return Text.from_markup(
                f"{pane_keys}  |  {nav_keys}"
                f"[dim]/[/dim]=filter  [dim]p[/dim]=pending  [dim]l[/dim]=histogram  [dim]b[/dim]=breakdown  "
                f"[dim]w[/dim]=window{h_key}  |  [dim]?[/dim]=help  [dim]q[/dim]=quit"
            )
        elif self._focused_pane() == "detail":
            return Text.from_markup(
                f"{pane_keys}  |  [dim]j/k[/dim]=nav  [dim]Esc[/dim]=back  |  [dim]?[/dim]=help  [dim]q[/dim]=quit"
            )
        else:
            return Text.from_markup(
                f"{pane_keys}  |  [dim]p[/dim]=pending  [dim]l[/dim]=histogram  [dim]b[/dim]=breakdown  "
                f"[dim]w[/dim]=window  |  [dim]?[/dim]=help  [dim]q[/dim]=quit"
            )


# =============================================================================
# MAIN
# =============================================================================

async def run_logger(duration: float | None = None):
    console = Console()

    console.print("\n[bold]HTTP Request Logger v2[/bold]")
    console.print("Monitors request/response pairs with latency tracking")
    console.print("[dim]Press ? for help[/dim]")
    if duration:
        console.print(f"[dim]Running for {duration}s...[/dim]")
    console.print()
    await asyncio.sleep(0.5)

    store = EventStore()
    simulator = TrafficSimulator(store)
    logger = HttpLogger(store, console)

    await simulator.start()
    start_time = time.time()

    try:
        with KeyboardInput() as keyboard:
            with Live(console=console, refresh_per_second=10) as live:
                logger.set_live(live)

                while logger.running:
                    if duration and (time.time() - start_time) > duration:
                        break

                    key = keyboard.get_key()
                    if key:
                        logger.handle_key(key)

                    await asyncio.sleep(0.05)

    finally:
        await simulator.stop()

    console.print(f"\n[bold]Done![/bold] {logger.total_requests()} completed requests")


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
