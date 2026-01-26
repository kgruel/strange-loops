# facts

Fact: the observation atom — what happened, when.

```python
from facts import Fact

# Factory — auto-timestamps, dict payload
f = Fact.of("heartbeat", service="api", latency=42)

# Direct construction — any payload type
f = Fact(kind="deploy", ts=datetime.now(timezone.utc), payload="v2.1.0")

# Serialization round-trip
d = f.to_dict()
f2 = Fact.from_dict(d)

# Kind predicate
f.is_kind("deploy", "rollback")  # True if kind matches any
```

## The atom

```
Fact[T]
 ├─ kind: str        # open routing key ("heartbeat", "deploy", etc.)
 ├─ ts: datetime     # when observed (timezone-aware)
 └─ payload: T       # the details — Shape knows the structure
```

Kind is an open string. No enum, no constrained set. Structure comes from Shape, not from kind.

Dict payloads are wrapped in `MappingProxyType` for immutability (same pattern as Fold.props in shapes).
