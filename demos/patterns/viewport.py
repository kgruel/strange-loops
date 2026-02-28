#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Viewport + scroll state — windowing, clamping, and cursor-follow.

This demo is static output: the frames are precomputed and rendered at
multiple zoom levels.

    uv run demos/patterns/viewport.py -q        # one-line summary
    uv run demos/patterns/viewport.py           # cursor-follow sequence
    uv run demos/patterns/viewport.py -v        # + overlay of full content
    uv run demos/patterns/viewport.py -vv       # multiple offsets side-by-side
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from painted import (
    Block,
    CliContext,
    Cursor,
    Style,
    Viewport,
    Zoom,
    border,
    join_horizontal,
    join_vertical,
    pad,
    run_cli,
    vslice,
    ROUNDED,
)


def _header(text: str) -> Block:
    return Block.text(f"  {text}", Style(dim=True))


def _spacer() -> Block:
    return Block.text("", Style())


@dataclass(frozen=True, slots=True)
class Frame:
    label: str
    cursor: Cursor
    viewport: Viewport


@dataclass(frozen=True, slots=True)
class DemoData:
    content: tuple[str, ...]
    visible: int
    follow: tuple[Frame, ...]
    manual_scroll: tuple[Frame, ...]


CONTENT: tuple[str, ...] = (
    "deploy api-gateway: build ✓ sha=9f2c7a1",
    "deploy api-gateway: push image",
    "deploy api-gateway: rollout 1/3 ready",
    "deploy api-gateway: rollout 2/3 ready",
    "deploy api-gateway: rollout 3/3 ready",
    "deploy api-gateway: smoke tests",
    "deploy api-gateway: health /ready 200",
    "deploy api-gateway: metrics p95=72ms",
    "deploy api-gateway: error_rate=0.08%",
    "deploy api-gateway: done",
    "tail logs api-gateway: conn=1243",
    "tail logs api-gateway: conn=1244",
    "tail logs api-gateway: conn=1245",
    "tail logs api-gateway: conn=1246",
    "tail logs api-gateway: warn: retrying",
    "tail logs api-gateway: ok",
    "rollout complete: 3/3 healthy",
    "status: green",
)


def _mk_follow_frames(*, content_len: int, visible: int) -> tuple[Frame, ...]:
    cur = Cursor(index=0, count=content_len)
    vp = Viewport(offset=0, visible=visible, content=content_len)
    frames: list[Frame] = [Frame("start", cur, vp)]

    cur = cur.move_to(visible - 1)
    vp = vp.scroll_into_view(cur.index)
    frames.append(Frame(f"cursor={cur.index} (still visible)", cur, vp))

    cur = cur.move_to(visible)
    vp = vp.scroll_into_view(cur.index)
    frames.append(Frame(f"cursor={cur.index} (scroll_into_view)", cur, vp))

    cur = cur.move_to(visible * 2 - 1)
    vp = vp.scroll_into_view(cur.index)
    frames.append(Frame(f"cursor={cur.index}", cur, vp))

    cur = cur.end()
    vp = vp.scroll_into_view(cur.index)
    frames.append(Frame("cursor=end", cur, vp))

    return tuple(frames)


def _mk_manual_scroll_frames(*, content_len: int, visible: int) -> tuple[Frame, ...]:
    cur = Cursor(index=min(9, max(0, content_len - 1)), count=content_len)
    vp = Viewport(offset=0, visible=visible, content=content_len)
    frames: list[Frame] = [Frame(f"cursor={cur.index} (fixed)", cur, vp)]

    vp = vp.scroll(visible + 2)
    frames.append(Frame(f"scroll +{visible + 2}", cur, vp))

    vp = vp.scroll(999)
    frames.append(Frame("scroll +999 (clamp to bottom)", cur, vp))

    vp = vp.scroll(-5)
    frames.append(Frame("scroll -5", cur, vp))

    return tuple(frames)


def _fetch() -> DemoData:
    visible = 5
    content_len = len(CONTENT)
    return DemoData(
        content=CONTENT,
        visible=visible,
        follow=_mk_follow_frames(content_len=content_len, visible=visible),
        manual_scroll=_mk_manual_scroll_frames(content_len=content_len, visible=visible),
    )


def _state_line(frame: Frame) -> str:
    cur = frame.cursor
    vp = frame.viewport
    count = cur.count
    end = min(vp.offset + vp.visible, vp.content)
    if vp.visible <= 0 or vp.content <= 0 or end <= vp.offset:
        window = "[]"
    else:
        window = f"[{vp.offset}..{end - 1}]"

    flags = []
    if vp.is_at_top:
        flags.append("top")
    if vp.is_at_bottom:
        flags.append("bottom")
    flag_str = "" if not flags else f" ({'|'.join(flags)})"

    max_idx = max(0, count - 1)
    return (
        f"cursor={cur.index}/{max_idx}  "
        f"offset={vp.offset} visible={vp.visible} content={vp.content} max={vp.max_offset}  "
        f"window={window}{flag_str}"
    )


def _content_block(content: tuple[str, ...], cursor: Cursor, *, width: int) -> Block:
    rows: list[Block] = []
    for i, line in enumerate(content):
        sel = "▸" if i == cursor.index else " "
        rows.append(Block.text(f"{i:02d} {sel} {line}", Style(), width=width))
    return join_vertical(*rows) if rows else Block.empty(width, 0)


def _window_block(content: tuple[str, ...], cursor: Cursor, vp: Viewport, *, width: int) -> Block:
    full = _content_block(content, cursor, width=width)
    window = vslice(full, vp.offset, vp.visible)
    if window.height < vp.visible:
        window = pad(window, bottom=vp.visible - window.height)
    return window


def _overlay_block(content: tuple[str, ...], cursor: Cursor, vp: Viewport, *, width: int) -> Block:
    if not content:
        return Block.text("(empty)", Style(dim=True), width=width)

    end = min(vp.offset + vp.visible, vp.content)
    rows: list[Block] = []
    for i, line in enumerate(content):
        in_window = vp.offset <= i < end
        top = in_window and i == vp.offset
        bottom = in_window and i == end - 1

        gutter = " "
        if top and bottom:
            gutter = "■"
        elif top:
            gutter = "┌"
        elif bottom:
            gutter = "└"
        elif in_window:
            gutter = "│"

        sel = "▸" if i == cursor.index else " "
        rows.append(Block.text(f"{gutter} {i:02d} {sel} {line}", Style(), width=width))
    return join_vertical(*rows)


def _frame_block(ctx: CliContext, frame: Frame, content: tuple[str, ...], *, overlay: bool) -> Block:
    w = max(20, min(ctx.width, 120))
    label = Block.text(f"[{frame.label}]", Style(dim=True), width=w)
    state = Block.text(_state_line(frame), Style(dim=True), width=w)
    window = _window_block(content, frame.cursor, frame.viewport, width=w)

    if not overlay:
        return join_vertical(label, state, window)

    overlay_block = _overlay_block(content, frame.cursor, frame.viewport, width=w)
    return join_vertical(
        label,
        state,
        _spacer(),
        Block.text("window (vslice):", Style(dim=True), width=w),
        window,
        _spacer(),
        Block.text("overlay (full content with viewport window):", Style(dim=True), width=w),
        overlay_block,
    )


def _render_minimal(data: DemoData) -> Block:
    vp = data.follow[-1].viewport
    return Block.text(
        f"viewport demo: content={vp.content} visible={vp.visible} max_offset={vp.max_offset}",
        Style(),
    )


def _render_summary(ctx: CliContext, data: DemoData) -> Block:
    frames = (data.follow[0], data.follow[1], data.follow[2], data.follow[-1])
    parts: list[Block] = [_header("cursor-follow: viewport.scroll_into_view(cursor.index)"), _spacer()]
    for f in frames:
        parts.append(_frame_block(ctx, f, data.content, overlay=False))
        parts.append(_spacer())
    return join_vertical(*parts)


def _render_detailed(ctx: CliContext, data: DemoData) -> Block:
    frames = (data.follow[0], data.follow[2], data.follow[-1])
    parts: list[Block] = [_header("cursor-follow with overlay (window moves over fixed data)"), _spacer()]
    for f in frames:
        parts.append(_frame_block(ctx, f, data.content, overlay=True))
        parts.append(_spacer())

    parts.append(_header("manual scroll: viewport.scroll(delta) clamps, cursor can be offscreen"))
    parts.append(_spacer())
    for f in (data.manual_scroll[0], data.manual_scroll[1], data.manual_scroll[2], data.manual_scroll[-1]):
        parts.append(_frame_block(ctx, f, data.content, overlay=False))
        parts.append(_spacer())

    return join_vertical(*parts)


def _slice_panel(
    content: tuple[str, ...],
    *,
    cursor_index: int | None,
    vp: Viewport,
    width: int,
    title: str,
) -> Block:
    cur = Cursor(index=cursor_index or 0, count=vp.content) if cursor_index is not None else Cursor(count=vp.content)
    inner_w = max(10, width - 2)
    full = _content_block(content, cur, width=inner_w)
    window = vslice(full, vp.offset, vp.visible)
    if window.height < vp.visible:
        window = pad(window, bottom=vp.visible - window.height)
    return border(window, chars=ROUNDED, title=title, style=Style(dim=True))


def _render_full(ctx: CliContext, data: DemoData) -> Block:
    content_len = len(data.content)
    base = Viewport(offset=0, visible=data.visible, content=content_len)

    offsets = (0, min(3, base.max_offset), base.max_offset)
    gap = 2
    n = len(offsets)
    col_w = max(18, (max(0, ctx.width) - gap * (n - 1)) // n)

    panels: list[Block] = []
    for off in offsets:
        vp = base.scroll_to(off)
        end = min(vp.offset + vp.visible, vp.content)
        title = f"offset={vp.offset}  window=[{vp.offset}..{max(vp.offset, end - 1)}]"
        panels.append(_slice_panel(data.content, cursor_index=None, vp=vp, width=col_w, title=title))

    row = (
        join_horizontal(*panels, gap=gap)
        if col_w >= 18 and ctx.width >= 60
        else join_vertical(*panels, gap=1)
    )

    overlay = _frame_block(ctx, data.follow[2], data.content, overlay=True)

    return join_vertical(
        _header("same content, different offsets (vslice windowing)"),
        _spacer(),
        row,
        _spacer(),
        _header("cursor-follow: the offset that keeps selection visible"),
        _spacer(),
        overlay,
    )


def _render(ctx: CliContext, data: DemoData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(ctx, data)
    if ctx.zoom == Zoom.FULL:
        return _render_full(ctx, data)
    return _render_detailed(ctx, data)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="viewport.py",
    )


if __name__ == "__main__":
    sys.exit(main())

