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
1. serialize the row through the S1 codec — ``payload`` rides as the
   VERBATIM stored TEXT, never re-serialized, so every existing signature
   and commitment hash survives the round trip;
2. append the line + ``\\n`` to the log, ``flush()`` + ``os.fsync()`` — the
   line is durable *before* the id is anything anyone can observe;
3. index into sqlite, and stamp the consumed byte offset, in ONE
   transaction (row and offset can never disagree);
4. return the id. The id in the receipt is the id in the durable line.

Catch-up on open
----------------
``store_meta.jsonl_offset`` holds the byte offset of the log consumed into
sqlite. On open:

- ``offset == size`` — in sync, nothing to do.
- ``offset < size`` — sqlite is behind (crash between step 2 and step 3, or
  an out-of-band append): tail forward, indexing the missed lines verbatim.
- ``offset > size`` (log shrank), the byte at ``offset - 1`` is not a
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

Not yet wired (loud, not silent)
--------------------------------
History-mutating ops would rewrite rows sqlite-side while the log kept the
originals, making the index no longer a function of the log. Until the log
rewrite ceremony is designed they refuse with :class:`JsonlCanonicalUnsupported`:
``absorb_edit`` and ``reanchor`` here; ``rebirth``/``compact`` live in
``libs/store`` and are out of this slice's reach. ``absorb_genesis`` refuses
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

__all__ = ["JsonlCanonicalUnsupported", "JsonlStore", "log_path_for"]

_log = logging.getLogger(__name__)

T = TypeVar("T")

_OFFSET_KEY = "jsonl_offset"

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
        self.catch_up()

    @property
    def log_path(self) -> Path:
        """The canonical log this store's sqlite index derives from."""
        return self._log_path

    # ---- offset bookkeeping ------------------------------------------

    def _read_offset(self) -> int | None:
        row = self._conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (_OFFSET_KEY,)
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None

    def _offset_stmt(self, offset: int) -> tuple[str, tuple]:
        return (
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)",
            (_OFFSET_KEY, str(offset)),
        )

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

    def _index(self, sql: str, row: tuple, offset: int) -> None:
        """Index one row and stamp the consumed offset — one transaction."""
        stmt, params = self._offset_stmt(offset)
        self._conn.execute(sql, row)
        self._conn.execute(stmt, params)
        self._conn.commit()

    def _write_fact_row(self, row: tuple) -> None:
        self._index(_FACT_INSERT, row, self._append_line(serialize_fact_row(row)))

    def _write_tick_row(self, row: tuple) -> None:
        self._index(_TICK_INSERT, row, self._append_line(serialize_tick_row(row)))

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
            self._index_offset(0)
            return "empty"

        if offset is None:
            self._rebuild("no consumed-offset marker recorded")
            return "rebuilt"
        if offset > size:
            self._rebuild(f"log shrank: offset {offset} > size {size}")
            return "rebuilt"
        if not self._prefix_intact(offset):
            self._rebuild(f"log content at offset {offset} does not match the index")
            return "rebuilt"
        if offset == size:
            return "synced"

        self._tail_forward(offset)
        return "tailed"

    def _has_rows(self) -> bool:
        for table in ("facts", "ticks"):
            if self._conn.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()[0]:
                return True
        return False

    def _index_offset(self, offset: int) -> None:
        stmt, params = self._offset_stmt(offset)
        self._conn.execute(stmt, params)
        self._conn.commit()

    def _truncate_torn_line(self) -> None:
        """Drop a trailing partial line (crash mid-write) from the log.

        Truncation, not skipping: partial bytes left at the tail would be
        concatenated onto by the next append, corrupting the canonical log.
        """
        size = self._log_size()
        if size == 0:
            return
        cut = 0
        with self._log_path.open("rb") as fh:
            fh.seek(size - 1)
            if fh.read(1) == b"\n":
                return
            # Scan backwards in chunks for the last newline — never load the
            # whole log (live logs run to hundreds of megabytes).
            pos = size
            while pos > 0:
                start = max(0, pos - 65536)
                fh.seek(start)
                chunk = fh.read(pos - start)
                idx = chunk.rfind(b"\n")
                if idx != -1:
                    cut = start + idx + 1
                    break
                pos = start
        # cut stays 0 when the whole file is one partial line.
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
        """
        if offset == 0:
            return True
        with self._log_path.open("rb") as fh:
            start = max(0, offset - 1024 * 64)
            fh.seek(start)
            chunk = fh.read(offset - start)
        if not chunk.endswith(b"\n"):
            return False
        line_start = chunk.rfind(b"\n", 0, len(chunk) - 1) + 1
        if line_start == 0 and start != 0:
            return True  # one very long line; the cheap check declines to judge
        line = chunk[line_start:-1].decode("utf-8", errors="replace")
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
        serialize = serialize_fact_row if t == "fact" else serialize_tick_row
        return serialize(tuple(stored)) == serialize(row)

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

    def _index_lines(self, offset: int) -> tuple[int, int, int]:
        """Index every complete line from ``offset``. Verbatim: no mint
        machinery, no signer, signatures ride as stored."""
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
        stmt, params = self._offset_stmt(end)
        self._conn.execute(stmt, params)
        self._conn.commit()
        return facts, ticks, end

    def _tail_forward(self, offset: int) -> None:
        facts, ticks, end = self._index_lines(offset)
        _log.info(
            "jsonl-canonical: %s behind %s — tailed %d fact(s), %d tick(s) to %d",
            self._path, self._log_path, facts, ticks, end,
        )

    def _rebuild(self, reason: str) -> None:
        """Rebuild the whole sqlite index from the log.

        Clears ``facts`` and ``ticks`` only: ``store_meta`` survives, because
        ``own_lineage`` (which ``_decl.genesis`` row is *self*) is identity,
        not fact — it is not in the log and cannot be re-derived from it.
        """
        _log.warning(
            "jsonl-canonical: rebuilding sqlite index %s from %s — %s",
            self._path, self._log_path, reason,
        )
        self._conn.execute("DELETE FROM facts")
        self._conn.execute("DELETE FROM ticks")
        facts, ticks, end = self._index_lines(0)
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
