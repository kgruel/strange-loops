# sign

JWT minting and verification, RSA key management, and JWKS publication.

A utility library — not a substrate primitive. Consumers (vouch, pile, comms)
import the public surface for OIDC-style cryptographic identity workflows.

## Usage

```python
from sign import KeyStore, load_or_generate, mint, verify, build_document

keystore = load_or_generate("/var/lib/myapp/keys")

# Mint a JWT — caller builds claims dict, library injects iss/iat/exp/jti.
token, jti = mint(
    keystore=keystore,
    issuer="https://issuer.example",
    claims={"sub": "alice", "aud": "api.example", "scope": "read"},
    ttl_seconds=900,
)

# Verify against the issuer's own keys (self-verify path).
claims = verify(
    token,
    public_keys=keystore.public_keys(),
    issuer="https://issuer.example",
    audience="api.example",
)

# Publish a JWKS document — wrap in your framework's HTTP handler.
jwks_doc = build_document(keystore)
```

## Modules

- `sign.keys` — `KeyStore`, `PublicKey`, `load_or_generate`
- `sign.jwt` — `mint`, `verify`
- `sign.jwks` — `build_document`, `build_openid_configuration`, `parse`
