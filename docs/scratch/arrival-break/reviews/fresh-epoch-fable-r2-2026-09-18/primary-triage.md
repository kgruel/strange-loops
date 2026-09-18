# Second-pass triage

Fable returned ACCEPT and closed the four original P2 findings. Source hashes
were unchanged during this review. It identified one additional P2: the rehearsal
runner did not attest the boundary tick or use a fixture that pinned receipt
identity. The corrected runner now has `--expect-tick` and a reusable physical
one-pass tick attestation helper. It checks exact returned-record equality during
a new run, inner TICK signature and latest predecessor hash. Ticks have no outer
Arrival signature under the wire contract; the helper asserts that absence.
The fixture includes a signed historical tick, so removing the receipt binding
refuses the boundary write. Final repository tests pass (132).

The real completed store was re-attested read-only at its original commit range;
its tick signature and predecessor pass, and whole-file bytes are unchanged.
The retrospective artifact honestly leaves returned-Commit equality null because
that original tick record was not retained separately.

Source checks requested by Fable are closed by independent local audit: ordinary
SQLite absorb defaults protocol 1 (`sqlite_store.py:800`), Arrival forwards the
passed protocol (`arrival_store.py:679`), lang genesis emits 1 (`document.py:825`),
and initialization emits 1 (`arrival_initialization.py:551`). CLI absorb 23 tests
pass. SDK current fold state consumes facts rather than a separate tick replay;
source cadence uses validated runtime facts. Strict tick since 0 is inclusive.
The actual loops initial-state comparison passed, resolving its fixture concern.

Test-only improvements make the strict negative-timestamp case discriminating
(fact before tick) and require the exact reserved FACT signature failure for
self-consistent intent mode mutation. Both focused checks pass.

The runner intentionally fails closed for unsupported generic evidence cases
(e.g. inventory containing internal declaration facts); the real loops input has
no internal declarations and no dropped units. These do not block the exercised
rehearsal. Broader generic tool support and optional architecture cleanup remain
separate work; no live cutover is performed.

A third Fable invocation was attempted for the final bounded delta, but Claude
CLI refused due its session usage limit. Its receipt is retained in the r3
archive; it is not an acceptance. Independent Luna review covers the final delta.
The overall real-store limitation is also recorded separately: authorized observer
mapping invalidates 39 retained historical tick-window commitments; the original
archive passes and the new tick passes. No clean historical audit is claimed.
