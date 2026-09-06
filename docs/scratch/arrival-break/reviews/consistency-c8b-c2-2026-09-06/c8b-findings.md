# c8b — Fable review

Effort: low. Finished: 2026-09-06T17:41:06.316727+00:00.
Packet SHA-256: `87563dfc32cbb0edd28098a2ee84fc159ec7cf0181f12c2489d21ea48721e3be`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** The slice implements the stated contracts correctly on the edges I could trace statically. Four non-blocking items follow, none regressions against cfb26920.

**Traced and confirmed**

- ID allocation precedes retention, so `state.pairs` is always exactly paired. Bookkeeping failure raises `_CollectionStepFailed` with no lifecycle fact appended (`arrival_sources.py:598-604`).
- `aiter(stream)` is captured separately from `stream`; `_close_owned_streams` dedupes by identity and attempts each handle once. The `getattr` lookup is inside the try, so a hostile `__getattr__` is an ordinary cleanup failure.
- Ordinary cleanup failure with a set `primary` is discarded, never masks. A cleanup interrupt with an interrupt primary is swallowed and the other handle still gets a close attempt. A cleanup interrupt with a non-interrupt primary is deferred until both handles are tried, then raised. Test at `test_arrival_sources_c8b.py:215` relies on Python 3.11+ preserving `_cancelled_exc` identity through Task and gather; that holds.
- Caller cancellation: outer `gather` raises immediately on cancellation without waiting for children, so the `except BaseException` settlement await is necessary and present.
- `execute_source_invocation` returns `SourceTierCollectionFailed` without appending the current tier; `bases` already includes the current basis; prior durable tiers intact. `_overall_fact` moved inside the try so a final-summary failure lands in the `collected_uncommitted` path with the fully collected tier.
- Original mismatch: baseline `prepare_collected_tier` used strict zip, so no prior corruption claim is warranted. Docs say this correctly.

**Findings**

1. **Low, unverified: `details.collection.basis` may serialize as `null`.** `sources.py:307` routes `exc.basis` through `_safe_detail`, which duck-types on four attribute names and returns `None` otherwise. Every other basis in `SourceRunResult.as_dict` uses `asdict`. Neither SDK test asserts the basis value, so a shape mismatch would pass silently. Correction: use `asdict(exc.basis)` and add one assertion that `evidence["basis"]` equals `result.bases[-1]` serialized. New code, not a regression.

2. **Low: unclassified sibling exceptions are dropped in the coordinator-failure branch.** In `collect_source_tier` the settled results are bucketed into `CollectedSource`, `_CollectionStepFailed`, and `CancelledError` only. A sibling that raised `KeyboardInterrupt` or `SystemExit` while another sibling's bookkeeping failed is returned by `return_exceptions=True`, matches no bucket, and vanishes: not in evidence, not re-raised. Scenario: operator hits Ctrl-C inside collector A's `__anext__` at the same moment collector B's ID service fails. Correction after bucketing:
   ```python
   leftover = [r for r in settled if isinstance(r, BaseException)
               and not isinstance(r, (Exception, asyncio.CancelledError))]
   if leftover:
       raise leftover[0]
   ```
   Rare; existing limitation in spirit since baseline had no sibling settlement at all.

3. **Low: cleanup failures after a collector error or invalid output leave no evidence.** When `primary` is set, `_close_owned_streams` result is discarded (`arrival_sources.py:629`), and even on the cleanup-primary path only `failures[0]` survives. The spec requires non-masking, which is met, but an operator cannot tell that the collector's own close failed. Correction: add `cleanup_error_type`/`cleanup_error_message` to the lifecycle payload and `CollectedSource`, and carry a tuple of failures rather than the first. Existing limitation: baseline only closed on invalid output.

4. **Low, validation caveat.** The validation report states the full SDK suite (509) ran before the last engine hardening for distinct-owner cleanup interruption and final-summary retention; only 13 SDK source tests ran on final production. Engine's full 2,539 did run on final code, and the SDK depends on engine behavior only through the result object, so risk is small. Correction: rerun the full SDK suite once before merge and update the report, or state the gap in the triage doc rather than the validation doc.

**Accepted edge worth noting, not a finding.** A cleanup `CancelledError` arriving while `primary` is a bookkeeping `_CollectionStepFailed` replaces it and discards that source's paired partial evidence, since cancellation propagates as control flow. This matches "existing control-flow exception retains identity" and "caller cancellation is not a normal incomplete return", but it means paired evidence is only guaranteed when no interrupt occurs during cleanup. Repeated cancellation during the settlement await in the `_CollectionStepFailed` branch propagates out of an `except` clause with tasks already cancelled; out of scope as stated.

**Outside scope, confirmed not claimed:** C2 normalization, subprocess termination, external rollback.
