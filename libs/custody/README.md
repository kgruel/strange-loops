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


## Explicit mapped bindings

`MappedCredentialProvider(root, namespace=..., receipt_observer=...)` provides
an opt-in alternative to locator-based custody. Exact namespace/observer
strings select an opaque managed key reference recorded with its public key.
All three signing domains use that binding with separate domain prefixes.
Hashed filesystem slots are storage details; labels retain their exact case,
Unicode spelling, and non-path characters. A binding does not authorize an
Arrival claim by itself: the engine separately checks captured history.

`for_write` returns lazy configuration. `resolve` loads and validates the
binding, private-derived public material, and any existing public convenience
file without creating or repairing anything. Missing unbound identities can
remain unsigned; malformed mappings, conflicting public material, missing
referenced private keys, and filesystem aliases refuse.

Explicit mutations are `create_binding(observer, token=...)`,
`import_legacy(vertex_path, observer, token=...)`, and
`bind_existing_ref(observer, key_ref, expected_public_key, token=...)`.
Import copies private material into managed custody and preserves the original
files. Reusing a managed reference is deliberate and does not introduce its
public key into an Arrival lineage. Existing bindings are not silently
replaced; local rotation is a separate future operation.

Mutations use a provider-wide POSIX advisory lock, durable intents, and
complete-file publication with no-clobber links. The supported filesystem must
provide those lock, link, and fsync semantics. Concurrent creators converge
on one binding; resolution remains read-only. There is no automatic orphan
cleanup or key deletion.

Keep the operation token when a mutation is interrupted.
`BindingMutationIncomplete` retains namespace, observer, token, candidate key
reference, and phase; the binding may already have been published.
`recover_binding(observer, token=...)` reconciles the retained intent and
candidate. It never replaces a missing key referenced by a published binding.
Explicit recovery may restore a missing token index from its retained intent
before a later candidate-key refusal; it does not claim zero filesystem effects
or create a key/binding in that case.
An import interrupted before copying private material needs the original
source re-presented with the same import token and expected public material;
recovery cannot invent that key. A completed imported candidate can recover
without the old source directory. Retrying with a different token does not
bypass an unfinished operation. Creation results report the returned binding
and effects of that invocation; they contain no private key material.
