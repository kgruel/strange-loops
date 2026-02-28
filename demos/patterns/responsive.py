#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Responsive layout — width drives layout; zoom drives detail.

Demonstrate width adaptation (three breakpoints):

    COLUMNS=40  uv run demos/patterns/responsive.py
    COLUMNS=80  uv run demos/patterns/responsive.py
    COLUMNS=120 uv run demos/patterns/responsive.py

Demonstrate zoom variation (orthogonal to width):

    uv run demos/patterns/responsive.py -q     # minimal
    uv run demos/patterns/responsive.py        # summary
    uv run demos/patterns/responsive.py -v     # detailed
    uv run demos/patterns/responsive.py -vv    # full
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from painted import (
    Align,
    Block,
    CliContext,
    Style,
    Wrap,
    Zoom,
    border,
    join_horizontal,
    join_responsive,
    join_vertical,
    pad,
    truncate,
    run_cli,
    ROUNDED,
)
from painted.palette import current_palette


# =============================================================================
# Sample data
# =============================================================================


@dataclass(frozen=True)
class Job:
    name: str
    status: str
    duration_s: int
    retries: int = 0
    note: str = ""
    logs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stage:
    name: str
    status: str
    duration_s: int
    owner: str
    jobs: tuple[Job, ...] = ()


@dataclass(frozen=True)
class Deployment:
    env: str
    status: str
    version: str
    actor: str
    started: str
    duration_s: int


@dataclass(frozen=True)
class Alert:
    severity: str
    service: str
    message: str
    since: str


@dataclass(frozen=True)
class Dashboard:
    repo: str
    branch: str
    commit: str
    run_id: str
    stages: tuple[Stage, ...]
    deploys: tuple[Deployment, ...]
    alerts: tuple[Alert, ...]


SAMPLE = Dashboard(
    repo="acme/payments",
    branch="main",
    commit="c7e4b9d",
    run_id="run-59381",
    stages=(
        Stage(
            name="lint + typecheck",
            status="success",
            duration_s=32,
            owner="ci-bot",
            jobs=(
                Job(name="ruff format --check", status="success", duration_s=8),
                Job(name="ty check src/", status="success", duration_s=12),
                Job(name="pytest -q (unit)", status="success", duration_s=12),
            ),
        ),
        Stage(
            name="build images (linux/amd64, linux/arm64)",
            status="success",
            duration_s=91,
            owner="ci-bot",
            jobs=(
                Job(name="docker buildx bake", status="success", duration_s=91, note="cache hit: 83%"),
            ),
        ),
        Stage(
            name="deploy staging",
            status="running",
            duration_s=118,
            owner="release-bot",
            jobs=(
                Job(
                    name="helm upgrade payments-api",
                    status="running",
                    duration_s=118,
                    logs=(
                        "diff: +2 pods, -2 pods (rolling)",
                        "waiting: 2/3 ready (readiness probe)",
                        "routing: 10% canary traffic",
                    ),
                ),
            ),
        ),
        Stage(
            name="smoke test: checkout + refund flow",
            status="queued",
            duration_s=0,
            owner="qa",
            jobs=(
                Job(
                    name="playwright suite",
                    status="queued",
                    duration_s=0,
                    note="blocked on staging deploy",
                ),
            ),
        ),
        Stage(
            name="deploy prod (canary: us-east-1, eu-west-1)",
            status="failed",
            duration_s=64,
            owner="release-bot",
            jobs=(
                Job(
                    name="helm upgrade payments-api",
                    status="failed",
                    duration_s=64,
                    retries=1,
                    note="rollout timed out",
                    logs=(
                        "error: pods stuck in ImagePullBackOff",
                        "hint: check registry permissions + image tag",
                        "rollback: canary disabled; prod unchanged",
                    ),
                ),
            ),
        ),
    ),
    deploys=(
        Deployment(
            env="staging",
            status="running",
            version="v2.18.0+build.143",
            actor="release-bot",
            started="10:12:08Z",
            duration_s=118,
        ),
        Deployment(
            env="prod",
            status="failed",
            version="v2.18.0+build.143",
            actor="release-bot",
            started="10:08:41Z",
            duration_s=64,
        ),
        Deployment(
            env="prod",
            status="success",
            version="v2.17.9+build.140",
            actor="k.sato",
            started="09:41:03Z",
            duration_s=232,
        ),
    ),
    alerts=(
        Alert(
            severity="page",
            service="payments-api",
            message="rollout paused: canary pods failing image pull; registry token expired for tag v2.18.0+build.143",
            since="10:09Z",
        ),
        Alert(
            severity="warn",
            service="checkout-web",
            message="elevated p95 latency on /api/v1/charge (2.1s); upstream retries increasing",
            since="10:05Z",
        ),
    ),
)


# =============================================================================
# Rendering helpers
# =============================================================================


def _breakpoint(width: int) -> str:
    if width < 50:
        return "narrow"
    if width < 100:
        return "medium"
    return "wide"


def _duration(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    m, s = divmod(seconds, 60)
    if m <= 0:
        return f"{s:>2}s"
    return f"{m:>2}m{s:02d}"


def _status_icon(status: str) -> str:
    return {
        "success": "✓",
        "running": "●",
        "failed": "✕",
        "queued": "…",
    }.get(status, "?")


def _status_style(status: str) -> Style:
    p = current_palette()
    return {
        "success": p.success.merge(Style(bold=True)),
        "running": p.accent.merge(Style(bold=True)),
        "failed": p.error.merge(Style(bold=True)),
        "queued": p.muted,
    }.get(status, Style())


def _spacer(width: int) -> Block:
    return Block.text("", Style(), width=width)


def _dim_header(text: str, *, width: int) -> Block:
    return Block.text(f"  {text}", Style(dim=True), width=width, wrap=Wrap.ELLIPSIS)


def _card(
    *,
    title: str,
    body: Block,
    outer_width: int,
    bordered: bool,
    accent: Style,
) -> Block:
    if outer_width <= 0:
        return Block.empty(0, 0)

    if not bordered:
        header = _dim_header(title, width=outer_width)
        return join_vertical(header, body, gap=0, align=Align.START)

    inner_width = max(1, outer_width - 2)
    body = truncate(body, inner_width)
    padded = pad(body, left=1, right=1)
    return border(
        padded,
        chars=ROUNDED,
        style=Style(dim=True),
        title=title,
        title_style=accent.merge(Style(bold=True)),
    )


# =============================================================================
# Panels
# =============================================================================


def render_pipeline_panel(data: Dashboard, *, ctx_width: int, zoom: Zoom, outer_width: int) -> Block:
    bp = _breakpoint(ctx_width)
    bordered = bp != "narrow"
    inner_width = max(1, outer_width - 2) if bordered else max(1, outer_width)

    show_duration = ctx_width >= 50
    show_owner = ctx_width >= 100

    if zoom == Zoom.MINIMAL:
        failed = sum(1 for s in data.stages if s.status == "failed")
        running = sum(1 for s in data.stages if s.status == "running")
        summary = f"{len(data.stages)} stages  ·  {failed} failed  ·  {running} running"
        body = Block.text(summary, Style(), width=inner_width, wrap=Wrap.ELLIPSIS)
        return _card(
            title="Pipeline",
            body=body,
            outer_width=outer_width,
            bordered=bordered,
            accent=current_palette().accent,
        )

    rows: list[Block] = []

    for stage in data.stages:
        icon = _status_icon(stage.status)
        icon_style = _status_style(stage.status)

        dur_w = 6 if show_duration else 0
        owner_w = 10 if show_owner else 0
        name_w = max(1, inner_width - 2 - dur_w - owner_w)

        name = Block.text(stage.name, Style(bold=True), width=name_w, wrap=Wrap.ELLIPSIS)
        parts: list[Block] = [
            Block.text(f"{icon} ", icon_style, width=2),
            name,
        ]
        if show_duration:
            parts.append(Block.text(f"{_duration(stage.duration_s):>5} ", Style(dim=True), width=6))
        if show_owner:
            parts.append(Block.text(stage.owner, Style(dim=True), width=10, wrap=Wrap.ELLIPSIS))
        row = join_horizontal(*parts, gap=0, align=Align.START)
        rows.append(row)

        if zoom >= Zoom.DETAILED and stage.jobs:
            for job in stage.jobs:
                job_icon = _status_icon(job.status)
                job_style = _status_style(job.status).merge(Style(dim=True))

                retry = f" x{job.retries}" if (show_owner and job.retries > 0) else ""
                suffix = f"  {_duration(job.duration_s)}{retry}"

                prefix = f"  {job_icon} "
                line_w = max(1, inner_width)
                note = f" — {job.note}" if job.note else ""
                text = f"{prefix}{job.name}{note}{suffix}"
                rows.append(Block.text(text, job_style, width=line_w, wrap=Wrap.ELLIPSIS))

                if zoom >= Zoom.FULL and job.logs:
                    log_wrap = Wrap.WORD if ctx_width >= 100 else Wrap.ELLIPSIS
                    for msg in job.logs[:3]:
                        rows.append(
                            Block.text(f"      {msg}", Style(dim=True), width=line_w, wrap=log_wrap)
                        )

    body = join_vertical(*rows, gap=0, align=Align.START)
    return _card(
        title="Pipeline",
        body=body,
        outer_width=outer_width,
        bordered=bordered,
        accent=current_palette().accent,
    )


def render_deploys_panel(data: Dashboard, *, ctx_width: int, zoom: Zoom, outer_width: int) -> Block:
    bp = _breakpoint(ctx_width)
    bordered = bp != "narrow"
    inner_width = max(1, outer_width - 2) if bordered else max(1, outer_width)

    show_actor = ctx_width >= 100
    show_started = ctx_width >= 50

    rows: list[Block] = []
    for d in data.deploys[: (2 if zoom == Zoom.MINIMAL else 4)]:
        icon = _status_icon(d.status)
        st = _status_style(d.status)

        env_w = 9 if ctx_width >= 50 else 8
        meta_w = 0
        if show_started:
            meta_w += 10  # " " + started
        if show_actor:
            meta_w += 11  # " " + actor

        version_w = max(1, inner_width - 2 - env_w - meta_w)

        parts: list[Block] = [
            Block.text(f"{icon} ", st, width=2),
            Block.text(d.env, Style(bold=True), width=env_w, wrap=Wrap.ELLIPSIS),
            Block.text(d.version, Style(), width=version_w, wrap=Wrap.ELLIPSIS),
        ]
        if show_started:
            parts.append(Block.text(f" {d.started}", Style(dim=True), width=10))
        if show_actor:
            parts.append(Block.text(f" {d.actor}", Style(dim=True), width=11, wrap=Wrap.ELLIPSIS))
        rows.append(join_horizontal(*parts, gap=0))

    body = join_vertical(*rows, gap=0)
    return _card(
        title="Deploys",
        body=body,
        outer_width=outer_width,
        bordered=bordered,
        accent=current_palette().accent,
    )


def render_alerts_panel(data: Dashboard, *, ctx_width: int, zoom: Zoom, outer_width: int) -> Block:
    bp = _breakpoint(ctx_width)
    bordered = bp != "narrow"
    inner_width = max(1, outer_width - 2) if bordered else max(1, outer_width)

    rows: list[Block] = []
    for a in data.alerts[: (1 if zoom == Zoom.MINIMAL else 3)]:
        sev_icon = "!" if a.severity == "page" else "⚠"
        sev_style = current_palette().error if a.severity == "page" else current_palette().warning

        head = join_horizontal(
            Block.text(f"{sev_icon} ", sev_style.merge(Style(bold=True)), width=2),
            Block.text(a.service, Style(bold=True), width=max(1, inner_width - 8), wrap=Wrap.ELLIPSIS),
            Block.text(a.since.rjust(6), Style(dim=True), width=6),
        )
        head = truncate(head, inner_width)
        rows.append(head)

        if zoom >= Zoom.SUMMARY:
            wrap = Wrap.WORD if ctx_width >= 100 else Wrap.ELLIPSIS
            rows.append(Block.text(f"  {a.message}", Style(dim=True), width=inner_width, wrap=wrap))

    body = join_vertical(*rows, gap=0)
    return _card(
        title="Alerts",
        body=body,
        outer_width=outer_width,
        bordered=bordered,
        accent=current_palette().error if any(a.severity == "page" for a in data.alerts) else current_palette().warning,
    )


def render_dashboard(ctx: CliContext, data: Dashboard) -> Block:
    width = max(1, ctx.width)
    bp = _breakpoint(width)

    title_left = Block.text(
        f" deploy pipeline  {data.repo}  ",
        current_palette().accent.merge(Style(bold=True)),
    )
    title_right = Block.text(
        f"{data.branch}@{data.commit}  {data.run_id}",
        Style(dim=True),
    )
    title = truncate(join_horizontal(title_left, title_right, gap=0, align=Align.START), width)

    meta = Block.text(
        f" width={ctx.width}  breakpoint={bp}  zoom={int(ctx.zoom)} ",
        Style(dim=True),
        width=width,
        wrap=Wrap.ELLIPSIS,
    )

    left_outer = min(56, width)
    right_outer = min(42, width)

    pipeline = render_pipeline_panel(data, ctx_width=width, zoom=ctx.zoom, outer_width=left_outer)

    right_col = join_vertical(
        render_deploys_panel(data, ctx_width=width, zoom=ctx.zoom, outer_width=right_outer),
        _spacer(right_outer),
        render_alerts_panel(data, ctx_width=width, zoom=ctx.zoom, outer_width=right_outer),
        gap=0,
    )

    main = join_responsive(
        pipeline,
        right_col,
        available_width=width,
        gap=2,
        align=Align.START,
    )

    return join_vertical(title, meta, _spacer(width), main, gap=0, align=Align.START)


# =============================================================================
# run_cli integration
# =============================================================================


def _fetch() -> Dashboard:
    return SAMPLE


def _render(ctx: CliContext, data: Dashboard) -> Block:
    return render_dashboard(ctx, data)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="responsive.py",
    )


if __name__ == "__main__":
    sys.exit(main())
