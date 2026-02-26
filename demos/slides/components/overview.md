---
id: components
title: Components
group: components
order: 1
align: center
---

# Components

[spacer]

[zoom:0]

stateful widgets: `spinner`, `progress`, `list`, `text input`

[spacer]

[demo:spinner]

[spacer]

state is **immutable** - methods return new instances

[spacer]

↓ for interactive examples

[zoom:1]

the component pattern: `State` + `render()`

[spacer]

<!-- docgen:begin py:painted._components.spinner:SpinnerState#definition -->
```python
@dataclass(frozen=True)
class SpinnerState:
    """Immutable spinner state tracking current frame."""

    frame: int = 0
    frames: SpinnerFrames = DOTS

    def tick(self) -> SpinnerState:
        """Advance to the next frame, wrapping around."""
        cursor = Cursor(index=self.frame, count=len(self.frames.frames), mode=CursorMode.WRAP).next()
        return replace(self, frame=cursor.index)
```
<!-- docgen:end -->

<!-- docgen:begin py:painted._components.spinner:spinner#signature -->
```python
def spinner(
    state: SpinnerState,
    *,
    style: Style | None = None,
    icons: "IconSet | None" = None,
) -> Block:
```
<!-- docgen:end -->
