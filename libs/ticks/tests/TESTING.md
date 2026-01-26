# Testing Philosophy

## Priority Order

1. **Integration tests first** — test full paths through the system
2. **Fakes over mocks** — stateful, reusable test doubles when needed
3. **Behavior not implementation** — test public API, not internals
4. **Shared fixtures** — common setup in conftest.py
5. **Parametrization** — slim test count, expand case coverage

## Test Structure

```
tests/
├── TESTING.md         # This file
├── conftest.py        # Shared fixtures
├── helpers.py         # Event types, projections, serializers
├── test_integration.py  # Full paths: Stream→Consumer→State
└── test_behavior.py     # Edge cases, error paths
```

## What to Test

**Integration** (test_integration.py):
- Stream emits → Projection folds → state updates
- Stream emits → EventStore appends → events available
- Stream fan-out → multiple consumers receive
- FileWriter writes → Tailer reads back
- EventStore persists → reload preserves events
- Forward bridges typed streams

**Behavior** (test_behavior.py):
- Edge cases: empty inputs, boundary conditions
- Error paths: missing config, invalid cursors
- Resource management: close(), context managers

## What NOT to Test

- That `Stream._taps` is a list
- That `Projection` calls `apply()` internally
- Individual methods in isolation when integration covers them
- Implementation details that could change without affecting behavior

## Anti-Patterns

Avoid these:

```python
# Testing implementation, not behavior
def test_stream_has_taps_list():
    assert hasattr(stream, '_taps')

# Conditional assertions (silent pass)
if exit_code != 0:
    assert False

# Unit test where integration would cover more
def test_projection_apply_called():
    with patch.object(proj, 'apply') as mock:
        ...
```

## Fixtures Philosophy

Fixtures provide building blocks, not pre-wired scenarios.
Tests compose fixtures to express their specific intent.

```python
# Good: fixture provides the tool
@pytest.fixture
def stream() -> Stream[Event]:
    return Stream[Event]()

# Test composes what it needs
async def test_fan_out(stream):
    proj1 = SumProjection(initial=0)
    proj2 = SumProjection(initial=100)
    stream.tap(proj1)
    stream.tap(proj2)
    ...
```

## Coverage

- Target: 100%
- Enforced in CI via `--cov-fail-under=100`
- Exclusions: `TYPE_CHECKING`, `NotImplementedError`, protocol stubs (`...`)

Coverage is a floor, not a ceiling. 100% coverage doesn't mean
the tests are good — but less than 100% means something isn't tested.
