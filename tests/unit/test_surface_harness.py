"""Tests for the deterministic, non-TTY Surface test harness."""

from __future__ import annotations

from painted import Style
from painted.mouse import MouseAction, MouseButton, MouseEvent
from painted.tui import (
    Layer,
    Pop,
    Push,
    Quit,
    Stay,
    Surface,
    TestSurface,
    render_layers,
)


class SimpleApp(Surface):
    def __init__(self, *, on_emit=None):
        super().__init__(on_emit=on_emit)
        self.msg = "init"
        self.mouse_count = 0

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        self._buf.put_text(0, 0, self.msg, Style(fg="green", bold=True))

    def on_key(self, key: str) -> None:
        if key == "x":
            self.msg = "x"
        elif key == "q":
            self.quit()

    def on_mouse(self, event: MouseEvent) -> None:
        if event.is_click:
            self.mouse_count += 1
            self.msg = f"m{self.mouse_count}"


class TestHarnessBasics:
    def test_runs_to_completion_and_captures_frames(self):
        emitted: list[tuple[str, dict]] = []
        app = SimpleApp(on_emit=lambda k, d: emitted.append((k, d)))

        harness = TestSurface(
            app,
            width=10,
            height=2,
            input_queue=["x", "q", "y"],  # "y" should never run
        )
        frames = harness.run_to_completion()

        assert len(frames) == 3  # initial + "x" + "q"
        assert frames[0].lines[0].rstrip().startswith("init")
        assert frames[1].lines[0].rstrip().startswith("x")
        assert frames[2].lines[0].rstrip().startswith("x")  # quit still renders once

        assert emitted == [
            ("ui.key", {"key": "x"}),
            ("ui.key", {"key": "q"}),
        ]

    def test_processes_mouse_events(self):
        emitted: list[tuple[str, dict]] = []
        app = SimpleApp(on_emit=lambda k, d: emitted.append((k, d)))

        click = MouseEvent(
            action=MouseAction.PRESS,
            button=MouseButton.LEFT,
            x=2,
            y=1,
            shift=False,
            meta=False,
            ctrl=False,
        )

        harness = TestSurface(app, width=10, height=2, input_queue=[click, "q"])
        frames = harness.run_to_completion()

        assert frames[1].lines[0].rstrip().startswith("m1")
        assert emitted[0][0] == "ui.mouse"
        assert emitted[0][1]["button"] == "LEFT"
        assert emitted[0][1]["x"] == 2


def _get_layers(state: dict) -> tuple[Layer, ...]:
    return state["layers"]


def _set_layers(state: dict, layers: tuple[Layer, ...]) -> dict:
    return {**state, "layers": layers}


def _base_layer() -> Layer:
    def handle(key: str, ls: None, app_state: dict):
        if key == "p":
            return ls, app_state, Push(layer=_modal_layer())
        if key == "q":
            return ls, app_state, Quit()
        return ls, app_state, Stay()

    def render(ls: None, app_state: dict, view):
        view.put_text(0, 0, "BASE", Style(fg="cyan", bold=True))

    return Layer(name="base", state=None, handle=handle, render=render)


def _modal_layer() -> Layer:
    def handle(key: str, ls: None, app_state: dict):
        if key == "b":
            return ls, app_state, Pop()
        if key == "q":
            return ls, app_state, Quit()
        return ls, app_state, Stay()

    def render(ls: None, app_state: dict, view):
        view.put_text(0, 0, "MODAL", Style(fg="red", bold=True))

    return Layer(name="modal", state=None, handle=handle, render=render)


class LayerApp(Surface):
    def __init__(self):
        super().__init__()
        self.state = {"layers": (_base_layer(),)}

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        render_layers(self.state, self._buf, _get_layers)

    def on_key(self, key: str) -> None:
        new_state, should_quit, _ = self.handle_key(key, self.state, _get_layers, _set_layers)
        self.state = new_state
        if should_quit:
            self.quit()


class TestHarnessLayers:
    def test_layer_stack_push_pop_quit(self):
        app = LayerApp()
        harness = TestSurface(app, width=10, height=2, input_queue=["p", "b", "q"])
        frames = harness.run_to_completion()

        assert frames[0].lines[0].startswith("BASE")
        assert frames[1].lines[0].startswith("MODAL")
        assert frames[2].lines[0].startswith("BASE")
        assert frames[3].lines[0].startswith("BASE")
