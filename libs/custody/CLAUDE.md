# custody — signing composition

The store's at-rest signing format: what any writer must compose to produce
a store that `sl store verify` accepts. One module (`signing.py`), re-exported
flat from the package root.

**You are here** because you're changing what a valid signed store *is*.
Consumers: `apps/loops` (the CLI verbs) and out-of-repo clients (e.g. tasked).
Every function takes a `vertex_path: Path` — custody never resolves vertex
locations; that's client knowledge (`loops.commands.resolve` today, an
eventual client lib later).

## Owns

- `TICK_DOMAIN` / `FACT_DOMAIN` — domain-separation constants. The
  architecture ratchet (`tests/test_architecture.py`) pins these string
  literals to exactly this lib: **never re-hardcode them elsewhere**, import.
- `keys/` custody layout — flat `keys/ed25519.key` is the self-observer
  (delta-2 back-compat); `keys/<observer>/` per-observer (delta 3).
- `ensure_signing_key` — the single minting entry point. Its gitignore side
  effect is protocol, not convenience: key CREATION owns the committed-key
  mitigation. Everything else only loads.
- Signer/verifier builders matching engine's injection contracts
  (`tick_signer`, `fact_signer`, `verify_chain` key-lookup).

## Boundaries

- Depends on `sign` (loops-agnostic Ed25519 — keep it that way) and `engine`
  (`load_declaration` for the store-canonical observer-key registry).
- `engine` never imports custody — INJECTION NOT IMPORT. Apps compose.
- Verification asymmetry is deliberate: tick signatures pass under ANY
  declared key (receipt claim); fact signatures verify against THAT
  observer's key exactly (authorship claim).

## Tests

Direct unit tests here (`tests/`). The full composition — real CLI emit →
verify paths — lives in `apps/loops/tests/test_tick_signing.py` and
`test_fact_signing_composition.py`.
