# S4 — persisted signature state in write receipts (impl report)

Branch: `slice/s4-receipt-attestation` (off wave HEAD 4b5fa979)
Commits: 22c8dba3 (engine), 2aafd2f1 (loops CLI emit mark)

## What was built

`Receipt` (engine/vertex.py) gains two additive, defaulted fields:

- `attestation: FactAttestation | None` — `FactAttestation(signed, observer,
  signature_present)`, read back from the COMMITTED fact row via a new
  read-only store method `SqliteStore.fact_signature(fact_id)`.
- `tick_attestation: TickAttestation | None` — `TickAttestation(signed,
  signature_present, chained)`, read back from the COMMITTED tick row via
  `SqliteStore.tick_signature_state(tick_id)`. `append_tick` now returns the
  committed tick row id (its previous `None` return had no consumers) so the
  receipt can address that row; `_fire_live_boundaries` returns
  `(tick, tick_row_id)`.

**Tri-state contract** (documented on Receipt): `None` = "store doesn't
report attestation" (EventStore/FileStore, storeless vertex, gate rejection)
— never "unsigned". `signed=False` is a positive claim from a committed row.
`signed` and `signature_present` coincide at write time (same committed
column); kept distinct per the P1 sketch so verification-grade claims can
land without renaming.

Neither read-back ever migrates schema; pre-signature/pre-chain schemas
report honestly (`None` signature, `chained=False`). `JsonlStore` inherits
both (sqlite index row is written inside the same append).

Composition: `VertexProgram.receive`/`receive_as` and
`VertexHandle.receive`/`receive_as` (S3) return the engine `Receipt`
unchanged, so `ReceiveResult.receipt` carries attestation with zero changes
to those layers.

CLI: `emit`'s tick mark (`signed`/`unsigned`) previously inferred from
whether a tick signer was wired — the exact configuration inference the
contract condemns. It now reads `receipt.tick_attestation`, falling back to
the old inference only on tri-state `None`.

## Oracle results

Tests: `libs/engine/tests/test_receipt_attestation.py`, parametrized
sqlite + jsonl-canonical (15 tests, all pass).

1. Signed store + signing observer → `signed=True`, and the committed row
   verifies via `verify_facts(verifier=...)` (fake deterministic scheme),
   `ok=True, signed=1, sig_checked=True`. PASS.
2. Configured-but-None signer → bob's receipt `signed=False` while alice's
   is `signed=True` under identical configuration; cross-checked against
   `store.fact_signature` both ways. PASS.
3. Unsigned store → `FactAttestation(signed=False, ...)`. PASS.
4. Tick-fired receive → `TickAttestation(signed=True, chained=True)` from
   the committed tick row; cross-checked via `verify_chain(verifier=...)`
   (`ok=True, signed=1`). Unsigned-tick sibling reports `signed=False,
   chained=True`. PASS.
5. Mutation check: temporarily pointed `_fact_attestation` at
   `store._fact_signer is not None` (config inference) → the alice/bob test
   failed in both parametrizations (2 failed); reverted → green. KILLED.

Suites: `libs/engine/tests` 1410 passed; `apps/loops/tests` 2521 passed,
1 xfailed. (One transient `test_topology` ModuleNotFoundError('loops') flake
appeared once, reproduced at baseline behavior only intermittently, and
passes on re-run at both baseline and with changes — env race, not this
slice.)

## Deviations / scope notes

- **Ceremony receipts need no extension**: `absorb_genesis`/`absorb_edit`
  already refuse unsigned rows before writing and return `"signed": True`
  from the actual signature outcome — the honesty is already satisfied, so
  no shape change was forced.
- **Mutation oracle direction**: the "row signed but config says unsigned"
  direction is unreachable through `receive` (no `signature_override` on
  that path); coverage is via the same-config/different-row alice-bob pair,
  which kills the config-inference mutant in both directions of claim.
- `Receipt` consumers audited before the change (CLI emit, hooks, tasks,
  handle): all access fields by name; new fields are defaulted → additive.
