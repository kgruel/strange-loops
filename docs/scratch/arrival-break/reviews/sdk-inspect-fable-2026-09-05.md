# SDK Arrival inspection Fable review — queued 2026-09-05

The static full-source review packet is prepared at
`/tmp/loops-arrival-review/sdk-inspect-fable-prompt.txt`. It includes the
complete inspection DTO, Arrival/legacy resolver, document fingerprint helper,
real temporary Arrival regression file, and minimalCLI dispatch seam.

Fable invocation is deliberately queued until the stated 21:20 CDT quota
reset. It must use the verified static command with safe mode, tools disabled,
no session persistence, JSON output, `claude-fable-5-1[1m]`, and the prompt's
maximum 1,000 words/five findings. The raw result should be written to
`/tmp/loops-arrival-review/sdk-inspect-fable-result.json`, then this receipt
must record modelUsage, dispositions, fixes, and rerun evidence.

Local validation before review:

- `libs/sdk`: `uv run --package sdk pytest tests -q` — 408 passed in 12.74s.
- `apps/loops-min`: `uv run --package loops-min pytest tests -q` — 6 passed in
  2.79s.
- repository root: `uv run pytest tests/architecture -q` — 101 passed in
  5.12s.
- `libs/sdk`: scoped Ruff for inspection DTO/resolver/tests — passed.
