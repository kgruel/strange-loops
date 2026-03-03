#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Layer stack — modal push/pop and Action flow.

Layers are a small, composable pattern for building modal UIs:

- Render is bottom-to-top (later layers can cover earlier ones).
- Input goes to the top layer only.
- Actions returned by `Layer.handle(...)` drive the stack:
  Stay | Pop(result) | Push(layer) | Quit
- The base layer never pops (stack is never empty).

This demo teaches the pattern with static output by replaying a few key
scripts and rendering the resulting action/stack trace and snapshots.

    uv run demos/patterns/layers.py -q        # one-line summary
    uv run demos/patterns/layers.py           # per-scenario actions
    uv run demos/patterns/layers.py -v        # step table + key frames
    uv run demos/patterns/layers.py -vv       # bordered + render-order snapshot
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
    join_vertical,
    pad,
    run_cli,
    ROUNDED,
)
from painted.icon_set import current_icons
from painted.palette import current_palette
from painted.tui import Layer, Pop, Push, Quit, Stay
from painted.tui.testing import buffer_to_lines


SERVICES: tuple[str, ...] = (
    "api-gateway",
    "auth-service",
    "worker",
    "scheduler",
    "metrics",
)


@dataclass(frozen=True, slots=True)
class DemoState:
    layers: tuple[Layer, ...]
    last_deploy: str | None = None
    status: str = ""


def _get_layers(state: DemoState) -> tuple[Layer, ...]:
    return state.layers


def _set_layers(state: DemoState, layers: tuple[Layer, ...]) -> DemoState:
    return replace(state, layers=layers)


def _draw_box(view, *, x: int, y: int, w: int, h: int, title: str, lines: list[str]) -> None:
    p = current_palette()
    box_style = p.muted
    title_style = p.accent.merge(Style(bold=True))
    text_style = Style(bold=True)

    if w < 2 or h < 2:
        return

    top = "+" + ("-" * (w - 2)) + "+"
    mid = "|" + (" " * (w - 2)) + "|"
    bot = "+" + ("-" * (w - 2)) + "+"

    view.put_text(x, y, top, box_style)
    for row in range(1, h - 1):
        view.put_text(x, y + row, mid, box_style)
    view.put_text(x, y + h - 1, bot, box_style)

    if title:
        t = f" {title} "
        t = t[: max(0, w - 2)]
        view.put_text(x + 1, y, t, title_style)

    for i, line in enumerate(lines[: max(0, h - 2)]):
        clipped = line[: max(0, w - 2)]
        view.put_text(x + 1, y + 1 + i, clipped, text_style)


def _base_layer() -> Layer:
    def handle(key: str, ls: int, app_state: DemoState):
        if key == "j":
            return min(ls + 1, len(SERVICES) - 1), app_state, Stay()
        if key == "k":
            return max(ls - 1, 0), app_state, Stay()
        if key == "enter":
            return ls, app_state, Push(layer=_confirm_layer(SERVICES[ls]))
        if key == "?":
            return ls, app_state, Push(layer=_help_layer("base"))
        if key == "x":
            # Intentional: demonstrate that the base layer never pops.
            return ls, app_state, Pop(result="base-pop")
        if key == "q":
            return ls, app_state, Quit()
        return ls, app_state, Stay()

    def render(ls: int, app_state: DemoState, view):
        p = current_palette()
        view.fill(0, 0, view.width, view.height, " ", Style())

        view.put_text(0, 0, "services", p.muted.merge(Style(bold=True)))
        for i, svc in enumerate(SERVICES):
            marker = ">" if i == ls else " "
            style = Style(bold=True) if i == ls else p.muted
            view.put_text(0, 1 + i, f"{marker} {svc}", style)

        footer_y = max(0, view.height - 2)
        footer = "enter=confirm  ?=help  x=pop(base)  q=quit"
        view.put_text(0, footer_y, footer[: view.width], p.muted)

        status = app_state.status
        if app_state.last_deploy:
            status = status or f"queued deploy: {app_state.last_deploy}"
        view.put_text(0, footer_y + 1, (status or " ")[: view.width], p.muted)

    return Layer(name="base", state=0, handle=handle, render=render)


def _confirm_layer(service_name: str) -> Layer:
    def handle(key: str, ls: str, app_state: DemoState):
        if key == "y":
            return ls, app_state, Pop(result=ls)
        if key == "n":
            return ls, app_state, Pop(result=None)
        if key == "?":
            return ls, app_state, Push(layer=_help_layer("confirm"))
        if key == "q":
            return ls, app_state, Quit()
        return ls, app_state, Stay()

    def render(ls: str, app_state: DemoState, view):
        w = min(36, max(14, view.width - 4))
        h = 5
        x = max(0, (view.width - w) // 2)
        y = max(0, (view.height - h) // 2)
        _draw_box(
            view,
            x=x,
            y=y,
            w=w,
            h=h,
            title="CONFIRM",
            lines=[
                f"Deploy {ls}?",
                "",
                "y=yes  n=no  ?=help",
            ],
        )

    return Layer(name="confirm", state=service_name, handle=handle, render=render)


def _help_layer(context: str) -> Layer:
    def handle(key: str, ls: str, app_state: DemoState):
        if key == "escape":
            return ls, app_state, Pop(result=None)
        return ls, app_state, Stay()

    def render(ls: str, app_state: DemoState, view):
        w = min(32, max(18, view.width - 6))
        h = 6
        x = max(0, view.width - w - 1)
        y = 1
        if ls == "base":
            lines = ["base keys:", "  j/k move", "  enter confirm", "  q quit", "esc close"]
        else:
            lines = ["confirm keys:", "  y confirm", "  n cancel", "  q quit", "esc close"]
        _draw_box(view, x=x, y=y, w=w, h=h, title="HELP", lines=lines)

    return Layer(name="help", state=context, handle=handle, render=render)


def _layer_state_repr(layer: Layer) -> str:
    if layer.name == "base" and isinstance(layer.state, int):
        idx = max(0, min(layer.state, len(SERVICES) - 1))
        return f"cursor={idx}:{SERVICES[idx]}"
    if layer.name == "confirm" and isinstance(layer.state, str):
        return f"service={layer.state}"
    if layer.name == "help" and isinstance(layer.state, str):
        return f"context={layer.state}"
    return str(layer.state)


def _stack_sig(layers: tuple[Layer, ...]) -> str:
    return "[" + ", ".join(f"{l.name}({_layer_state_repr(l)})" for l in layers) + "]"


def _snapshot(state: DemoState, *, width: int, height: int) -> list[str]:
    from painted.buffer import Buffer
    from painted.tui import render_layers

    buf = Buffer(width, height)
    buf.fill(0, 0, width, height, " ", Style())
    render_layers(state, buf, _get_layers)
    return buffer_to_lines(buf)


def _snapshot_progressive(
    state: DemoState, *, width: int, height: int
) -> list[tuple[str, list[str]]]:
    from painted.buffer import Buffer
    from painted.buffer import BufferView

    layers = _get_layers(state)
    if not layers:
        return []

    buf = Buffer(width, height)
    buf.fill(0, 0, width, height, " ", Style())
    view = BufferView(buf, 0, 0, width, height)

    out: list[tuple[str, list[str]]] = []
    names: list[str] = []
    for layer in layers:
        names.append(layer.name)
        layer.render(layer.state, state, view)
        label = "after " + "+".join(names)
        out.append((label, buffer_to_lines(buf)))
    return out


def _action_str(action) -> str:
    match action:
        case Stay():
            return "Stay"
        case Quit():
            return "Quit"
        case Push(layer=layer):
            return f"Push({layer.name})"
        case Pop(result=result):
            return f"Pop({result!r})" if result is not None else "Pop(None)"
    return type(action).__name__


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    keys: list[str]


@dataclass(frozen=True, slots=True)
class StepTrace:
    i: int
    key: str
    handled_by: str
    action_str: str
    stack_before: str
    stack_after: str
    pop_result: str | None
    frame_after: list[str]
    progressive_after: list[tuple[str, list[str]]]


@dataclass(frozen=True, slots=True)
class ScenarioTrace:
    scenario: Scenario
    initial_stack: str
    initial_frame: list[str]
    steps: list[StepTrace]
    invariants_ok: bool
    action_counts: dict[str, int]


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="help blocks confirm",
        keys=["enter", "?", "y", "escape", "y", "q"],
    ),
    Scenario(
        name="cancel confirm",
        keys=["j", "enter", "n", "q"],
    ),
    Scenario(
        name="base never pops",
        keys=["x", "q"],
    ),
)


def _step_key(
    state: DemoState, key: str, *, snap_w: int, snap_h: int
) -> tuple[DemoState, bool, StepTrace, bool]:
    layers = _get_layers(state)
    top = layers[-1]

    handled_by = top.name
    stack_before = _stack_sig(layers)
    new_layer_state, new_app_state, action = top.handle(key, top.state, state)
    action_s = _action_str(action)

    from dataclasses import replace as _replace

    updated_top = _replace(top, state=new_layer_state)
    updated_layers = (*layers[:-1], updated_top)

    should_quit = False
    pop_result: object | None = None

    match action:
        case Stay():
            new_state = _set_layers(new_app_state, updated_layers)
        case Push(layer=new_layer):
            new_state = _set_layers(new_app_state, (*updated_layers, new_layer))
        case Pop(result=result):
            pop_result = result
            if len(layers) > 1:
                new_state = _set_layers(new_app_state, layers[:-1])
            else:
                new_state = _set_layers(new_app_state, updated_layers)
        case Quit():
            should_quit = True
            new_state = new_app_state
        case _:
            new_state = _set_layers(new_app_state, updated_layers)

    # Domain reaction after the layer action (typical pattern: Pop returns data).
    if isinstance(action, Pop) and handled_by == "confirm":
        if pop_result is None:
            new_state = replace(new_state, status="deploy canceled")
        elif isinstance(pop_result, str):
            new_state = replace(new_state, last_deploy=pop_result, status="")

    stack_after = _stack_sig(_get_layers(new_state))
    frame_after = _snapshot(new_state, width=snap_w, height=snap_h)
    progressive = _snapshot_progressive(new_state, width=snap_w, height=snap_h)

    base_never_popped = True
    if len(layers) == 1 and isinstance(action, Pop):
        base_never_popped = (len(_get_layers(new_state)) == 1) and (
            _get_layers(new_state)[0].name == "base"
        )

    step = StepTrace(
        i=0,
        key=key,
        handled_by=handled_by,
        action_str=action_s,
        stack_before=stack_before,
        stack_after=stack_after,
        pop_result=None if pop_result is None else str(pop_result),
        frame_after=frame_after,
        progressive_after=progressive,
    )
    return new_state, should_quit, step, base_never_popped


def _run_scenario(scenario: Scenario, *, snap_w: int, snap_h: int) -> ScenarioTrace:
    state = DemoState(layers=(_base_layer(),))

    initial_stack = _stack_sig(_get_layers(state))
    initial_frame = _snapshot(state, width=snap_w, height=snap_h)

    steps: list[StepTrace] = []
    action_counts: dict[str, int] = {"Stay": 0, "Push": 0, "Pop": 0, "Quit": 0}
    base_ok = True

    for i, key in enumerate(scenario.keys):
        state, should_quit, step, base_never_popped = _step_key(
            state, key, snap_w=snap_w, snap_h=snap_h
        )
        step = replace(step, i=i)
        steps.append(step)

        if step.action_str.startswith("Stay"):
            action_counts["Stay"] += 1
        elif step.action_str.startswith("Push"):
            action_counts["Push"] += 1
        elif step.action_str.startswith("Pop"):
            action_counts["Pop"] += 1
        elif step.action_str.startswith("Quit"):
            action_counts["Quit"] += 1

        base_ok = base_ok and base_never_popped
        if should_quit:
            break

    invariants_ok = base_ok and (len(_get_layers(state)) >= 1)
    return ScenarioTrace(
        scenario=scenario,
        initial_stack=initial_stack,
        initial_frame=initial_frame,
        steps=steps,
        invariants_ok=invariants_ok,
        action_counts=action_counts,
    )


def _lines_block(lines: list[str], *, width: int, max_lines: int) -> Block:
    p = current_palette()
    style = p.muted
    rows = [Block.text(line.rstrip(), style, width=width) for line in lines[:max_lines]]
    if not rows:
        return Block.text("(no frame)", style, width=width)
    return join_vertical(*rows)


def _render_minimal(traces: list[ScenarioTrace]) -> Block:
    p = current_palette()
    icons = current_icons()
    ok = all(t.invariants_ok for t in traces)
    icon = icons.check if ok else icons.cross
    style = p.success if ok else p.error

    counts = {"Stay": 0, "Push": 0, "Pop": 0, "Quit": 0}
    for t in traces:
        for k, v in t.action_counts.items():
            counts[k] = counts.get(k, 0) + v

    summary = f"{icon} layers demo: {len(traces)} scenarios"
    actions = f"actions: Stay={counts['Stay']} Push={counts['Push']} Pop={counts['Pop']} Quit={counts['Quit']}"
    inv = "invariants: base_never_pops ✓" if ok else "invariants: base_never_pops ✗"
    return join_vertical(
        Block.text(summary, style),
        Block.text(actions, p.muted),
        Block.text(inv, p.muted),
    )


def _render_summary(traces: list[ScenarioTrace]) -> Block:
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []

    for t in traces:
        icon = icons.check if t.invariants_ok else icons.cross
        header_style = p.success if t.invariants_ok else p.error
        header = Block.text(f"{icon} {t.scenario.name}", header_style)
        keys_line = Block.text(f"  keys: {' -> '.join(t.scenario.keys)}", p.muted)
        actions_line = Block.text(
            "  actions: " + " -> ".join(s.action_str for s in t.steps),
            p.muted,
        )
        final_stack = t.steps[-1].stack_after if t.steps else t.initial_stack
        stack_line = Block.text(f"  stack: {final_stack}", p.muted)
        sections.append(
            join_vertical(header, keys_line, actions_line, stack_line, Block.text("", Style()))
        )

    return join_vertical(*sections, _render_minimal(traces))


def _render_detailed(ctx: CliContext, traces: list[ScenarioTrace]) -> Block:
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []

    snap_w = max(24, min(60, ctx.width - 6))
    snap_h = 10

    for t in traces:
        icon = icons.check if t.invariants_ok else icons.cross
        title = f"{icon} {t.scenario.name}"
        keys_line = Block.text(f"keys: {' -> '.join(t.scenario.keys)}", p.muted)

        rows: list[Block] = [keys_line, Block.text("", Style())]
        for s in t.steps:
            line = (
                f"{s.i:02d} key={s.key:<7s} top={s.handled_by:<7s} "
                f"action={s.action_str:<14s} {s.stack_before} -> {s.stack_after}"
            )
            rows.append(Block.text(line, Style(dim=True), width=max(0, ctx.width - 2)))

        # Key frames: initial + structural steps.
        key_steps = [s for s in t.steps if s.action_str.startswith(("Push", "Pop", "Quit"))]
        frames: list[Block] = [Block.text("", Style()), Block.text("frames:", p.muted)]
        frames.append(Block.text("  [initial]", Style(dim=True)))
        frames.append(_lines_block(t.initial_frame, width=snap_w, max_lines=snap_h))
        for s in key_steps:
            frames.append(Block.text(f"  [after '{s.key}' / {s.action_str}]", Style(dim=True)))
            frames.append(_lines_block(s.frame_after, width=snap_w, max_lines=snap_h))

        inner = join_vertical(*rows, *frames)
        sections.append(
            border(
                pad(inner, right=max(0, snap_w - inner.width)),
                title=title,
                chars=ROUNDED,
                style=p.muted,
            )
        )
        sections.append(Block.text("", Style()))

    return join_vertical(*sections, _render_minimal(traces))


def _render_full(ctx: CliContext, traces: list[ScenarioTrace]) -> Block:
    p = current_palette()
    icons = current_icons()
    sections: list[Block] = []

    snap_w = max(24, min(60, ctx.width - 6))
    snap_h = 10

    for t in traces:
        icon = icons.check if t.invariants_ok else icons.cross
        title = f"{icon} {t.scenario.name}"
        keys_line = Block.text(f"keys: {' -> '.join(t.scenario.keys)}", p.muted)

        rows: list[Block] = [keys_line, Block.text("", Style()), Block.text("steps:", p.muted)]
        for s in t.steps:
            line = (
                f"[{s.i:02d}] key={s.key:<7s} handled_by={s.handled_by:<7s} "
                f"action={s.action_str:<14s}"
            )
            rows.append(Block.text(line, Style(dim=True), width=max(0, ctx.width - 2)))

        # Render order: show progressive buffer snapshots at max stack depth.
        max_step = None
        max_depth = 0
        for s in t.steps:
            depth = s.stack_after.count("(")  # one per layer
            if depth > max_depth:
                max_depth = depth
                max_step = s

        order: list[Block] = []
        if max_step is not None and max_step.progressive_after:
            order.append(Block.text("", Style()))
            order.append(
                Block.text(
                    f"render order @ step {max_step.i:02d} (after '{max_step.key}'):", p.muted
                )
            )
            for label, lines in max_step.progressive_after:
                order.append(Block.text(f"  [{label}]", Style(dim=True)))
                order.append(_lines_block(lines, width=snap_w, max_lines=snap_h))

        inner = join_vertical(*rows, *order)
        sections.append(
            border(
                pad(inner, right=max(0, snap_w - inner.width)),
                title=title,
                chars=ROUNDED,
                style=p.muted,
            )
        )
        sections.append(Block.text("", Style()))

    return join_vertical(*sections, _render_minimal(traces))


def _render(ctx: CliContext, traces: list[ScenarioTrace]) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(traces)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(traces)
    if ctx.zoom == Zoom.FULL:
        return _render_full(ctx, traces)
    return _render_detailed(ctx, traces)


def _fetch() -> list[ScenarioTrace]:
    # Fixed snapshot size for stable goldens.
    snap_w = 44
    snap_h = 10
    return [_run_scenario(s, snap_w=snap_w, snap_h=snap_h) for s in SCENARIOS]


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="layers.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
