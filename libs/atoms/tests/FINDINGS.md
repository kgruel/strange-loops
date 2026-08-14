# Property Test Findings: `libs/atoms`

## FINDING-1: `Fact.__hash__` violates hash contract for equal facts with dict payloads

- **Invariant Violated**: Python object model hash invariant: if `f1 == f2`, then `hash(f1) == hash(f2)`. Equal `Fact` instances must hash to the same value and deduplicate when placed in a `set` or used as `dict` keys.
- **Source Location**: `libs/atoms/src/atoms/fact.py:90-94` (`Fact.__hash__`):
  ```python
  def __hash__(self):
      try:
          return hash((self.kind, self.ts, self.payload, self.observer, self.origin))
      except TypeError:
          return hash((self.kind, self.ts, id(self.payload), self.observer, self.origin))
  ```
- **Root Cause**: `Fact.__init__` wraps dictionary payloads in `MappingProxyType` to provide immutability. In Python, `MappingProxyType` is unhashable (`TypeError: unhashable type: 'mappingproxy'`). The `except TypeError:` fallback hashes `id(self.payload)` (the memory address of the mapping proxy object). Consequently, two distinct but value-equal `Fact` objects have different `id(self.payload)` values and thus produce different hash values.
- **Minimal Reproducing Example**:
  ```python
  from atoms import Fact

  f1 = Fact(kind="heartbeat", ts=0.0, payload={"x": 1}, observer="alice", origin="")
  f2 = Fact(kind="heartbeat", ts=0.0, payload={"x": 1}, observer="alice", origin="")

  assert f1 == f2                # Passes: facts are equal
  assert hash(f1) == hash(f2)    # FAILS: hashes differ (e.g. 7261765691127057509 != 6590615651478372814)
  assert len({f1, f2}) == 1      # FAILS: set contains 2 elements instead of deduplicating to 1
  ```
