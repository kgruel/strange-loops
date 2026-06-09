"""sign — JWT minting/verification, key management, and JWKS publication.

Utility-library scope. Public surface re-exported here for flat-import
convenience; the per-module imports (`sign.keys`, `sign.jwt`, `sign.jwks`)
are equally public.

`sign.ed25519` (detached digest signatures with domain separation) is
namespaced-only: its names deliberately mirror `sign.keys`
(`load_or_generate`), so it is not re-exported flat. Import as
``from sign import ed25519``.
"""

from sign.jwks import build_document, build_openid_configuration, parse
from sign.jwt import mint, verify
from sign.keys import KeyStore, PublicKey, load_or_generate

__all__ = [
    "KeyStore",
    "PublicKey",
    "build_document",
    "build_openid_configuration",
    "load_or_generate",
    "mint",
    "parse",
    "verify",
]
