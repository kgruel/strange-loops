# D0/D2 code audit: credential requests and local binding persistence

## Current seams

The neutral engine contract is deliberately callback-only:
`engine.credentials.WriteCredentials` has independent tick, inner-fact, and
outer-Arrival signer callables; `CredentialProvider.for_write(vertex: Path)`
has only a mutable locator input
([credentials.py:18-36](../../../libs/engine/src/engine/credentials.py)). It carries
no provider namespace, requested observer, opaque reference, public key, or
captured lineage/position. That cannot represent D0's binding selection or
supply public evidence for checking it.

SDK `CustodyCredentialProvider.for_write` selects from the vertex path and
builds all three callbacks at once
([emit.py:92-107](../../../libs/sdk/src/sdk/emit.py)). It correctly keeps domains
separate. It still lets the callback select an author only after receipt
planning. The currently refused `key_dir` override is correctly not a
namespace substitute (C4).

Arrival call sites that must migrate as one coherent contract are:

| Entrypoint | Current credential seam |
| --- | --- |
| preview, ordinary emit, batch | `sdk.emit` calls `for_write(target_path)` before the engine prepare call (emit.py:183, 425, 682). |
| source invocation | `sdk.sources` calls it once before source planning (sources.py:456-63). |
| declaration/kind/grant/revoke edits | `sdk.declare._arrival_credentials` accepts either a raw `WriteCredentials` or `for_write(vertex)`; `sdk.kind` routes edits through it. |
| legacy held writer/ceremony | `engine.handle.receive` calls it per write (handle.py:1500); ceremony reads only `.fact_signer` (ceremony.py:562). These are compatibility consumers. |
| initialization and observer keygen | SDK directly calls `ensure_signing_key` and signer factories (declare.py:510-19; kind.py:506-15), bypassing the provider. |

Runtime uses the supplied fact signer for inner rows, Arrival signer for fact
and packed-batch envelopes, and tick signer for generated ticks
([runtime_write.py:669-75, 973-88, 1011-20, 1284-92](../../../libs/engine/src/engine/runtime_write.py)).
The tick envelope's custodian remains a separate physical-genesis wire field;
the provider must not infer an inner tick signer from it.

## Current custody compatibility behavior

`custody.signing` maps a vertex path to `<parent>/keys`. The flat key is
only the exact locator stem's self key; other observers use exact nested path
components. `_observer_key_dir` rejects invalid/reserved components, case
aliases, symlinks, and regular-file components; `_self_key_dir` refuses
different flat/nested public keys but permits identical copies
([signing.py:39-183](../../../libs/custody/src/custody/signing.py)). Missing key
material is an honest unsigned result; ambiguous/aliased material raises.
A new provider must preserve that distinction rather than minting or borrowing
a key on an unresolved mapping.

This layout is a compatibility resolver, not a D0 identity model: it derives
self identity from the vertex filename and selects nested references by a
filesystem spelling. In particular, initialization before its vertex exists
uses the future filename stem. If founding observer differs, its nested
fact/Arrival key can exist while `tick_signer_for` selects no self key.
That is current permitted unsigned-tick behavior, but it proves why tick
selection needs an explicit request rather than a filename rule.

D2 also cannot treat `ed25519.pub` as trusted mapping evidence today:
`sign.ed25519.load` reads only `ed25519.key`, and
`load_or_generate` then rewrites the convenience `.pub` file
([ed25519.py:146-69](../../../libs/sign/src/sign/ed25519.py)). A migration/binding
validator must derive public material from the private key and refuse a
present mismatching or malformed `.pub` before it invokes that convenience
repair path.

## Recommended bounded implementation split

1. **Engine-neutral request context.** Add a frozen request/evidence value
   beside `WriteCredentials`, not a custody import. It needs provider
   namespace, exact observer, requested domain/purpose, optional transitional
   locator, and the operation's lineage/captured head/proposed position where
   available. The response exposes opaque key reference plus public-key
   material and domain signer; engine code checks history at its existing
   capture/successor point. A compatibility adapter may still implement
   `for_write(vertex)`, but it must be explicit and must not claim mapped
   evidence.
2. **Move selection to the captured operation boundary.** Ordinary/batch
   preparation knows the fact observer; declaration preparation knows its
   author and successor rule; runtime knows a generated tick and physical
   genesis. The engine coordinator should request those capabilities after
   it has the relevant capture, while SDK passes the provider rather than
   preselected location-only callbacks. Do not retrofit legacy handle/ceremony
   beyond an adapter in this slice.
3. **Separate mapped filesystem provider.** Keep
   `CustodyCredentialProvider` as the location-scoped compatibility provider;
   a new mapped provider takes explicit namespace configuration.
   Persist exact-label -> opaque-reference plus derived public material in a
   provider-owned mapping; private filename layout remains private. Creation
   must publish one key and one mapping atomically enough that concurrent
   losers load the winner. A mapping that points to a missing key refuses.
   A private key without a mapping after interruption is not automatically
   adopted; recovery is explicit.
4. **Compatibility onboarding, no automatic migration.** A caller can
   explicitly bind an unambiguous legacy flat/nested key with its exact
   observer label and self-label evidence, after validating private-derived
   public material and existing `.pub`. Do not scan and guess bindings,
   infer a namespace, lower alias/ambiguity refusals, move live keys, or
   overload `key_dir`.

## Acceptance

Use subprocess/process-level temporary `XDG_STATE_HOME`,
`XDG_CONFIG_HOME`, and `LOOPS_HOME` for every custody fixture. Prove
exact-label namespace separation, all three domains, no key mint on a missing
read binding, and refusal on mapping/key/public mismatch. Exercise declaration
successor validation, ordinary/batch author selection, explicit tick selection,
and initialization bootstrap separately. Add interruption/concurrent-create
tests for private-key publication and mapping publication; no test may use
real user keys or stores.

Unresolved policy decisions: persistent mapping format/location and recovery
UX; whether one response can carry all operation capabilities or requests are
per domain; and the explicit bootstrap authority for a namespace. None require
an Arrival wire change.
