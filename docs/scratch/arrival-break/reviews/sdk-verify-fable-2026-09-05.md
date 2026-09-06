# SDK Arrival verification Fable review — queued 2026-09-05

The static full-source review packet is ready at
`/tmp/loops-arrival-review/sdk-verify-fable-prompt.txt`. It includes the full
verification operation and DTO, FileLedger `Full` implementation, real SDK and
engine prefix tests, and minimalCLI wiring.

The Fable invocation remains queued until the stated quota reset. It must use
safe mode, disabled tools, no session persistence, JSON output, model
`claude-fable-5-1[1m]`, and the packet's 1,000-word/five-finding cap. Save its
raw result to `/tmp/loops-arrival-review/sdk-verify-fable-result.json`; then
record model usage, dispositions, fixes, and rerun evidence here.

Local evidence before review:

- `libs/engine`: `uv run --package engine pytest tests/test_arrival_contract.py -k 'full_verification' -q` — 3 passed, 29 deselected.
- `libs/sdk`: `uv run --package sdk pytest tests/test_verify.py -q` — 4 passed.
- `libs/sdk`: scoped Ruff for `verify.py`, DTO/export, and tests — passed.
- `apps/loops-min`: `uv run --package loops-min pytest tests -q` — 6 passed; scoped Ruff — passed.
- Full SDK suite currently reports 403 passed, 14 failed. Every failure is in pre-existing/concurrent Arrival emit and preview tests, caused by `runtime_write.capture_runtime` calling `copy.deepcopy` on frozen `lang.ast.FoldCollect`; none reaches `verify_target`.
- Architecture suite currently reports 100 passed, 1 failed: `libs/sdk/tests/test_arrival_init.py` imports undeclared `ulid`, unrelated to this slice.

## Pagination and bounded-explicit-target supplement — queued

`/tmp/loops-arrival-review/sdk-pagination-fable-supplement-prompt.txt` contains
the complete changed file snapshot paging code, real engine and SDK paging
tests, verification prefix guard/normalization, and the amended query design.
It uses the same safe-mode, tools-disabled, no-persistence JSON invocation and
1,000-word/five-finding limit as the main queued review.

Supplemental local validation:

- `libs/engine`: `uv run --package engine pytest tests/test_arrival_consumer.py tests/test_arrival_contract.py -k 'not full_verification_stops_at_its_captured_prefix' -q` — 50 passed, 1 deselected; scoped Ruff passed.
- `libs/sdk`: `uv run --package sdk pytest tests/test_arrival_read.py tests/test_verify.py -q` — 25 passed; scoped Ruff passed.
- `apps/loops-min`: `uv run --package loops-min pytest tests/test_cli.py -q` — 6 passed; scoped Ruff passed.
