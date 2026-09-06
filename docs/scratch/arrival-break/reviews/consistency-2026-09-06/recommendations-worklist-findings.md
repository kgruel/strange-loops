# recommendations-worklist — Fable review

Effort: low. Finished: 2026-09-06T15:52:54.508211+00:00.
Packet SHA-256: `cf2648afbe5b4c382ea313a98b8bfe2fe18d2ebbf0d009183f5b210942dfa7f1`.

Static reviewer output; findings still require primary triage.

**Overall judgment:** The matrix and D1–D6 are internally consistent with the source shown, and the C1–C9 order is roughly right. Two recommendations would cause unintended semantic changes if executed as written: C2 (routing `sync_target` through the current normalizer flattens pre-mutation refusals into "projection-unknown") and D4 (a "boundary-bearing" predicate is narrower than what hydration actually dispatches on). D1/D2 are missing a prerequisite: the credential interface is keyed on a locator path, and the identity the mapping should key on is never named. Everything else is sequencing detail.

## Findings

**F1 — (a) C2 as written introduces a regression. Priority: high.**
Span: matrix C2 (line 104), D6 (lines 184–196); `sdk/errors.py:339-342`, `sdk/read.py:1810-1835`.
Evidence: `normalize_exception` maps every `ProjectionSyncError` and `SearchIndexSyncError` to `ProjectionOutcomeUnknown`, whose docstring says derived state "may have changed". The matrix (line 67) says sync *refuses* on unwatermarked rows and inconsistent/foreign markers, i.e. before any derived write. Today `sync_target` leaks engine types, which are at least distinguishable. Applying C2 literally would make a clean pre-mutation refusal indistinguishable from an interrupted catch-up.
Also `agreement=projected_after.ordinal >= target.ordinal` (line 1833) is an ordinal comparison exposed as a boolean, which the matrix itself forbids (lines 138–139) and D6 argues against.
Failure: operator sees "projection-unknown", runs a reconciliation/audit it did not need, or worse treats a foreign-marker refusal as transient and retries.
Correction: before routing `sync_target` through normalization, split the engine sync error family (or add a `mutated: bool | None` attribute) so refusal-before-write maps to `ArrivalRefusal` and only post-write failures map to `ProjectionOutcomeUnknown`. Replace `agreement` with exact equality of resolved heads or drop it.

**F2 — (a) C3's "shared rule" should be lifted from `open_read`, not `runtime_write`, and needs one more clause. Priority: high.**
Span: matrix C3 (line 105); `arrival_declarations.py:854-870`, `runtime_write.py:697-705`, `arrival_consumer.py:183-215`.
Evidence: declaration prep calls `head_at` only when `represented.ordinal <= captured.ordinal`; above H it clamps without membership. Confirmed as stated. Two further divergences the doc does not list: (1) `runtime_write` refuses when `observed.ordinal == captured.ordinal and observed != captured`; `open_read` does not check this at all (line 209–215 just adopts `observed`). (2) Declaration prep raises a bare `ProjectionBehind` at line 860 while every other failure in that block is `DeclarationPreparationRefused`; whether `ProjectionBehind` is a `DeclarationPreparationError` is not in the packet, so either it escapes unwrapped or gets wrapped generically at line 902.
Failure: a rolled-back-and-reappended ledger at the same height passes `open_read` with a projection watermark naming the old record; reads would report a `projected_through` that is not a prefix of the captured head.
Correction: extract one helper from `open_read` (it is the superset: continuation cases included), add the equal-ordinal hash check to it, and call it from all three sites. Add a regression for same-height fork on the read path, not only for the above-H clamp.

**F3 — (a) Aggregate shape is decided in different orders across readers, contradicting the matrix's own capture claim. Priority: medium.**
Span: matrix row "Summary, state, timeline" (line 60) and C7 (line 109); `sdk/read.py:1493-1522`.
Evidence: `read_timeline` first branches on `has_local_descriptor_aggregate` (assumed from its name to inspect the local file) and routes to `_aggregate_timeline` without opening the root; only otherwise does it open the root and consult the effective declaration. Summary/state per the docstring at 117–127 open the root first. So local-aggregate/effective-single goes one way in timeline and another in summary.
Failure: a local edit that adds `combine` before the declaration is committed makes timeline compose members while summary refuses or reports single-store, from the same locator.
Correction: C7 should first make all three readers use effective-first, and the matrix line 60 should say local shape is only a resolution hint. Add both disagreement directions to the "Same backend across SDK entrypoints" scenario now, not after C7.

**F4 — (b) D4's collision predicate should be name equality, not "boundary-bearing". Priority: medium-high.**
Span: D4 (lines 130–150), C5 (line 107); `vertex.py:809-820, 837-846`.
Evidence: `hydrate_snapshot` dispatches every owned tick by `self._loops.get(tick.name)` and separately by `tick.name == self._name`. A vertex tick therefore calls `replay_boundary` on any loop sharing the vertex name, boundary-bearing or not; `replay_boundary` resets projection state when `loop.reset` is set. Conversely a loop tick with the vertex's name sets `_vertex_period_start`. The count fallback at 837–846 also keys on `ticked_loops` by name.
Failure: a passive loop with `reset` named like the vertex is silently reset by every vertex tick; no boundary trigger exists so a "boundary-bearing" predicate would never fire.
Correction: interim predicate is simply `loop_name == vertex_name` for any loop, refused at runtime materialization and declaration preparation. Reserve the richer per-form analysis D4 asks for as a later relaxation, not the initial gate.

**F5 — (b)+(c) D1/D2 lack a prerequisite: the credential interface is locator-keyed and the mapping key is unnamed. Priority: high for sequencing.**
Span: D1 bounded implementation (lines 58–67), D2 items 1–2 (lines 81–84), D3 (lines 120–121), C4; `credentials.py:36`, `signing.py:139-152`, `emit.py:98-104`.
Evidence: `CredentialProvider.for_write(vertex: Path)` carries no observer, domain, or declared identity; self-observer is the locator stem, and before the file exists (init) it is also the stem. D3 says binding must become locator-independent; D2 says map "exact observer identity" to key refs. Nowhere does the packet say whether that identity is the stem, the declared vertex name from historized documents, or the genesis observer. The wire profile makes tick `observer` the genesis observer, so these three can diverge today.
Failure: D2 item 1 binds the flat key to "its existing self observer" by stem, later init/declaration uses the declared name, and the mapping never matches; signer loading falls back to unsigned silently (signing.py returns `None`), which the pipeline treats as legal.
Correction: add a D0 decision naming the binding key (recommend: genesis observer, checked against the declared name at init) and change the provider protocol to a request carrying observer+domain+lineage before D2 design starts. For C4, verify no CLI/test passes `key_dir` before adding the refusal; the packet does not show callers.

**F6 — (a) C8's source cleanup concern is confirmed and slightly worse than stated. Priority: medium-low.**
Span: C8 (line 110); `arrival_sources.py:468-492`.
Evidence: `aclose` is invoked only on the invalid-output break. An exception raised in the loop body (`id_factory()`) is caught by `except Exception` and recorded as a *source* error with the coordinator's exception type; cancellation leaves the stream to GC-based finalization.
Failure: an ID-factory fault appears in the lifecycle fact as if the collector failed, violating "source errors must remain distinguishable".
Correction: move `id_factory()` out of the loop or outside the `try`; call `aclose` in `finally` unconditionally when the stream exposes it. Add the cancellation test C8 already asks for.

## Omitted-evidence questions

- Does ordinary emit verify fact/Arrival signatures against `keys_valid_at` before append, or only `verify(authorship)`? Declaration edits do (`_signed_with_existing_key`); D1's "unauthorized replacement key is not a rotation" gate depends on the answer for facts.
- Is `ProjectionBehind` a `DeclarationPreparationError` (F2)?
- Does `sync_projection` distinguish pre-write refusal from post-write failure internally (F1)?

## Recommended first slice

**C3 with the equal-ordinal clause, plus the initializer re-raise from C8.** Smallest, pure correctness, no API change, and it removes duplicated interpretation before C2 touches classification.

Acceptance gates:
1. One helper resolves and validates a CURRENT watermark against a captured head; `open_read`, `_current_write_basis`, and `prepare_declaration_edit` all call it.
2. Regressions: above-H watermark with fabricated prefix refuses in all three paths; legitimate above-H advance yields `projected_through == captured`; same-height fork refuses in read and prep; continuation tests unchanged.
3. `declare` uses bare `raise` when `normalized is exc`; test asserts `__cause__` is not self.
4. Existing 56-test read suite and declaration interruption suite pass unchanged.
5. F1's error split is written as the next slice's precondition before any `sync_target` normalization lands.
