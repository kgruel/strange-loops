# TUI Core: Surface and Layers

Interactive painted apps are built from:

- `Surface`: owns the terminal lifecycle and buffer diff loop
- `Layer`: a modal stack primitive for input routing and render ordering

See also:
- `docs/ARCHITECTURE.md`: input/render flow diagrams (`../ARCHITECTURE.md`)
- `docs/DATA_PATTERNS.md`: frozen state + pure functions (`../DATA_PATTERNS.md`)

---

## Surface

`Surface` is the async event loop wrapper (alt-screen, keyboard/mouse input, dirty rendering, resize handling).

<!-- docgen:begin py:painted.app:Surface#signature -->
```python
class Surface:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.app:Surface.run#signature -->
```python
    async def run(self) -> None:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.app:Surface.handle_key#signature -->
```python
    def handle_key(
        self,
        key: str,
        state: Any,
        get_layers: Callable[[Any], tuple[Layer, ...]],
        set_layers: Callable[[Any, tuple[Layer, ...]], Any],
    ) -> tuple[Any, bool, Any]:
```
<!-- docgen:end -->

## Layer stack

Layers model “modal scopes” (help overlay, search overlay, confirmation dialog). Input routes **top-down**; render paints **bottom-up**.

<!-- docgen:begin py:painted.layer:Layer#definition -->
```python
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
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.layer:process_key#signature -->
```python
def process_key(
    key: str,
    state: A,
    get_layers: Callable[[A], tuple[Layer, ...]],
    set_layers: Callable[[A, tuple[Layer, ...]], A],
) -> tuple[A, bool, Any]:
```
<!-- docgen:end -->

<!-- docgen:begin py:painted.layer:render_layers#signature -->
```python
def render_layers(
    state: A,
    buf: Buffer,
    get_layers: Callable[[A], tuple[Layer, ...]],
) -> None:
```
<!-- docgen:end -->

---

## Pattern: app owns state, layers are pure

The intended shape:

- App state: immutable dataclass containing all UI state (including `layers`)
- Layers: `(key, layer_state, app_state) -> (layer_state, app_state, action)`
- Rendering: layer paints into a `BufferView` derived from the app buffer

This keeps “what the UI is” (state) separate from “how it runs” (Surface) and “how it routes” (layers).
