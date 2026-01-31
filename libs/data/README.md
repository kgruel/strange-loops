# data

Observation atoms, contracts, and ingress.

Consolidates:
- **facts**: `Fact` — the observation atom
- **specs**: `Spec`, `Field`, `Fold` ops, `Parse` ops — contracts
- **sources**: `Source`, `Runner` — ingress adapters

## Usage

```python
from data import Fact, Spec, Source

# Create an observation
f = Fact.of("heartbeat", "alice", service="api", latency=42)

# Define a contract
spec = Spec(name="health", about="Service health", ...)

# Configure ingress
source = Source(command="uptime", kind="system", observer="monitor")
```
