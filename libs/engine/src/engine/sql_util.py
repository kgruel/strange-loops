"""sql_util — shared SQL predicate builders for the read paths.

Tiny by design: a predicate that must mean the same thing at every read
surface gets ONE spelling here, so no site can drift.
"""

from __future__ import annotations

__all__ = ["kind_subtree_predicate"]


def kind_subtree_predicate(kind: str, column: str = "kind") -> tuple[str, list[str]]:
    """``(sql, params)`` for "exactly this kind, or its dotted subtree".

    Matches ``kind`` exactly and anything starting with ``kind + "."``
    (``"ui"`` matches ``"ui"`` and ``"ui.key"``, never ``"uix"``).

    Binary equality / ``substr`` prefix — deliberately not LIKE, which is
    wrong twice here (SOL-R2-02): ``_``/``%`` are LIKE wildcards (and valid
    kind characters), and LIKE compares ASCII case-insensitively; ``substr``
    is an exact binary compare. Not GLOB either: ``*``/``?``/``[`` would
    need escaping. The three params are the kind repeated.
    """
    return (
        f"({column} = ? OR substr({column}, 1, length(?) + 1) = ? || '.')",
        [kind, kind, kind],
    )
