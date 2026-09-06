# Consistency slice 1 validation — 2026-09-06

This is an independent validation of C3 (custody-completed projection basis) and
C8a (unchanged initializer exception propagation) in the shared Arrival worktree.
No live stores, keys, commits, or staging were used.

## Source checks

`engine.arrival_head_seam.complete_projection_custody` is the shared narrow seam
(at `arrival_head_seam.py:945`). It checks projection lineage before custody
lookup, resolves the exact `Watermark` through `head_at`, rejects a returned head
with a different lineage or ordinal, rejects a same-height hash different from
captured H, and clamps a legitimately advanced prefix back to captured H. The
backend exception from `head_at` remains the evidence/refusal supplied by the
adapter.

The seam is used by fresh `arrival_consumer.open_read` (`arrival_consumer.py:192`),
ordinary and batch runtime capture (`runtime_write.py:698` and `:989`), and
`prepare_declaration_edit` (`arrival_declarations.py:864`). Declaration preparation
now validates an above-H watermark through custody before retaining H as its
bounded basis. Continuation resume intentionally retains its separate token and
view-generation checks; it is not silently widened into the fresh-open path.

C8a in `sdk/declare.py:632-639` preserves an already-normalized exception with a
bare `raise`, avoiding a self-cause. The initializer tests cover both an unmapped
exception retaining its original cause and a `KeyboardInterrupt` retaining object
identity with no cause.

## Commands and results

- `uv run pytest libs/engine/tests/test_arrival_consumer.py libs/engine/tests/test_arrival_declaration_custody.py libs/engine/tests/test_runtime_write.py libs/sdk/tests/test_arrival_init.py libs/sdk/tests/test_verify.py -q` — **72 passed**.
- From `/Users/kaygee/Code/loops-wt/arrival-finish/libs/engine`, `uv run pytest -q` — **2528 passed, 1 skipped** (Sol's final run). Exact stdout for the preceding 2524-test run is retained at `/tmp/loops-arrival-consistency-slice1-2026-09-06/engine-final.txt`; the final three-case interleaving check below ran after the additional tests landed.
- `uv run pytest libs/sdk/tests -q` — **497 passed** (Terra's final run).
- `uv run pytest tests/architecture -q` — **101 passed**.

The SDK and architecture runs were performed after the shared C3 helper and its
callers were present. The final engine rerun above additionally includes the
later engine-side custody regression file.

The focused local initializer check `uv run pytest tests/test_arrival_init.py -q` from
`/Users/kaygee/Code/loops-wt/arrival-finish/libs/sdk` passed **11**. The final
engine interleaving check was run from the engine package directory with
`uv run pytest tests/test_arrival_projection_custody_integration.py tests/test_arrival_consumer.py -k 'wrong_coordinate or real_file_projection_advance_after_capture_is_vouched_and_bounded' -q`:
**3 passed, 25 deselected**.

The focused declaration cases cover a valid projection advance, foreign lineage,
missing above-H prefix, same-height hash substitution, and wrong-coordinate
custody output; invalid cases refuse before signing/scanning and close snapshot,
query, and ledger resources. Runtime cases cover the same refusal classes and
valid advance clamp.

No actionable C3/C8a defect remains in the inspected supported fresh-open,
runtime-capture, declaration-preparation, or initializer paths. The continuation
branch remains deliberately separate by contract. C2 outcome normalization and
C8b collector ownership are outside this slice.
