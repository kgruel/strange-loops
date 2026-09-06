# c2-design — Fable review

Effort: low. Finished: 2026-09-06T17:42:07.374585+00:00.
Packet SHA-256: `72be3c08a9d617fba260004ec669818ea3892dd80ce107bb6ccf57c4db19b0f6`.

Static reviewer output; findings still require primary triage.

**Verdict: needs correction** (one medium item; the rest are refinements). No regressions: every issue below is an existing limitation or a gap in the design text, and no C2 production change is claimed.

## Findings

**1. Medium — `phase` already has a public meaning at the top level of `details`.**
Source: `libs/sdk/src/sdk/errors.py:101` copies any `exc.phase` into `details["phase"]`; the design (lines 51, 56, 125) introduces `phase` as new evidence at `details.evidence.phase` and says no current exception carries it. Scenario: worklist step 1 adds `self.phase = "derived-sync"` to `ProjectionSyncError`. `_identity_details` then emits `details["phase"]` automatically, so the value appears twice, and the top-level slot already carries whatever vocabulary initialization/restore wrappers use for their `phase` attribute. An SDK consumer cannot tell whether `details.phase` is the legacy operation-specific string or the new coordinator-stage vocabulary. Correction: state explicitly that `evidence.phase` is populated only by the new serializer from a distinctly named attribute (for example `coordinator_phase`), or declare that the two must always be equal and list the legacy `phase` values as part of the v1 vocabulary. Also add the invariant that `attempt=not-entered` implies `state=not-attempted`, since the schema currently permits contradictory pairs.

**2. Low/Medium — search sync has a cheap not-entered proof the design leaves unused.**
Source: `libs/engine/src/engine/arrival_search.py:169-203`. Once `target` is set, failures from `query.open_snapshot` (line 171) and `registry._search_maintenance_for` (line 176) are wrapped as `SearchIndexSyncError` even though no maintainer handle existed and `build` was never called. The coordinator can prove this without inspecting nested classes: `maintenance is None` or a local flag set just before line 178. The design (lines 102-108, 127-128) allows `attempt=not-entered` "only when their coordinator can establish it" but never names this case, and the first acceptance test (lines 158-161) only mentions maintainer failures. By contrast, `sync_projection` (`arrival_maintenance.py:242-243`) enters `catch_up` as the first statement inside its wrapper, so it can only ever prove `entered`. Correction: worklist step 1 should say search sync sets `attempt=not-entered, state=not-attempted` when the build boundary was not reached, projection sync always reports `entered/unknown`, and add an acceptance case for a snapshot refusal after target selection. Existing limitation, not a regression.

**3. Low — cause serialization source is underspecified.**
Source: design line 60 and step 2 (lines 131-134). `ProjectionSyncError` and `SearchIndexSyncError` expose an explicit `cause` attribute; `DeclarationPreparationRefused` (`arrival_declarations.py:802-805, 906-909`) only has `__cause__`. The design says "keep the Python exception chain in-process; serialize at most a documented short chain" but does not say whether the serializer reads `cause`, `__cause__`, or both, nor the depth. Scenario: the serializer follows `__cause__` and a declaration refusal that wrapped an `OSError` from reading the cache file serializes the OS message including the filesystem path, which is arguably fine, but a deeper chain could carry adapter diagnostics the design says to exclude. Correction: specify "explicit `cause` attribute if present, else `__cause__`, depth at most 2, `message` truncated to a fixed length, identity fields via `_identity_details`, never `__context__`".

**4. Low — dead mapping and an unstated leak in the `sync_target` routing step.**
Source: `errors.py:339` already maps `ProjectionSyncError` to `ProjectionOutcomeUnknown`, so its second appearance in the refusal tuple at `errors.py:375` is unreachable and reads as if a refusal mapping exists. Separately, worklist step 3 routes `sync_target` (`read.py:1826`) through normalization, but `sync_projection` raises bare `TypeError` (`arrival_maintenance.py:201, 216, 246`) which `normalize_exception` returns unchanged, and `ValueError` from the search spec check (`arrival_search.py:160`) likewise escapes. Correction: remove the dead tuple entry as part of step 2, and have step 3 state that `TypeError`/`ValueError` remain direct engine exceptions under the existing SDK promise, so the "documented compatibility transition" clause is not read as covering them.

## Confirmed sound
- `NotWitnessed` handling matches `arrival_head_seam.py:259-264`; `_identity_details` already omits `commit` when `None`, so the mint case serializes head-only without invention.
- `observed_after` dual-loop at `errors.py:128,137` correctly distinguishes Head versus SearchCoverage; no change needed for the evidence object.
- `P >= target` reporting (`arrival_maintenance.py:267-274`) is described accurately as custody-resolved coverage, not row audit.
- Cancellation identity is preserved: both engine wrappers catch `Exception` only, and `sync_search_index` re-raises via `normalized is exc`.
- Keeping C8b's `details.collection` separate from `details.evidence` is consistent with `SourceTerminalResult.details` being a plain dict, and additive placement preserves `loops.sdk/error/v1`.

Recommendation: fix finding 1 in the design text before implementation begins; 2 through 4 can be folded into the worklist wording.
