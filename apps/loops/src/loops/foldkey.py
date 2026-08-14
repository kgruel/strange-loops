"""foldkey — the canonical string projection of a fold-key value.

A fold key's identity IS its string projection
(decision:design/fold-key-string-projection, resolving
thread:fold-key-identity-native-vs-string): the engine projects with the
same ``str()`` at the fold boundary (``atoms.engine`` keyed folds), so fold
state, the CLI address grammar, the source-fact buckets
(``engine.vertex_reader``'s ``f"{kind}/{key}"``), and ``surface._row_key``
all carry one identity. This module is the projection applied wherever a
raw payload value must become a key on the read side.

Kept in its own leaf module (imports nothing) so ``surface`` and any
future consumer share the projection without cycles."""
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
