"""Autoresearch monitor TUI — iteration-centric experiment exploration.

Each iteration is a time window between consecutive experiment facts.
Navigate through iterations to see what the agent did: logs emitted,
findings updated, ideas proposed. Live-refreshes to show in-progress
iteration activity as it streams in.

  loops read VERTEX --lens autoresearch -i
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from painted import Block, Style, Wrap, Zoom
from painted import join_horizontal, join_vertical, border, pad
from painted.core.cell import Cell
from painted.core.span import Line, Span
from painted.tui import Surface
from painted.views import ListState, list_view

if TYPE_CHECKING:
    from atoms import FoldItem, FoldState


# ---------------------------------------------------------------------------
# Sparkline
# ---------------------------------------------------------------------------

_SPARK = "▁▂▃▄▅▆▇█"


def _sparkline_block(
    values: list[float],
    statuses: list[str],
    direction: str,
    width: int,
) -> Block:
    """Sparkline as a styled Block. Green=keep, red=discard, dim=running."""
    if not values:
        return Block.empty(0, 1)

    show = values[-width:]
    show_st = statuses[-width:]
    lo, hi = min(show), max(show)
    rng = hi - lo or 1

    cells: list[Cell] = []
    for v, st in zip(show, show_st):
        idx = int((v - lo) / rng * (len(_SPARK) - 1))
        # For "lower is better": invert so lower values get taller bars
        if direction == "lower":
            idx = len(_SPARK) - 1 - idx
        ch = _SPARK[idx]

        if st == "keep":
            style = Style(fg="green")
        elif st == "discard":
            style = Style(fg="red")
        else:
            style = Style(fg="yellow")
        cells.append(Cell(ch, style))

    return Block([cells], len(cells))


# ---------------------------------------------------------------------------
# Iteration data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IterationView:
    """One iteration of the optimization loop."""

    number: int
    is_running: bool
    commit: str
    metric: float | None
    status: str  # "keep" | "discard" | "running"
    delta_pct: float | None
    description: str
    logs: tuple["FoldItem", ...]
    findings: tuple["FoldItem", ...]
    ideas: tuple["FoldItem", ...]
    hypotheses: tuple["FoldItem", ...]


def _get_section(data: "FoldState", kind: str) -> list["FoldItem"]:
    for section in data.sections:
        if section.kind == kind:
            return list(section.items)
    return []


def _get_config(data: "FoldState") -> dict[str, str]:
    config: dict[str, str] = {}
    for item in _get_section(data, "config"):
        key = item.payload.get("key", "")
        value = item.payload.get("value", "")
        if key:
            config[key] = value
    return config


def _format_metric(value: float) -> str:
    if value == int(value):
        return str(int(value))
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _build_iterations(data: "FoldState", primary_metric: str, direction: str) -> list[IterationView]:
    """Build iteration views from fold state using timestamp attribution."""
    experiment_items = _get_section(data, "experiment")
    all_logs = _get_section(data, "log")
    all_findings = _get_section(data, "finding")
    all_ideas = _get_section(data, "idea")
    all_hyps = _get_section(data, "hypothesis")

    def _in_window(item: "FoldItem", after: float, until: float) -> bool:
        ts = item.ts or 0
        return after < ts <= until

    iterations: list[IterationView] = []
    baseline_val: float | None = None
    prev_ts: float = 0

    for i, exp in enumerate(experiment_items):
        exp_ts = exp.ts or 0
        payload = exp.payload

        try:
            metric = float(payload.get(primary_metric, ""))
        except (ValueError, TypeError):
            metric = None

        if baseline_val is None and metric is not None:
            baseline_val = metric

        delta: float | None = None
        if metric is not None and baseline_val is not None and baseline_val != 0:
            delta = ((metric - baseline_val) / abs(baseline_val)) * 100

        logs = tuple(l for l in all_logs if _in_window(l, prev_ts, exp_ts))
        findings = tuple(f for f in all_findings if _in_window(f, prev_ts, exp_ts))
        ideas = tuple(d for d in all_ideas if _in_window(d, prev_ts, exp_ts))
        hyps = tuple(h for h in all_hyps if _in_window(h, prev_ts, exp_ts))

        iterations.append(IterationView(
            number=i + 1,
            is_running=False,
            commit=str(payload.get("commit", ""))[:7],
            metric=metric,
            status=str(payload.get("status", "?")),
            delta_pct=delta,
            description=str(payload.get("description", "")),
            logs=logs,
            findings=findings,
            ideas=ideas,
            hypotheses=hyps,
        ))
        prev_ts = exp_ts

    # In-progress iteration: supporting facts after last experiment
    last_ts = experiment_items[-1].ts if experiment_items else 0
    running_logs = tuple(l for l in all_logs if (l.ts or 0) > last_ts)
    running_findings = tuple(f for f in all_findings if (f.ts or 0) > last_ts)
    running_ideas = tuple(d for d in all_ideas if (d.ts or 0) > last_ts)
    running_hyps = tuple(h for h in all_hyps if (h.ts or 0) > last_ts)

    if running_logs or running_findings or running_ideas or running_hyps:
        iterations.append(IterationView(
            number=len(experiment_items) + 1,
            is_running=True,
            commit="",
            metric=None,
            status="running",
            delta_pct=None,
            description="",
            logs=running_logs,
            findings=running_findings,
            ideas=running_ideas,
            hypotheses=running_hyps,
        ))

    return iterations


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AppState:
    """Immutable state for the autoresearch monitor."""

    config: dict[str, str]
    iterations: list[IterationView]
    primary_metric: str
    direction: str
    baseline: float | None
    best: float | None
    best_run: int
    total_experiments: int

    # UI state
    cursor: ListState
    focus: str  # "list" or "detail"
    detail_scroll: int  # scroll offset for detail panel

    @staticmethod
    def from_fold(data: "FoldState") -> AppState:
        config = _get_config(data)
        primary_metric = config.get("primary_metric", "")
        direction = config.get("direction", "lower")

        from .autoresearch_app import _build_iterations
        iterations = list(reversed(_build_iterations(data, primary_metric, direction)))

        # Compute progress (oldest-first for correct baseline)
        experiments = sorted(
            [it for it in iterations if not it.is_running],
            key=lambda it: it.number,
        )
        baseline: float | None = None
        best: float | None = None
        best_run = 0
        for it in experiments:
            if it.metric is not None:
                if baseline is None:
                    baseline = it.metric
                if best is None or (
                    (it.metric > best if direction == "higher" else it.metric < best)
                ):
                    best = it.metric
                    best_run = it.number

        return AppState(
            config=config,
            iterations=iterations,
            primary_metric=primary_metric,
            direction=direction,
            baseline=baseline,
            best=best,
            best_run=best_run,
            total_experiments=len(experiments),
            cursor=ListState().with_count(len(iterations)),
            focus="list",
            detail_scroll=0,
        )

    @property
    def selected(self) -> IterationView | None:
        if not self.iterations or self.cursor.selected >= len(self.iterations):
            return None
        return self.iterations[self.cursor.selected]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _focus_border(focused: bool) -> Style:
    """Green border when focused, dim when not."""
    return Style(fg="green") if focused else Style(dim=True)


def _render_header_panels(state: AppState, w: int) -> Block:
    """Two panels: status+sparkline (left) + config (right)."""
    config = state.config
    muted = Style(dim=True)
    bold = Style(bold=True)
    border_style = Style(dim=True)

    objective = config.get("objective", "autoresearch")
    pm = state.primary_metric

    # --- Status panel ---
    status_texts: list[tuple[str, Style]] = []

    if state.best is not None and state.baseline is not None:
        bl_s = _format_metric(state.baseline)
        best_s = _format_metric(state.best)
        pct = ((state.best - state.baseline) / abs(state.baseline)) * 100 if state.baseline else 0
        sign = "+" if pct >= 0 else ""
        improved = (state.direction == "higher" and pct > 0) or (state.direction == "lower" and pct < 0)
        delta_style = Style(fg="green", bold=True) if improved else Style(fg="red", bold=True)
        status_texts.append((f"{pm}: {bl_s} -> {best_s} ({sign}{pct:.1f}%)", delta_style))
    else:
        status_texts.append((pm or "no metric", muted))

    total = state.total_experiments
    kept = sum(1 for it in state.iterations if it.status == "keep")
    running = any(it.is_running for it in state.iterations)
    run_str = f"Runs: {total}  {kept} kept"
    if running:
        run_str += "  >> running"
    status_texts.append((run_str, muted))

    # Width split
    gap = 1
    inner_total = w - gap - 8
    left_inner = max(20, min(inner_total * 60 // 100, max(len(t) for t, _ in status_texts)))
    right_inner = max(15, inner_total - left_inner)

    left_rows = [Block.text(t, s, width=left_inner) for t, s in status_texts]

    # Sparkline — chronological order (oldest first)
    chrono = sorted(state.iterations, key=lambda it: it.number)
    values = [it.metric for it in chrono if it.metric is not None]
    statuses = [it.status for it in chrono if it.metric is not None]
    spark_w = min(len(values), left_inner)
    if spark_w > 0:
        left_rows.append(_sparkline_block(values, statuses, state.direction, spark_w))

    # --- Config panel ---
    config_texts: list[tuple[str, Style]] = []
    for key in ["primary_metric", "direction", "scope"]:
        val = config.get(key, "")
        if val:
            config_texts.append((f"{key}: {val}", muted))

    left_content = join_vertical(*left_rows)
    right_content = join_vertical(
        *[Block.text(t, s, width=right_inner, wrap=Wrap.WORD) for t, s in config_texts]
    ) if config_texts else Block.empty(right_inner, 1)

    left_panel = border(
        pad(left_content, left=1, right=1),
        title=objective,
        title_style=bold,
        style=border_style,
    )
    right_panel = border(
        pad(right_content, left=1, right=1),
        title="Config",
        title_style=muted,
        style=border_style,
    )

    return join_horizontal(left_panel, right_panel, gap=gap)


def _render_iteration_list(state: AppState, height: int, width: int) -> Block:
    """Wide iteration list panel with focus-colored border."""
    muted = Style(dim=True)
    plain = Style()
    green = Style(fg="green")
    red = Style(fg="red")
    yellow = Style(fg="yellow")

    items: list[Line] = []
    for it in state.iterations:
        spans: list[Span] = []
        num_str = f"#{it.number:<3}"

        if it.is_running:
            spans.append(Span(num_str, yellow))
            spans.append(Span(" >> running...", yellow))
        else:
            spans.append(Span(num_str, plain))
            spans.append(Span(f" {it.commit} ", muted))

            if it.metric is not None:
                spans.append(Span(f"{_format_metric(it.metric):>7}", plain))
            else:
                spans.append(Span("      -", muted))

            if it.status == "keep":
                spans.append(Span(f"  {it.status}", green))
            elif it.status == "discard":
                spans.append(Span(f"  {it.status}", red))
            else:
                spans.append(Span(f"  {it.status}", muted))

            if it.delta_pct is not None:
                sign = "+" if it.delta_pct >= 0 else ""
                spans.append(Span(f" {sign}{it.delta_pct:.0f}%", muted))

            # Description snippet
            if it.description:
                desc = it.description
                spans.append(Span(f"  {desc}", muted))

        items.append(Line(tuple(spans)))

    cursor = state.cursor.scroll_into_view(height)
    content = list_view(cursor, items, height, width=width - 4)

    focused = state.focus == "list"
    title = f"Iterations ({len(state.iterations)})"
    return border(
        pad(content, left=1, right=1),
        style=_focus_border(focused),
        title=title,
        title_style=Style(bold=True) if focused else muted,
    )


def _render_detail(iteration: IterationView, w: int, h: int, scroll: int, focused: bool) -> Block:
    """Detail panel with focus-colored border."""
    plain = Style()
    muted = Style(dim=True)
    bold = Style(bold=True)
    accent = Style(fg="cyan")
    green = Style(fg="green")

    content_w = max(20, w - 4)
    rows: list[Block] = []

    # Description
    if iteration.description:
        rows.append(Block.text(
            iteration.description, plain, width=content_w, wrap=Wrap.WORD,
        ))

    # Logs
    if iteration.logs:
        rows.append(Block.text("", plain))
        for log in iteration.logs:
            log_type = str(log.payload.get("type", ""))
            message = str(log.payload.get("message", ""))
            files = log.payload.get("files", "")

            type_tag = f"[{log_type}]" if log_type else ""
            type_block = Block.text(type_tag, muted, width=12)

            msg_text = message
            if files:
                msg_text += f"  ({files})"
            msg_block = Block.text(msg_text, plain, width=max(10, content_w - 14), wrap=Wrap.WORD)
            rows.append(join_horizontal(type_block, msg_block, gap=2))
            rows.append(Block.text("", plain))

    # Findings
    if iteration.findings:
        rule = "\u2500\u2500 Findings " + "\u2500" * max(0, content_w - 11)
        rows.append(Block.text(rule, muted))
        for f in iteration.findings:
            target = str(f.payload.get("target", "?"))
            message = str(f.payload.get("message", ""))
            rows.append(Block.text(f"  {target}", accent, width=content_w))
            if message:
                rows.append(Block.text(
                    f"  {message}", muted, width=content_w, wrap=Wrap.WORD,
                ))
            rows.append(Block.text("", plain))

    # Ideas
    if iteration.ideas:
        rule = "\u2500\u2500 Ideas " + "\u2500" * max(0, content_w - 8)
        rows.append(Block.text(rule, muted))
        for idea in iteration.ideas:
            name = str(idea.payload.get("name", "?"))
            status = str(idea.payload.get("status", "untried"))
            desc = str(idea.payload.get("description", ""))
            if status == "tried":
                indicator, style = "+", green
            else:
                indicator, style = "o", plain
            rows.append(Block.text(f"  {indicator} {name}", style, width=content_w))
            if desc:
                rows.append(Block.text(
                    f"    {desc}", muted, width=content_w, wrap=Wrap.WORD,
                ))
            rows.append(Block.text("", plain))

    # Hypotheses
    if iteration.hypotheses:
        rule = "\u2500\u2500 Hypotheses " + "\u2500" * max(0, content_w - 14)
        rows.append(Block.text(rule, muted))
        for hyp in iteration.hypotheses:
            name = str(hyp.payload.get("name", "?"))
            status = str(hyp.payload.get("status", "proposed"))
            prediction = str(hyp.payload.get("prediction", ""))
            rows.append(Block.text(f"  [{status}] {name}", plain, width=content_w))
            if prediction:
                rows.append(Block.text(
                    f"    {prediction}", muted, width=content_w, wrap=Wrap.WORD,
                ))

    if not rows:
        rows.append(Block.text("  No activity recorded", muted, width=content_w))

    full = join_vertical(*rows)

    from painted.core.compose import vslice
    inner_h = max(1, h - 2)  # -2 for border
    # Clamp scroll so we don't scroll past the content
    max_scroll = max(0, full.height - inner_h)
    clamped_scroll = min(scroll, max_scroll)
    visible = vslice(full, clamped_scroll, inner_h)

    # Title shows iteration info
    if iteration.is_running:
        title = f"#{iteration.number} >> running..."
        title_style = Style(fg="yellow", bold=True)
    else:
        metric_str = f"  {_format_metric(iteration.metric)}" if iteration.metric is not None else ""
        delta_str = ""
        if iteration.delta_pct is not None:
            sign = "+" if iteration.delta_pct >= 0 else ""
            delta_str = f"  ({sign}{iteration.delta_pct:.1f}%)"
        title = f"#{iteration.number}  {iteration.commit}  {iteration.status}{metric_str}{delta_str}"
        title_style = Style(bold=True) if focused else muted

    return border(
        pad(visible, left=1, right=1),
        style=_focus_border(focused),
        title=title,
        title_style=title_style,
    )


def _render_footer(state: AppState, w: int) -> Block:
    """Footer: key hints."""
    muted = Style(dim=True)

    if state.focus == "list":
        left = "j/k navigate  Tab detail  q quit"
    else:
        left = "j/k scroll  Tab iterations  q quit"

    right = "refreshing every 2s"
    gap = max(1, w - len(left) - len(right))
    line = left + " " * gap + right
    return Block.text(line, muted, width=w)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class AutoresearchApp(Surface):
    """Interactive autoresearch iteration explorer."""

    def __init__(
        self,
        vertex_path: Path,
        observer: str | None = None,
        *,
        _initial_state: "AppState | None" = None,
    ) -> None:
        super().__init__(fps_cap=10, on_start=self._on_start)
        self._vertex_path = vertex_path
        self._observer = observer
        self._state: AppState | None = _initial_state
        self._error: str | None = None
        self._w = 80
        self._h = 24
        # If initial state is injected (e.g. for testing), skip the first
        # auto-refresh so the injected state isn't immediately overwritten.
        self._last_refresh = time.monotonic() if _initial_state is not None else 0.0
        self._refresh_interval = 2.0

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    async def _on_start(self) -> None:
        asyncio.get_running_loop().call_soon(self._load_data)

    def _load_data(self) -> None:
        """Load fold state from vertex."""
        try:
            from loops.commands.fetch import fetch_fold
            data = fetch_fold(self._vertex_path, observer=self._observer)

            if self._state is None:
                # Initial load
                self._state = AppState.from_fold(data)
                # Select the most recent iteration (newest)
                if self._state.iterations:
                    n = len(self._state.iterations)
                    self._state = replace(
                        self._state,
                        cursor=self._state.cursor.move_to(n - 1),
                    )
            else:
                # Refresh: preserve cursor position and focus
                old_cursor = self._state.cursor
                old_focus = self._state.focus
                old_scroll = self._state.detail_scroll
                new_state = AppState.from_fold(data)
                # Keep cursor in bounds
                n = len(new_state.iterations)
                selected = min(old_cursor.selected, n - 1) if n > 0 else 0
                self._state = replace(
                    new_state,
                    cursor=new_state.cursor.move_to(selected),
                    focus=old_focus,
                    detail_scroll=old_scroll,
                )
        except Exception as e:
            self._error = str(e)
        self._last_refresh = time.monotonic()
        self.mark_dirty()

    def update(self) -> None:
        """Auto-refresh on timer."""
        now = time.monotonic()
        if now - self._last_refresh >= self._refresh_interval:
            self._load_data()

    def on_key(self, key: str) -> None:
        if key in ("q", "Q", "escape"):
            self.quit()
            return

        if self._state is None:
            return

        state = self._state

        if key == "tab":
            new_focus = "detail" if state.focus == "list" else "list"
            self._state = replace(state, focus=new_focus)
            self.mark_dirty()
            return

        if state.focus == "list":
            self._handle_list_key(key)
        else:
            self._handle_detail_key(key)

    def _handle_list_key(self, key: str) -> None:
        state = self._state
        if state is None:
            return

        old = state.cursor.selected
        cursor = state.cursor

        if key in ("j", "down"):
            cursor = cursor.move_down()
        elif key in ("k", "up"):
            cursor = cursor.move_up()
        elif key in ("g", "home"):
            cursor = cursor.move_to(0)
        elif key in ("G", "end"):
            cursor = cursor.move_to(len(state.iterations) - 1)
        elif key == "enter":
            self._state = replace(state, focus="detail", detail_scroll=0)
            self.mark_dirty()
            return

        if cursor.selected != old:
            self._state = replace(state, cursor=cursor, detail_scroll=0)
            self.mark_dirty()

    def _handle_detail_key(self, key: str) -> None:
        state = self._state
        if state is None:
            return

        scroll = state.detail_scroll
        if key in ("j", "down"):
            scroll += 1
        elif key in ("k", "up"):
            scroll = max(0, scroll - 1)
        elif key in ("g", "home"):
            scroll = 0
        elif key in ("G", "end"):
            scroll = 9999  # clamped in render
        elif key == "page_down":
            scroll += self._h // 2
        elif key == "page_up":
            scroll = max(0, scroll - self._h // 2)

        # Keep non-negative; upper bound clamped in _render_detail
        scroll = max(0, scroll)

        if scroll != state.detail_scroll:
            self._state = replace(state, detail_scroll=scroll)
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        w, h = self._buf.width, self._buf.height
        self._buf.fill(0, 0, w, h, " ", Style())

        if self._error:
            msg = Block.text(f"Error: {self._error}", Style(fg="red"))
            msg.paint(self._buf.region(1, 1, w - 2, 1), 0, 0)
            return

        if self._state is None:
            msg = Block.text("Loading...", Style(dim=True))
            msg.paint(self._buf.region(1, 1, w - 2, 1), 0, 0)
            return

        state = self._state

        # Layout: header panels + iteration list + detail + footer
        header = _render_header_panels(state, w)
        footer = _render_footer(state, w)

        header_h = header.height
        footer_h = 1

        # Iteration list: ~30% of remaining height, min 5 rows
        remaining = max(8, h - header_h - footer_h)
        n_iters = len(state.iterations)
        list_inner_h = max(3, min(n_iters, remaining * 30 // 100))
        list_panel = _render_iteration_list(state, list_inner_h, w)
        list_h = list_panel.height

        # Detail: everything else
        detail_h = max(4, remaining - list_h)

        selected = state.selected
        if selected:
            detail = _render_detail(
                selected, w, detail_h, state.detail_scroll,
                focused=state.focus == "detail",
            )
        else:
            detail = Block.text("No iterations", Style(dim=True))

        # Paint
        y = 0
        header.paint(self._buf.region(0, y, min(header.width, w), header_h), 0, 0)
        y += header_h

        list_panel.paint(self._buf.region(0, y, min(list_panel.width, w), list_h), 0, 0)
        y += list_h

        detail.paint(self._buf.region(0, y, min(detail.width, w), detail_h), 0, 0)

        footer.paint(self._buf.region(0, h - 1, min(footer.width, w), 1), 0, 0)
