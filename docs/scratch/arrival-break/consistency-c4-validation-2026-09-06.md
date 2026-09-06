# C4 independent validation — September 6, 2026

## Final validation

Against the frozen provider tests:

* From `libs/sdk`: `uv run pytest -q` — **528 passed** in 22.74s.
* From the repository root: `uv run pytest tests/architecture -q` — **101 passed** in 5.50s.
* From `libs/sdk`: `uv run ruff check src/sdk/emit.py tests/test_emit.py` — **clean**.

The `emit.py` and `test_emit.py` SHA-256 values were identical before and
after these checks. Raw logs are in `/tmp/loops-arrival-c4-2026-09-06/`.

```text
6a73c80688aae65b35f1690b9fa1908aaebd1e4ae591f43817cd5cc2b142f129  libs/sdk/src/sdk/emit.py
785414bfa3234340aade6101b597503169d82925b145a43f3fadc77f56504edd  libs/sdk/tests/test_emit.py
```

## Scope

This audit checks the SDK custody-provider boundary, all provider callsites,
and the relationship between local signing material, public observer
registration, and the Arrival signing domains. It does not change production or
tests.

## Callsite inventory

`CustodyCredentialProvider` is public through `sdk.__init__` and is constructed
as the default provider by `emit.py`, `declare.py`, `kind.py`, and
`sources.py`. Its `for_write(vertex)` returns the three independent
`WriteCredentials` callables: fact, Arrival, and tick. The callables are
constructed by `custody.signing` from the vertex path, so they use the
co-located `keys/` layout and exact observer directory rules.

The SDK write entrypoints that accept a `CredentialProvider` are
`emit_fact`, `emit_batch`, `preview_emission`, `add_kind`, `edit_kind`,
`remove_kind`, `revoke_observer`, and `run_sources`; declaration edits also
accept a provider or already-created `WriteCredentials`. These paths call
`for_write` and pass all three domains into the engine. No current caller
passes `key_dir` to the provider except the regression tests.

`grant_observer` is a separate registration path. With `key=None`,
`kind.py:466-484` calls `custody.ensure_signing_key(vertex_path,
observer=observer_name)` directly, then uses the configured provider only for
the authoring declaration append. Thus a custom `CredentialProvider` controls
the declaration author's signing callables but does not control where the new
observer's registered public key is generated. This is a real API limitation;
it is safe only while registration remains explicitly co-located custody or
the caller supplies `key=`. A future mapped provider must cover registration
and all three signing domains together.

Arrival initialization has the analogous explicit boundary: the default path
uses `ensure_signing_key` plus the fact and Arrival signers, while complete
custom initialization requires caller-supplied `signer`, `fact_signer`, and
`public_key` (`declare.py:505-526`). A partial custom pair is refused. This
keeps key publication and both signature domains matched, but there is no
generic `CredentialProvider` parameter for initializer key generation.

## C4 disposition and risks

The accepted C4 fix makes `CustodyCredentialProvider(key_dir=...)` refuse
immediately with `SdkValueError` (`sdk/emit.py:95-100`) before any signer lookup
or filesystem operation. The paired tests cover positional and keyword forms,
assert no custody resolver is called, and check a missing directory stays absent
while an existing directory and its sentinel content remain unchanged.
This resolves the prior accepted-but-unused configuration hazard
without inventing a second key-root mapping.

The refusal is the correct bounded behavior under the current custody contract:
`fact_signer_for`, `arrival_signer_for`, and `tick_signer_for` each accept a
vertex path, and the public key-history verifier binds exact observer labels to
introduced keys. Silently treating `key_dir` as a root for only one signer or
for registration would create domain/key mismatches. The compatibility impact
is that callers should use the default constructor only when the co-located
custody layout is intended. Callers that intended an alternate key root need an
explicit custom signer/provider and must arrange observer registration
consistently; no migration of existing co-located keys is implied.

The remaining registration limitation is deferred API debt rather than a C4
regression. A custom provider plus `grant_observer(key=None)` can still mint the
new observer key under default co-located custody while signing the declaration
with custom author credentials. The public result remains cryptographically
coherent when the supplied `key` is intentional, but a deployment expecting
the provider to own all key material must pass the key explicitly or wait for a
provider API that accepts observer and signing-domain requests. No current
contract says `CredentialProvider` owns public-key generation, so this should
not be presented as a failed C4 guarantee.

## Validation status

The source audit found no other provider callsite that interprets `key_dir` or
silently falls back to a legacy writer. The concrete C4 acceptance boundary is
the early typed refusal and no-resolution/no-filesystem side effect, followed
by unchanged default three-domain signing. The final full SDK and architecture
results above were run after the implementation freeze.
