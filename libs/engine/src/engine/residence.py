"""residence — where a vertex's store lives, and which file is authoritative.

A vertex declares one ``store`` locator. That locator names the **canonical
artifact**, and its extension is the mode switch:

===============  ==========================================================
``.jsonl``       JSONL-canonical (design/architecture/jsonl-canonical-store).
                 The log is the store; the sqlite index is derived and
                 rebuildable, and lives at the sibling ``.db`` path.
``.db``          sqlite-canonical (the status quo). No log.
``.sqlite``
===============  ==========================================================

Extension-as-switch is not new here: :func:`engine.compiler.materialize_vertex`
already dispatched ``.db``/``.sqlite`` to ``SqliteStore`` and everything else
to the flat ``EventStore``, and :func:`engine.jsonl_store.log_path_for` already
encodes the ``.db``↔``.jsonl`` sibling pair. This module states the rule once
and gives every caller the two paths it can want:

- :func:`canonical_store_path` — the declared artifact, absolute.
- :func:`index_path_for` — the sqlite file to *connect* to.
- :func:`resolve_store_path` — both composed, the read path's workhorse.

Why the read path resolves to the index and not the canonical file: reads are
sqlite reads (``StoreReader``, FTS, ``since``/``between``, direct
``sqlite3.connect``) and stay exactly as they are under the flip. Only the
*write* path cares which file is authoritative, and it asks with
:func:`is_jsonl_canonical`. The three-line "resolve relative to the vertex
file" idiom this replaces was duplicated at ~25 call sites; collapsing it is
what makes one translation point possible at all.

Pure functions over paths — no I/O, no store construction. Materializing a
missing index is :func:`engine.jsonl_store.ensure_index`, which needs I/O and
therefore does not live here.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "CANONICAL_LOG_SUFFIX",
    "SQLITE_SUFFIXES",
    "canonical_store_path",
    "index_path_for",
    "is_jsonl_canonical",
    "resolve_store_path",
]

CANONICAL_LOG_SUFFIX = ".jsonl"
SQLITE_SUFFIXES = (".db", ".sqlite")


def is_jsonl_canonical(declared: Path | str) -> bool:
    """True when this store locator names a JSONL-canonical log."""
    return Path(declared).suffix == CANONICAL_LOG_SUFFIX


def canonical_store_path(declared: Path | str, vertex_path: Path | None) -> Path:
    """The declared artifact as an absolute path.

    Relative locators resolve against the *vertex file's* directory, never
    the process cwd — a vertex is portable, a cwd is not.
    """
    path = Path(declared)
    if not path.is_absolute() and vertex_path is not None:
        path = (Path(vertex_path).parent / path).resolve()
    return path


def index_path_for(canonical: Path | str) -> Path:
    """The sqlite file to connect to for a given canonical locator.

    JSONL-canonical → the sibling ``.db``; sqlite-canonical → itself.
    Idempotent: feeding an index path back through returns it unchanged.
    """
    path = Path(canonical)
    if is_jsonl_canonical(path):
        return path.with_suffix(".db")
    return path


def resolve_store_path(declared: Path | str, vertex_path: Path | None) -> Path:
    """Declared locator → absolute sqlite path to read from.

    The single translation point for the read path. Does not check
    existence and does not materialize a missing index; callers that must
    tolerate a fresh clone go through :func:`engine.jsonl_store.ensure_index`.
    """
    return index_path_for(canonical_store_path(declared, vertex_path))
