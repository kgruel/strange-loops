# engine

Temporal infrastructure and identity.

Consolidates:
- **ticks**: `Tick`, `Vertex`, `Store`, `Stream`, `Projection` — temporal primitives
- **peers**: `Peer`, `Grant` — identity and policy

## Usage

```python
from engine import Tick, Vertex, Peer, Grant

# Create a vertex
v = Vertex("main")
v.register("count", 0, lambda s, p: s + 1)

# Define identity with permissions
peer = Peer("alice", potential=frozenset({"count"}))
```
