# strange-loops

A system for focusing attention. Observations flow in, accumulate into state,
boundaries resolve, conclusions flow out. The conclusions re-enter as new
observations. The loop closes through the observer.

## The Model

Three shapes:

| Shape | Structure | Question |
|-------|-----------|----------|
| **Fact** | kind + ts + payload + observer | What happened? |
| **Spec** | fields + folds + boundary | How does attention focus? |
| **Tick** | name + ts + payload + origin | What did a period become? |

See [STRANGE-LOOPS.md](STRANGE-LOOPS.md) for the paradigm.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the implementation.

## Setup

```bash
uv sync
```

## Test

```bash
uv run --package atoms pytest libs/atoms/tests
uv run --package engine pytest libs/engine/tests
uv run --package lang pytest libs/lang/tests
uv run --package painted pytest libs/painted/tests
uv run --package store pytest libs/store/tests
```
