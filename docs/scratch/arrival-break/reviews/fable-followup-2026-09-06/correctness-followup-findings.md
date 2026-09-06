# correctness-followup — Fable review

Effort: low. Finished: 2026-09-06T14:36:30.740682+00:00.
Packet SHA-256: `9c1b587622db1962a55bbe0d5875935784f02bd4beb603648d9d45cfd0458d3b`.

Static reviewer output; findings still require primary triage.

**Result: no High/Medium defects demonstrated in the excerpts. Two Low findings, plus questions.**

## Findings

**1. Low — `recovered` result reports `file_written=True` even when the cache was already published.**
`libs/engine/src/engine/arrival_declarations.py:1308-1313` and `:1345-1348`. When `current == plan.proposed_text.encode()` the branch only cleans artifacts and marks `published`; no bytes are written by this call, yet `_result(..., file_written=True, ...)` is returned unconditionally. Consequence: SDK `DeclarationEditResult.file_written` (`libs/sdk/src/sdk/declare.py:120`) misreports what this recovery did. Repro: interrupt an apply after cache publication but before intent removal, run `recover_declaration`, inspect `file_written`. Fix: thread a boolean from the branch taken.

**2. Low / conditional — `capture_aggregate` takes ownership of a caller-supplied `opened_root`, including on failure.**
`libs/engine/src/engine/arrival_aggregate.py:297-305` closes `opened_root` if `_effective_declaration` raises, and lines 306-309 / 343-346 / `AggregateCapture.close` close it on any later failure or on capture close. `OpenedRead.close` is idempotent, so double-close is safe, but a caller who continues to use `opened_root.snapshot` after `open_aggregate_read` exits (or after a refused capture) gets a closed snapshot. If transfer of ownership is intended, it is undocumented at `open_aggregate_read` (`libs/sdk/src/sdk/aggregate.py:370-388`). Not a demonstrated bug; a contract question.

## What was checked and held up

- **Restore audits** (`arrival_restore.py:195-226, 261-267, 312-314`): row tuple layouts for fact/tick match `plan_ordinary_write` row order and `rows_of_body`; `(ord, seq)` is unique so the sort is stable against the ledger stream; pre-append audit is against `before`, post-append against `selected` with a lagging watermark resolving to `observed`; the `observed.ordinal > through.ordinal` clamp is unreachable on the supported path but harmless. Ahead/forked projections are refused via `head_at` failure or exact row mismatch before `replicate`; post-commit audit failure surfaces as `RestoreForwardIncomplete` with the commit retained and unwitnessed. No synthesized receipt.
- **Declaration anchor audit** (`:157-192`): genesis-absent prefix requires a null anchor; adopted prefix requires exact genesis row equality; identity checks via `validate_arrival_declaration_anchor`.
- **Consumer** (`arrival_consumer.py:140-215`): continuation keeps the original captured/represented basis, validates both by full hash, rejects generation change, absent projection, and regression below the token prefix; every reported watermark is membership-checked.
- **Boundary consumption** (`vertex.py:1266-1283`): tick edge and fact key both go through microsecond rounding; the parametrized 4.0000004/4.0000006 test cases resolve correctly on both sides of round-to-nearest; same-time earlier ordinal is consumed, later ordinal eligible, earlier-ts late fact excluded, future fact eligible. Fact `ts` is left as REAL.
- **Recovery** (`arrival_declarations.py:508-590, 1243-1348`): basis requires `projected_through == captured`; predecessor and exact suffix verified by full hash / record match; no new Commit; `changes=None`; SDK serializes basis via `asdict`.
- **Aggregate**: descriptor nodes expand from the adopted effective declaration, storeless from local AST; overlay vs member selection is consistent between `streams` and `_eligible_members`; repeated occurrences keyed by full path.

## Remaining uncertainty (questions, not findings)

- Whether `ProjectionBehind` and `AtomicLimitExceeded` raised inside `prepare_declaration_edit`'s try (`:855-858`) subclass `DeclarationPreparationError`; otherwise they are rewrapped as `DeclarationPreparationRefused` at `:898-901`, losing the typed signal.
- Whether a snapshot with `represented is None` can still return fact rows; if so, `_audit_projection` returns at `:211-212` without auditing them.
- Whether `documents_to_vertex` preserves `combine`/`discover` so `_detached(local_ast)` at `arrival_aggregate.py:294` keeps storeless topology (the two-member composition test suggests yes).
- Whether the raw ledger from `_open_components` or the `AttestedLedger` wrapper `actual` needs its own close (`arrival_restore.py:306-311, 323-327`).
