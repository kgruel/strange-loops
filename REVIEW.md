# Review: libs/sign-carve

## Critical

None.

## Important

None.

## Minor

None.

## Questions

None.

## Notes

- Prior Important finding for missing root runtime dependencies is fixed: `pyproject.toml:13`-`pyproject.toml:15` declares `pyjwt[crypto]>=2.9`, `cryptography>=43`, and `python-ulid>=3.0`; `uv.lock:858`-`uv.lock:874` reflects those dependencies for `strange-loops`.
- Prior Important finding for unsupported JWKS algorithms is fixed: `libs/sign/src/sign/jwks.py:53`-`libs/sign/src/sign/jwks.py:57` now skips entries unless `kty == "RSA"` and `alg == "RS256"`, and `libs/sign/tests/test_jwks.py:80`-`libs/sign/tests/test_jwks.py:89` covers an RSA `HS256` entry.
