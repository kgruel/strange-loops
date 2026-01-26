#!/usr/bin/env python3
"""Demo 09: Layer — modal stacking for input and rendering.

Layer bundles input handling and rendering for modal UI:
- Base layer handles normal interaction
- Push overlays (help, settings) on top
- Pop to dismiss and return to previous layer

Run: uv run python demos/demo_09_layer.py
Press 'h' for help, 's' for settings, 'q' to quit.
"""

import asyncio
from dataclasses import dataclass, replace

from cells import (
    RenderApp, Block, Style, BufferView,
    join_vertical, pad, border,
    ROUNDED,
    Layer, Stay, Pop, Push, Quit, process_key, render_layers,
)


@dataclass(frozen=True)
class AppState:
    """Application state."""
    counter: int = 0
    volume: int = 50  # 0-100
    layers: tuple[Layer, ...] = ()
    width: int = 80
    height: int = 24


# -- Layer accessors --

def get_layers(state: AppState) -> tuple[Layer, ...]:
    return state.layers


def set_layers(state: AppState, layers: tuple[Layer, ...]) -> AppState:
    return replace(state, layers=layers)


# -- Help Layer --

def handle_help(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Stay | Pop | Push | Quit]:
    """Any key dismisses help."""
    return None, app_state, Pop()


def render_help(layer_state: None, app_state: AppState, view: BufferView) -> None:
    """Render help overlay."""
    rows = [
        Block.text(" Help ", Style(fg="cyan", bold=True)),
        Block.empty(1, 1),
        Block.text(" h    show this help", Style(dim=True)),
        Block.text(" s    open settings", Style(dim=True)),
        Block.text(" +/-  adjust counter", Style(dim=True)),
        Block.text(" q    quit", Style(dim=True)),
        Block.empty(1, 1),
        Block.text(" press any key to close ", Style(fg="cyan", dim=True)),
    ]
    content = join_vertical(*rows)
    content = pad(content, left=2, right=2, top=1, bottom=1)
    boxed = border(content, ROUNDED, Style(fg="cyan"))

    # Center
    x = max(0, (app_state.width - boxed.width) // 2)
    y = max(0, (app_state.height - boxed.height) // 2)
    boxed.paint(view, x, y)


def make_help_layer() -> Layer[None]:
    return Layer(name="help", state=None, handle=handle_help, render=render_help)


# -- Settings Layer --

@dataclass(frozen=True)
class SettingsEdit:
    """Temporary edit state for settings."""
    volume: int = 50


def handle_settings(key: str, layer_state: SettingsEdit, app_state: AppState) -> tuple[SettingsEdit, AppState, Stay | Pop | Push | Quit]:
    """Settings: up/down changes volume, Enter confirms, Escape cancels."""
    if key == "escape":
        # Cancel: discard changes
        return layer_state, app_state, Pop()

    if key == "enter":
        # Confirm: apply changes
        return layer_state, replace(app_state, volume=layer_state.volume), Pop()

    if key == "up":
        new_state = replace(layer_state, volume=min(100, layer_state.volume + 10))
        return new_state, app_state, Stay()

    if key == "down":
        new_state = replace(layer_state, volume=max(0, layer_state.volume - 10))
        return new_state, app_state, Stay()

    return layer_state, app_state, Stay()


def render_settings(layer_state: SettingsEdit, app_state: AppState, view: BufferView) -> None:
    """Render settings overlay."""
    vol = layer_state.volume
    bar_filled = vol // 10
    bar_empty = 10 - bar_filled
    bar_str = "[" + "#" * bar_filled + "-" * bar_empty + "]"

    rows = [
        Block.text(" Settings ", Style(fg="yellow", bold=True)),
        Block.empty(1, 1),
        Block.text(f" Volume: {vol:3d}%", Style(fg="white")),
        Block.text(f" {bar_str}", Style(fg="green" if vol > 30 else "red")),
        Block.empty(1, 1),
        Block.text(" up/down  adjust", Style(dim=True)),
        Block.text(" enter    confirm", Style(dim=True)),
        Block.text(" escape   cancel", Style(dim=True)),
    ]
    content = join_vertical(*rows)
    content = pad(content, left=2, right=2, top=1, bottom=1)
    boxed = border(content, ROUNDED, Style(fg="yellow"))

    # Center
    x = max(0, (app_state.width - boxed.width) // 2)
    y = max(0, (app_state.height - boxed.height) // 2)
    boxed.paint(view, x, y)


def make_settings_layer(initial_volume: int) -> Layer[SettingsEdit]:
    return Layer(
        name="settings",
        state=SettingsEdit(volume=initial_volume),
        handle=handle_settings,
        render=render_settings,
    )


# -- Base Layer --

def handle_base(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Stay | Pop | Push | Quit]:
    """Base layer: counter, push overlays."""
    if key == "q":
        return None, app_state, Quit()

    if key == "h":
        return None, app_state, Push(make_help_layer())

    if key == "s":
        return None, app_state, Push(make_settings_layer(app_state.volume))

    if key in ("+", "="):
        return None, replace(app_state, counter=app_state.counter + 1), Stay()

    if key in ("-", "_"):
        return None, replace(app_state, counter=max(0, app_state.counter - 1)), Stay()

    return None, app_state, Stay()


def render_base(layer_state: None, app_state: AppState, view: BufferView) -> None:
    """Render base content."""
    # Title
    title = Block.text(" Layer Demo ", Style(fg="white", bold=True))
    title.paint(view, 2, 1)

    # Counter
    counter_text = f"Counter: {app_state.counter}"
    counter = Block.text(counter_text, Style(fg="cyan", bold=True))
    counter.paint(view, 4, 4)

    # Volume display
    vol_text = f"Volume: {app_state.volume}%"
    vol = Block.text(vol_text, Style(fg="green" if app_state.volume > 30 else "red"))
    vol.paint(view, 4, 6)

    # Instructions
    instructions = [
        Block.text("+/-  counter", Style(dim=True)),
        Block.text("h    help", Style(dim=True)),
        Block.text("s    settings", Style(dim=True)),
        Block.text("q    quit", Style(dim=True)),
    ]
    y = 9
    for inst in instructions:
        inst.paint(view, 4, y)
        y += 1

    # Layer stack indicator (bottom right)
    layer_names = [layer.name for layer in app_state.layers]
    stack_text = "layers: " + " > ".join(layer_names)
    stack = Block.text(stack_text, Style(fg="magenta", dim=True))
    stack.paint(view, 2, app_state.height - 1)


def make_base_layer() -> Layer[None]:
    return Layer(name="base", state=None, handle=handle_base, render=render_base)


# -- App --

class Demo09App(RenderApp):
    def __init__(self):
        super().__init__()
        self._state = AppState(layers=(make_base_layer(),))
        self._should_quit = False

    def layout(self, width: int, height: int) -> None:
        self._state = replace(self._state, width=width, height=height)

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        render_layers(self._state, self._buf, get_layers)

    def on_key(self, key: str) -> None:
        self._state, should_quit, _result = process_key(key, self._state, get_layers, set_layers)

        if should_quit:
            self.quit()


if __name__ == "__main__":
    asyncio.run(Demo09App().run())
