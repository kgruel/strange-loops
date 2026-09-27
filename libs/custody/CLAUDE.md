# custody — signing composition

The store's at-rest signing composition: signer/verifier callbacks injected
into the engine. One module (`signing.py`), re-exported
flat from the package root.

**You are here** because you're changing what a valid signed store *is*.
Consumers: the SDK and explicit offline/out-of-repo composition. The JSON CLI
uses the SDK, not custody directly. Locator-based helpers take a
`vertex_path: Path`; target resolution belongs to the composing caller.

## Owns

- `TICK_DOMAIN` / `FACT_DOMAIN` — domain-separation constants. The
  architecture ratchet (`tests/architecture/`) pins these string
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
- `engine` never imports custody — INJECTION NOT IMPORT. The SDK composes runtime access; offline migration callers inject their signer.
- Verification asymmetry is deliberate: tick signatures pass under ANY
  declared key (receipt claim); fact signatures verify against THAT
  observer's key exactly (authorship claim).

## Tests

Direct unit tests live here (`tests/`). SDK, root migration integration, and
installed-wheel tests cover composition. The old frontend's tests retired with
`apps/loops`; they are not active coverage.
