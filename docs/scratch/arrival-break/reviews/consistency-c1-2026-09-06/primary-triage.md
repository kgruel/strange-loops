# C1 Fable-low review: primary triage

Fable 5.1 at low effort **accepted** the frozen C1 implementation on September
6, 2026. No production defect or blocking finding was reported. The
[raw findings](c1-findings.md), [packet](c1-prompt.txt), [slice diff](c1.patch),
manifest, result and model metadata are retained here. The runner confirmed
substantive `claude-fable-5-1` output and no source drift at launch. The tiny
Haiku CLI helper was not the reviewer.

Root independently inspected the two-file production diff, routing helpers,
real registered-adapter fixture, and the following four findings.

1. **Borrowed root close:** resolved by existing source, no implementation
   change. `engine.arrival_consumer.OpenedRead.close` checks `_closed`, sets it
   before closing resources, and returns immediately on subsequent calls.
   Aggregate and outer context cleanup therefore release each underlying
   resource once. The packet contained `open_read` but omitted this class,
   which explains the reviewer's uncertainty. A root probe invoked `close()`
   twice with counting snapshot/query/ledger handles: each received one call.
   No ownership rewrite is warranted by C1.
2. **Explicit empty registry and built-in file:** accepted as additional
   contract coverage. Terra adds `file` alongside `opaque` to the three
   unknown-backend cases, with default-registry construction and legacy
   probing poisoned. This is test-only follow-up; the accepted production
   code is unchanged.
3. **README legacy scope:** accepted. Root qualifies registry-controlled opens
   as Arrival opens and explicitly states that legacy targets retain their
   behavior without consulting the registry. Contrary to the review's closing
   wording, the ambiguous README paragraph was new in C1, not pre-existing.
4. **Omitted-registry compatibility:** no extra test needed. Existing SDK tests
   exercise default file-backed reads, including timeline, entity and
   inspection. The full SDK suite passed, and default selection expressions
   are unchanged. Duplicating that coverage in the C1 file adds no new proof.

The final production files are exactly those Fable reviewed. Subsequent test
expansion and README clarification are root-triaged follow-ups, not a second
Fable approval. Suite evidence and final scope status are recorded in the
[slice report](../../consistency-c1-2026-09-06.md).
