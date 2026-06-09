# sign — JWT, keys, JWKS

Utility library: mint and verify JWTs, manage RSA signing keys, publish JWKS
and OpenID Connect discovery documents. Framework-free — consumers wrap the
pure-function outputs in their own HTTP layer.

**You are here.** `libs/sign` is a utility library, **not** a substrate primitive.
It depends on `cryptography`, `pyjwt`, and `python-ulid`. No internal loops deps
(no `atoms`, no `engine`).

## Public surface

The public API is exactly what each module's `__all__` exports — re-exported flat
from the package root. Both forms work; prefer whichever reads better at the call site.

```python
# Flat:
from sign import (
    KeyStore, PublicKey, load_or_generate,        # keys
    mint, verify,                                 # jwt
    build_document, build_openid_configuration, parse,  # jwks
)

# Namespaced:
from sign.keys import KeyStore, PublicKey, load_or_generate
from sign.jwt import mint, verify
from sign.jwks import build_document, build_openid_configuration, parse
```

### `sign.keys`

- `KeyStore` — owns one RSA signing keypair. Internal attributes are
  underscore-prefixed (`_signing_key`, `_kid`, `_jwk_dict`); they have no
  stability contract for external consumers. The only public method is `public_keys()`.
- `PublicKey(kid, alg, key)` — frozen dataclass; the verify-side input shape.
- `load_or_generate(dir)` — returns a KeyStore. Generates a fresh RSA-2048
  keypair if `dir` is empty; otherwise loads what's there.

`KeyStore.public_keys()` returns a `list[PublicKey]`. Today the list has one
element; the shape anticipates key rotation.

### `sign.jwt`

- `mint(*, keystore, issuer, claims, ttl_seconds, jti=None) -> (token, jti)` —
  caller builds the claims dict (sub, aud, act, scope, …). Library only injects
  `iss`, `iat`, `exp`, `jti`. Claim contents are not inspected.
- `verify(token, *, public_keys, issuer, audience) -> claims_dict` — looks up
  the signing key by `kid` from the token header. Validates iss/aud/exp/signature.
  Claim-content validation (`sub` non-empty, RFC 8693 `act` shape, scope checks)
  is the caller's responsibility.

`audience` is a required `str`. Use the self-verify path with
`keystore.public_keys()` or the remote-verify path with `jwks.parse(fetched_doc)`.

### `sign.ed25519` (namespaced-only: `from sign import ed25519`)

Detached digest signatures with mandatory domain separation — the loops
provenance-arc primitive (tick signing, delta 2). Deterministic Ed25519
(RFC 8032). Not re-exported flat: names mirror `sign.keys` by design.

- `Keypair(private, public)` — frozen; `.public_b64` is the raw-32-byte
  base64 wire/registry format (44 chars, inline-able in declarations).
- `load_or_generate(dir)` — `ed25519.key` (PKCS8 PEM, 0600) +
  `ed25519.pub` (the base64 registry string verbatim).
- `sign(keypair, digest, *, domain) -> str` — base64 signature over
  `domain + b":" + digest`. Empty domain raises.
- `verify(public, signature_b64, digest, *, domain) -> bool` — False on any
  verification failure (bad base64, wrong key/domain/digest), never raises
  for those.
- `public_key_b64` / `public_key_from_b64` — registry format conversions.

The domain constant (e.g. `loops-tick-v1`) belongs to the composing layer,
not this library.

### `sign.jwks`

- `build_document(keystore) -> dict` — JWKS document per RFC 7517.
- `build_openid_configuration(issuer, *, jwks_uri, **extra) -> dict` — OIDC
  discovery doc. Additional fields (response_types_supported, etc.) pass
  through `**extra` verbatim.
- `parse(jwks_dict) -> list[PublicKey]` — inverse of `build_document` for
  the verify-side; consumers use this to convert a fetched JWKS into the input
  shape `verify()` accepts.

## Stability posture

**Utility-library scope. NOT part of the loops protocol.**

Breaking changes ship via a tagged loops release; each consumer (vouch, pile,
comms) bumps their `pyproject.toml` pin when ready. Coordinated upgrade, not
atomic monorepo-wide commits. This is the same posture as `libs/store` — useful
shared code, not substrate.

**The public surface** is exactly what `__init__.py` re-exports and what each
module's `__all__` declares. Submodules without a leading underscore are public.
Anything underscore-prefixed (attributes on KeyStore, helper modules if added)
is internal — no stability contract.

## Port history

Sourced from `~/Code/commission/src/commission/server/`:
- `keys.py` → `sign/keys.py`. Added `PublicKey` dataclass + `KeyStore.public_keys()`.
  Internal attrs underscored.
- `jwt_mint.py` → `sign/jwt.py`. Reshape: `mint` now takes a claims dict instead
  of named domain fields (agent_username/fellow_username/delegation_id leaked
  domain vocab); `verify` now takes `public_keys: Sequence[PublicKey]` instead
  of a keystore (supports both self-verify and remote-verify without dispatch);
  sub/act content validation was dropped (caller's domain); audience is now a
  required `str`.
- `wellknown.py` → `sign/jwks.py`. Litestar handlers replaced with pure
  functions returning dicts; consumers wrap them in their own framework.
  `parse()` added as the remote-verify normalization bridge.

## Build & Test

```bash
uv run --package sign pytest libs/sign/tests           # all tests
uv run --package sign pytest libs/sign/tests/test_jwt.py  # single file
uv run ruff check libs/sign                            # lint
```
