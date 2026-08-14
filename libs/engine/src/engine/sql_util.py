"""sql_util — shared SQL predicate builders for the read paths.

Tiny by design: a predicate that must mean the same thing at every read
surface gets ONE spelling here, so no site can drift.
"""

from __future__ import annotations

__all__ = ["kind_subtree_predicate", "sqlite_busy"]


def sqlite_busy(exc: BaseException) -> bool:
    """Is this sqlite error a transient BUSY/LOCKED, not damage?

    Primary evidence is the error code (``SQLITE_BUSY`` 5 / ``SQLITE_LOCKED``
    6, low byte of any extended code); the message substring is the fallback
    for wrappers that lose the code. ONE spelling (SOL-R4-04): preflight's
    busy classification and the jsonl store's destructive-recovery guards
    must agree, or an authentic ``SQLITE_LOCKED`` ("database table is
    locked", which the old text-only guard missed) quarantines a healthy
    index before preflight can classify it as refused-busy.
    """
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        return (code & 0xFF) in (5, 6)
    msg = str(exc)
    return "database is locked" in msg or "database table is locked" in msg


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
