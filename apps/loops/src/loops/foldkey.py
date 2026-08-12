"""foldkey — the canonical string projection of a stored fold-key value.

One projection, shared by every read-side consumer that must meet a stored
fold key coming from the OTHER side of the string boundary
(finding:chw-sol-r5-provenance-key-lookup):

- the engine folds by the NATIVE payload value (``is not None`` acceptance —
  numeric ``0`` and ``False`` are legal keys),
- the CLI address grammar and the source-fact buckets
  (``engine.vertex_reader``'s ``f"{kind}/{key}"``) carry the STRING form,
- ``surface._row_key`` projects rows with the same ``str()``.

Kept in its own leaf module (imports nothing) so ``surface`` and
``provenance`` — and any future consumer — share the projection without
cycles. Deliberately NOT an identity ruling: native ``0`` and string
``"0"`` stay distinct fold entries that happen to project to the same
display key; merging them is held at
thread:fold-key-identity-native-vs-string.
"""
from __future__ import annotations

from typing import Any


def project_fold_key(val: Any) -> str | None:
    """Project a stored fold-key value to its canonical string form.

    ``None`` (no key) stays ``None`` — mirroring the engine's fold
    acceptance gate; everything else is ``str()``.
    """
    if val is None:
        return None
    return str(val)
