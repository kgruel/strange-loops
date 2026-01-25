"""Layer: modal stacking primitive for input handling and rendering."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Generic, TypeVar

from .buffer import Buffer, BufferView

S = TypeVar("S")  # Layer state type
A = TypeVar("A")  # App state type


@dataclass(frozen=True, slots=True)
class Stay:
    """Keep current layer, input consumed."""

    pass


@dataclass(frozen=True, slots=True)
class Pop:
    """Remove current layer from stack, optionally returning a result."""

    result: Any = None


@dataclass(frozen=True, slots=True)
class Push:
    """Add new layer on top of stack."""

    layer: Layer


@dataclass(frozen=True, slots=True)
class Quit:
    """Signal the app should exit."""

    pass


Action = Stay | Pop | Push | Quit


@dataclass(frozen=True, slots=True)
class Layer(Generic[S]):
    """A layer bundles state, input handling, and rendering for modal stacking.

    - state: layer-local state, created on push, gone on pop
    - handle: (key, layer_state, app_state) -> (layer_state, app_state, action)
    - render: (layer_state, app_state, buffer_view) -> None
    """

    name: str
    state: S
    handle: Callable[[str, S, Any], tuple[S, Any, Action]]
    render: Callable[[S, Any, BufferView], None]


def process_key(
    key: str,
    state: A,
    get_layers: Callable[[A], tuple[Layer, ...]],
    set_layers: Callable[[A, tuple[Layer, ...]], A],
) -> tuple[A, bool, Any]:
    """Process a key through the layer stack (top layer handles).

    Returns: (new_app_state, should_quit, pop_result)
    - should_quit: True if Quit action was returned
    - pop_result: value from Pop(result=...) if layer popped, else None

    get_layers/set_layers allow this to work with any state type that contains layers.
    """
    layers = get_layers(state)
    if not layers:
        return state, False, None

    top = layers[-1]
    new_layer_state, new_app_state, action = top.handle(key, top.state, state)

    # Update the layer in the stack with new state
    updated_top = replace(top, state=new_layer_state)
    updated_layers = (*layers[:-1], updated_top)

    match action:
        case Stay():
            return set_layers(new_app_state, updated_layers), False, None
        case Pop(result=result):
            if len(layers) > 1:  # never pop the base layer
                return set_layers(new_app_state, layers[:-1]), False, result
            return set_layers(new_app_state, updated_layers), False, result
        case Push(layer=new_layer):
            return set_layers(new_app_state, (*updated_layers, new_layer)), False, None
        case Quit():
            return new_app_state, True, None

    return set_layers(new_app_state, updated_layers), False, None


def render_layers(
    state: A,
    buf: Buffer,
    get_layers: Callable[[A], tuple[Layer, ...]],
) -> None:
    """Render layers bottom-to-top into buffer."""
    layers = get_layers(state)
    view = BufferView(buf, 0, 0, buf.width, buf.height)
    for layer in layers:
        layer.render(layer.state, state, view)
