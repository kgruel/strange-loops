# sdk-verify-pagination — Fable review

Effort: low. Finished: 2026-09-06T14:30:58.923940+00:00.
Packet SHA-256: `14dd02dfdbf2491a19d31ebae8fc09f685176ec77c7380684c638c208cb7f9a0`.

Static reviewer output; findings still require primary triage.

**Result: no demonstrated actionable defects in the excerpted supported paths.** Two conditional concerns and the checks performed follow.

## Conditional concerns (not demonstrated; depend on code outside the excerpt)

1. **Absent-projection anchor validation ordering** — `libs/engine/src/engine/arrival_consumer.py:163` calls `validate_arrival_declaration_anchor(...)` before the `watermark is None` branch at line 164. For an ALLOW_BEHIND read that gets `_AbsentFileQuerySnapshot` (`arrival_file_backend.py:1450`), the anchor is presumably `(None, None)`. If the validator treats a `None` own_lineage as a refusal rather than "nothing to license", the documented "empty allow-behind snapshot" path can never be reached. Trigger: `open_read(..., requirement=ALLOW_BEHIND)` on a descriptor whose projection file does not exist. Question, not proof: what does the validator do with `own_lineage is None`?

2. **Full verification claims rest on `_log.walk()` semantics** — `arrival_file_backend.py:764-779` only checks that the record found at the target ordinal matches the claimed head. The "grammar, density, lineage, hash-chain" claims in `VerifyResult.claims` (`types.py:911`) are true only if `walk()` itself validates every record it yields (hash chain continuity, dense ordinals, single lineage). The docstring asserts this; the excerpt does not show it. If `walk()` is lenient on any of these, `verify_target` would report a stronger guarantee than it establishes.

## What was checked and found consistent

- **Full-head CAS / verification bounds**: `_verified_prefix` (`verify.py:26-44`) refuses lineage mismatch, ordinal beyond captured, hash mismatch via `head_at`, and re-checks the `Full` return. `verify(Full)` stops at the named ordinal and makes no tail claim.
- **Watermark membership**: every reported watermark goes through `ledger.head_at` (`arrival_consumer.py:183`, `arrival_file_backend.py:659-666`), which reads the ledger record and refuses on lineage disagreement rather than manufacturing a head.
- **Immutable paging basis**: continuation resume re-resolves both `captured_head` and `projected_through` against the ledger (`arrival_consumer.py:148-151`); the snapshot re-verifies `captured_head` equality, lineage, watermark reach, and CURRENT-vs-behind tokens (`arrival_file_backend.py:926-947`). Bound derivation is stable across appends: CURRENT reads bind to `captured.ordinal` both fresh and resumed; ALLOW_BEHIND binds to the same watermark ordinal on resume, so `_generation(bound)` reproduces.
- **Generation invalidation**: `_generation` (`arrival_file_backend.py:1032-1088`) digests schema version, bound, anchor identity, and all projected rows through the bound. Rebuilds that alter any bounded row, or declaration anchor changes, change the token; a projection that merely catches up beyond the bound does not, which is correct.
- **Filter/cursor validation**: `facts()` refuses invalid order, `limit < 1`, and any request differing from the continuation's (`arrival_file_backend.py:1118-1123`). Cursor predicate and `ORDER BY` both use `(arrival_ordinal, arrival_seq, id)` in the matching direction, so packed-record row splits resume correctly. `read_facts` (`read.py:755-765`) enforces before/after exclusivity and order agreement before opening.
- **Declaration drift**: `_arrival_declaration` runs on first pages only (`read.py:776-777`); this is safe because a resumed page is bounded to the same prefix and the generation digest already covers the `_decl` rows and genesis anchor within that bound.
- **Resource ownership**: both openers close snapshot, query, then ledger on every failure path (`arrival_consumer.py:219-224`, `verify.py:92-94`); `OpenedRead` exposes neither the ledger nor the query handle; `FactPageResult.as_dict` never serializes an unprotected `Continuation`.

## Remaining uncertainty

Behaviour of `_log.walk()`, `_log.read()` on out-of-range ordinals (e.g. a negative `through`), `validate_arrival_declaration_anchor`, and `_AbsentFileQuerySnapshot` were not in the excerpt. The `fact_id + "~"` prefix upper bound (`arrival_file_backend.py:1129`) excludes ids containing characters above `~`; that only matters if fact ids can contain such characters.
