**ACCEPT.** I found no P1 in the frozen source. The P2s below should land before the real cutover, and the first missing-context item is an unverified risk that becomes P1 if it holds. This was a static review; no tests were run.

Fresh filtering is consistent across the execution consumers I could see: hydration, pending boundaries, source cadence, C6 owned ticks, `read_state`, and aggregate per-member floors. Global dedup, the tick-id collision check, signed-era detection, `prev_hash`, and window hashes all read full history. The physical-vs-projection comparison catches an invented marker, a stripped marker, and a moved ordinal or sequence. Own-lineage selection cannot be influenced by foreign genesis rows. Recovery rejects both a field-only and a field-plus-payload epoch tamper, the second through FACT signature verification.

## P2

1. **Strict-mode hydration widened to ticks with negative `ts` — `runtime_write.py:949-964,1008`.**
   - **Trigger:** a strict store holding an own-origin tick with `ts < 0`.
   - **Consequence:** that tick now resets the loop on rehydrate, where previously `TickRequest()` with `since=0` excluded it from hydration. This is a behaviour change in the default mode. It contradicts the accepted C6 note that hydration selection "must not be widened accidentally" (`consistency-c6…md:159-162`).
   - The same diff changes `plan_ordinary_write:1119` and `capture._ticks` to read full tick history. That fixes a latent wrong-`prev_hash` and chain break when the latest physical tick has negative `ts`, so I would keep both changes.
   - **Fix:** record the decision in the C6 design and add a strict regression test covering a negative-`ts` owned tick for both the hydrate reset and the chain predecessor. The only current coverage is the fresh-mode test.

2. **Acceptance item 7 is not actually tested — `tests/test_arrival_migration_boundary.py:612-618`.**
   - **Trigger:** the `epoch-downgrade` mutation rewrites the payload but leaves the intent root field `"runtime_epoch": "fresh"`. It is therefore caught by the payload-equality check at `arrival_adoption.py:762-770`, not by signature verification.
   - **Consequence:** a self-consistent downgrade (root field set to `strict` plus a protocol-1 payload) is never exercised. The code does refuse it, because the FACT digest no longer verifies, but no test proves that.
   - **Fix:** add a mutation that also sets the root field to `strict`, and the reverse case (strict to fresh) on the strict parameterisation.
   - **Related:** `_plan_from_intent:646` takes the mode from the unsigned intent field and cross-checks it against the draft. The design text and ADOPTION.md say the mode is "derived from the draft". Deriving it from the draft payload would remove the redundant field.

3. **Rehearsal signature evidence no longer reads custody bytes — `scripts/arrival_rehearsal.py:209-239`.**
   - **Trigger:** `_verify_rehearsal_emit` now verifies the in-memory `commit.records` instead of `ledger.read(...)`.
   - **Consequence:** `signed_fact_and_arrival: true` attests the returned Commit object rather than the physical row.
   - **Fix:** after matching the record, call `ledger.read(record["ord"])`, require it to equal the commit record, and verify the signatures on the row that was read.

4. **Rehearsal epoch and history assertions are one-sided — `scripts/arrival_rehearsal.py:447-454,430-434`.**
   - **Trigger:** the script asserts the fresh epoch only. It never checks `adopted.runtime_epoch == args.runtime_epoch`, that a strict run reports `{"mode": "strict", "anchor_ordinal": None}`, or that a fresh run's sections are at their declared initial values (only a hash is recorded).
   - **Consequence:** the claim "history preserved" is recorded (`fact_total`, `tick_total`) but never compared against the inventory counts less dropped units.
   - **Fix:** add these assertions to the script.

## Nonblocking

- **Low-level downgrade bypass:** `hydrate_arrival_candidate` and `runtime_epoch_from_anchor` accept `wire_record=None` and return strict without any physical check (`declaration.py:150-155`, `runtime_write.py:1041-1057`). A projection stripped of its marker therefore passes on this API. Supported paths always supply the wire record. Consider requiring it, or naming the unverified variant.
- **Read cost:** `OpenedRead.runtime_epoch()` (`arrival_consumer.py:96-106`) calls `ledger.read(A)`, which is a verified walk from ordinal 0 (`arrival.py:1207-1220`). On a migrated store A sits at the end of history, so every `read_state`, every aggregate member capture (`arrival_aggregate.py:256`), and every `capture_runtime` pays O(history).
   - Aggregate summary and timeline reads pay this too, although they do not need the epoch.
   - `read_state` computes it twice for an aggregate root.
   - It cannot be skipped for strict stores without reopening the downgrade hole, so compute it lazily for aggregates and cache it by anchor `record_hash`.
- **Adapter contract tightened:** `runtime_epoch_from_anchor` is called with a wire record even for strict stores, so `read_state` now needs the adapter to supply the exact `payload_text` and `signature` on `Fact`. This is not recorded on `QuerySnapshot`.
- **Payload built in two places:** `_anchor_payload` and `build_declaration_anchor_draft` build the payload separately, and it is identical today. Several sites also hard-code protocol `1`, and the docstring at `document.py:150` is now stale. Share one builder and one named base-protocol constant.
- **Narrower protocol acceptance:** `_runtime_epoch_payload` now refuses protocol 0, negative, float, or string values that the old `> VERSION` check accepted. This is the fail-closed direction, but it changes behaviour for legacy resolution.
- **Doc wording:** "first post-A event starts period context" holds for pending planning only. Hydration never seeds `_vertex_period_start` from facts, so a first post-A boundary gets `since` equal to its own `ts`. This is existing behaviour and only the wording is off.

## Missing context

- **Possible P1:** grep every use of `DECLARATION_PROTOCOL_VERSION`, including `arrival_store._genesis_payload`, the app's absorb command, `migrate`, the `store` lib, and the Go oracle vectors. Any emitter that stamps the constant now writes protocol 2 without the marker, and every reader will refuse that payload.
- Check other callers of `analyze_boundary_continuity`, `_build_effective_arrival_candidate` (which now returns 8 values instead of 6), and `RuntimeCapture.facts` and `.ticks` in `sdk/declare.py` and `sdk/source.py`.
- Confirm `rows_of_body` yields tuples, since the comparison at `declaration.py:168` uses tuple equality.
- Check how `normalize_exception` maps `DeclarationResolutionError` and `UnsupportedProtocol`, which `open_read` can now raise through `validate_arrival_declaration_anchor`.
- Confirm the CLI and `open_vertex` paths over a fresh store reach the legacy resolver's refusal rather than doing a full-history `Vertex.replay`.
