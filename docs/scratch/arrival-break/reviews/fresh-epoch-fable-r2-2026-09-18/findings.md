**ACCEPT.** I found no P1 in the supplied source, and all four prior P2s are closed in code. One new P2 (tick attestation in the rehearsal runner) and one emitter check I could not complete from this packet should be resolved before cutover. This was a static review: I ran no tests and used no tools.

## Closure

| # | Prior finding | Status | Basis |
|---|---|---|---|
| 1 | Strict hydration widened to `ts<0` ticks | **Closed** | `runtime_write.py:960-970` selects `tick.ts >= 0.0` for strict and `ordinal > anchor` for fresh. `all_ticks` still feeds C6 (`:987`), `_current_tick_context`, signed-era detection and `capture._ticks`. `plan_pending_boundaries` receives `runtime_ticks`, so the strict pending policy is unchanged. The C6 design (`:164-169`) records the split, and a test was added (see P3-a). |
| 2 | Self-consistent epoch tamper untested | **Closed in code; test weak** | The `epoch-self-consistent` mutation rewrites the intent root field and the draft payload, in both directions. By my reading the mutated payload is byte-identical to `_anchor_payload(documents, opposite)`. It therefore passes the payload and body checks at `arrival_adoption.py:762-780` and is rejected only by FACT signature verification at `:788`. `intent.exists()` after the after-append case confirms it never reached the retire branch (see P3-b). |
| 3 | Signature evidence read from the in-memory Commit | **Closed for the fact** | `arrival_rehearsal.py:228-257` reads `ledger.read(ord)`, requires it to equal the commit record, and verifies both signature domains on the row it read. The boundary tick is not covered (see P2). |
| 4 | One-sided epoch and history assertions | **Closed; fails closed** | The runner now checks `adopted.runtime_epoch`, the expected epoch in both modes, and kind/fact/tick counts against inventory less dropped units. For fresh it also compares sections with the declared initial values. See the checks below for fragility. |
| – | App-side protocol emitter | **Closed** | `store.py:1249-1251,1269,1304` takes the protocol from `genesis_payload()`, which returns literal 1. This also restores the golden line `protocol v1`. |

## P2

**The runner and its test never attest the boundary tick, and nothing pins the `receipt_observer` fix.**
- **Where:** `scripts/arrival_rehearsal.py:209-257,432-436` and `tests/test_arrival_rehearsal_runner.py:113-143`.
- **Reproduce:** revert `receipt_observer=args.observer`. The `seal=True` fixture has no legacy tick, so it is the unsigned era and `_tick_signature` returns `None` (`runtime_write.py:855-862`). An unsigned tick is appended and `test_fresh_rehearsal_seal_emits_a_signed_fact_and_tick` still passes, because it asserts only the record kinds `["fact","tick"]`.
- **Consequence:** `evidence.json` records nothing about the tick: no id, no signature check, no `prev_hash` continuity. A real-store fresh run cannot be told apart from one that wrote no tick, except by the head ordinal.
- **Why other checks don't cover it:**
  - Full verify does not check the tick body signature.
  - The `audit_deep` chain check exists only in the pytest integration test, not in the runner.
- **Fix:**
  - Locate the `k=="tick"` record in `commit.records`, read the physical row and require equality with the commit record.
  - Verify `body.signature` over `tick_commitment_hash` under the TICK domain.
  - Require `prev_hash == tick_row_hash(latest prior physical tick)`.
  - Record the tick id and these verdicts in evidence, assert them in the runner test, and add an expect-tick switch.

## Checks needed before cutover (source not in this packet)

1. **Engine genesis emitter (becomes a P1 if it fails).**
   - **What to check:** `absorb_genesis(documents, …)` receives no protocol from the app, so `SqliteStore.absorb_genesis` stamps it itself. `ArrivalStore._genesis_payload(protocol, …)` (`arrival_store.py:679`) passes that value straight through.
   - **Why it may fail:** the diff flips the stored-row and receipt assertions from the constant (2) to `1` without modifying `sqlite_store.py`. Either those tests were failing at 72faf1d5 or they fail now, unless the engine already stamps a literal 1.
   - **Impact if it stamps the constant:** every new absorb writes protocol 2 without the marker, and `_runtime_epoch_payload` refuses it permanently. `loops store absorb` still dispatches to this path on a migrated, unadopted Arrival store, where the anchor is append-only.
   - **Gate:** run `rg DECLARATION_PROTOCOL_VERSION` and confirm only reader-side uses remain, then run `test_store_absorb.py`. Also check `build_declaration_anchor_draft`, `migrate`, the `store` rebirth path, and the Go oracle vectors.
2. **Other strict tick selectors.** Confirm `read_state`/`arrival_consumer`, the aggregate path, and `sdk/source.py` cadence take ticks from `_build_effective_arrival_candidate`, not from their own `since=-inf` request. `RuntimeCapture.ticks` now returns all ticks, and there is no public `runtime_ticks` accessor to match `runtime_facts`.
3. **Boundary at `ts == 0.0`.** Confirm the adapter's `TickRequest(since=0)` filter is `>=`, so `ts >= 0.0` matches the previous behaviour exactly.
4. **Runner fragility (fails closed, but could block the real rehearsal).**
   - Does `compile_vertex` return a dict of specs that have a `.replay` method?
   - Does `state.sections` include the implicit `cite` loop or template-generated loops that `compile_vertex(declared)` omits?
   - Legacy `_decl.*` rows are counted by inventory but excluded by the default `read_summary`, which would cause a false refusal and leaves their preservation unasserted. Use `include_internal=True` and subtract the adoption anchor.
   - Dropped tick units do not decrement `inv.tick_count`.

## P3

- **a. Finding 1 test may be vacuous** (`test_runtime_write.py:631-672`). The fact has `ts=1` and the tick `ts=-1`. If hydration merges by event time, the state is `{"total":3}` whether the tick is included or excluded. Setting the fact to `ts=-2` makes the test discriminate under either ordering. No test covers strict pending-boundary selection, or asserts that fresh hydration consumes a negative-`ts` post-anchor tick (for example via the third tick's `since`).
- **b. Finding 2 test asserts only `SdkError`.** Pin the signature-verification reason, or add a control run where a permissive verifier lets the same mutation pass.
- **c. Absorb text and JSON use different protocol sources.** The text render uses the app-side `protocol` while the JSON uses the engine receipt. Render from `receipt["protocol"]` on the real path.
- **d. Protocol literals are scattered.** `genesis_payload`, `_anchor_payload`, the initialization builder and `(1, 2)` in `_runtime_epoch_payload` should share one constant and one builder.
- **e. Small runner cleanups.**
  - The `isinstance(state_epoch, dict)` check is now dead code.
  - Counts are not re-asserted after the emit.
  - The export is compared with the ledger stream, not with the raw target file.
- **f. `capture_runtime` reads the genesis ordinal before validating the anchor** (`:1282-1285`). A bogus projected ordinal raises an untyped error. It still fails closed.

## Optional preexisting architecture concerns

- The physical read of the anchor on every read and capture walks the whole history. Cache it by the anchor's `record_hash`.
- `wire_record=None` still yields strict with no physical check on the low-level API.
- CLI `store absorb` remains an alternate adoption path for migrated Arrival stores. It bypasses `adopt_arrival`'s reviewed checks and preempts a later fresh-epoch adoption.
- Strict reads now require the adapter to supply exact `payload_text` and `signature`, and protocol acceptance is narrower (integers 1 or 2 only).
