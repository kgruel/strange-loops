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
   counts can never disagree. Any failure rolls the whole transaction back,
   leaving the log untouched;
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
  newline, or the last line ending at ``offset`` does not re-serialize to
  the sqlite row it names — full rebuild of the sqlite index from the log,
  logged loudly at WARNING. That last check is the "hash match": a
  byte-compare of the codec's canonical line against the indexed row is
  exactly a commitment comparison, done on one line rather than the file.
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

Not yet wired (loud, not silent)
--------------------------------
History-mutating ops would rewrite rows sqlite-side while the log kept the
originals, making the index no longer a function of the log. Until the log
rewrite ceremony is designed they refuse with :class:`JsonlCanonicalUnsupported`:
``absorb_edit`` and ``reanchor`` here; ``rebirth``/``compact`` live in
``libs/store`` and are detected, not refused (above). ``absorb_genesis`` refuses
too — the judgment call the slice allowed. It is append-shaped, not
history-mutating, but its write is a ``BEGIN IMMEDIATE`` compare-and-swap
that may roll back *after* the row is built; flush-first durability would
make a rolled-back genesis real in the log. Reconciling the two orderings is
design work, not a small wiring, so it fails loudly here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Generic, TypeVar

from .jsonl_codec import (
    JsonlCodecError,
    deserialize_row,
    serialize_fact_row,
    serialize_tick_row,
)
from .sqlite_store import SqliteStore

__all__ = [
    "JsonlCanonicalUnsupported",
    "JsonlStore",
    "ensure_index",
    "log_path_for",
    "open_canonical_store",
    "resolved_index",
]

_log = logging.getLogger(__name__)

T = TypeVar("T")

_OFFSET_KEY = "jsonl_offset"
_FACT_COUNT_KEY = "jsonl_fact_count"
_TICK_COUNT_KEY = "jsonl_tick_count"

_CHUNK = 64 * 1024

_FACT_INSERT = (
    "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
_TICK_INSERT = (
    "INSERT INTO ticks (id, name, ts, since, origin, payload, "
    "prev_hash, window_start, fact_cursor, window_hash, signature) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


class JsonlCanonicalUnsupported(NotImplementedError):
    """A history-mutating op was called on a JSONL-canonical store.

    Rewriting sqlite rows in place would break the layer's whole claim — that
    the index is a function of the log (design/architecture/jsonl-canonical
    -store). The log-rewrite ceremony is not designed yet, so these refuse
    rather than silently diverge.
    """


def log_path_for(db_path: Path) -> Path:
    """The canonical log beside a store db: ``<name>.db`` → ``<name>.jsonl``."""
    return Path(db_path).with_suffix(".jsonl")


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
    try:
        conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (_OFFSET_KEY,)
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    if row is None:
        return False
    try:
        return int(row[0]) == size
    except (TypeError, ValueError):
        return False


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
        self._ensure_fact_signature_column()
        self._ensure_chain_columns()
        self._ensure_meta_table()
        try:
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
        row = self._conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None

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
        sql = "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)"
        for key, value in (
            (_OFFSET_KEY, offset),
            (_FACT_COUNT_KEY, facts),
            (_TICK_COUNT_KEY, ticks),
        ):
            self._conn.execute(sql, (key, str(value)))

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
        return self._log_size()

    def _write(self, sql: str, row: tuple, line: str, is_fact: bool) -> None:
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

    def _write_fact_row(self, row: tuple) -> None:
        self._write(_FACT_INSERT, row, serialize_fact_row(row), True)

    def _write_tick_row(self, row: tuple) -> None:
        self._write(_TICK_INSERT, row, serialize_tick_row(row), False)

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

        facts, ticks = self._tail_forward(offset, base_facts, base_ticks)
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
        must re-serialize byte-identically from the sqlite row it names — a
        commitment comparison over one line rather than the whole file.

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
            t, row = deserialize_row(line)
        except (JsonlCodecError, UnicodeError):
            return False
        return self._row_matches(t, row)

    def _row_matches(self, t: str, row: tuple) -> bool:
        table, cols = (
            ("facts", "id, kind, ts, observer, origin, payload, signature")
            if t == "fact"
            else (
                "ticks",
                "id, name, ts, since, origin, payload, prev_hash, "
                "window_start, fact_cursor, window_hash, signature",
            )
        )
        stored = self._conn.execute(
            f"SELECT {cols} FROM {table} WHERE id = ?", (row[0],)
        ).fetchone()
        if stored is None:
            return False
        # Compare VALUES, not re-serialized text: sqlite's REAL affinity
        # returns 1700000000.0 for a line carrying 1700000000, and
        # re-serializing would make every integral ts/since look corrupt —
        # a full rebuild on every open, drowning the real-corruption signal.
        # Python's cross-type numeric equality normalizes that uniformly.
        return tuple(stored) == tuple(row)

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
        self, offset: int, base_facts: int, base_ticks: int
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
            t, row = deserialize_row(line)
            self._conn.execute(_FACT_INSERT if t == "fact" else _TICK_INSERT, row)
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
        facts, ticks, end = self._index_lines(offset, base_facts, base_ticks)
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
        facts, ticks, end = self._index_lines(0, 0, 0)
        _log.warning(
            "jsonl-canonical: rebuilt %d fact(s), %d tick(s) from %s (offset %d)",
            facts, ticks, self._log_path, end,
        )

    # ---- refusals ------------------------------------------------------

    def _refuse(self, op: str) -> None:
        raise JsonlCanonicalUnsupported(
            f"{op} is not wired for a JSONL-canonical store: it would rewrite "
            "sqlite rows while the canonical log kept the originals, so the "
            "index would stop being a function of the log. See "
            "design/architecture/jsonl-canonical-store — the log-rewrite "
            "ceremony is a later slice."
        )

    def absorb_genesis(self, *args: Any, **kwargs: Any):  # noqa: D102
        self._refuse("absorb_genesis")

    def absorb_edit(self, *args: Any, **kwargs: Any):  # noqa: D102
        self._refuse("absorb_edit")

    def reanchor(self, *args: Any, **kwargs: Any):  # noqa: D102
        self._refuse("reanchor")
