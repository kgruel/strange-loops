# custody

Loops signing composition — the store's at-rest signing format, below every writer.

Owns the `loops-tick-v1` / `loops-fact-v1` domain-separation constants, the
custody-co-located `keys/` layout (per-observer nesting + flat self-observer
back-compat), the signer/verifier builders, and `ensure_signing_key`. Observer
names remain exact identities: a filesystem spelling collision refuses rather
than borrowing another observer's key. A renamed vertex may retain a nested
self key; all signer domains and `ensure_signing_key` select that one key.
Identical flat and nested self copies are one self key; conflicting key material
refuses until repaired. A differently spelled nested observer remains a
distinct observer and is never used as the self fallback. Observer components
cannot name the reserved `ed25519.key` or `ed25519.pub` custody files when
mapped to directories. This is a local custody-layout restriction, not an
observer label restriction in the event protocol. A self observer with such a
stem uses only the flat layout.

Signer loading never creates keys. Concurrent explicit key creation publishes
one complete private key; all callers load that key and derive its public file.

Any client that emits signed facts or ticks must compose identically or
`sl store verify` reports breaks — that's why this is a lib, not CLI code.
Depends on `sign` (loops-agnostic Ed25519 primitives) and `engine`
(store-canonical declaration resolution). The engine itself never imports
this — it takes signer callables by injection.
