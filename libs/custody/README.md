# custody

Loops signing composition — the store's at-rest signing format, below every writer.

Owns the `loops-tick-v1` / `loops-fact-v1` domain-separation constants, the
custody-co-located `keys/` layout (per-observer nesting + flat self-observer
back-compat), the signer/verifier builders, and `ensure_signing_key`.

Any client that emits signed facts or ticks must compose identically or
`sl store verify` reports breaks — that's why this is a lib, not CLI code.
Depends on `sign` (loops-agnostic Ed25519 primitives) and `engine`
(store-canonical declaration resolution). The engine itself never imports
this — it takes signer callables by injection.
