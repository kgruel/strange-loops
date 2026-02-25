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

```python
# Each component follows the same pattern:
# 1. Immutable state dataclass
# 2. Pure render function: state -> Block

@dataclass(frozen=True)
class SpinnerState:
    frame: int = 0
    frames: tuple[str, ...] = DOTS

    def tick(self) -> "SpinnerState":
        return replace(self, frame=(self.frame + 1) % len(self.frames))

def spinner(state: SpinnerState, style: Style = Style()) -> Block:
    char = state.frames[state.frame]
    return Block.text(char, style)
```
