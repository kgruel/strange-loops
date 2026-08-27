"""residence — where a vertex's store lives, and which file is authoritative.

A vertex declares one ``store`` locator. That locator names the **canonical
artifact**, and its extension is the mode switch — :func:`canonical_mode`,
one function with three arms:

===============  ==========================================================
``.arrival``     arrival-canonical (decision:design/arrival-sliceA-
                 authority). The arrival log holds custody; the sqlite
                 index at the sibling ``.db`` is derived and rebuildable.
``.jsonl``       log-canonical, the pre-arrival shape. The log is the
                 store; the sqlite index is derived, at the sibling
                 ``.db``.
``.db``          sqlite-canonical (the original shape). No log.
``.sqlite``
===============  ==========================================================

There is deliberately no stored mode flag, meta key, or configuration: the
mode is the declared locator's suffix and nothing else. A mode that lived in
two places could disagree, and a mode that lived in mutable state would be a
maintenance surface custody law forbids (arrival law 5).

Extension-as-switch is not new here: :func:`engine.compiler.materialize_vertex`
already dispatched ``.db``/``.sqlite`` to ``SqliteStore`` and everything else
to the flat ``EventStore``. This module states the rule once and gives every
caller the paths it can want:

- :func:`canonical_store_path` — the declared artifact, absolute.
- :func:`index_path_for` — the sqlite file to *connect* to.
- :func:`canonical_for` — its inverse, given an explicit mode. Under three
  modes a ``.db`` has two possible canonical siblings, so a pure function of
  the index path alone cannot answer; existence-based disambiguation is
  :mod:`engine.probe`'s, where existence checks are legal.
- :func:`resolve_store_path` — declared → index composed, the read path's
  workhorse.

Both directions of the sibling bijection live here: a naming rule stated in
two modules is a naming rule that can disagree. The arrival companion-file
names (``.arrival.lock``, ``.arrival.tmp``) have their one spelling in
:mod:`engine.arrival` and are re-exported, not re-derived.

Why the read path resolves to the index and not the canonical file: reads
are sqlite reads (``StoreReader``, FTS, ``since``/``between``, direct
``sqlite3.connect``) and execute through the projection in every mode —
arrival law 1 permits exactly that. Only the *write* path cares which file
is authoritative, and it asks :func:`canonical_mode`.

Pure functions over paths — no I/O, no store construction. Materializing a
missing index is :func:`engine.jsonl_store.ensure_index`, which needs I/O and
therefore does not live here.
"""

from __future__ import annotations

from pathlib import Path

from .arrival import ARRIVAL_SUFFIX, arrival_path_for, lock_path_for, tmp_path_for

__all__ = [
    "ARRIVAL_SUFFIX",
    "CANONICAL_LOG_SUFFIX",
    "SQLITE_SUFFIXES",
    "arrival_path_for",
    "canonical_for",
    "canonical_mode",
    "canonical_store_path",
    "index_path_for",
    "lock_path_for",
    "resolve_store_path",
    "sqlite_sidecars",
    "tmp_path_for",
]

CANONICAL_LOG_SUFFIX = ".jsonl"
SQLITE_SUFFIXES = (".db", ".sqlite")

_INDEX_SUFFIX = ".db"

# Which suffix a canonical mode's artifact carries — the sibling bijection's
# one spelling, read by canonical_for. sqlite maps to itself: the index IS
# the canonical artifact there.
_MODE_SUFFIX = {"arrival": ARRIVAL_SUFFIX, "jsonl": CANONICAL_LOG_SUFFIX}


def canonical_mode(declared: Path | str) -> str:
    """Which artifact class is authoritative for a store locator.

    ``"arrival"`` | ``"jsonl"`` | ``"sqlite"`` — one function, three arms,
    callers compare. A family of per-mode booleans is how a two-mode
    architecture creeps back in, so there isn't one.

    Any suffix that is not a log suffix answers ``"sqlite"``: that is what
    ``open_canonical_store`` does with such a path (connect to it as
    sqlite) — with one named exception, ``engine.compiler``'s flat
    ``EventStore`` fallback for suffixes outside the store family, which
    checks the suffix itself before consulting this switch. "Is this a
    loops artifact at all" is :func:`engine.probe.probe_target`'s question,
    not a path function's.
    """
    suffix = Path(declared).suffix
    if suffix == ARRIVAL_SUFFIX:
        return "arrival"
    if suffix == CANONICAL_LOG_SUFFIX:
        return "jsonl"
    return "sqlite"


def is_jsonl_canonical(declared: Path | str) -> bool:  # noqa: D103 — shim, see below
    # Retired alias, NOT exported and named by nothing else in libs: kept
    # importable only for the lazy import at
    # apps/loops/src/loops/commands/store.py:142, which executes before any
    # mode check and would ImportError every store read verb if deleted —
    # apps/ is diff-empty for the whole arrival wave, so the caller cannot
    # move until the CLI-surface cut. Deleted there, together with Rule 18's
    # allowlist entry for this line. Behavior-identical to the pre-arrival
    # answer: an .arrival locator answers False (its agreement audit is a
    # later cut's).
    return canonical_mode(declared) == "jsonl"


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

    A log mode (arrival or jsonl) → the sibling ``.db``; sqlite mode →
    itself. Idempotent: feeding an index path back through returns it
    unchanged.
    """
    path = Path(canonical)
    if canonical_mode(path) == "sqlite":
        return path
    return path.with_suffix(_INDEX_SUFFIX)


def canonical_for(index_path: Path | str, mode: str) -> Path:
    """The canonical artifact beside a store db, for an EXPLICIT mode.

    The inverse of :func:`index_path_for`, and equally idempotent per mode.
    The mode is a parameter because it cannot be a deduction: with three
    modes, ``<name>.db`` has two possible canonical siblings, and which one
    exists is an I/O question this module refuses to ask (probe's job). A
    caller that knows its mode — and every writer does, from its declared
    locator — gets the pure answer.
    """
    path = Path(index_path)
    suffix = _MODE_SUFFIX.get(mode)
    if suffix is None:
        if mode != "sqlite":
            raise ValueError(f"unknown canonical mode {mode!r}")
        return path
    return path.with_suffix(suffix)


def sqlite_sidecars(path: Path | str) -> tuple[Path, ...]:
    """The WAL/SHM sidecar paths sqlite may keep beside a db file.

    The db itself is NOT included — callers that delete or size a store
    spell it ``(path, *sqlite_sidecars(path))``. Pure path arithmetic, no
    existence check: one spelling of the ``-wal``/``-shm`` naming rule.
    """
    path = Path(path)
    return tuple(path.parent / (path.name + s) for s in ("-wal", "-shm"))


def resolve_store_path(declared: Path | str, vertex_path: Path | None) -> Path:
    """Declared locator → absolute sqlite path to read from.

    The single translation point for the read path. Does not check
    existence and does not materialize a missing index; callers that must
    tolerate a fresh clone go through :func:`engine.jsonl_store.ensure_index`.
    Unchanged under the arrival mode BY DESIGN: reads execute through the
    derived index in every mode (arrival law 1), which is what keeps every
    reader above this function mode-agnostic.
    """
    return index_path_for(canonical_store_path(declared, vertex_path))
