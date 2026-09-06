# C3 continuation independent validation — September 6, 2026

Status: final source audit and owner-freeze validation complete. The current
tree passed the owning package, SDK, architecture, and scoped lint checks. No
live stores were opened by this audit and no source or test files were edited.

## Contract traced

`Continuation` is an in-memory value carrying the exact full captured custody
head H, projected full head P, facts request, page cursor, and derived-view
generation (`libs/engine/src/engine/arrival_contract.py:348-362`).
`OpenedRead.continuation` refuses an unrepresented projection or absent
generation and copies the current basis H/P into the token
(`libs/engine/src/engine/arrival_consumer.py:69-93`).

On resume, `open_read` resolves both token heads through `ledger.head_at` and
requires each returned full head to equal the token value
(`arrival_consumer.py:111-163`). It then opens the bounded snapshot, validates
the declaration anchor and watermark, and runs the watermark through
`complete_projection_custody` (`arrival_consumer.py:165-197`). A current
snapshot/custody contradiction now uses `HeadMismatch` unconditionally:
foreign lineage remains `NotAuthority`, while a returned same-height hash or
coordinate that contradicts custody is `HeadMismatch`. Token H/P resolution,
generation, disappearance, and projected-prefix regression retain their
`InvalidContinuation` rules. Backend exceptions raised by `head_at` pass
through unchanged; the implementation does not relabel every token or
membership failure as `InvalidContinuation`.

The five focused negative cases cover foreign lineage, a missing/raw backend
prefix refusal, same-coordinate hash substitution, a wrong coordinate, and a
wrong-lineage coordinate (`libs/engine/tests/test_arrival_consumer.py:466-570`).
Existing cases additionally cover projection disappearance, generation changes
and CURRENT refusal of a token issued from a behind projection. Source tracing
also confirms that the unchanged prefix-regression and request-equality checks
remain in place; this pass adds no dedicated regression for those branches.
A custody-vouched
projection advance beyond H is accepted while the returned read basis retains
the token H/P (`test_arrival_consumer.py:571-633`).

The file query snapshot uses the continuation's projected-through head P as
its row bound when resuming (`libs/engine/src/engine/arrival_file_backend.py:926-961`),
which is deliberately P rather than H when P < H. Facts request validation
uses structural equality (`request != continuation.request`), not object
identity (`arrival_file_backend.py:1117-1123`). This preserves a page's
continuation boundary across later appends. The SDK integration appends and
synchronizes later rows between pages, then verifies that resumed reads retain
the original basis and exclude those rows while a fresh read sees them
(`libs/sdk/tests/test_arrival_read.py:614-650`).

## Independent acceptance and limits

The current implementation closes the previously identified gap: a resumed
snapshot cannot silently accept an unverified returned watermark coordinate.
The helper validates watermark lineage, resolves custody membership, checks
the returned coordinate, and compares the full hash at the captured height.
It does not audit every projection row; same-generation projection content is
trusted under the query adapter's view-generation contract. Continuation
tokens remain process-local. Valid projection advancement and the original
H/P token basis are intentionally separate from the current snapshot's
watermark. Raw adapter `head_at` refusal identity is preserved.

Sol's pre-fix proof was run in an isolated copy whose consumer bytes match
`git show bacaeb96:libs/engine/src/engine/arrival_consumer.py` (SHA256
`7ade5e7a10110bcbad033a70e3e40976879c46c7cd32ab690d9d594809b50a20`): the
focused probe reported 3 failed and 2 passed, with 26 deselected. This is
agent-reported baseline evidence; no live store was used here. The current
focused continuation set passed 31 tests according to the owner handoff.

## Final validation evidence

Commands were run from the package directories as required:

* `cd libs/engine && uv run pytest -q` — **2568 passed, 1 skipped** in
  156.81s. Log: `/tmp/loops-arrival-c3-continuation-2026-09-06/engine-full.txt`.
* `cd libs/sdk && uv run pytest -q` — **540 passed** in 49.45s. Log:
  `/tmp/loops-arrival-c3-continuation-2026-09-06/sdk-full.txt`.
* `uv run pytest tests/architecture -q` from the worktree root — **101
  passed** in 8.75s. Log:
  `/tmp/loops-arrival-c3-continuation-2026-09-06/architecture-full.txt`.
* `cd libs/engine && uv run ruff check src/engine/arrival_consumer.py tests/test_arrival_consumer.py` — **All checks passed!** Log:
  `/tmp/loops-arrival-c3-continuation-2026-09-06/ruff-engine.txt`.
* `cd libs/sdk && uv run ruff check tests/test_arrival_read.py` — **All checks
  passed!** Log: `/tmp/loops-arrival-c3-continuation-2026-09-06/ruff-sdk.txt`.

The before/after hashes are identical, confirming no post-run mutation of the
three scoped files:

```
9bbbafef0b17614ec945d5565fd71c0306ad7459c1d167360205e930dbd2ddc4  libs/engine/src/engine/arrival_consumer.py
fc56f8db3f2150310043eae9f4c503971b94b0956fc11498bb44e566f1d7db90  libs/engine/tests/test_arrival_consumer.py
7640514ca302eb0bada0135092c93b3ac1364c9619521d65e11f7d72958206a7  libs/sdk/tests/test_arrival_read.py
```

The continuation hardening has no actionable supported-path blocker in this
audit. The remaining limits are the intentional process-local token boundary,
adapter-defined projection contents, and backend-specific refusal semantics.
