# Post-review inline-parameter validation

Worktree: `/Users/kaygee/Code/loops-wt/arrival-finish`.

This evidence records commands already run after adding the inline literal
parameter regression. No command was rerun for this receipt.

| Command | Observed result |
| --- | --- |
| `uv run --package sdk pytest libs/sdk/tests/test_arrival_boundary_continuity.py -q` | `6 passed in 0.60s` |
| `uv run --package sdk ruff check libs/sdk/tests/test_arrival_boundary_continuity.py` | `All checks passed!` |
| `uv run --package sdk pytest libs/sdk/tests -q` | `546 passed in 23.98s` |
| `git diff --check -- libs/sdk/src/sdk/kind.py libs/sdk/tests/test_arrival_boundary_continuity.py` | no output; success |

The new real-store test writes an inline template row, then asserts the exact
serializer shape before declaring it:

```python
source_document["payload"]["params"] == [
    {"values": {"kind": "inline_generated"}}
]
```

The production serializer is
`libs/lang/src/lang/document.py::_template_source_to_payload`; it emits
`"params": [_source_params_to_json(sp) for sp in t.params]`, and
`_source_params_to_json` stores each row under `"values"`. The C6 analyzer
reads that same shape in
`libs/engine/src/engine/arrival_boundary_continuity.py::_namespace`.
