# Primary triage

Fable 5.1 returned ACCEPT on frozen baseline `72faf1d5`, with four P2 items to
close before cutover. The first review packet is immutable. Its source-drift
receipt records the runner's receipt-observer fix made during review; that
change and the subsequent corrections are included in the second review.

1. **Strict negative-timestamp hydration:** preserve the prior strict `ts >= 0`
   hydration selection. Full physical tick capture remains available to C6 and
   custody predecessor/window checks. Fresh replay uses post-anchor ordinals,
   including negative event timestamps. Added a strict reset/predecessor test
   and clarified the C6 design decision.
2. **Self-consistent intent downgrade/upgrade:** recovery integration now changes
   both root mode and draft payload in both directions, preserving stale
   signatures. Cryptographic verification refuses it. The field-only mutation
   is also retained. Documentation describes cross-checking and authenticating
   the mode rather than implying the redundant intent field is absent.
3. **Physical emitted-row evidence:** reread the emitted fact at its commit
   ordinal, require equality with the returned commit row, then verify its FACT
   and ARRIVAL signatures.
4. **Initial state/history evidence:** assert adoption mode, exact strict/fresh
   state-generation metadata, fresh zero-input declared fold state, and history
   totals/per-kind counts adjusted by migration drops.

The real fresh rehearsal additionally exposed a runner configuration omission:
receipt-observer was unset, so a seal requiring a tick refused before append.
The provider now binds the requested observer; a subprocess regression proves
fresh seal emits fact plus tick. The first refused copy is retained as evidence.

## Missing-context closure

Sol audited all protocol-version uses. The only additional production issue was
CLI absorb advertising the maximum supported version 2 while emitting default
protocol 1; receipts now use the actual genesis payload version, pinned by tests.
Migration and store emitters remain v1 by default. No Go source exists here.
Continuity callsites carry the validated epoch, candidate tuple consumers match,
and declaration/source SDK modules do not consume the changed capture fields.

Luna independently confirmed tuple projection equality, existing documented SDK
declaration-error behavior, and legacy `open_vertex`/CLI fail-closed handling of
fresh protocol 2. A synthetic CLI read refused with no stdout. No normalization
or error-taxonomy change is required. Period-start wording now distinguishes
live/pending planning from hydration.

## Nonblocking follow-ups

- Epoch physical-row validation entails an O(history) walk; cache/lazy aggregate
  optimization can be considered without weakening downgrade checks.
- Low-level callers without a physical anchor remain a trusted API boundary;
  supported Arrival read/write paths provide custody evidence. This is not a
  claim of cryptographic re-verification on every read.
- Document exact payload-text/signature adapter expectations more centrally and
  consolidate protocol payload builders/constants in a future cleanup.
- Malformed legacy protocol values now fail closed intentionally.

Final correction review and real-copy proof are recorded separately in the
second review and fresh rehearsal artifacts.
