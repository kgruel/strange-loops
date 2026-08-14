"""jsonl_store — the canonical write path: JSONL is the store, sqlite an index.

The authority flip of design/architecture/jsonl-canonical-store. Today a
store's truth lives in sqlite; here the truth is ONE interleaved append-only
log per store (``<name>.jsonl``, sibling of ``<name>.db``) and sqlite is a
derived, rebuildable index over it.

Seam choice (subclass, not wrapper)
-----------------------------------
``SqliteStore.append``/``append_tick`` do the mint work — id generation,
chain linkage, window hashing, era-aware signing, the signing floor — and
then persist one fully-assembled row. That row is *already* the exact shape
the commitment hashers and :mod:`engine.jsonl_codec` take (7 fact fields /
11 tick fields), so the only thing this layer must change is **where the row
lands first**. A wrapper would have to re-derive or re-implement all of that
mint logic to see the row; a subclass overriding the ``_write_fact_row`` /
``_write_tick_row`` seam sees it for free, inherits every read method
(``since``/``since_raw``/``between``/``StoreReader``/FTS) byte-for-byte
unchanged, and adds no branch to the read path. Mint logic stays in one
place; only durability order is overridden.

Write order (the receipt originates at the log)
-----------------------------------------------
0. reconcile: if the stamped offset and the log's size disagree, run
   catch-up before anything else. A post-fsync failure leaves a durable
   line the index has not consumed; appending over it would stamp the
   offset past the orphan and bury it while reporting ``synced``. No
   append may ever skip an unindexed durable line;
1. serialize the row through the S1 codec — ``payload`` rides as the
   VERBATIM stored TEXT, never re-serialized, so every existing signature
   and commitment hash survives the round trip;
2. **stage** the sqlite INSERT in an open, uncommitted transaction. Nothing
   is observable yet, but a rejected row (duplicate id via ``id_override``
   on the transport/replay path, constraint violation) fails *here* — before
   any byte reaches the log, so a refused write can never leave an orphan
   line the index doesn't name;
3. append the line + ``\\n`` to the log, ``flush()`` + ``os.fsync()`` — the
   line is durable *before* the id is anything anyone can observe;
4. stamp the consumed byte offset and row counts and COMMIT — the index row
   becomes visible only after its line is durable, and row, offset and
   counts can never disagree. Any failure rolls the whole transaction back.
   Before step 3 that leaves the log untouched; *after* the fsync the line
   is already durable and stays so — the rollback leaves it unindexed and
   unstamped, which is the recoverable state step 0 (and catch-up on open)
   exists to resolve;
5. return the id. The id in the receipt is the id in the durable line.

Staging the INSERT before the append inverts the literal "sqlite indexed
after" ordering, but preserves the property that ordering exists for: an
uncommitted row is invisible to every reader, and the commit lands strictly
after the fsync. Crash between fsync and commit → the row is rolled back and
the offset unstamped, so the next open tails the line forward.

Catch-up on open
----------------
``store_meta.jsonl_offset`` holds the byte offset of the log consumed into
sqlite. On open:

- ``offset == size`` — in sync, nothing to do.
- ``offset < size`` — sqlite is behind (crash between step 2 and step 3, or
  an out-of-band append): tail forward, indexing the missed lines verbatim.
- ``offset`` outside ``0..size`` (log shrank, or negative metadata), the
  byte at ``offset - 1`` is not a
  newline, or the last line ending at ``offset`` does not decode to the
  sqlite row it names — full rebuild of the sqlite index from the log,
  logged loudly at WARNING. That last check is a commitment comparison done
  on one line rather than the file: the line is decoded through the codec
  and its fields compared by VALUE against the indexed row (not by
  re-serialized bytes — see :meth:`JsonlStore._row_matches` for why sqlite's
  numeric affinity makes a byte-compare report false corruption).
- **offset absent** with a non-empty log: a store that has never recorded a
  consumption point cannot claim any prefix is indexed, so it rebuilds
  (rather than tailing from 0 into PK conflicts). This is also the shape a
  freshly exported log + its source db has, and rebuild is the honest answer
  there: it makes the index a pure function of the log.

A torn final line (crash mid-write, no trailing newline) is **truncated**
off the log before any tailing or appending — not merely skipped. Leaving
partial bytes at the tail would let the next append concatenate onto junk
and corrupt the canonical log. Truncation is the only mutation this layer
ever performs on the log; everything else is append.

Catch-up and rebuild insert rows **verbatim**: no signer runs, no floor
check, no id minted, signatures ride as stored. Indexing is not re-emitting
(same posture as ``store.jsonl.rebuild_jsonl``). A rebuild clears ``facts``
and ``ticks`` only — ``store_meta`` (notably ``own_lineage``, the store's
identity, which is not a fact) is preserved.

This follows the :class:`engine.tailer.Tailer` pattern (persisted byte
offset, complete-lines-only, incomplete tail left alone) but does not use
the class: ``Tailer`` ``json.loads``-es each line before handing it on,
discarding the verbatim line text this layer needs for the integrity
compare and for the era-exact codec decode.

Out-of-band sqlite writers
--------------------------
``libs/store``'s ``merge``/``receive``/``rebirth``/``compact`` open their own
connection to the ``.db`` and write ``facts``/``ticks`` directly, bypassing
the log entirely. This layer cannot refuse them (they never touch this
class), so it *detects* them: the offset stamp carries the fact/tick counts
consumed from the log, and open compares them against ``COUNT(*)``. A
mismatch refuses with :class:`JsonlCanonicalUnsupported` rather than
rebuilding — rebuilding would silently destroy exactly the rows that were
written out of band.

What open-time detection covers, exactly — it is two cheap checks, never a
content walk, so the scope is narrower than "direct sqlite writes are
detected":

- **inserts** — the stamped counts vs ``COUNT(*)``;
- an edit to the **last log-consumed row** — the last-line integrity
  compare (:meth:`_prefix_intact`);
- an offset outside ``0..size``, a shrunk log, a torn tail — rebuild
  triggers.

An in-place update to any **interior** row opens clean, and deliberately so:
catching it would cost an O(n) walk of the whole log on every open. That
walk is ``sl store verify``'s job — a fact sealed by a tick has its content
committed in that tick's window hash, so ``verify_chain`` breaks on exactly
the edit this path lets through. The residue is the custody boundary ticks
already have: a **live-edge** fact (emitted, not yet sealed) is committed to
by nothing, so a direct edit to it is undetectable until the next boundary —
the same limit :meth:`SqliteStore.verify_facts` documents for signature
strips. Both halves are pinned in ``tests/test_jsonl_store.py``.

The counts also do not survive a store that simultaneously trips a rebuild
trigger — a cleared offset marker or a shrunk log makes the stamped counts
exactly as untrustworthy as the offset, so the rebuild runs and out-of-band
rows are lost with it. Checking counts *before* rebuilding would block
legitimate recoveries; two abnormal events have to stack to reach that
window.

The counts are never cached per handle: every stamp derives them from the
*committed* marker, read under the write lock the INSERT already took. Two
open handles on one store (a daemon plus an ``sl emit``) would otherwise each
stamp their own stale idea of the total, and a perfectly consistent store
would refuse to open, naming writers that never ran.

Declaration ceremonies (wired) and what still refuses
-----------------------------------------------------
``absorb_genesis`` and ``absorb_edit`` are append-shaped and run here per
design:architecture/jsonl-declaration-ceremony-encoding: the base ceremonies
reconcile first (``_sync_derived_state``), run every compare-and-swap check
inside ``BEGIN IMMEDIATE`` *before* any log byte, then hand the assembled
rows to the ``_ceremony_persist`` seam — which this class overrides to append
the ceremony as ONE durable line (a plain fact line for one row, a
``"t":"batch"`` envelope for several; one line is the log's atomicity unit,
so a torn ceremony is truncated whole and recovery can never expose a partial
one), fsync, and stamp offset + counts before the commit. A refusal
(``GenesisExists``/``NoGenesis``/``AmbiguousGenesis``/``StaleDeclarationHead``/
``ReservedKindViolation``/signing failures) rolls back with the log
byte-identical to its pre-call state.

``reanchor`` is genuinely history-mutating — it rewrites sqlite rows the log
keeps the originals of — and still refuses with
:class:`JsonlCanonicalUnsupported` until the log-rewrite ceremony is
designed. ``rebirth``/``compact`` live in ``libs/store`` and are detected,
not refused (above).
"""

from __future__ import annotations

import itertools
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Generic, TypeVar

from .canonical_audit import (
    FACT_COUNT_KEY as _FACT_COUNT_KEY,
)
from .canonical_audit import (
    OFFSET_KEY as _OFFSET_KEY,
)
from .canonical_audit import (
    TICK_COUNT_KEY as _TICK_COUNT_KEY,
)
from .canonical_audit import (
    row_matches,
)
from .jsonl_codec import (
    JsonlCodecError,
    deserialize_records,
    serialize_batch,
    serialize_fact_row,
    serialize_tick_row,
)
from .residence import log_path_for
from .sqlite_store import (
    FACT_INSERT_SQL,
    TICK_INSERT_SQL,
    SqliteStore,
)

__all__ = [
    "JsonlCanonicalUnsupported",
    "JsonlStore",
    "ensure_index",
    "open_canonical_store",
    "resolved_index",
]

_log = logging.getLogger(__name__)

# Quarantine-name sequence for corrupt-index renames: pid + counter, no
# wall clock (SOL-R3-04 — deterministic, collision-free within a process).
_QUARANTINE_SEQ = itertools.count(1)

T = TypeVar("T")

# Marker keys live in engine.canonical_audit — one spelling for the writer
# that stamps them and the auditor that reads them (imported above).

_CHUNK = 64 * 1024


class _RowAlreadyIndexed(Exception):
    """A tail-forward hit a row the index already carries.

    Internal to :meth:`JsonlStore.catch_up`, which answers it with a rebuild.
    Never escapes the module.
    """


class JsonlCanonicalUnsupported(NotImplementedError):
    """A history-mutating op was called on a JSONL-canonical store.

    Rewriting sqlite rows in place would break the layer's whole claim — that
    the index is a function of the log (design/architecture/jsonl-canonical
    -store). The log-rewrite ceremony is not designed yet, so these refuse
    rather than silently diverge.
    """


def _as_int(value: object) -> int | None:
    """A store_meta value as an int, or None when it cannot be one.

    A marker that is absent, NULL or not a number is not a position to trust;
    every caller here treats "cannot be read" and "not recorded" the same way.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def open_canonical_store(canonical: Path, **kwargs: Any) -> SqliteStore[Any]:
    """Open the right store class for a store locator (see ``engine.residence``).

    ``.jsonl`` → :class:`JsonlStore` over the sibling index; anything else →
    :class:`SqliteStore` at the path itself. One place to ask "which file is
    authoritative here", so no write site can answer it differently.
    """
    from .residence import index_path_for, is_jsonl_canonical

    canonical = Path(canonical)
    if is_jsonl_canonical(canonical):
        return JsonlStore(path=index_path_for(canonical), log_path=canonical, **kwargs)
    return SqliteStore(path=canonical, **kwargs)


def _index_is_current(index: Path, canonical: Path) -> bool:
    """Whether ``index`` has consumed the whole log — cheaply, read-only.

    One read-only sqlite connection for the stamped offset and one ``stat``
    for the log's size; no scan, no lock, no store construction. Anything
    that makes the answer unknowable (no index tables yet, no offset marker,
    a value that isn't an integer, an unreadable db) answers "not current":
    the honest response is to let :class:`JsonlStore`'s catch-up decide,
    which is where every recovery rule already lives.
    """
    import sqlite3

    from .declaration import _open_readonly

    try:
        size = canonical.stat().st_size
    except OSError:
        return True  # no log to be behind
    if size == 0:
        # Nothing durable exists, so nothing durable can be unindexed. Says
        # current without touching the db at all — an index that is wrong
        # about an empty log is a JsonlStore-open concern (it refuses), not
        # something a read-path resolve should provoke.
        return True
    # A quarter-second, not _open_readonly's 5s default: this runs on every
    # read resolve, and "a writer is holding the lock" is a fine reason to
    # answer "not current" and let JsonlStore's catch-up decide.
    conn = _open_readonly(index, timeout=0.25)
    if conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (_OFFSET_KEY,)
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return row is not None and _as_int(row[0]) == size


def ensure_index(canonical: Path) -> Path:
    """Materialize — and catch up — the sqlite index for a JSONL-canonical log.

    The doctrine's fresh-clone case: the ``.jsonl`` is tracked in git, the
    derived ``.db`` is not, so the first read after a clone finds no index.
    Opening a :class:`JsonlStore` runs the S3 catch-up (offset absent + a
    non-empty log ⇒ full rebuild), which is exactly "materialize the index
    from the log". Closing immediately leaves no handle behind.

    An *existing* index is not evidence of a current one. The log is the
    store: a line can be durable and unindexed (the post-fsync crash
    window, or another process's log write). Short-circuiting on
    ``index.exists()`` left every read-only invocation — which never
    constructs a ``JsonlStore`` — silently omitting canonical facts until
    some writer happened along. So an existing index is checked for
    staleness (:func:`_index_is_current`: one read-only meta read, one
    stat) and opened only when it is behind.

    A no-op — no store constructed, no lock taken — when ``canonical`` is
    not JSONL-canonical, when the log itself is missing (nothing to build
    from; let the caller's own not-found handling speak), or when the index
    is already current. Read paths may call this on every resolve.
    """
    from .residence import index_path_for, is_jsonl_canonical

    canonical = Path(canonical)
    index = index_path_for(canonical)
    if not is_jsonl_canonical(canonical) or not canonical.exists():
        return index
    if index.exists() and _index_is_current(index, canonical):
        return index
    store: JsonlStore[Any] = JsonlStore(
        path=index,
        log_path=canonical,
        serialize=lambda d: d,
        deserialize=lambda d: d,
    )
    store.close()
    return index


def resolved_index(declared: Path | str, vertex_path: Path | None = None) -> Path:
    """:func:`engine.residence.resolve_store_path`, materializing on the way.

    The read path's resolution seam. ``resolve_store_path`` is pure — it can
    only *name* the sqlite index — so a fresh clone (log tracked, derived
    index not) resolves to a path that does not exist, and every reader's
    ``if not store_path.exists()`` answers "empty store" for the one
    invocation that should have built it. Resolving through here makes
    materialization part of resolution, so no reader can observe the gap.

    Materialization is not only the missing-index case: :func:`ensure_index`
    also tails an existing index that is behind the log, so a read-only
    invocation cannot report a durable fact as absent.

    Identical to ``resolve_store_path`` in every other case: the same path,
    with :func:`ensure_index`'s two-read no-op in front of it.
    """
    from .residence import canonical_store_path

    return ensure_index(canonical_store_path(declared, vertex_path))


class JsonlStore(SqliteStore[T], Generic[T]):
    """A store whose canonical persistence is its JSONL log.

    Same constructor as :class:`SqliteStore` plus an optional ``log_path``
    (defaults to the db path with a ``.jsonl`` suffix). Opening runs
    catch-up; every append writes the log first.
    """

    def __init__(self, *, log_path: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._log_path = (
            Path(log_path) if log_path is not None else log_path_for(self._path)
        )
        try:
            self._open_index()
        except sqlite3.Error as exc:
            # The derived index itself does not open as sqlite (non-sqlite
            # bytes, truncated header — low-level corruption catch-up cannot
            # route around). The index is DERIVED and the canonical log is
            # the store, so discarding and rebuilding it from the log is this
            # layer's own recovery, same class as the _rebuild triggers. Two
            # guards keep the unlink honest: a transient lock is not
            # corruption (re-raise — another handle owns a live index), and
            # with no canonical log on disk the db is the only artifact
            # (re-raise — never destroy what cannot be re-derived).
            if "database is locked" in str(exc) or not self._log_path.is_file():
                raise
            self._recover_index(kwargs, exc)

    def _recover_index(self, kwargs: dict[str, Any], exc: BaseException) -> None:
        """Discard-and-rebuild a corrupt derived index — serialized (SOL-R3-04).

        Concurrent openers racing the destructive discard could each
        unlink-and-recreate, ending on different inodes with divergent
        reads. Recovery therefore runs under an interprocess lock FILE
        beside the index (``flock`` on its own fd — which also serializes
        threads, the lock being per-fd): sqlite cannot provide the lock,
        its file is the casualty. Under the lock a would-be loser first
        RE-OPENS at the path — re-checking corruption and binding whatever
        inode now lives there (the winner's rebuilt index) — and only a
        still-corrupt index is quarantined (atomic rename to
        ``<name>.corrupt.<pid>-<seq>``, never a blind unlink) and rebuilt
        from the log.
        """
        import fcntl

        from .residence import sqlite_sidecars

        lock_path = self._path.with_name(self._path.name + ".recovery-lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("ab") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                # Loser path: a winner may already have recovered — re-check
                # under the lock by reopening the current file at the path.
                super().__init__(**kwargs)
                self._open_index()
                return
            except sqlite3.Error as retry_exc:
                if "database is locked" in str(retry_exc):
                    raise  # a live handle owns the index — not corruption
            _log.warning(
                "jsonl-canonical: derived index %s unusable (%s) — "
                "discarding and rebuilding from %s",
                self._path, exc, self._log_path,
            )
            quarantine = self._path.with_name(
                f"{self._path.name}.corrupt.{os.getpid()}-{next(_QUARANTINE_SEQ)}"
            )
            try:
                self._path.replace(quarantine)  # atomic, evidence preserved
            except FileNotFoundError:
                pass
            for stale in sqlite_sidecars(self._path):
                stale.unlink(missing_ok=True)
            super().__init__(**kwargs)  # fresh empty index at the same path
            self._open_index()  # offset absent + non-empty log ⇒ rebuild

    def _open_index(self) -> None:
        """Schema prep + catch-up, leaving the db reopenable on failure."""
        try:
            self._ensure_fact_signature_column()
            self._ensure_chain_columns()
            self._ensure_meta_table()
            self.catch_up()
        except BaseException:
            # A raise out of __init__ must leave the db reopenable: an
            # uncommitted DELETE on a leaked connection locks the file
            # forever, turning one bad open into a permanently bricked store.
            try:
                self._conn.rollback()
            finally:
                self._conn.close()
            raise

    @property
    def log_path(self) -> Path:
        """The canonical log this store's sqlite index derives from."""
        return self._log_path

    # ---- offset bookkeeping ------------------------------------------

    def _read_meta_int(self, key: str) -> int | None:
        return _as_int(self._meta_get(key))

    def _read_offset(self) -> int | None:
        return self._read_meta_int(_OFFSET_KEY)

    def _marked_counts(self) -> tuple[int, int] | None:
        """The committed (fact, tick) counts the log accounts for.

        ``None`` for a store whose markers were never written (pre-marker
        store): there is nothing to compare against, and inventing a
        baseline from this handle's guesses is exactly the bug the markers
        exist to avoid. Always read from the db, never cached per handle —
        a second open handle would otherwise stamp its own stale idea of
        the count over a concurrent writer's correct one.
        """
        facts = self._read_meta_int(_FACT_COUNT_KEY)
        ticks = self._read_meta_int(_TICK_COUNT_KEY)
        if facts is None or ticks is None:
            return None
        return facts, ticks

    def _stamp(self, offset: int, facts: int, ticks: int) -> None:
        """Stage the offset + indexed-row-count marks (caller commits)."""
        for key, value in (
            (_OFFSET_KEY, offset),
            (_FACT_COUNT_KEY, facts),
            (_TICK_COUNT_KEY, ticks),
        ):
            self._meta_set(key, value)

    def _row_counts(self) -> tuple[int, int]:
        facts = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        ticks = self._conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        return int(facts), int(ticks)

    def _log_size(self) -> int:
        try:
            return self._log_path.stat().st_size
        except OSError:
            return 0

    # ---- the write path ----------------------------------------------

    def _append_line(self, line: str) -> int:
        """Append one durable line; return the log size after it.

        fsync, not just flush: the receipt is minted here, so the line must
        outlive a power cut, not merely a process crash.
        """
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        data = (line + "\n").encode("utf-8")
        with self._log_path.open("ab") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
            return fh.tell()

    def _write(self, sql: str, row: tuple, line: str, is_fact: bool) -> str | None:
        """Stage the INSERT, make the line durable, then stamp and commit.

        The INSERT runs first, uncommitted: a rejected row (duplicate id from
        ``id_override``, any constraint) fails before a byte reaches the log,
        so a refused append can never orphan a line. Nothing is observable
        until the commit, which happens strictly after the fsync.

        Reconcile first: see :meth:`_reconcile`.
        """
        self._reconcile()
        try:
            self._conn.execute(sql, row)
            # Committed-row honesty (SOL-R3-02): read the signature back
            # after the INSERT (AFTER triggers fired), before commit — the
            # receipt reports what the index will actually hold.
            committed = self._committed_signature(
                "facts" if is_fact else "ticks", row[0]
            )
            # The INSERT has taken sqlite's write lock, so the committed
            # markers read here cannot be raced by another handle: whatever
            # a concurrent writer stamped is already visible, and nothing
            # further can land until we commit or roll back. Increment from
            # that committed value — never from a per-handle cache, which
            # would stamp a stale count over another writer's correct one
            # and brick the store on the next open.
            marked = self._marked_counts()
            if marked is None:
                facts, ticks = self._row_counts()  # pre-marker store: adopt
            else:
                facts, ticks = marked
                facts += 1 if is_fact else 0
                ticks += 0 if is_fact else 1
            offset = self._append_line(line)
            self._stamp(offset, facts, ticks)
            self._conn.commit()
            return committed
        except BaseException:
            self._conn.rollback()
            raise

    def _reconcile(self) -> None:
        """Refuse to stamp past a durable line the index has not consumed.

        A failure *after* the fsync (sqlite error, power cut, the process
        dying) rolls the transaction back, leaving the line durable and the
        offset unstamped — that is the recoverable state, and the next open
        tails it forward. But a long-lived handle never reopens: it would
        append line N+1 and stamp the offset past *both*, burying the orphan
        forever while reporting ``synced``. So every append reconciles first.

        Cheap in the common case: one ``store_meta`` read and one ``stat``,
        no scan, no lock. Only a disagreement pays for :meth:`catch_up`
        (which also covers a shrunk log, a torn tail and untrustworthy
        offset metadata). Two handles racing the same orphan line is a loud
        failure, not a silent one: the loser's tail INSERT hits the primary
        key, rolls back, and the line stays recoverable.
        """
        if self._read_offset() == self._log_size():
            return
        self.catch_up()

    def _sync_derived_state(self) -> None:
        """Reconcile before the mint reads chain state off the index.

        ``_write``'s reconcile is too late for a tick: ``append_tick`` has by
        then already derived ``prev_hash``, ``window_start`` and the fact
        cursor from an index that may not have consumed a durable line. The
        successor would link past the orphan, and that mis-linkage goes into
        the canonical log itself — where no later catch-up or rebuild can
        repair it. Reconciling in front of the derivation costs two syscalls
        when the index is current.
        """
        self._reconcile()

    def _ceremony_persist(self, rows: list[tuple]) -> None:
        """Make a declaration ceremony canonical: one durable line, stamped.

        Runs inside the ceremony's open ``BEGIN IMMEDIATE`` transaction,
        after every CAS check passed and the fact INSERTs (+ meta stamps)
        are staged, immediately before the caller's COMMIT — the same shape
        as :meth:`_write` steps 3–4. One row serializes as a plain fact
        line; several as one ``batch`` envelope line (the log's atomicity
        unit), so recovery can never expose a partial ceremony. Any failure
        after the fsync rolls the index back and leaves the line durable
        and unindexed — the standard recoverable state the next
        open/reconcile tails forward, all N rows atomically.
        """
        line = serialize_batch(rows) if len(rows) > 1 else serialize_fact_row(rows[0])
        # Same committed-marker discipline as _write: the staged INSERTs
        # hold sqlite's write lock, so the marker read here cannot be raced.
        marked = self._marked_counts()
        if marked is None:
            # Pre-marker store: adopt. _row_counts() already includes the
            # ceremony's staged rows on this connection.
            facts, ticks = self._row_counts()
        else:
            facts, ticks = marked
            facts += len(rows)
        offset = self._append_line(line)
        self._stamp(offset, facts, ticks)

    def _write_fact_row(self, row: tuple) -> str | None:
        return self._write(FACT_INSERT_SQL, row, serialize_fact_row(row), True)

    def _write_tick_row(self, row: tuple) -> str | None:
        return self._write(TICK_INSERT_SQL, row, serialize_tick_row(row), False)

    # ---- catch-up -----------------------------------------------------

    def catch_up(self) -> str:
        """Reconcile the sqlite index with the log. Returns what it did:
        ``"synced"``, ``"tailed"``, ``"rebuilt"`` or ``"empty"``."""
        self._truncate_torn_line()
        size = self._log_size()
        offset = self._read_offset()

        if size == 0:
            # No log yet. An index with rows but no log is not a
            # JSONL-canonical store — refuse rather than invent a log.
            if self._has_rows():
                raise JsonlCanonicalUnsupported(
                    f"{self._path} has indexed rows but no canonical log at "
                    f"{self._log_path} — export it first "
                    "(store.jsonl.export_jsonl), then open it JSONL-canonical"
                )
            self._index_offset(0, 0, 0)
            return "empty"

        if offset is None:
            self._rebuild("no consumed-offset marker recorded")
            return "rebuilt"
        if not 0 <= offset <= size:
            # Outside the log's byte range in either direction. A negative
            # offset is not a seek position to try — it is metadata that
            # cannot be true, exactly as untrustworthy as one past the end.
            self._rebuild(f"offset {offset} outside the log's 0..{size} byte range")
            return "rebuilt"
        if not self._prefix_intact(offset):
            self._rebuild(f"log content at offset {offset} does not match the index")
            return "rebuilt"

        marked = self._marked_counts()
        if marked is None:
            # Pre-marker store: no baseline exists, so nothing can be judged
            # out of band. Adopt the current row counts as the baseline so
            # every later open has something honest to compare against.
            base_facts, base_ticks = self._row_counts()
            judge = False
        else:
            base_facts, base_ticks = marked
            judge = True

        if offset == size:
            if judge:
                self._refuse_out_of_band(base_facts, base_ticks)
            else:
                self._index_offset(offset, base_facts, base_ticks)
            return "synced"

        try:
            facts, ticks = self._tail_forward(offset, base_facts, base_ticks)
        except _RowAlreadyIndexed as collision:
            self._rebuild(str(collision))
            return "rebuilt"
        if judge:
            self._refuse_out_of_band(facts, ticks)
        return "tailed"

    def _refuse_out_of_band(self, expect_facts: int, expect_ticks: int) -> None:
        """Refuse a db carrying rows that never came through the log.

        ``libs/store``'s merge/receive/rebirth/compact open their own
        connection and INSERT straight into ``facts``/``ticks``. Those rows
        are invisible to the log, so the index is no longer a function of it.
        Refusing is the only non-destructive answer: rebuilding would delete
        precisely the out-of-band rows. Catches inserts only. An edit to the
        last consumed row is the last-line compare's job; an edit to an
        interior row is ``verify_chain``'s (module docstring).
        """
        facts, ticks = self._row_counts()
        if facts == expect_facts and ticks == expect_ticks:
            return
        raise JsonlCanonicalUnsupported(
            f"{self._path} holds rows that did not come through "
            f"{self._log_path}: sqlite has {facts} fact(s)/{ticks} tick(s), the "
            f"log accounts for {expect_facts}/{expect_ticks}. "
            "Out-of-band writers (store.merge, store.receive, rebirth, "
            "compact) are not wired for a JSONL-canonical store. Recovery: "
            "open it as a plain SqliteStore and re-export the log "
            "(store.jsonl.export_jsonl) before reopening JSONL-canonical."
        )

    def _has_rows(self) -> bool:
        for table in ("facts", "ticks"):
            if self._conn.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()[0]:
                return True
        return False

    def _index_offset(self, offset: int, facts: int, ticks: int) -> None:
        self._stamp(offset, facts, ticks)
        self._conn.commit()

    def _last_newline_before(self, fh, end: int) -> int:
        """Byte offset just past the last ``\\n`` strictly before ``end``.

        Scans backwards in chunks — never loads the whole log, and never
        gives up as a function of line length (a single 70KB payload must
        not silently disable the integrity check). 0 when there is none.
        """
        pos = end
        while pos > 0:
            start = max(0, pos - _CHUNK)
            fh.seek(start)
            chunk = fh.read(pos - start)
            idx = chunk.rfind(b"\n")
            if idx != -1:
                return start + idx + 1
            pos = start
        return 0

    def _truncate_torn_line(self) -> None:
        """Drop a trailing partial line (crash mid-write) from the log.

        Truncation, not skipping: partial bytes left at the tail would be
        concatenated onto by the next append, corrupting the canonical log.
        """
        size = self._log_size()
        if size == 0:
            return
        with self._log_path.open("rb") as fh:
            fh.seek(size - 1)
            if fh.read(1) == b"\n":
                return
            cut = self._last_newline_before(fh, size)
        # cut is 0 when the whole file is one partial line.
        _log.warning(
            "jsonl-canonical: torn final line in %s — truncating %d byte(s)",
            self._log_path, size - cut,
        )
        with self._log_path.open("r+b") as fh:
            fh.truncate(cut)
            fh.flush()
            os.fsync(fh.fileno())

    def _prefix_intact(self, offset: int) -> bool:
        """Cheap integrity check on the consumed prefix.

        ``offset`` must land just past a newline, and the last line before it
        must decode to the same field values as the sqlite row it names
        (value equality via ``_row_matches`` — sqlite's numeric affinity
        makes byte comparison a false-mismatch trap) — a commitment
        comparison over one line rather than the whole file.

        One line, not the file: judging every row would make each open O(n)
        over the log. So this catches an edit to the last consumed row and
        nothing behind it — interior content is ``verify_chain``'s scope.
        """
        if offset == 0:
            return True
        with self._log_path.open("rb") as fh:
            fh.seek(offset - 1)
            if fh.read(1) != b"\n":
                return False
            # Walk back to the true line start however long the line is —
            # declining to judge past a fixed window would turn the check off
            # as a function of payload size.
            line_start = self._last_newline_before(fh, offset - 1)
            fh.seek(line_start)
            raw = fh.read(offset - 1 - line_start)
        try:
            line = raw.decode("utf-8")
        except UnicodeError:
            return False
        try:
            records = deserialize_records(line)
        except (JsonlCodecError, UnicodeError):
            return False
        # A batch line expands to N rows; every one must match its index row.
        # Cost is bounded by ceremony size, never log size — the "one line,
        # not the file" posture holds.
        return all(self._row_matches(t, row) for t, row in records)

    def _row_matches(self, t: str, row: tuple) -> bool:
        """Delegates to :func:`engine.canonical_audit.row_matches`.

        Open-time reconciliation and out-of-band verification must share one
        definition of "the same row" — value equality, never re-serialized
        text (sqlite's REAL affinity would make every integral ts look
        corrupt). Two copies of that rule is two answers about one store.
        """
        return row_matches(self._conn, t, row)

    def _read_lines(self, offset: int):
        """Yield ``(line, end_offset)`` for every COMPLETE line from offset."""
        with self._log_path.open("rb") as fh:
            fh.seek(offset)
            pos = offset
            for raw in fh:
                if not raw.endswith(b"\n"):
                    return  # incomplete tail — never indexed
                pos += len(raw)
                line = raw[:-1].decode("utf-8").strip()
                if line:
                    yield line, pos

    def _index_lines(
        self, offset: int, base_facts: int, base_ticks: int, *, rebuilding: bool = False
    ) -> tuple[int, int, int]:
        """Index every complete line from ``offset``. Verbatim: no mint
        machinery, no signer, signatures ride as stored.

        Returns ``(new_facts, new_ticks, end_offset)`` and stamps
        ``base + new`` — the marker is derived from the committed baseline
        handed in, never from per-handle state.
        """
        facts = ticks = 0
        end = offset
        for line, pos in self._read_lines(offset):
            # A batch line expands to its inner rows in array order — the
            # line is indexed entirely or (torn) truncated entirely, so a
            # ceremony can never index as a subset. facts += N; the offset
            # stamps at the line's end as for any line.
            for t, row in deserialize_records(line):
                try:
                    self._conn.execute(
                        FACT_INSERT_SQL if t == "fact" else TICK_INSERT_SQL, row
                    )
                except sqlite3.IntegrityError as exc:
                    if rebuilding:
                        # The tables were just cleared, so a collision here
                        # means the LOG carries the id twice. Rebuilding again
                        # would recurse forever on a log that cannot index.
                        raise JsonlCanonicalUnsupported(
                            f"{self._log_path} carries {t} {row[0]} more than "
                            "once — the canonical log cannot be indexed as "
                            "written"
                        ) from exc
                    raise _RowAlreadyIndexed(
                        f"index already holds {t} {row[0]}, a row the "
                        f"consumed-offset marker ({offset}) calls unindexed"
                    ) from exc
                if t == "fact":
                    facts += 1
                else:
                    ticks += 1
            end = pos
        self._stamp(end, base_facts + facts, base_ticks + ticks)
        self._conn.commit()
        return facts, ticks, end

    def _tail_forward(
        self, offset: int, base_facts: int, base_ticks: int
    ) -> tuple[int, int]:
        try:
            facts, ticks, end = self._index_lines(offset, base_facts, base_ticks)
        except _RowAlreadyIndexed as collision:
            # The marker understates what the index consumed: a line the offset
            # calls unindexed already has its row. Same class as the
            # ``_prefix_intact`` failure one line up in ``catch_up`` — the
            # index is not a function of the log at the stamped offset — and
            # the same answer, rebuild, because every colliding row IS
            # reproducible from the canonical log (unlike the out-of-band rows
            # ``_refuse_out_of_band`` protects). Raising instead would make the
            # store a permanent dead end that the verify gate calls
            # recoverable; before this, it surfaced as a raw sqlite
            # IntegrityError traceback out of every read verb.
            self._conn.rollback()
            raise collision
        _log.info(
            "jsonl-canonical: %s behind %s — tailed %d fact(s), %d tick(s) to %d",
            self._path, self._log_path, facts, ticks, end,
        )
        return base_facts + facts, base_ticks + ticks

    def _rebuild(self, reason: str) -> None:
        """Rebuild the whole sqlite index from the log.

        Clears ``facts`` and ``ticks`` only: ``store_meta`` survives, because
        ``own_lineage`` (which ``_decl.genesis`` row is *self*) is identity,
        not fact — it is not in the log and cannot be re-derived from it.

        The FTS index is dropped in the same transaction. ``facts`` has no
        ``AUTOINCREMENT``, so ``DELETE FROM facts`` resets sqlite's rowid
        counter and re-indexed rows take rowids that previously named other
        facts. ``facts_fts.fact_rowid`` keys on exactly that rowid and
        ``fts_state.last_rowid`` is the incremental watermark, so a surviving
        FTS index would resolve stale text to new facts and skip every
        re-indexed row. Dropping it makes search report ``missing`` (the
        honest "run reindex" state) instead of answering wrongly.
        """
        _log.warning(
            "jsonl-canonical: rebuilding sqlite index %s from %s — %s",
            self._path, self._log_path, reason,
        )
        self._conn.execute("DELETE FROM facts")
        self._conn.execute("DELETE FROM ticks")
        self._conn.execute("DROP TABLE IF EXISTS facts_fts")
        self._conn.execute("DROP TABLE IF EXISTS fts_state")
        facts, ticks, end = self._index_lines(0, 0, 0, rebuilding=True)
        _log.warning(
            "jsonl-canonical: rebuilt %d fact(s), %d tick(s) from %s (offset %d)",
            facts, ticks, self._log_path, end,
        )

    # ---- refusals ------------------------------------------------------

    def reanchor(self, *args: Any, **kwargs: Any):  # noqa: D102
        # Scope pin: reanchor is history-mutating, not append-shaped — it
        # belongs to the (undesigned) log-rewrite ceremony. The append-shaped
        # ceremonies (absorb_genesis/absorb_edit) are inherited and land
        # through the _ceremony_persist seam.
        raise JsonlCanonicalUnsupported(
            "reanchor is not wired for a JSONL-canonical store: it would "
            "rewrite sqlite rows while the canonical log kept the originals, "
            "so the index would stop being a function of the log. See "
            "design/architecture/jsonl-canonical-store — the log-rewrite "
            "ceremony is a later slice."
        )
