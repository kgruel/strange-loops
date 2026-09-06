# C2 independent validation — September 6, 2026

## Final validation status

The accepted C2 source is green under the final review state:

* From `libs/engine`: `uv run pytest -q` — **2,550 passed, 1 skipped** in 83.89s.
* From `libs/sdk`: `uv run pytest -q` — **525 passed** in 40.88s.
* From the repository root: `uv run pytest tests/architecture -q` — **101 passed** in 7.07s.
* Package-local scoped Ruff for all changed C2 sources/tests — **clean**.

The final source changes remain operation-specific. The call graph does not
introduce a new engine-wide coordinator framework or require helper reuse across
maintenance, search, and declaration operations: each wrapper records only the
boundary it actually owns, while the SDK serializer consumes the shared shape.
The Fable corrections for absent versus explicit-null context, unsupported
scalar identity omission, and contradictory reversed effects are covered by the
latest focused tests. Final transcripts are in
`/tmp/loops-arrival-c2-2026-09-06/engine-reviewed-final.txt`,
`sdk-reviewed-final.txt`, `architecture-reviewed-final.txt`,
`ruff-engine-reviewed-final.txt`, and `ruff-sdk-reviewed-final.txt`.

Status: implementation validated. Full runs and the final constructor check
are recorded below under Implementation assessment and validation. The initial
audit is retained as historical reasoning; it describes the pre-C2 source.
The validator changed no production or test files.

## Initial audit (before implementation)

The design's central separation is sound: custody completion, derived
maintenance, cache/artifact publication, and dispatch are separate effects.
`ProjectionSyncError` and `SearchIndexSyncError` already retain the target and
before/observed evidence, while `normalize_exception` preserves real Commit
receipts for append outcomes. The existing wrappers catch `Exception`, so
`KeyboardInterrupt` and cancellation retain their identity.

The current source still exhibits the two intended routing gaps:

* `libs/sdk/src/sdk/read.py:1821-1829` calls Arrival `sync_projection` directly.
  A known `ProjectionSyncError` therefore bypasses `normalize_exception`, unlike
  `sync_search_index` at `read.py:1797-1801`. The acceptance test must exercise
  the public `sync_target` path and assert `ProjectionOutcomeUnknown`, with the
  target, projected-before, observed-after, and nested cause retained.
* `libs/sdk/src/sdk/errors.py:87-155` currently serializes stable coordinates
  only. It does not yet emit the proposed bounded `details["evidence"]` or
  causal details. The implementation must keep the legacy
  `details["phase"]` copied at line 101 separate from the new
  `evidence.phase`; use the proposed `coordinator_phase` attribute. A cause
  serializer should prefer an explicit `.cause`, otherwise `__cause__`, stop
  after two causal nodes with an identity cycle guard, cap messages, and avoid
  `__context__` and record payloads.

## Control-boundary checks for implementation

Search has a provable pre-build boundary. Once `_target` succeeds at
`libs/engine/src/engine/arrival_search.py:168-169`, failures from
`query.open_snapshot` (171) or `_search_maintenance_for` (176) occur before
`maintenance.build` (178). The implementation should mark these
`attempt=not-entered, state=not-attempted`; it should flip to
`attempt=entered` immediately before `build`. A failure from `build`, or from
post-build coverage validation, must not be relabeled as a known no-effect
failure. Tests need both snapshot/provider refusal and build failure.

Projection's catch-up wrapper begins at `arrival_maintenance.py:242-243`, so a
failure from `catch_up` or its resulting verification can only claim
`entered/unknown`. Failures before that inner boundary remain ordinary
preparation/refusal errors unless the coordinator adds a separate proven
phase. `_snapshot_state` after a failed catch-up is deliberately best effort
(`:283-294`); `observed_after=None` must remain uncertainty, never a no-write
claim.

The public `sync_target` wrapper should catch and normalize ordinary engine
exceptions for the Arrival branch while preserving cancellation and unmatched
`TypeError`/`ValueError` behavior. The normalizer must remove the unreachable
second `ProjectionSyncError` entry in its generic refusal tuple once the
dedicated projection mapping remains authoritative.

## Acceptance limits

The evidence object must not imply a transaction spanning custody and derived
state. A successful maintainer result with `projected_after` beyond the
requested target proves coverage of that target, not row-level provenance.
Likewise, `ProjectionOutcomeUnknown` must not be serialized as a custody
unknown or as proof that no derived rows changed.

Source C8b evidence remains operation-specific at `details.collection`; it
should not be flattened into a scalar maintenance error. Its paired partial
facts/IDs and earlier durable tiers should survive the shared serializer if
the caller serializes the complete source result.

## Implementation assessment and validation

The settled implementation addresses the two concrete gaps. `sync_target` now
normalizes the Arrival maintenance branch while preserving unchanged
exceptions, and the engine wrappers supply `coordinator_phase` plus resource
effects. Search records `not-entered/not-attempted` until immediately before
`build`; projection records `entered/unknown` around catch-up. The SDK
serializer emits `loops.sdk/evidence/v1`, bounded explicit-cause chains, safe
coordinates, and the legacy top-level `details.phase` separately.

The declaration preparation wrapper now carries `prepare` evidence and
preserves captured/projected coordinates. Its compatibility constructor retains
the former positional `Exception` arguments; three focused regressions cover
that boundary. No custody transaction is implied by any maintenance evidence.

Full package runs were captured before that final constructor-only compatibility
patch:

* From `libs/engine`: `uv run pytest -q` — **2,547 passed, 1 skipped** in 72.97s.
* From `libs/sdk`: `uv run pytest -q` — **523 passed** in 18.87s.
* From the repository root: `uv run pytest tests/architecture -q` — **101 passed** in 6.33s.

Post-patch focused evidence from `libs/engine` is **10 passed** for
`tests/test_arrival_declaration_custody.py`; package-local scoped Ruff passes
for all changed C2 source/tests. The command transcripts are in
`/tmp/loops-arrival-c2-2026-09-06/engine-full.txt`, `sdk-full.txt`,
`architecture-full.txt`, `ruff-engine.txt`, and `ruff-sdk.txt`.

Current source hashes for the frozen review packet:

```text
bcec160590cb9d3d18797e63171e6651dd6118e49077c111ee94d9749a06d8ed  libs/engine/src/engine/arrival_maintenance.py
edbc31f71addca3aa9c23d286c896f9a51ce3c8cb01a63ac3a859c2b7fbf3064  libs/engine/src/engine/arrival_search.py
ac3a0b7ba465dfc1bf247224cda29284cf4ade582c030d7b022d41c99a9c10ce  libs/engine/src/engine/arrival_declarations.py
d956636a83ce14c0ad90f931e19e2f8c3154d31e57c152562422fa32609a9db4  libs/sdk/src/sdk/errors.py
7db73bf6c487abf0f59502b091eedf652a84fd0aaf0bfee0ce5066c50376d161  libs/sdk/src/sdk/read.py
9d93414c51b1d63f720d8e820f52ea4b61dca7c517a2f6eaff8f67c31f67de2d  libs/sdk/tests/test_arrival_evidence.py
4d6256c10353e12116434e8a395a78b123ad164151d4636c5917e170200f9229  libs/engine/tests/test_arrival_maintenance.py
1608a4ef4222fc1686930a3ba8e26645323cb3b310986a6329d6c503c1611367  libs/engine/tests/test_arrival_search.py
fad63d441b6bcae4c9876b2cb9a8e563234047027556553f970deb893927079e  libs/engine/tests/test_arrival_declaration_custody.py
3a6426f58a595b9ce6b6d6e7da212aa2d21455b867b1f89234fe40b79b0f59bb  libs/sdk/tests/test_arrival_search.py
```
