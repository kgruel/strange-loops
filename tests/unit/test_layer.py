"""Tests for Layer primitive and helper functions."""

from dataclasses import dataclass, replace

import pytest

from painted.tui import Buffer, BufferView, Layer, Stay, Pop, Push, Quit, Action, process_key, render_layers


@dataclass
class AppState:
    """Test state with layers and a counter."""

    layers: tuple[Layer, ...]
    counter: int = 0


def get_layers(state: AppState) -> tuple[Layer, ...]:
    return state.layers


def set_layers(state: AppState, layers: tuple[Layer, ...]) -> AppState:
    return replace(state, layers=layers)


class TestActionTypes:
    """Tests for action type immutability."""

    def test_stay_frozen(self):
        """Stay is frozen."""
        s = Stay()
        with pytest.raises((AttributeError, TypeError)):
            s.x = 1  # type: ignore

    def test_pop_frozen(self):
        """Pop is frozen."""
        p = Pop()
        with pytest.raises((AttributeError, TypeError)):
            p.x = 1  # type: ignore

    def test_pop_has_result_field(self):
        """Pop has an optional result field."""
        p = Pop()
        assert p.result is None

        p2 = Pop(result="selected_item")
        assert p2.result == "selected_item"

    def test_push_frozen(self):
        """Push is frozen."""
        layer = Layer(
            name="test",
            state=None,
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=lambda ls, app, v: None,
        )
        p = Push(layer=layer)
        with pytest.raises((AttributeError, TypeError)):
            p.x = 1  # type: ignore

    def test_quit_frozen(self):
        """Quit is frozen."""
        q = Quit()
        with pytest.raises((AttributeError, TypeError)):
            q.x = 1  # type: ignore

    def test_layer_frozen(self):
        """Layer is frozen."""
        layer = Layer(
            name="test",
            state=None,
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=lambda ls, app, v: None,
        )
        with pytest.raises((AttributeError, TypeError)):
            layer.name = "other"  # type: ignore

    def test_layer_has_state_field(self):
        """Layer has a state field."""
        layer = Layer(
            name="test",
            state={"foo": "bar"},
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=lambda ls, app, v: None,
        )
        assert layer.state == {"foo": "bar"}


class TestProcessKeyStay:
    """Tests for Stay action behavior."""

    def test_stay_keeps_layer_returns_new_state(self):
        """Stay action keeps the layer and returns the new state."""

        def handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, replace(app_state, counter=app_state.counter + 1), Stay()

        layer = Layer(name="base", state=None, handle=handle, render=lambda ls, app, v: None)
        state = AppState(layers=(layer,), counter=0)

        new_state, should_quit, result = process_key("x", state, get_layers, set_layers)

        assert new_state.counter == 1
        assert len(new_state.layers) == 1
        assert new_state.layers[0].name == "base"
        assert should_quit is False
        assert result is None

    def test_stay_with_empty_layers(self):
        """Stay with no layers returns state unchanged."""
        state = AppState(layers=(), counter=5)
        new_state, should_quit, result = process_key("x", state, get_layers, set_layers)
        assert new_state.counter == 5
        assert len(new_state.layers) == 0
        assert should_quit is False
        assert result is None


class TestProcessKeyPop:
    """Tests for Pop action behavior."""

    def test_pop_removes_top_layer(self):
        """Pop action removes top layer from stack."""

        def base_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, app_state, Stay()

        def modal_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, replace(app_state, counter=99), Pop()

        base = Layer(name="base", state=None, handle=base_handle, render=lambda ls, app, v: None)
        modal = Layer(name="modal", state=None, handle=modal_handle, render=lambda ls, app, v: None)
        state = AppState(layers=(base, modal), counter=0)

        new_state, should_quit, result = process_key("q", state, get_layers, set_layers)

        assert new_state.counter == 99
        assert len(new_state.layers) == 1
        assert new_state.layers[0].name == "base"
        assert should_quit is False
        assert result is None

    def test_pop_does_not_remove_base_layer(self):
        """Pop action does not remove the last (base) layer."""

        def handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, replace(app_state, counter=42), Pop()

        base = Layer(name="base", state=None, handle=handle, render=lambda ls, app, v: None)
        state = AppState(layers=(base,), counter=0)

        new_state, should_quit, result = process_key("q", state, get_layers, set_layers)

        # State is updated but layer remains
        assert new_state.counter == 42
        assert len(new_state.layers) == 1
        assert new_state.layers[0].name == "base"
        assert should_quit is False
        assert result is None

    def test_pop_with_result(self):
        """Pop action can return a result value."""

        def modal_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, app_state, Pop(result="selected_item")

        def base_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, app_state, Stay()

        base = Layer(name="base", state=None, handle=base_handle, render=lambda ls, app, v: None)
        modal = Layer(name="modal", state=None, handle=modal_handle, render=lambda ls, app, v: None)
        state = AppState(layers=(base, modal), counter=0)

        new_state, should_quit, result = process_key("enter", state, get_layers, set_layers)

        assert len(new_state.layers) == 1
        assert new_state.layers[0].name == "base"
        assert should_quit is False
        assert result == "selected_item"


class TestProcessKeyPush:
    """Tests for Push action behavior."""

    def test_push_adds_new_layer(self):
        """Push action adds a new layer on top of the stack."""

        def modal_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, app_state, Stay()

        modal = Layer(name="modal", state=None, handle=modal_handle, render=lambda ls, app, v: None)

        def base_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, replace(app_state, counter=10), Push(layer=modal)

        base = Layer(name="base", state=None, handle=base_handle, render=lambda ls, app, v: None)
        state = AppState(layers=(base,), counter=0)

        new_state, should_quit, result = process_key("m", state, get_layers, set_layers)

        assert new_state.counter == 10
        assert len(new_state.layers) == 2
        assert new_state.layers[0].name == "base"
        assert new_state.layers[1].name == "modal"
        assert should_quit is False
        assert result is None

    def test_top_layer_handles_next_key(self):
        """After Push, the new top layer handles subsequent keys."""

        def modal_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, replace(app_state, counter=app_state.counter + 100), Stay()

        modal = Layer(name="modal", state=None, handle=modal_handle, render=lambda ls, app, v: None)

        def base_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            if key == "m":
                return None, app_state, Push(layer=modal)
            return None, replace(app_state, counter=app_state.counter + 1), Stay()

        base = Layer(name="base", state=None, handle=base_handle, render=lambda ls, app, v: None)
        state = AppState(layers=(base,), counter=0)

        # Push modal
        state, _, _ = process_key("m", state, get_layers, set_layers)
        assert len(state.layers) == 2

        # Now modal handles
        state, _, _ = process_key("x", state, get_layers, set_layers)
        assert state.counter == 100


class TestProcessKeyQuit:
    """Tests for Quit action behavior."""

    def test_quit_signals_should_quit(self):
        """Quit action returns should_quit=True."""

        def handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            if key == "q":
                return None, app_state, Quit()
            return None, app_state, Stay()

        layer = Layer(name="base", state=None, handle=handle, render=lambda ls, app, v: None)
        state = AppState(layers=(layer,), counter=0)

        new_state, should_quit, result = process_key("q", state, get_layers, set_layers)

        assert should_quit is True
        assert result is None

    def test_quit_from_modal_layer(self):
        """Quit from a modal layer also signals should_quit."""

        def base_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, app_state, Stay()

        def modal_handle(key: str, layer_state: None, app_state: AppState) -> tuple[None, AppState, Action]:
            return None, app_state, Quit()

        base = Layer(name="base", state=None, handle=base_handle, render=lambda ls, app, v: None)
        modal = Layer(name="modal", state=None, handle=modal_handle, render=lambda ls, app, v: None)
        state = AppState(layers=(base, modal), counter=0)

        new_state, should_quit, result = process_key("q", state, get_layers, set_layers)

        assert should_quit is True


class TestLayerState:
    """Tests for layer state threading."""

    def test_layer_state_is_threaded_through_handle(self):
        """Layer state is passed to handle and updated in the layer."""

        def handle(key: str, layer_state: int, app_state: AppState) -> tuple[int, AppState, Action]:
            # Increment layer state on each key
            return layer_state + 1, app_state, Stay()

        layer = Layer(name="counter", state=0, handle=handle, render=lambda ls, app, v: None)
        state = AppState(layers=(layer,), counter=0)

        # First key
        state, _, _ = process_key("a", state, get_layers, set_layers)
        assert state.layers[0].state == 1

        # Second key
        state, _, _ = process_key("b", state, get_layers, set_layers)
        assert state.layers[0].state == 2

        # Third key
        state, _, _ = process_key("c", state, get_layers, set_layers)
        assert state.layers[0].state == 3

    def test_layer_state_independent_of_app_state(self):
        """Layer state and app state are updated independently."""

        def handle(key: str, layer_state: dict, app_state: AppState) -> tuple[dict, AppState, Action]:
            new_layer_state = {**layer_state, "count": layer_state.get("count", 0) + 1}
            new_app_state = replace(app_state, counter=app_state.counter + 10)
            return new_layer_state, new_app_state, Stay()

        layer = Layer(name="test", state={}, handle=handle, render=lambda ls, app, v: None)
        state = AppState(layers=(layer,), counter=0)

        state, _, _ = process_key("x", state, get_layers, set_layers)

        assert state.layers[0].state == {"count": 1}
        assert state.counter == 10

    def test_pushed_layer_has_its_own_state(self):
        """A pushed layer starts with its own initial state."""

        def modal_handle(key: str, layer_state: str, app_state: AppState) -> tuple[str, AppState, Action]:
            return layer_state + "!", app_state, Stay()

        modal = Layer(name="modal", state="hello", handle=modal_handle, render=lambda ls, app, v: None)

        def base_handle(key: str, layer_state: int, app_state: AppState) -> tuple[int, AppState, Action]:
            if key == "m":
                return layer_state, app_state, Push(layer=modal)
            return layer_state + 1, app_state, Stay()

        base = Layer(name="base", state=0, handle=base_handle, render=lambda ls, app, v: None)
        state = AppState(layers=(base,), counter=0)

        # Modify base state
        state, _, _ = process_key("x", state, get_layers, set_layers)
        assert state.layers[0].state == 1

        # Push modal
        state, _, _ = process_key("m", state, get_layers, set_layers)
        assert len(state.layers) == 2
        assert state.layers[0].state == 1  # base unchanged
        assert state.layers[1].state == "hello"  # modal has its own state

        # Modify modal state
        state, _, _ = process_key("x", state, get_layers, set_layers)
        assert state.layers[1].state == "hello!"


class TestRenderLayers:
    """Tests for render_layers function."""

    def test_renders_layers_in_order(self):
        """render_layers calls each layer's render in bottom-to-top order."""
        render_order: list[str] = []

        def make_render(name: str):
            def render(layer_state, app_state: AppState, view: BufferView) -> None:
                render_order.append(name)

            return render

        layer1 = Layer(
            name="layer1",
            state=None,
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=make_render("layer1"),
        )
        layer2 = Layer(
            name="layer2",
            state=None,
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=make_render("layer2"),
        )
        layer3 = Layer(
            name="layer3",
            state=None,
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=make_render("layer3"),
        )

        state = AppState(layers=(layer1, layer2, layer3))
        buf = Buffer(10, 5)

        render_layers(state, buf, get_layers)

        assert render_order == ["layer1", "layer2", "layer3"]

    def test_renders_to_buffer_view(self):
        """render_layers passes a BufferView covering the full buffer."""
        captured_view: list[BufferView] = []

        def capture_render(layer_state, app_state: AppState, view: BufferView) -> None:
            captured_view.append(view)

        layer = Layer(
            name="test",
            state=None,
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=capture_render,
        )
        state = AppState(layers=(layer,))
        buf = Buffer(20, 10)

        render_layers(state, buf, get_layers)

        assert len(captured_view) == 1
        assert captured_view[0].width == 20
        assert captured_view[0].height == 10

    def test_empty_layers_no_render(self):
        """render_layers with no layers does nothing."""
        state = AppState(layers=())
        buf = Buffer(10, 5)

        # Should not raise
        render_layers(state, buf, get_layers)

    def test_render_receives_layer_state(self):
        """render_layers passes the layer's state to its render function."""
        captured_states: list = []

        def capture_render(layer_state, app_state: AppState, view: BufferView) -> None:
            captured_states.append(layer_state)

        layer = Layer(
            name="test",
            state={"key": "value"},
            handle=lambda k, ls, app: (ls, app, Stay()),
            render=capture_render,
        )
        state = AppState(layers=(layer,))
        buf = Buffer(10, 5)

        render_layers(state, buf, get_layers)

        assert len(captured_states) == 1
        assert captured_states[0] == {"key": "value"}
