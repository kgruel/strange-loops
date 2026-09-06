# first-slice — Fable review

Effort: low. Finished: 2026-09-06T16:30:19.716438+00:00.
Packet SHA-256: `129048522518dfebf2446cd08c1dd4c75066d1ff45e3a271ab0a87097b732988`.

Static reviewer output; findings still require primary triage.

**Verdict: accept.** The C3 helper and its three callers match the stated contract, and C8a is correct. No blocking defects; the items below are small hardening and evidence gaps.

## Findings

**1. Low, `libs/engine/src/engine/arrival_head_seam.py:979`, same-height check is custody-vs-custody, not projection-vs-custody.**
`observed` comes from `head_at(represented)` and `captured` from open attestation. Both are custody answers. A projection watermark carries no hash, so this branch detects custody drift between attestation and completion (rollback or same-height fork), not a substituted projection. The behavior is right and worth keeping; the message "projection head disagrees with captured custody head" and the slice doc's "same-height hash substitution" overstate what is proven. Smallest correction: reword message and doc line 57 to "custody head at captured height changed since attestation". No code change needed.

**2. Low, `libs/engine/src/engine/arrival_consumer.py:200`, continuation branch still uses bare `head_at` with an unused result.**
On resume, `observed` is only used for its exception. A returned head at the wrong coordinate or a same-height hash change is not checked here, unlike the fresh path. This is explicitly retained by scope (continuation lifecycle untouched), so not a defect for this slice. Record it as C-next work rather than fixing now. If you want the cheap subset, applying the helper with `conflict_refusal=InvalidContinuation` would be a one-line change, but that widens scope.

**3. Low, `libs/engine/tests/test_arrival_consumer.py:502`, consumer regression omits the wrong-coordinate case.**
Runtime and declaration suites parametrize `wrong-coordinate`; the fresh-read suite covers only foreign/missing/substitution. Add `"wrong-coordinate"` returning `Head(lineage, captured.ordinal - 1, "wrong")` expecting `HeadMismatch`. Also assert closure order `["snapshot", "query", "ledger"]` there as the other cases do.

**4. Low, `libs/engine/src/engine/arrival_declarations.py:871`, `ProjectionBehind` is swallowed into `DeclarationPreparationRefused`.**
`ProjectionBehind` is not a `DeclarationPreparationError`, so the generic `except Exception` at line 906 rewraps it. This predates the slice and the branch is normally dead for CURRENT snapshots, so no correction required now. Note it so the C2 phase/cause work does not treat the raised type as intentional.

**5. Evidence gap, `libs/engine/src/engine/arrival_declarations.py:864`, declaration prep now calls `head_at` above H where it previously did not.**
Before the slice, an advanced watermark short-circuited to `captured` with no custody call. Now the attested ledger must resolve an ordinal above its attested head. The packet shows only delegation at `arrival_head_seam.py:1852`, not `FileLedger.head_at`. Runtime capture already did this unconditionally, so it is likely fine, but no live-file test in the packet exercises a watermark above H on any path (the advance tests re-attest first, so watermark stays at or below H).

## What checks out

- Helper: lineage check before `head_at`, coordinate check, same-height full-head equality, clamp. Backend refusals pass through with cause intact (declaration test asserts `__cause__`).
- Callers keep their own behind/absent refusals and public families. `_ensure_current_basis` still requires `projected_through == captured_head`, which the clamp satisfies.
- ALLOW_BEHIND fresh reads: helper resolves the lower ordinal and `projected_through` becomes the lower head. The live test at line 630 covers this via `open_read`.
- Resource closure on refusal is asserted on all three paths; signing and append are never reached before refusal.
- C8a: bare `raise` preserves identity, traceback, existing `__cause__`, and interrupts. Mapped exceptions chain from the engine exception. Taxonomy unchanged.

## Validation gaps

- No live-backend test where `snapshot.represented.ordinal > captured.ordinal` on fresh read, runtime capture, or declaration prep. Only synthetic ledgers prove the clamp.
- No fresh-read wrong-coordinate regression (finding 3).
- Reported pass counts (engine 2,524, SDK 496, architecture 101) are unverified in this packet.
