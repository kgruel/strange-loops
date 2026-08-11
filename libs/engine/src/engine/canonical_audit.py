"""canonical_audit — does the derived index still agree with the canonical log?

A JSONL-canonical store (design/architecture/jsonl-canonical-store) has two
artifacts: the ``.jsonl`` log, which IS the store, and the sibling ``.db``,
which is an index derived from it. Every verification surface before this
module walked the *index* only, so an out-of-band sqlite row — a row the log
never carried — still rendered ``✓ chain intact`` at rc=0. That is a false
attestation of exactly the lie-class the chain exists to prevent
(design/store/verify-canonical-agreement).

This module is the reader that judges the two artifacts against each other.

**Pure reader, by contract.** Nothing here constructs a :class:`~engine.
jsonl_store.JsonlStore`. That constructor *repairs* — catch-up, torn-line
truncation, rebuild-on-divergence — and repair destroys the evidence
verification exists to inspect. Open-time recovery and verification are
opposite contracts, so they never share a code path: the log is read with
plain file IO through :mod:`engine.jsonl_codec`, the index with a read-only
sqlite connection, and neither offset nor count marker is ever written.

Two depths:

``audit_agreement``  (L1, the default gate)
    Three O(1)-ish checks: the stamped byte offset equals the log's size, the
    stamped row counts equal ``COUNT(*)`` per table, and the last complete log
    line agrees field-for-field with the index row it names. Cheap enough to
    run in front of every store read verb.

``audit_deep``  (``--deep``)
    Streams every log line — bounded memory, never the whole 111MB-class log
    at once — comparing fields *and* order against the index rows in rowid
    order, then re-derives the tick hash chain FROM CANONICAL CONTENT rather
    than from the index it is judging.

SCOPE BOUNDARY, stated rather than implied: a *coordinated* edit of an
unsealed fact in both artifacts is uncaught here, because nothing yet commits
to that fact's content — the witnesses at the live edge are the fact's own
signature and the next seal, not this audit. Pinned by
``test_interior_tamper_of_an_unsealed_fact_is_caught_by_nothing``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .jsonl_codec import JsonlCodecError, deserialize_row
from .sqlite_store import (
    FACT_COLUMNS,
    TICK_COLUMNS,
    _fact_row_hash,
    _tick_row_hash,
)

__all__ = [
    "OFFSET_KEY",
    "FACT_COUNT_KEY",
    "TICK_COUNT_KEY",
    "Check",
    "AgreementReport",
    "row_matches",
    "audit_agreement",
    "audit_deep",
]

# The marker keys, spelled once. ``engine.jsonl_store`` writes them and this
# module reads them; two spellings of a marker name is how a writer and an
# auditor end up disagreeing about a store that is fine.
OFFSET_KEY = "jsonl_offset"
FACT_COUNT_KEY = "jsonl_fact_count"
TICK_COUNT_KEY = "jsonl_tick_count"

_EMPTY_WINDOW = hashlib.sha256().hexdigest()


@dataclass(frozen=True)
class Check:
    """One named agreement check and its verdict.

    ``name`` is the handle a caller reports ("offset", "counts", …) so the
    output can say WHICH check failed rather than "verification failed".
    """

    name: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.name, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class AgreementReport:
    """The verdict of an audit: every check that ran, in the order it ran."""

    checks: tuple[Check, ...] = ()
    deep: bool = False
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def divergences(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.ok)

    def summary(self) -> str:
        """One line naming the failures — '' when everything agreed."""
        return "; ".join(f"{c.name}: {c.detail}" for c in self.divergences)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "deep": self.deep,
            "checks": [c.as_dict() for c in self.checks],
            **({"counts": dict(self.counts)} if self.counts else {}),
        }


# --- shared primitives -----------------------------------------------------


def row_matches(conn, t: str, row: tuple) -> bool:
    """Does the index row named by this log row carry the same VALUES?

    Value equality, never re-serialized text: sqlite's REAL affinity returns
    ``1700000000.0`` for a line carrying ``1700000000``, so a byte comparison
    would call every integral ``ts`` corrupt. Python's cross-type numeric
    equality normalizes that uniformly.

    Extracted from ``JsonlStore._row_matches`` — which now delegates here —
    so open-time reconciliation and out-of-band verification cannot drift
    into two different definitions of "the same row".
    """
    table, columns = (
        ("facts", FACT_COLUMNS) if t == "fact" else ("ticks", TICK_COLUMNS)
    )
    columns = _present(conn, table, columns)
    stored = conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE id = ?", (row[0],)
    ).fetchone()
    if stored is None:
        return False
    return tuple(stored) == _trim(row, len(columns))


def _present(conn, table: str, columns: tuple[str, ...]) -> tuple[str, ...]:
    """``columns`` narrowed to those the table actually has.

    A pre-signature-era index has no ``signature`` column. Verification never
    migrates schema (the same rule ``verify_chain`` holds), so it asks for what
    is there and compares the arity it got.
    """
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return tuple(c for c in columns if c in have)


def _trim(row: tuple, n: int) -> tuple:
    """A full-arity codec row cut to ``n`` fields, refusing to drop a value.

    Dropping a *present* signature to match a signature-less index would make
    a strip look like agreement, so the trailing fields must be ``None``.
    """
    if len(row) <= n:
        return tuple(row)
    if any(v is not None for v in row[n:]):
        return tuple(row)  # arity mismatch → compares unequal, which is right
    return tuple(row[:n])


def _open_index(index: Path):
    from .declaration import _open_readonly

    if not index.exists():
        return None
    conn = _open_readonly(index)
    if conn is None:
        return None
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    except Exception:  # noqa: BLE001 — an unreadable index is "no index"
        conn.close()
        return None
    if not {"facts", "ticks"} <= tables:
        conn.close()
        return None
    return conn


def _meta_int(conn, key: str) -> int | None:
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
    except Exception:  # noqa: BLE001 — no store_meta table is "no marker"
        return None
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _log_size(canonical: Path) -> int:
    try:
        return canonical.stat().st_size
    except OSError:
        return -1


def _iter_lines(canonical: Path) -> Iterator[tuple[int, int, str]]:
    """Yield ``(lineno, end_offset, line)`` for every COMPLETE log line.

    Streams one line at a time — a 111MB log is never resident. An incomplete
    tail (the torn-write window) ends iteration: it was never indexed, and
    truncating it is the *writer's* job, not an auditor's.
    """
    with canonical.open("rb") as fh:
        pos = 0
        for lineno, raw in enumerate(fh, 1):
            if not raw.endswith(b"\n"):
                return
            pos += len(raw)
            text = raw[:-1].decode("utf-8", "replace").strip()
            if text:
                yield lineno, pos, text


def _last_line(canonical: Path, size: int) -> str | None:
    """The last complete line of the log, read without scanning the file."""
    if size <= 0:
        return None
    with canonical.open("rb") as fh:
        end = size
        fh.seek(end - 1)
        if fh.read(1) != b"\n":
            return None
        # Walk back in chunks until a newline appears before the final one.
        chunk = 64 * 1024
        start = end - 1
        while start > 0:
            read_from = max(0, start - chunk)
            fh.seek(read_from)
            buf = fh.read(start - read_from)
            idx = buf.rfind(b"\n")
            if idx != -1:
                start = read_from + idx + 1
                break
            start = read_from
        fh.seek(start)
        raw = fh.read(end - 1 - start)
    try:
        return raw.decode("utf-8").strip() or None
    except UnicodeError:
        return None


# --- L1: the default agreement gate ----------------------------------------


def audit_agreement(canonical: Path) -> AgreementReport:
    """The default gate: do the log and its index still agree, cheaply?

    Three checks, in the order a divergence is most likely to be explained by:

    ``index``      the derived index exists and is a readable store
    ``offset``     stamped byte offset == the log's size on disk
    ``counts``     stamped fact/tick counts == ``COUNT(*)`` per table
    ``last-line``  the last complete log line == the index row it names

    Together they catch the two lie-shapes the index-only walk missed: an
    out-of-band sqlite row (counts diverge) and a durable-but-unindexed log
    line (offset diverges). Interior agreement is ``audit_deep``'s scope.
    """
    canonical = Path(canonical)
    from .residence import index_path_for

    checks: list[Check] = []
    size = _log_size(canonical)
    if size < 0:
        return AgreementReport(
            (Check("log", False, f"canonical log unreadable at {canonical}"),)
        )

    conn = _open_index(index_path_for(canonical))
    if conn is None:
        return AgreementReport(
            (
                Check(
                    "index",
                    False,
                    f"no readable derived index at {index_path_for(canonical)} — "
                    "run any read verb to materialize it, then verify",
                ),
            )
        )
    try:
        checks.append(Check("index", True, "derived index readable"))
        offset = _meta_int(conn, OFFSET_KEY)
        counts = _row_counts(conn)
        checks.append(_check_offset(offset, size))
        checks.append(_check_counts(conn, counts))
        checks.append(_check_last_line(conn, canonical, size))
        return AgreementReport(tuple(checks), counts=counts)
    finally:
        conn.close()


def _row_counts(conn) -> dict[str, int]:
    return {
        "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
        "ticks": conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0],
    }


def _check_offset(offset: int | None, size: int) -> Check:
    if offset is None:
        if size == 0:
            return Check("offset", True, "empty log, nothing to have consumed")
        return Check(
            "offset", False,
            f"no consumed-offset marker, but the log holds {size} byte(s) — "
            "the index cannot account for the canonical log",
        )
    if offset == size:
        return Check("offset", True, f"index has consumed all {size} byte(s)")
    if offset < size:
        return Check(
            "offset", False,
            f"log is ahead of the index: {size - offset} durable byte(s) "
            f"unindexed (offset {offset}, log {size})",
        )
    return Check(
        "offset", False,
        f"index claims to have consumed {offset} byte(s) but the log holds "
        f"only {size} — the log was truncated or replaced",
    )


def _check_counts(conn, counts: dict[str, int]) -> Check:
    marked_facts = _meta_int(conn, FACT_COUNT_KEY)
    marked_ticks = _meta_int(conn, TICK_COUNT_KEY)
    if marked_facts is None or marked_ticks is None:
        if not counts["facts"] and not counts["ticks"]:
            return Check("counts", True, "no rows, no markers")
        return Check(
            "counts", False,
            f"no row-count markers, but the index holds {counts['facts']} "
            f"fact(s) and {counts['ticks']} tick(s)",
        )
    bad = []
    if marked_facts != counts["facts"]:
        bad.append(
            f"facts: index has {counts['facts']}, log accounts for {marked_facts}"
        )
    if marked_ticks != counts["ticks"]:
        bad.append(
            f"ticks: index has {counts['ticks']}, log accounts for {marked_ticks}"
        )
    if bad:
        return Check(
            "counts", False,
            "; ".join(bad) + " — row(s) entered the index out of band",
        )
    return Check(
        "counts", True,
        f"{counts['facts']} fact(s), {counts['ticks']} tick(s) accounted for",
    )


def _check_last_line(conn, canonical: Path, size: int) -> Check:
    if size == 0:
        return Check("last-line", True, "empty log")
    line = _last_line(canonical, size)
    if line is None:
        return Check(
            "last-line", False,
            "the log's final line is incomplete or unreadable",
        )
    try:
        t, row = deserialize_row(line)
    except (JsonlCodecError, UnicodeError) as exc:
        return Check("last-line", False, f"final log line does not decode: {exc}")
    if not row_matches(conn, t, row):
        return Check(
            "last-line", False,
            f"final log {t} {row[0]} does not match the index row of the "
            "same id — the index was edited out of band",
        )
    return Check("last-line", True, f"final log {t} {row[0]} matches the index")


# --- --deep: line-by-line, and the chain from canonical content ------------


def audit_deep(canonical: Path) -> AgreementReport:
    """Stream the whole log and judge the index against it, line by line.

    Runs :func:`audit_agreement` first (a cheap check that already failed is
    the more useful report), then two deeper passes in one streaming walk:

    1. **Content and order.** Every log line is decoded and compared, field
       for field, against the next index row in *rowid* order for its table.
       Facts and ticks carry independent rowids, so cross-table interleave is
       not recoverable from sqlite and is not claimed to be checked — per
       table, order is exact.
    2. **The chain, re-derived from canonical content.** ``prev_hash``,
       ``window_start`` continuity and ``window_hash`` are recomputed from the
       rows the *log* carries, using the same era-aware hashers the write path
       used. This is the check the index-only walk cannot make: a chain that
       verifies against a poisoned index still has to verify against the log.

    Memory is bounded by row COUNT, not payload size: the walk keeps one
    32-byte digest and one id per fact, and never holds a payload after the
    line that carried it is judged.
    """
    canonical = Path(canonical)
    from .residence import index_path_for

    base = audit_agreement(canonical)
    if any(c.name in ("log", "index") and not c.ok for c in base.checks):
        return AgreementReport(base.checks, deep=True, counts=base.counts)

    conn = _open_index(index_path_for(canonical))
    if conn is None:  # pragma: no cover — audit_agreement just opened it
        return AgreementReport(base.checks, deep=True)
    try:
        checks = [*base.checks, *_deep_checks(conn, canonical)]
        return AgreementReport(tuple(checks), deep=True, counts=base.counts)
    finally:
        conn.close()


def _index_cursor(conn, table: str, columns: tuple[str, ...]):
    cols = _present(conn, table, columns)
    return len(cols), conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} ORDER BY rowid"
    )


def _deep_checks(conn, canonical: Path) -> list[Check]:
    fact_arity, fact_rows = _index_cursor(conn, "facts", FACT_COLUMNS)
    tick_arity, tick_rows = _index_cursor(conn, "ticks", TICK_COLUMNS)
    cursors = {"fact": (fact_arity, fact_rows), "tick": (tick_arity, tick_rows)}
    seen = {"fact": 0, "tick": 0}

    chain = _ChainWalk()
    content: Check | None = None

    for lineno, _end, line in _iter_lines(canonical):
        try:
            t, row = deserialize_row(line)
        except (JsonlCodecError, UnicodeError) as exc:
            content = content or Check(
                "content", False, f"log line {lineno} does not decode: {exc}"
            )
            break
        arity, rows = cursors[t]
        stored = rows.fetchone()
        seen[t] += 1
        if stored is None:
            content = content or Check(
                "content", False,
                f"log line {lineno} ({t} {row[0]}) has no index row — the "
                f"index holds only {seen[t] - 1} {t}(s)",
            )
            break
        if tuple(stored) != _trim(row, arity):
            content = content or Check(
                "content", False,
                f"log line {lineno} ({t} {row[0]}) disagrees with index "
                f"{t} {stored[0]} at the same position"
                + (
                    ""
                    if stored[0] == row[0]
                    else " — the index rows are out of log order"
                ),
            )
            break
        chain.feed(lineno, t, row)

    if content is None:
        extra = [
            f"{n} extra {t}(s)"
            for t, (_a, rows) in cursors.items()
            if (n := len(rows.fetchall()))
        ]
        content = (
            Check(
                "content", False,
                "index holds row(s) the log never carried: " + ", ".join(extra),
            )
            if extra
            else Check(
                "content", True,
                f"{seen['fact']} fact(s) and {seen['tick']} tick(s) match the "
                "log field-for-field, in order",
            )
        )
    return [content, chain.verdict()]


class _ChainWalk:
    """Re-derives the tick chain from log content as the log streams by.

    Keeps ``(id, row-hash)`` per fact — bounded by fact count, never payload
    size — because a window commitment is a hash over the fact rows inside it
    and the log is the only place those rows are authoritative.
    """

    def __init__(self) -> None:
        self._fact_ids: list[str] = []
        self._fact_hashes: list[bytes] = []
        self._pos: dict[str, int] = {}
        self._prev_row: tuple | None = None
        self._last_cursor: str | None = None
        self._breaks: list[str] = []
        self._chained = 0

    def feed(self, lineno: int, t: str, row: tuple) -> None:
        if t == "fact":
            self._pos.setdefault(row[0], len(self._fact_ids))
            self._fact_ids.append(row[0])
            self._fact_hashes.append(bytes.fromhex(_fact_row_hash(row)))
            return
        self._tick(lineno, row)

    def _tick(self, lineno: int, row: tuple) -> None:
        if row[9] is None:  # pre-chain era — nothing committed to verify
            self._prev_row = row
            return
        self._chained += 1
        expected_prev = (
            _tick_row_hash(self._prev_row) if self._prev_row is not None else None
        )
        if row[6] != expected_prev:
            self._break(lineno, row, "prev_hash mismatch — tick sequence altered")
        if self._last_cursor is not None and row[7] != self._last_cursor:
            self._break(
                lineno, row,
                "window_start does not continue the previous fact_cursor — "
                "coverage gap",
            )
        if self._window_hash(row[7], row[8]) != row[9]:
            self._break(
                lineno, row, "window_hash mismatch — facts in the window altered"
            )
        self._last_cursor = row[8]
        self._prev_row = row

    def _break(self, lineno: int, row: tuple, reason: str) -> None:
        if len(self._breaks) < 10:
            self._breaks.append(f"log line {lineno} (tick {row[0]}): {reason}")

    def _cursor_pos(self, fact_id: str) -> int | None:
        """A window cursor as a position in log fact order.

        ``""`` is the start-of-store sentinel (position 0, before the first
        fact); an id the log never carried is unresolvable — the window then
        hashes empty, exactly as ``SqliteStore._window_hash`` does, so an
        honest empty window still agrees and a real one mismatches.
        """
        if fact_id == "":
            return 0
        pos = self._pos.get(fact_id)
        return None if pos is None else pos + 1

    def _window_hash(self, start: str, end: str) -> str:
        lo = self._cursor_pos(start)
        hi = self._cursor_pos(end)
        if lo is None or hi is None:
            return _EMPTY_WINDOW
        h = hashlib.sha256()
        for digest in self._fact_hashes[lo:hi]:
            h.update(digest.hex().encode())
        return h.hexdigest()

    def verdict(self) -> Check:
        if self._breaks:
            return Check("chain", False, "; ".join(self._breaks))
        return Check(
            "chain", True,
            f"{self._chained} chained tick(s) re-derived from canonical content",
        )
