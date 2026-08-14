"""probe — what IS this path, without touching it.

Every client that opens loops artifacts must answer the same question: is
this a ``.vertex`` declaration, a JSONL-canonical log, the derived sqlite
index beside one, or a sqlite-canonical store? Answering it wrong is a
correctness error — writing to a derived ``.db`` is an out-of-band insert
the log never sees. Before this module every client re-derived the answer
from suffix checks; :func:`probe_target` states it once, composed over
:mod:`engine.residence` (the extension-is-the-switch rule) rather than
re-spelling it.

**A probe is a location claim, never a verdict claim.** ``probe_target``
reports where things are and which artifact is authoritative; it does not
bless content. In particular :attr:`TargetInfo.index_current` is offset
parity only (see its docstring), and no field here asserts "this store is
intact" — that is :mod:`engine.canonical_audit`'s scope, reached through
:mod:`engine.preflight`.

**Pure inspection, by contract.** Nothing here constructs a store, creates
a file, materializes an index, or repairs anything. The constructor-shaped
traps are deliberately avoided: no :class:`~engine.jsonl_store.JsonlStore`
(its ``__init__`` repairs), no ``ensure_index``/``resolved_index`` (they
materialize), no bare ``sqlite3.connect`` (it CREATES a missing file and
can spawn ``-wal``/``-shm`` siblings). Sqlite is only ever opened through
the read-only URI helper, and file content is read with plain ``open('rb')``.

Classification taxonomy (documented here so the matrix test reads as spec):

- The **suffix classifies**; content corroborates and existence is
  orthogonal. A missing ``foo.jsonl`` still probes as ``jsonl_log`` with
  ``exists=False`` — the caller asked about a location, and the location's
  meaning does not depend on whether anything is there yet.
- ``.vertex`` → ``vertex``. The declared ``store`` locator (parsed from
  content, not guessed) supplies the canonical/index paths.
- ``.jsonl`` → ``jsonl_log``: the file IS the store; the sibling ``.db``
  is its derived index.
- ``.db``/``.sqlite`` **with a sibling ``.jsonl``** → ``derived_index``:
  not a write target at all.
- ``.db``/``.sqlite`` with no sibling log → ``sqlite_store``
  (sqlite-canonical, the pre-flip status quo).
- Anything else → ``unknown``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .residence import (
    CANONICAL_LOG_SUFFIX,
    SQLITE_SUFFIXES,
    canonical_store_path,
    index_path_for,
    log_path_for,
)

__all__ = [
    "VERTEX_SUFFIX",
    "TargetInfo",
    "probe_target",
    "write_surface_reason",
]

VERTEX_SUFFIX = ".vertex"

_SQLITE_MAGIC = b"SQLite format 3\x00"


@dataclass(frozen=True)
class TargetInfo:
    """What a path is, where its authority lives — and nothing stronger.

    Every field is a location or provenance claim. None of them is an
    integrity verdict; the strongest health-adjacent field,
    :attr:`index_current`, is scoped below.
    """

    target_type: str
    """One of ``vertex | jsonl_log | derived_index | sqlite_store | unknown``.

    Classified by suffix (see the module docstring's taxonomy); existence
    is carried by :attr:`exists`, not folded into the type.
    """

    canonical_mode: str | None
    """``"jsonl"`` or ``"sqlite"`` — which artifact class is authoritative.

    ``None`` when there is no store to have a mode: an ``unknown`` target,
    or a ``vertex`` that declares no ``store`` (or cannot be parsed).
    """

    canonical_path: Path | None
    """The authoritative artifact — the only path a writer may open.

    For a ``derived_index`` this is the sibling log, NOT the probed path.
    ``None`` exactly when :attr:`canonical_mode` is ``None``.
    """

    index_path: Path | None
    """The sqlite file reads connect to (`engine.residence.index_path_for`)."""

    exists: bool
    """Does the probed path itself exist on disk?"""

    index_current: bool | None
    """Has the derived index consumed the whole log — by OFFSET PARITY ONLY.

    A SCOPE STATEMENT, NOT AN INTEGRITY CLAIM (the same discipline as
    ``canonical_audit.Check.beyond_offset``). This is one stamped-offset
    read against one ``stat``: it distinguishes "the index has consumed
    every log byte" from "it is behind / absent / unreadable". It does NOT
    say the index rows agree with the log — an out-of-band sqlite insert
    or an interior edit can leave offset parity perfectly intact. Agreement
    is :func:`engine.canonical_audit.audit_agreement`'s claim, reached via
    :func:`engine.preflight.read_preflight`; no caller may render this
    field as "verified".

    ``None`` when the question does not apply: sqlite-canonical stores
    (the index IS the store), unknown targets, storeless vertices, or a
    log that does not exist yet.
    """

    declaration_status: str | None
    """For ``vertex`` targets: the provenance string from
    :func:`engine.declaration.load_declaration_status` (``store`` /
    ``file-pre-genesis`` / ``unhistorized`` / ``aggregate-head``).
    ``None`` for non-vertex targets, and for a vertex file that is missing
    or fails to parse (the parse error lands in :attr:`reason`)."""

    writable: bool
    """May a WRITER legitimately open the probed path as authoritative?

    False for a ``derived_index`` regardless of filesystem bits — writes
    there are out-of-band by construction. For canonical artifacts this is
    the authority claim AND an ``os.access`` writability check on the file
    (or its nearest existing ancestor when the file is absent). It does not
    promise a later open will succeed; it reports what inspection can see.

    NOTE this is a claim about the PROBED path (for a vertex target, the
    ``.vertex`` file itself) — the canonical store's writability is the
    separate :attr:`canonical_writable` dimension.
    """

    canonical_writable: bool | None
    """Is the canonical store's FULL WRITE SURFACE writable — the canonical
    artifact itself, the derived index (writable, or creatable when absent),
    AND the containing directory sqlite needs for its WAL/SHM siblings —
    all by the same ``os.access`` inspection as :attr:`writable`
    (:func:`write_surface_reason`; SOL-R1-04 + SOL-R2-04).

    A location-scoped filesystem claim, not an open-success promise. For a
    ``vertex`` target this is the dimension a store-writing ceremony must
    consult; :attr:`writable` there speaks only for the declaration file.
    ``None`` exactly when :attr:`canonical_path` is ``None`` (nothing to
    evaluate)."""

    reason: str
    """One human-readable line explaining the classification — and carrying
    anything the typed fields cannot (parse errors, content that disagrees
    with the suffix, why a target is not writable)."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "canonical_mode": self.canonical_mode,
            "canonical_path": (
                str(self.canonical_path) if self.canonical_path else None
            ),
            "index_path": str(self.index_path) if self.index_path else None,
            "exists": self.exists,
            "index_current": self.index_current,
            "declaration_status": self.declaration_status,
            "writable": self.writable,
            "canonical_writable": self.canonical_writable,
            "reason": self.reason,
        }


def probe_target(path: Path | str) -> TargetInfo:
    """Classify a path against the residence rule — pure inspection.

    Never creates, materializes, or repairs anything (module docstring has
    the full contract). Returns a :class:`TargetInfo` for every input; an
    unrecognized suffix answers ``target_type="unknown"`` rather than
    raising, because "what is this?" deserves an answer even when the
    answer is "not a loops artifact".
    """
    path = Path(path)
    suffix = path.suffix
    if suffix == VERTEX_SUFFIX:
        return _probe_vertex(path)
    if suffix == CANONICAL_LOG_SUFFIX:
        return _probe_log(path)
    if suffix in SQLITE_SUFFIXES:
        return _probe_sqlite(path)
    return TargetInfo(
        target_type="unknown",
        canonical_mode=None,
        canonical_path=None,
        index_path=None,
        exists=path.exists(),
        index_current=None,
        declaration_status=None,
        writable=False,
        canonical_writable=None,
        reason=(
            f"unrecognized suffix {suffix or '(none)'} — not a vertex "
            "declaration, canonical log, or sqlite store locator"
        ),
    )


# --- per-class probes -------------------------------------------------------


def _probe_vertex(path: Path) -> TargetInfo:
    exists = path.is_file()
    if not exists:
        return TargetInfo(
            target_type="vertex",
            canonical_mode=None,
            canonical_path=None,
            index_path=None,
            exists=False,
            index_current=None,
            declaration_status=None,
            writable=_writable(path),
            canonical_writable=None,
            reason="vertex declaration does not exist",
        )
    try:
        from .declaration import load_declaration_status

        ast, status = load_declaration_status(path)
    except Exception as exc:  # noqa: BLE001 — a probe reports, never raises
        return TargetInfo(
            target_type="vertex",
            canonical_mode=None,
            canonical_path=None,
            index_path=None,
            exists=True,
            index_current=None,
            declaration_status=None,
            writable=_writable(path),
            canonical_writable=None,
            reason=f"vertex declaration does not resolve: {exc}",
        )
    store_field = getattr(ast, "store", None)
    if store_field is None:
        return TargetInfo(
            target_type="vertex",
            canonical_mode=None,
            canonical_path=None,
            index_path=None,
            exists=True,
            index_current=None,
            declaration_status=status,
            writable=_writable(path),
            canonical_writable=None,
            reason="vertex declares no store — declaration only",
        )
    canonical = canonical_store_path(store_field, path)
    mode = "jsonl" if canonical.suffix == CANONICAL_LOG_SUFFIX else "sqlite"
    return TargetInfo(
        target_type="vertex",
        canonical_mode=mode,
        canonical_path=canonical,
        index_path=index_path_for(canonical),
        exists=True,
        index_current=_currency(canonical) if mode == "jsonl" else None,
        declaration_status=status,
        writable=_writable(path),
        canonical_writable=write_surface_reason(canonical) is None,
        reason=f"vertex declaring a {mode}-canonical store at {canonical}",
    )


def _probe_log(path: Path) -> TargetInfo:
    exists = path.is_file()
    corroboration = _log_content_note(path) if exists else ""
    return TargetInfo(
        target_type="jsonl_log",
        canonical_mode="jsonl",
        canonical_path=path,
        index_path=index_path_for(path),
        exists=exists,
        index_current=_currency(path) if exists else None,
        declaration_status=None,
        writable=_writable(path),
        canonical_writable=write_surface_reason(path) is None,
        reason=(
            "JSONL-canonical log — the log is the store; the sibling .db "
            "is a derived, rebuildable index" + corroboration
        )
        if exists
        else "JSONL-canonical log locator — nothing on disk yet",
    )


def _probe_sqlite(path: Path) -> TargetInfo:
    exists = path.is_file()
    sibling_log = log_path_for(path)
    corroboration = _sqlite_content_note(path) if exists else ""
    if sibling_log.is_file():
        return TargetInfo(
            target_type="derived_index",
            canonical_mode="jsonl",
            canonical_path=sibling_log,
            index_path=path,
            exists=exists,
            index_current=_currency(sibling_log),
            declaration_status=None,
            writable=False,
            canonical_writable=write_surface_reason(sibling_log) is None,
            reason=(
                f"derived index over the JSONL-canonical log at "
                f"{sibling_log} — NOT a write target: writing here is an "
                "out-of-band insert the log cannot account for; writers "
                "open the log (engine.jsonl_store.open_canonical_store)"
                + corroboration
            ),
        )
    return TargetInfo(
        target_type="sqlite_store",
        canonical_mode="sqlite",
        canonical_path=path,
        index_path=path,
        exists=exists,
        index_current=None,
        declaration_status=None,
        writable=_writable(path),
        canonical_writable=write_surface_reason(path) is None,
        reason=(
            "sqlite-canonical store — no sibling canonical log; the db is "
            "the store" + corroboration
        )
        if exists
        else "sqlite-canonical store locator — nothing on disk yet",
    )


# --- inspection helpers (all read-only) -------------------------------------


def _currency(canonical: Path) -> bool | None:
    """Offset parity of the derived index, or None when unanswerable.

    Composes ``jsonl_store._index_is_current`` (one read-only sqlite meta
    read + one stat — it never constructs a store) but refuses to answer
    for a missing index: "current" and "absent" must not collapse.
    """
    from .jsonl_store import _index_is_current

    if not canonical.is_file():
        return None
    index = index_path_for(canonical)
    if not index.is_file():
        return False
    return _index_is_current(index, canonical)


def write_surface_reason(canonical_path: Path | str) -> str | None:
    """Reason the canonical store's FULL write surface is unwritable, or None.

    The surface a store-writing ceremony touches is wider than the canonical
    artifact (SOL-R1-04 + SOL-R2-04): a JSONL-canonical open also writes the
    derived sqlite index, and any sqlite open needs the containing directory
    for its WAL/SHM siblings. Pure ``os.access`` inspection — ``_writable``
    walks to the nearest existing ancestor, so a missing index counts as
    creatable when its directory is writable. A location-scoped claim, never
    an open-success promise. Idempotent on a ``.db`` (index == canonical).
    """
    canonical_path = Path(canonical_path)
    if not _writable(canonical_path):
        return f"canonical store not writable: {canonical_path}"
    index = index_path_for(canonical_path)
    if not _writable(index):
        return f"derived index not writable: {index}"
    if not _writable(canonical_path.parent):
        return (
            f"store directory not writable: {canonical_path.parent} — "
            "sqlite needs it for WAL/SHM siblings"
        )
    return None


def _writable(path: Path) -> bool:
    """Filesystem writability of ``path``, or of its nearest existing ancestor."""
    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent
    return os.access(probe, os.W_OK)


def _log_content_note(path: Path) -> str:
    """Corroborate a ``.jsonl`` suffix against its first complete line."""
    try:
        with path.open("rb") as fh:
            raw = fh.readline()
    except OSError as exc:
        return f"; content unreadable: {exc}"
    if not raw.strip():
        return ""
    if not raw.endswith(b"\n"):
        return "; first line incomplete (torn or still being written)"
    from .jsonl_codec import JsonlCodecError, deserialize_records

    try:
        deserialize_records(raw[:-1].decode("utf-8").strip())
    except (JsonlCodecError, UnicodeError):
        return "; content does not decode as loops log rows"
    return ""


def _sqlite_content_note(path: Path) -> str:
    """Corroborate a sqlite suffix against the sqlite magic header."""
    try:
        with path.open("rb") as fh:
            head = fh.read(len(_SQLITE_MAGIC))
    except OSError as exc:
        return f"; content unreadable: {exc}"
    if not head:
        return "; file is empty"
    if head != _SQLITE_MAGIC:
        return "; content is not a sqlite database"
    return ""
