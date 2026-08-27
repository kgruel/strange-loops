"""Shared scaffolding for the store suite's arrival tests.

The stub signer kit, one home. Nothing in this package verifies a signature
— ``ArrivalLog.mint`` checks a founding key's SHAPE only — so the store lib's
tests mint and append with a deterministic stand-in rather than taking a
crypto dependency the library itself does not have. Names mirror
``libs/engine/tests/conftest.py``'s kit exactly, so the same scaffolding
reads the same from either side of the seam.
"""

from __future__ import annotations

import base64
import hashlib

# A shape-valid founding key in the raw-32-byte base64 wire format.
STUB_KEY = base64.b64encode(b"k" * 32).decode()


def stub_sign(observer: str, commitment: str) -> str:
    """A deterministic stand-in signer with the store's injected shape."""
    return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()
