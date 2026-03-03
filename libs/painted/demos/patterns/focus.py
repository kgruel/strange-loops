#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Focus + Cursor + Search — navigation vs capture.

TestSurface replays scripted inputs through a three-widget mini app:
- Focus drives navigation between widgets (Tab / Shift+Tab) using ring_next/ring_prev.
- Capture mode routes all keys into the focused widget (Escape releases).
- Cursor drives list selection in the services widget.
- Search + filter_fuzzy drives a command palette in the search widget.

    uv run demos/patterns/focus.py -q        # one-line result
    uv run demos/patterns/focus.py           # emission trace
    uv run demos/patterns/focus.py -v        # trace + key frames
    uv run demos/patterns/focus.py -vv       # bordered scenarios + more frames
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace

from painted import (
    Block,
    CliContext,
    Style,
    Zoom,
    border,
    join_horizontal,
    join_vertical,
    pad,
    run_cli,
    truncate,
    ROUNDED,
)
from painted.icon_set import current_icons
from painted.palette import current_palette
from painted.tui import (
    Cursor,
    CursorMode,
    Focus,
    Search,
    Surface,
    TestSurface,
    filter_fuzzy,
    ring_next,
    ring_prev,
)


# --- Sample data ---


@dataclass(frozen=True, slots=True)
class Service:
    name: str
    version: str
    region: str
    health: str  # ok | degraded | down
    p95_ms: int
    error_rate: float


SERVICES: tuple[Service, ...] = (
    Service("api-gateway", "2.14.3", "us-east-1", "ok", 72, 0.08),
    Service("auth-service", "1.9.1", "us-east-1", "degraded", 188, 1.42),
    Service("billing", "3.2.0", "us-west-2", "ok", 96, 0.22),
    Service("worker", "5.7.4", "us-east-1", "ok", 41, 0.03),
    Service("scheduler", "4.1.8", "us-east-1", "ok", 55, 0.06),
    Service("metrics", "0.18.0", "us-east-1", "ok", 24, 0.01),
    Service("logger", "0.9.7", "us-west-2", "ok", 33, 0.02),
    Service("cache", "2.3.6", "us-east-1", "ok", 12, 0.00),
    Service("queue", "1.12.2", "us-east-1", "ok", 67, 0.10),
    Service("storage", "6.0.1", "us-west-2", "down", 0, 100.0),
)

COMMANDS: tuple[str, ...] = (
    "deploy api-gateway",
    "deploy auth-service",
    "rollback auth-service",
    "tail logs api-gateway",
    "tail logs auth-service",
    "scale worker +2",
    "restart scheduler",
    "drain queue",
    "warm cache",
    "open metrics dashboard",
)

WIDGETS: tuple[str, ...] = ("services", "search", "details")


# --- Mini app under test ---


@dataclass(frozen=True, slots=True)
class AppState:
    focus: Focus = Focus(id="services")
    services_cursor: Cursor = Cursor(index=0, count=len(SERVICES), mode=CursorMode.WRAP)
    search: Search = Search()
    last_command: str | None = None
    last_event: str = ""


def _service_style(service: Service) -> Style:
    p = current_palette()
    if service.health == "ok":
        return p.success
    if service.health == "degraded":
        return p.warning
    return p.error


def _panel_title(widget_id: str, focus: Focus) -> tuple[str, Style]:
    p = current_palette()
    is_focused = focus.id == widget_id
    if not is_focused:
        return widget_id, p.muted
    if focus.captured:
        return f"{widget_id}  CAP", p.accent.merge(Style(bold=True))
    return f"{widget_id}  NAV", p.accent


def _fixed_height(block: Block, height: int) -> Block:
    if block.height >= height:
        return block
    return pad(block, bottom=height - block.height)


def _services_panel(state: AppState, *, width: int, height: int) -> Block:
    p = current_palette()
    title, title_style = _panel_title("services", state.focus)
    content_w = max(0, width - 2)
    content_h = max(0, height - 2)

    header = Block.text(
        "name                 health   p95   err%", Style(dim=True), width=content_w
    )
    rows: list[Block] = [header]

    for i, svc in enumerate(SERVICES):
        selected = i == state.services_cursor.index
        marker = ">" if selected else " "
        health = svc.health.upper()
        p95 = "--" if svc.p95_ms == 0 else f"{svc.p95_ms:>3d}"
        err = f"{svc.error_rate:>5.2f}"

        base = _service_style(svc)
        row_style = base.merge(Style(bold=True)) if selected else base.merge(p.muted)
        line = f"{marker} {svc.name:<20.20s} {health:<8s} {p95:>3s}  {err:>5s}"
        rows.append(Block.text(line, row_style, width=content_w))

    content = _fixed_height(join_vertical(*rows), content_h)
    return border(content, chars=ROUNDED, title=title, title_style=title_style, style=title_style)


def _search_panel(state: AppState, *, width: int, height: int) -> Block:
    p = current_palette()
    title, title_style = _panel_title("search", state.focus)
    content_w = max(0, width - 2)
    content_h = max(0, height - 2)

    matches = filter_fuzzy(COMMANDS, state.search.query)
    selected = state.search.selected if state.search.selected < len(matches) else -1

    query_style = (
        p.accent.merge(Style(bold=True))
        if state.focus.id == "search" and state.focus.captured
        else Style()
    )
    query_line = join_horizontal(
        Block.text("query: ", Style(dim=True)),
        Block.text(state.search.query or " ", query_style),
    )
    query_line = pad(query_line, right=max(0, content_w - query_line.width))

    rows: list[Block] = [query_line, Block.text("", Style(), width=content_w)]
    rows.append(Block.text("matches (fuzzy):", Style(dim=True), width=content_w))

    max_rows = max(0, content_h - len(rows) - 1)
    for i, cmd in enumerate(matches[:max_rows]):
        is_sel = i == selected
        marker = ">" if is_sel else " "
        style = p.accent.merge(Style(bold=True)) if is_sel else Style(dim=True)
        rows.append(Block.text(f"{marker} {cmd}", style, width=content_w))

    footer = Block.text(f"{len(matches):>2d} match(es)", Style(dim=True), width=content_w)
    content = _fixed_height(join_vertical(*rows, footer), content_h)
    return border(content, chars=ROUNDED, title=title, title_style=title_style, style=title_style)


def _details_panel(state: AppState, *, width: int, height: int) -> Block:
    p = current_palette()
    title, title_style = _panel_title("details", state.focus)
    content_w = max(0, width - 2)
    content_h = max(0, height - 2)

    svc = SERVICES[state.services_cursor.index] if SERVICES else None
    cmd = state.last_command or "(none)"

    rows: list[Block] = [
        Block.text("selected service:", Style(dim=True), width=content_w),
        Block.text(
            f"  {svc.name}  v{svc.version}  {svc.region}" if svc else "  (none)",
            Style(bold=True),
            width=content_w,
        ),
        Block.text(
            f"  health={svc.health}  p95={svc.p95_ms}ms  err={svc.error_rate:.2f}%" if svc else "",
            (_service_style(svc).merge(Style(dim=True)) if svc else Style(dim=True)),
            width=content_w,
        ),
        Block.text("", Style(), width=content_w),
        Block.text("last command:", Style(dim=True), width=content_w),
        Block.text(
            f"  {cmd}", p.accent if state.last_command else Style(dim=True), width=content_w
        ),
        Block.text("", Style(), width=content_w),
        Block.text("recent deploy log:", Style(dim=True), width=content_w),
        Block.text("  10:34:12Z  build ✓  sha=9f2c7a1", p.muted, width=content_w),
        Block.text("  10:34:20Z  rollout  4/4 healthy", p.muted, width=content_w),
        Block.text("  10:34:24Z  metrics  p95=72ms err=0.08%", p.muted, width=content_w),
        Block.text("  10:34:28Z  done", p.muted, width=content_w),
    ]

    content = _fixed_height(join_vertical(*rows), content_h)
    return border(content, chars=ROUNDED, title=title, title_style=title_style, style=title_style)


class FocusDemoApp(Surface):
    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()

    def render(self) -> None:
        if self._buf is None:
            return
        buf = self._buf
        buf.fill(0, 0, buf.width, buf.height, " ", Style())

        top_h = max(0, buf.height - 1)
        gap = 1
        w = buf.width

        left_w = max(22, min(30, (w - gap * 2) // 3))
        mid_w = max(22, min(30, (w - gap * 2) // 3))
        right_w = max(0, w - left_w - mid_w - gap * 2)

        if right_w < 22 and w >= 70:
            bump = 22 - right_w
            left_w = max(22, left_w - bump // 2)
            mid_w = max(22, mid_w - bump + bump // 2)
            right_w = max(0, w - left_w - mid_w - gap * 2)

        services = _services_panel(self.state, width=left_w, height=top_h)
        search = _search_panel(self.state, width=mid_w, height=top_h)
        details = _details_panel(self.state, width=right_w, height=top_h)
        top = join_horizontal(services, search, details, gap=gap)

        mode = "CAPTURE" if self.state.focus.captured else "NAV"
        status = (
            f"focus={self.state.focus.id}:{mode}   event={self.state.last_event or '—'}   q=quit"
        )
        status_style = current_palette().muted
        status_line = Block.text(status, status_style, width=buf.width)

        ui = join_vertical(top, status_line)
        ui.paint(buf, 0, 0)

    def on_key(self, key: str) -> None:
        st = self.state

        if key == "q":
            self.emit("ui.quit", focus=st.focus.id, captured=st.focus.captured)
            self.quit()
            return

        if key == "escape" and st.focus.captured:
            self.state = replace(st, focus=st.focus.release(), last_event="release")
            self.emit("focus.release", widget=st.focus.id)
            return

        if not st.focus.captured:
            if key in ("tab", "shift_tab"):
                before = st.focus.id
                after = ring_next(WIDGETS, before) if key == "tab" else ring_prev(WIDGETS, before)
                self.state = replace(
                    st, focus=st.focus.focus(after), last_event=f"focus {before}->{after}"
                )
                self.emit("focus.move", from_id=before, to_id=after, nav=key)
                return

            if key == "enter":
                self.state = replace(
                    st, focus=st.focus.capture(), last_event=f"capture {st.focus.id}"
                )
                self.emit("focus.capture", widget=st.focus.id)
                return

            self.state = replace(st, last_event=f"ignored '{key}' (nav)")
            self.emit("key.ignored", key=key, focus=st.focus.id, mode="nav")
            return

        # Captured: route all keys into the focused widget.
        if st.focus.id == "services":
            self._on_services_key(key)
            return
        if st.focus.id == "search":
            self._on_search_key(key)
            return

        self.state = replace(st, last_event=f"ignored '{key}' (details)")
        self.emit("key.ignored", key=key, focus=st.focus.id, mode="capture")

    def _on_services_key(self, key: str) -> None:
        st = self.state
        cur = st.services_cursor.with_count(len(SERVICES))
        if key in ("j", "down"):
            cur2 = cur.next()
            svc = SERVICES[cur2.index].name if SERVICES else ""
            self.state = replace(
                st, services_cursor=cur2, last_event=f"cursor {cur.index}->{cur2.index}"
            )
            self.emit("services.cursor", index=cur2.index, service=svc)
            return
        if key in ("k", "up"):
            cur2 = cur.prev()
            svc = SERVICES[cur2.index].name if SERVICES else ""
            self.state = replace(
                st, services_cursor=cur2, last_event=f"cursor {cur.index}->{cur2.index}"
            )
            self.emit("services.cursor", index=cur2.index, service=svc)
            return
        if key in ("g", "home"):
            cur2 = cur.home()
            svc = SERVICES[cur2.index].name if SERVICES else ""
            self.state = replace(st, services_cursor=cur2, last_event="cursor home")
            self.emit("services.cursor", index=cur2.index, service=svc)
            return
        if key in ("G", "end"):
            cur2 = cur.end()
            svc = SERVICES[cur2.index].name if SERVICES else ""
            self.state = replace(st, services_cursor=cur2, last_event="cursor end")
            self.emit("services.cursor", index=cur2.index, service=svc)
            return
        if key == "enter":
            svc = SERVICES[cur.index].name if SERVICES else ""
            self.state = replace(st, last_event=f"open {svc}")
            self.emit("services.open", service=svc, index=cur.index)
            return

        self.state = replace(st, last_event=f"ignored '{key}' (services)")
        self.emit("key.ignored", key=key, focus=st.focus.id, mode="capture")

    def _on_search_key(self, key: str) -> None:
        st = self.state
        matches = filter_fuzzy(COMMANDS, st.search.query)

        if key == "backspace":
            s2 = st.search.backspace()
            self.state = replace(st, search=s2, last_event=f"query '{s2.query}'")
            self.emit("search.query", query=s2.query)
            return
        if key == "enter":
            cmd = st.search.selected_item(matches)
            self.state = replace(st, last_command=cmd, last_event=f"run '{cmd or ''}'")
            self.emit("cmd.run", command=cmd or "", query=st.search.query)
            return
        if key in ("j", "down"):
            s2 = st.search.select_next(len(matches))
            self.state = replace(st, search=s2, last_event=f"select {s2.selected}")
            self.emit("search.select", selected=s2.selected, match_count=len(matches))
            return
        if key in ("k", "up"):
            s2 = st.search.select_prev(len(matches))
            self.state = replace(st, search=s2, last_event=f"select {s2.selected}")
            self.emit("search.select", selected=s2.selected, match_count=len(matches))
            return

        if len(key) == 1 and key.isprintable() and not key.isspace():
            s2 = st.search.type(key)
            self.state = replace(st, search=s2, last_event=f"query '{s2.query}'")
            self.emit("search.query", query=s2.query)
            return

        self.state = replace(st, last_event=f"ignored '{key}' (search)")
        self.emit("key.ignored", key=key, focus=st.focus.id, mode="capture")


# --- Test scenarios ---


@dataclass(frozen=True)
class Scenario:
    name: str
    keys: list[str]
    expected_emissions: list[str]
    unexpected_emissions: list[str]


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="capture required",
        keys=["j", "enter", "j", "escape", "q"],
        expected_emissions=["key.ignored", "focus.capture", "services.cursor", "focus.release"],
        unexpected_emissions=["cmd.run"],
    ),
    Scenario(
        name="ring navigation",
        keys=["tab", "tab", "shift_tab", "q"],
        expected_emissions=["focus.move"],
        unexpected_emissions=["focus.capture"],
    ),
    Scenario(
        name="capture owns keys",
        keys=["tab", "enter", "tab", "escape", "tab", "q"],
        expected_emissions=["focus.capture", "key.ignored", "focus.release", "focus.move"],
        unexpected_emissions=[],
    ),
    Scenario(
        name="fuzzy search",
        keys=["tab", "enter", "d", "p", "j", "enter", "escape", "q"],
        expected_emissions=[
            "focus.move",
            "focus.capture",
            "search.query",
            "search.select",
            "cmd.run",
        ],
        unexpected_emissions=[],
    ),
)


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    emissions: list[tuple[str, dict]]
    frames: list[object]  # CapturedFrame
    passed: bool
    checks: list[tuple[str, bool]]


def run_scenario(scenario: Scenario) -> ScenarioResult:
    app = FocusDemoApp()
    harness = TestSurface(app, width=88, height=22, input_queue=scenario.keys)
    frames = harness.run_to_completion()
    emissions = harness.emissions

    emission_kinds = [k for k, _ in emissions]
    checks: list[tuple[str, bool]] = []

    for kind in scenario.expected_emissions:
        checks.append((f"{kind} seen", kind in emission_kinds))
    for kind in scenario.unexpected_emissions:
        checks.append((f"{kind} absent", kind not in emission_kinds))

    passed = all(ok for _, ok in checks)
    return ScenarioResult(
        scenario=scenario,
        emissions=emissions,
        frames=frames,
        passed=passed,
        checks=checks,
    )


# --- Rendering ---


def _emission_style(kind: str) -> Style:
    p = current_palette()
    if kind.startswith(("focus.", "services.", "search.", "cmd.", "key.")):
        return p.accent
    return p.muted


def _emission_block(kind: str, data: dict) -> Block:
    data_str = " ".join(f"{k}={v}" for k, v in data.items())
    return join_horizontal(
        Block.text(f"  {kind:<18s}", _emission_style(kind)),
        Block.text(f" {data_str}", Style(dim=True)),
    )


def _check_block(description: str, passed: bool) -> Block:
    p = current_palette()
    icons = current_icons()
    icon = icons.check if passed else icons.cross
    style = p.success if passed else p.error
    return Block.text(f"  {icon} {description}", style)


def _render_minimal(results: list[ScenarioResult], width: int) -> Block:
    p = current_palette()
    icons = current_icons()
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    all_ok = passed == total
    icon = icons.check if all_ok else icons.cross
    style = p.success if all_ok else p.error
    return truncate(Block.text(f"{icon} focus demo: {passed}/{total} scenarios", style), width)


def _key_frames(result: ScenarioResult) -> list[tuple[str, object]]:
    keys = result.scenario.keys
    idxs: list[int] = [0]
    if len(result.frames) > 1:
        idxs.append(1)
    try:
        enter_i = keys.index("enter")
        idxs.append(enter_i + 1)
    except ValueError:
        pass
    if result.frames:
        idxs.append(len(result.frames) - 1)
    # De-dup while preserving order
    seen: set[int] = set()
    out: list[tuple[str, object]] = []
    for i in idxs:
        if i in seen or i < 0 or i >= len(result.frames):
            continue
        seen.add(i)
        label = "initial" if i == 0 else f"after '{keys[i - 1]}'"
        out.append((label, result.frames[i]))
    return out


def _frame_block(frame: object, *, width: int, max_lines: int) -> Block:
    # CapturedFrame: .lines is list[str] of exact surface width lines.
    lines = getattr(frame, "lines", [])
    rows = [Block.text(line.rstrip(), Style(dim=True), width=width) for line in lines[:max_lines]]
    if not rows:
        return Block.text("(no frame)", Style(dim=True), width=width)
    return join_vertical(*rows)


def _render_summary(results: list[ScenarioResult], width: int) -> Block:
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []

    for r in results:
        icon = icons.check if r.passed else icons.cross
        header_style = p.success if r.passed else p.error
        header = Block.text(f"{icon} {r.scenario.name}", header_style)
        keys_line = Block.text(f"  keys: {' -> '.join(r.scenario.keys)}", Style(dim=True))

        # Prefer domain emissions; ui.key is left in but muted.
        trace = join_vertical(*[_emission_block(k, d) for k, d in r.emissions])
        checks = join_vertical(*[_check_block(desc, ok) for desc, ok in r.checks])

        sections.append(join_vertical(header, keys_line, trace, checks, Block.text("", Style())))

    return truncate(join_vertical(*sections, _render_minimal(results, width)), width)


def _render_detailed(results: list[ScenarioResult], width: int) -> Block:
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []
    snap_w = max(20, min(width - 6, 96))
    snap_lines = 10

    for r in results:
        icon = icons.check if r.passed else icons.cross
        header_style = p.success if r.passed else p.error
        header = Block.text(f"{icon} {r.scenario.name}", header_style)
        keys_line = Block.text(f"  keys: {' -> '.join(r.scenario.keys)}", Style(dim=True))
        trace = join_vertical(*[_emission_block(k, d) for k, d in r.emissions])

        frames: list[Block] = []
        for label, frame in _key_frames(r):
            frames.append(Block.text(f"  [{label}]", Style(dim=True)))
            frames.append(_frame_block(frame, width=snap_w, max_lines=snap_lines))
            frames.append(Block.text("", Style()))

        sections.append(join_vertical(header, keys_line, trace, Block.text("", Style()), *frames))

    return truncate(join_vertical(*sections, _render_minimal(results, width)), width)


def _render_full(results: list[ScenarioResult], width: int) -> Block:
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []
    snap_w = max(20, min(width - 6, 120))

    for r in results:
        icon = icons.check if r.passed else icons.cross
        title = f"{icon} {r.scenario.name}"
        keys_line = Block.text(f"keys: {' -> '.join(r.scenario.keys)}", Style(dim=True))
        trace = join_vertical(*[_emission_block(k, d) for k, d in r.emissions])
        checks = join_vertical(*[_check_block(desc, ok) for desc, ok in r.checks])

        frame_blocks: list[Block] = []
        for label, frame in _key_frames(r):
            frame_blocks.append(Block.text(f"[{label}]", Style(dim=True)))
            frame_blocks.append(_frame_block(frame, width=snap_w, max_lines=16))
            frame_blocks.append(Block.text("", Style()))

        inner = join_vertical(
            keys_line,
            Block.text("", Style()),
            Block.text("emissions:", Style(dim=True)),
            trace,
            Block.text("", Style()),
            checks,
            Block.text("", Style()),
            Block.text("frames:", Style(dim=True)),
            join_vertical(*frame_blocks) if frame_blocks else Block.empty(0, 0),
        )
        sections.append(
            border(
                pad(inner, right=max(0, snap_w - inner.width)),
                chars=ROUNDED,
                title=title,
                style=p.muted,
            )
        )
        sections.append(Block.text("", Style()))

    return join_vertical(*sections, _render_minimal(results, width))


def _render(ctx: CliContext, results: list[ScenarioResult]) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(results, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(results, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return _render_full(results, ctx.width)
    return _render_detailed(results, ctx.width)


def _fetch() -> list[ScenarioResult]:
    return [run_scenario(s) for s in SCENARIOS]


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="focus.py",
    )


if __name__ == "__main__":
    sys.exit(main())
