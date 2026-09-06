# Post-review assertion validation

Only two assertions were added to the existing parametrized opaque-root test
after Fable's frozen review: local status is drifted, and local/effective
fingerprints differ. Production did not change.

Observed execution from `libs/sdk`:

```text
uv run pytest -q tests/test_arrival_inspect_contract.py
.....                                                                    [100%]
5 passed in 0.21s

uv run ruff check tests/test_arrival_inspect_contract.py
All checks passed!
```

The full SDK 559 / architecture 101 results in the frozen packet precede this
assertion-only change. No additional behavior or production code was added.
