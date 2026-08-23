"""canonical_audit — does the derived index still agree with the canonical log?

An arrival-canonical store has two artifacts: the ``.arrival`` log, which IS
the store, and the sibling ``.db``, which is an index derived from it. Every
verification surface before this module walked the *index* only, so an
out-of-band sqlite row — a row the log never carried — still rendered
``✓ chain intact`` at rc=0. That is a false attestation of exactly the lie-class
the chain exists to prevent (design/store/verify-canonical-agreement).

This module is the reader that judges the two artifacts against each other.

**Pure reader, by contract.** Nothing here constructs an :class:`~engine.
arrival_store.ArrivalStore` or :class:`~engine.jsonl_store.JsonlStore`. Those
constructors *repair* — catch-up, torn-line truncation, rebuild-on-divergence
— and repair destroys the evidence verification exists to inspect. Open-time
recovery and verification are opposite contracts, so they never share a code
path: the log is read with pure readers, the index with a read-only sqlite
connection, and no mark or metadata is ever written.

Two depths:

``audit_agreement``  (L1, the default gate)
    Five checks per §D3 for arrival stores:
    - ``index``: derived index exists and is readable.
    - ``consumed``: stamped ResumeMark vs log head ordinal (suffix count via
      ``walk_marked`` — O(records behind)).
    - ``rewound``: any index row with arrival_ordinal > consumed_ordinal.
    - ``counts``: stamped counters vs COUNT(*), plus NULL-coordinate backstop.
    - ``consumed_edge``: read record at consumed ordinal via
      :meth:`engine.arrival.ArrivalLog.anchor`, expand ``rows_of_record``,
      and ``row_matches`` every row.
    L1 MUST NOT call ``ArrivalLog.read`` or ``ArrivalLog.walk`` (both walk from zero).

``audit_deep``  (``--deep``)
    L1 then full :meth:`engine.arrival.ArrivalLog.walk` (density, hashes,
    ordinals, chain), row-by-row index comparison over ``rows_of_record``,
    multiset derived log audit (:func:`engine.arrival_projection.audit_derived_log`),
    and tick hash chain re-derived from log content.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .arrival import (
    ArrivalCorrupt,
    ArrivalError,
    ArrivalLog,
    ResumeMark,
)
from .arrival_projection import (
    audit_derived_log,
    derived_log_path_for,
    rows_of_record,
)
from .jsonl_codec import JsonlCodecError, deserialize_records
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

# The marker keys, spelled once.
ARRIVAL_LINEAGE_KEY = "arrival_lineage"
ARRIVAL_OFFSET_KEY = "arrival_offset"
ARRIVAL_ORDINAL_KEY = "arrival_ordinal"

OFFSET_KEY = "jsonl_offset"
FACT_COUNT_KEY = "jsonl_fact_count"
TICK_COUNT_KEY = "jsonl_tick_count"

_EMPTY_WINDOW = hashlib.sha256().hexdigest()


@dataclass(frozen=True)
class Check:
    """One named agreement check and its verdict.

    ``name`` is the handle a caller reports ("index", "consumed", "rewound",
    "counts", "consumed_edge", "content", "chain", "derived_log", …) so
    the output can say WHICH check failed rather than "verification failed".
    """

    name: str
    ok: bool
    detail: str = ""
    behind_by: int = 0
    at_ordinal: int = -1

    @property
    def beyond_offset(self) -> bool:
        """Compatibility property for legacy callers."""
        return self.behind_by > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "behind_by": self.behind_by,
            "at_ordinal": self.at_ordinal,
            "beyond_offset": self.beyond_offset,
        }


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

    @property
    def index_behind(self) -> bool:
        """Diverged, but only because the index is behind the log.

        A location claim, never an innocence claim. True when there is at
        least one divergence and every divergence has ``behind_by > 0`` (the
        index has not consumed through the arrival log head). Any other
        divergence — rewound marker, count mismatch, content mismatch, chain
        break — keeps this False.
        """
        d = self.divergences
        return bool(d) and all(c.behind_by > 0 for c in d)

    def summary(self) -> str:
        """One line naming the failures — '' when everything agreed."""
        return "; ".join(f"{c.name}: {c.detail}" for c in self.divergences)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "deep": self.deep,
            "index_behind": self.index_behind,
            "checks": [c.as_dict() for c in self.checks],
            **({"counts": dict(self.counts)} if self.counts else {}),
        }


# --- shared primitives -----------------------------------------------------


def row_matches(conn: sqlite3.Connection, t: str, row: tuple) -> bool:
    """Does the index row named by this log row carry the same VALUES?

    Value equality, never re-serialized text: sqlite's REAL affinity returns
    ``1700000000.0`` for a line carrying ``1700000000``, so a byte comparison
    would call every integral ``ts`` corrupt. Python's cross-type numeric
    equality normalizes that uniformly.
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


def _present(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> tuple[str, ...]:
    """``columns`` narrowed to those the table actually has."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return tuple(c for c in columns if c in have)


def _trim(row: tuple, n: int) -> tuple:
    """A full-arity codec row cut to ``n`` fields, refusing to drop a value."""
    if len(row) <= n:
        return tuple(row)
    if any(v is not None for v in row[n:]):
        return tuple(row)  # arity mismatch → compares unequal, which is right
    return tuple(row[:n])


def _open_index(index: Path) -> sqlite3.Connection | None:
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


def _meta_int(conn: sqlite3.Connection, key: str) -> int | None:
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _meta_str(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return None if row is None else str(row[0])


def _read_mark(conn: sqlite3.Connection) -> ResumeMark | None:
    lineage = _meta_str(conn, ARRIVAL_LINEAGE_KEY)
    offset = _meta_int(conn, ARRIVAL_OFFSET_KEY)
    ordinal = _meta_int(conn, ARRIVAL_ORDINAL_KEY)
    if lineage is None or offset is None or ordinal is None:
        return None
    return ResumeMark(
        arrival_lineage=lineage,
        arrival_offset=offset,
        arrival_ordinal=ordinal,
    )


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
        "ticks": conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0],
    }


def _log_size(canonical: Path) -> int:
    try:
        return canonical.stat().st_size
    except OSError:
        return -1


# --- Top-Level Audit Verbs -------------------------------------------------


def audit_agreement(canonical: Path) -> AgreementReport:
    """The default gate: do the log and its index still agree, cheaply?"""
    canonical = Path(canonical)
    from .residence import canonical_mode

    mode = canonical_mode(canonical)
    if mode == "arrival":
        return _audit_agreement_arrival(canonical)
    return _audit_agreement_jsonl(canonical)


def audit_deep(canonical: Path) -> AgreementReport:
    """Stream the whole log and judge the index against it, record by record."""
    canonical = Path(canonical)
    from .residence import canonical_mode

    mode = canonical_mode(canonical)
    if mode == "arrival":
        return _audit_deep_arrival(canonical)
    return _audit_deep_jsonl(canonical)


# --- Arrival L1 and --deep -------------------------------------------------


def _audit_agreement_arrival(canonical: Path) -> AgreementReport:
    from .residence import index_path_for

    if not canonical.exists():
        return AgreementReport(
            (Check("log", False, f"canonical log unreadable at {canonical}"),)
        )

    log = ArrivalLog(canonical)
    size = log.size()
    if size < 0:
        return AgreementReport(
            (Check("log", False, f"canonical log unreadable at {canonical}"),)
        )

    index_path = index_path_for(canonical)
    conn = _open_index(index_path)
    if conn is None:
        return AgreementReport(
            (
                Check(
                    "index",
                    False,
                    f"no readable derived index at {index_path} — "
                    "run any read verb to materialize it, then verify",
                ),
            )
        )

    try:
        checks: list[Check] = [Check("index", True, "derived index readable")]
        mark = _read_mark(conn)
        counts = _row_counts(conn)

        # 1. Anchor resolution
        anchor_record = log.anchor(mark) if mark is not None else None

        # 2. consumed check
        consumed_check = _check_consumed_arrival(log, size, mark, anchor_record)
        checks.append(consumed_check)

        # 3. rewound check
        rewound_check = _check_rewound_arrival(conn, mark)
        checks.append(rewound_check)

        # 4. counts check
        counts_check = _check_counts_arrival(conn, counts)
        checks.append(counts_check)

        # 5. consumed_edge check
        edge_check = _check_consumed_edge_arrival(conn, size, mark, anchor_record)
        checks.append(edge_check)

        return AgreementReport(tuple(checks), counts=counts)
    finally:
        conn.close()


def _check_consumed_arrival(
    log: ArrivalLog,
    size: int,
    mark: ResumeMark | None,
    anchor_record: dict | None,
) -> Check:
    if mark is None:
        if size == 0:
            return Check("consumed", True, "empty log, nothing to have consumed", at_ordinal=-1)
        resumed, pairs = log.walk_marked(None)
        suffix_count = sum(1 for _ in pairs)
        return Check(
            "consumed",
            False,
            f"index is behind arrival by {suffix_count} record(s), consumed through ordinal -1",
            behind_by=suffix_count,
            at_ordinal=-1,
        )

    if anchor_record is None:
        if mark.arrival_offset > size:
            return Check(
                "consumed",
                False,
                f"index claims to have consumed {mark.arrival_offset} byte(s) "
                f"through ordinal {mark.arrival_ordinal}, but the log holds only {size} — "
                "the log was truncated or replaced",
                at_ordinal=mark.arrival_ordinal,
            )
        return Check(
            "consumed",
            False,
            f"anchor verification failed; consumed position unverifiable at ordinal {mark.arrival_ordinal}",
            at_ordinal=mark.arrival_ordinal,
        )

    suffix_iter = log._walk_tail(mark.arrival_offset, anchor_record, mark.arrival_lineage)
    suffix_count = sum(1 for _ in suffix_iter)

    if suffix_count > 0:
        return Check(
            "consumed",
            False,
            f"index is behind arrival by {suffix_count} record(s), consumed through ordinal {mark.arrival_ordinal}",
            behind_by=suffix_count,
            at_ordinal=mark.arrival_ordinal,
        )
    if size > mark.arrival_offset:
        return Check(
            "consumed",
            False,
            f"index is behind arrival by 0 record(s), consumed through ordinal {mark.arrival_ordinal} — log ends mid-record",
            behind_by=1,
            at_ordinal=mark.arrival_ordinal,
        )
    return Check(
        "consumed",
        True,
        f"index has consumed through arrival ordinal {mark.arrival_ordinal}",
        at_ordinal=mark.arrival_ordinal,
    )


def _check_rewound_arrival(conn: sqlite3.Connection, mark: ResumeMark | None) -> Check:
    consumed_ord = mark.arrival_ordinal if mark is not None else -1
    max_fact_ord = conn.execute("SELECT MAX(arrival_ordinal) FROM facts").fetchone()[0]
    max_tick_ord = conn.execute("SELECT MAX(arrival_ordinal) FROM ticks").fetchone()[0]
    max_ords = [o for o in (max_fact_ord, max_tick_ord) if o is not None]
    offending_ord = max(max_ords) if max_ords else None

    if offending_ord is not None and offending_ord > consumed_ord:
        return Check(
            "rewound",
            False,
            f"index holds row(s) at arrival ordinal {offending_ord} beyond "
            f"consumed ordinal {consumed_ord} — the marker was rewound, which no writer produces",
            at_ordinal=offending_ord,
        )
    return Check(
        "rewound",
        True,
        f"no index rows beyond consumed ordinal {consumed_ord}",
        at_ordinal=consumed_ord,
    )


def _check_counts_arrival(conn: sqlite3.Connection, counts: dict[str, int]) -> Check:
    null_facts = conn.execute("SELECT COUNT(*) FROM facts WHERE arrival_ordinal IS NULL").fetchone()[0]
    null_ticks = conn.execute("SELECT COUNT(*) FROM ticks WHERE arrival_ordinal IS NULL").fetchone()[0]
    if null_facts > 0 or null_ticks > 0:
        return Check("counts", False, "this index holds a row carrying no arrival coordinate")

    return Check(
        "counts",
        True,
        f"{counts['facts']} fact(s), {counts['ticks']} tick(s) accounted for",
    )


def _check_consumed_edge_arrival(
    conn: sqlite3.Connection,
    size: int,
    mark: ResumeMark | None,
    anchor_record: dict | None,
) -> Check:
    if mark is None or mark.arrival_ordinal == -1:
        return Check(
            "consumed_edge",
            True,
            "empty log" if size == 0 else "index has consumed no records yet",
            at_ordinal=-1,
        )

    if anchor_record is None:
        return Check(
            "consumed_edge",
            False,
            f"record at consumed arrival ordinal {mark.arrival_ordinal} failed anchor verification",
            at_ordinal=mark.arrival_ordinal,
        )

    records = rows_of_record(anchor_record)
    for t, row in records:
        if not row_matches(conn, t, row):
            return Check(
                "consumed_edge",
                False,
                f"consumed arrival {t} {row[0]} at ordinal {mark.arrival_ordinal} does not match the index row of the same id — the index was edited out of band",
                at_ordinal=mark.arrival_ordinal,
            )

    if not records:
        label = f"consumed structural record at ordinal {mark.arrival_ordinal}"
    elif len(records) > 1:
        label = f"consumed arrival batch of {len(records)} row(s) at ordinal {mark.arrival_ordinal}"
    else:
        t, row = records[0]
        label = f"consumed arrival {t} {row[0]} at ordinal {mark.arrival_ordinal}"
    return Check("consumed_edge", True, f"{label} matches the index", at_ordinal=mark.arrival_ordinal)


def _audit_deep_arrival(canonical: Path) -> AgreementReport:
    from .residence import index_path_for

    base = _audit_agreement_arrival(canonical)
    if any(c.name in ("log", "index") and not c.ok for c in base.checks):
        return AgreementReport(base.checks, deep=True, counts=base.counts)

    conn = _open_index(index_path_for(canonical))
    if conn is None:  # pragma: no cover
        return AgreementReport(base.checks, deep=True)
    try:
        mark = _read_mark(conn)
        consumed_ordinal = mark.arrival_ordinal if mark is not None else -1
        deep_checks = _deep_checks_arrival(conn, canonical, consumed_ordinal)

        derived_target = derived_log_path_for(canonical)
        if derived_target.exists():
            derived_res = audit_derived_log(canonical)
            deep_checks.append(Check("derived_log", derived_res.ok, derived_res.detail))

        checks = [*base.checks, *deep_checks]
        return AgreementReport(tuple(checks), deep=True, counts=base.counts)
    finally:
        conn.close()


def _deep_checks_arrival(
    conn: sqlite3.Connection, canonical: Path, consumed_ordinal: int
) -> list[Check]:
    fact_arity, fact_rows = _index_cursor_arrival(conn, "facts", FACT_COLUMNS)
    tick_arity, tick_rows = _index_cursor_arrival(conn, "ticks", TICK_COLUMNS)
    cursors = {"fact": (fact_arity, fact_rows), "tick": (tick_arity, tick_rows)}
    seen = {"fact": 0, "tick": 0}

    chain = _ChainWalkArrival()
    diverged = _Divergences()

    try:
        log = ArrivalLog(canonical)
        for record in log.walk():
            ordinal = record["ord"]
            beyond = (consumed_ordinal is not None and ordinal > consumed_ordinal)
            records = rows_of_record(record)
            for t, row in records:
                arity, rows = cursors[t]
                stored = rows.fetchone()
                seen[t] += 1
                if stored is None:
                    diverged.add(
                        f"log record at ordinal {ordinal} ({t} {row[0]}) has no index row — the "
                        f"index holds only {seen[t] - 1} {t}(s)",
                        beyond,
                        behind_by=1 if beyond else 0,
                        at_ordinal=ordinal,
                    )
                elif tuple(stored) != _trim(row, arity):
                    diverged.add(
                        f"log record at ordinal {ordinal} ({t} {row[0]}) disagrees with index "
                        f"{t} {stored[0]} at the same position"
                        + (
                            ""
                            if stored[0] == row[0]
                            else " — the index rows are out of log order"
                        ),
                        False,
                        at_ordinal=ordinal,
                    )
                chain.feed(ordinal, t, row)
    except (ArrivalCorrupt, ArrivalError) as exc:
        diverged.add(f"log walk aborted: {exc}", False)
        chain.abort(-1)

    if diverged:
        content = diverged.verdict()
    else:
        extra = [
            f"{n} extra {t}(s)"
            for t, (_a, rows) in cursors.items()
            if (n := len(rows.fetchall()))
        ]
        content = (
            Check(
                "content",
                False,
                "index holds row(s) the log never carried: " + ", ".join(extra),
            )
            if extra
            else Check(
                "content",
                True,
                f"{seen['fact']} fact(s) and {seen['tick']} tick(s) match the "
                "log field-for-field, in order",
            )
        )
    return [content, chain.verdict()]


def _index_cursor_arrival(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]):
    cols = _present(conn, table, columns)
    return len(cols), conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} ORDER BY arrival_ordinal, arrival_seq"
    )


class _Divergences:
    """Content divergences found by the deep walk — all of them, capped report."""

    _CAP = 10

    def __init__(self) -> None:
        self._details: list[str] = []
        self._n = 0
        self._all_beyond = True
        self._behind_by = 0
        self._at_ordinal = -1

    def __bool__(self) -> bool:
        return self._n > 0

    def add(
        self,
        detail: str,
        beyond: bool,
        behind_by: int = 0,
        at_ordinal: int = -1,
    ) -> None:
        self._n += 1
        if len(self._details) < self._CAP:
            self._details.append(detail)
        self._all_beyond = self._all_beyond and beyond
        if beyond and behind_by > 0:
            self._behind_by += behind_by
        if at_ordinal >= 0 and self._at_ordinal < 0:
            self._at_ordinal = at_ordinal

    def verdict(self) -> Check:
        detail = "; ".join(self._details)
        if self._n > len(self._details):
            detail += f"; (+{self._n - len(self._details)} more)"
        return Check(
            "content",
            False,
            detail,
            behind_by=self._behind_by if self._all_beyond else 0,
            at_ordinal=self._at_ordinal,
        )


class _ChainWalkArrival:
    """Re-derives the tick chain from arrival log content as the log streams by."""

    def __init__(self) -> None:
        self._fact_ids: list[str] = []
        self._fact_hashes: list[bytes] = []
        self._pos: dict[str, int] = {}
        self._prev_row: tuple | None = None
        self._last_cursor: str | None = None
        self._breaks: list[str] = []
        self._chained = 0
        self._aborted: int | None = None

    def abort(self, lineno: int) -> None:
        self._aborted = lineno

    def feed(self, ordinal: int, t: str, row: tuple) -> None:
        if t == "fact":
            self._pos.setdefault(row[0], len(self._fact_ids))
            self._fact_ids.append(row[0])
            self._fact_hashes.append(bytes.fromhex(_fact_row_hash(row)))
            return
        self._tick(ordinal, row)

    def _tick(self, ordinal: int, row: tuple) -> None:
        if row[9] is None:  # pre-chain era — nothing committed to verify
            self._prev_row = row
            return
        self._chained += 1
        expected_prev = (
            _tick_row_hash(self._prev_row) if self._prev_row is not None else None
        )
        if row[6] != expected_prev:
            self._break(ordinal, row, "prev_hash mismatch — tick sequence altered")
        if self._last_cursor is not None and row[7] != self._last_cursor:
            self._break(
                ordinal,
                row,
                "window_start does not continue the previous fact_cursor — coverage gap",
            )
        if self._window_hash(row[7], row[8]) != row[9]:
            self._break(
                ordinal, row, "window_hash mismatch — facts in the window altered"
            )
        self._last_cursor = row[8]
        self._prev_row = row

    def _break(self, ordinal: int, row: tuple, reason: str) -> None:
        if len(self._breaks) < 10:
            self._breaks.append(f"log record at ordinal {ordinal} (tick {row[0]}): {reason}")

    def _cursor_pos(self, fact_id: str) -> int | None:
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
        if self._aborted is not None:
            return Check(
                "chain",
                False,
                f"chain walk aborted at ordinal {self._aborted} — "
                f"{self._chained} tick(s) re-derived before it, the rest of "
                "the log was unreadable and is unjudged",
            )
        return Check(
            "chain",
            True,
            f"{self._chained} chained tick(s) re-derived from canonical content",
        )


# --- Legacy JSONL Audit ----------------------------------------------------


def _audit_agreement_jsonl(canonical: Path) -> AgreementReport:
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
        checks.append(_check_offset_jsonl(conn, canonical, offset, size))
        checks.append(_check_counts_jsonl(conn, counts))
        checks.append(_check_last_line_jsonl(conn, canonical, size, offset))
        return AgreementReport(tuple(checks), counts=counts)
    finally:
        conn.close()


def _index_has_row_jsonl(conn, t: str, row_id: str) -> bool:
    table = "facts" if t == "fact" else "ticks"
    try:
        return bool(
            conn.execute(
                f"SELECT EXISTS(SELECT 1 FROM {table} WHERE id = ?)", (row_id,)
            ).fetchone()[0]
        )
    except Exception:  # noqa: BLE001
        return True


def _suffix_unindexed_jsonl(conn, canonical: Path, offset: int, size: int) -> bool:
    if not 0 <= offset < size:
        return False
    if offset > 0:
        with canonical.open("rb") as fh:
            fh.seek(offset - 1)
            if fh.read(1) != b"\n":
                return False
    with canonical.open("rb") as fh:
        fh.seek(offset)
        while True:
            raw = fh.readline()
            if not raw:
                return False
            if not raw.endswith(b"\n"):
                return True
            text = raw[:-1].decode("utf-8", "replace").strip()
            if text:
                break
    try:
        records = deserialize_records(text)
    except (JsonlCodecError, UnicodeError):
        return False
    t, row = records[0]
    return not _index_has_row_jsonl(conn, t, row[0])


def _check_offset_jsonl(conn, canonical: Path, offset: int | None, size: int) -> Check:
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
        if _suffix_unindexed_jsonl(conn, canonical, offset, size):
            return Check(
                "offset", False,
                f"index is behind the log by {size - offset} byte(s) "
                f"(offset {offset}, log {size}), and the first unindexed line "
                "is genuinely unindexed — consistent with an interrupted "
                "append; run --deep to judge the rest of that suffix",
                behind_by=size - offset,
            )
        return Check(
            "offset", False,
            f"consumed-offset marker says {offset} of {size} byte(s) are "
            "indexed, but the index already holds row(s) from beyond it — "
            "the marker was moved, which no writer does",
        )
    return Check(
        "offset", False,
        f"index claims to have consumed {offset} byte(s) but the log holds "
        f"only {size} — the log was truncated or replaced",
    )


def _check_counts_jsonl(conn, counts: dict[str, int]) -> Check:
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


def _last_line_jsonl(canonical: Path, size: int) -> str | None:
    if size <= 0:
        return None
    with canonical.open("rb") as fh:
        end = size
        fh.seek(end - 1)
        if fh.read(1) != b"\n":
            return None
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


def _check_last_line_jsonl(conn, canonical: Path, size: int, offset: int | None) -> Check:
    bound = size if offset is None else min(offset, size)
    scope = "final" if bound == size else "last consumed"
    if bound == 0:
        return Check(
            "last-line", True,
            "empty log" if size == 0 else "index has consumed no lines yet",
        )
    line = _last_line_jsonl(canonical, bound)
    if line is None:
        return Check(
            "last-line", False,
            f"the log's {scope} line is incomplete or unreadable",
        )
    try:
        records = deserialize_records(line)
    except (JsonlCodecError, UnicodeError) as exc:
        return Check(
            "last-line", False, f"{scope} log line does not decode: {exc}"
        )
    for t, row in records:
        if not row_matches(conn, t, row):
            return Check(
                "last-line", False,
                f"{scope} log {t} {row[0]} does not match the index row of "
                "the same id — the index was edited out of band",
            )
    t, row = records[0]
    label = (
        f"{scope} log batch of {len(records)} fact(s)"
        if len(records) > 1
        else f"{scope} log {t} {row[0]}"
    )
    return Check("last-line", True, f"{label} matches the index")


def _audit_deep_jsonl(canonical: Path) -> AgreementReport:
    from .residence import index_path_for

    base = _audit_agreement_jsonl(canonical)
    if any(c.name in ("log", "index") and not c.ok for c in base.checks):
        return AgreementReport(base.checks, deep=True, counts=base.counts)

    conn = _open_index(index_path_for(canonical))
    if conn is None:  # pragma: no cover
        return AgreementReport(base.checks, deep=True)
    try:
        offset = _meta_int(conn, OFFSET_KEY)
        unconsumed = offset is not None and _suffix_unindexed_jsonl(
            conn, canonical, offset, _log_size(canonical)
        )
        checks = [
            *base.checks,
            *_deep_checks_jsonl(conn, canonical, offset if unconsumed else None),
        ]
        return AgreementReport(tuple(checks), deep=True, counts=base.counts)
    finally:
        conn.close()


def _iter_lines_jsonl(canonical: Path) -> Iterator[tuple[int, int, str]]:
    with canonical.open("rb") as fh:
        pos = 0
        for lineno, raw in enumerate(fh, 1):
            if not raw.endswith(b"\n"):
                return
            pos += len(raw)
            text = raw[:-1].decode("utf-8", "replace").strip()
            if text:
                yield lineno, pos, text


def _deep_checks_jsonl(conn, canonical: Path, offset: int | None) -> list[Check]:
    def beyond(end: int) -> bool:
        return offset is not None and end > offset

    cols_fact = _present(conn, "facts", FACT_COLUMNS)
    cols_tick = _present(conn, "ticks", TICK_COLUMNS)
    fact_cur = conn.execute(f"SELECT {', '.join(cols_fact)} FROM facts ORDER BY rowid")
    tick_cur = conn.execute(f"SELECT {', '.join(cols_tick)} FROM ticks ORDER BY rowid")
    cursors = {"fact": (len(cols_fact), fact_cur), "tick": (len(cols_tick), tick_cur)}
    seen = {"fact": 0, "tick": 0}

    chain = _ChainWalkJsonl()
    diverged = _Divergences()

    for lineno, end, line in _iter_lines_jsonl(canonical):
        try:
            records = deserialize_records(line)
        except (JsonlCodecError, UnicodeError) as exc:
            diverged.add(
                f"log line {lineno} does not decode: {exc}", beyond(end)
            )
            chain.abort(lineno)
            break
        if len(records) > 1 and all(
            row[1].startswith("_decl.") for _t, row in records
        ):
            stamps = {row[2] for _t, row in records}
            if len(stamps) > 1:
                diverged.add(
                    f"log line {lineno}: declaration batch carries "
                    f"{len(stamps)} distinct ts — a ceremony is a single "
                    "ontology transition and stamps one effective timestamp",
                    False,
                )
        for t, row in records:
            arity, rows = cursors[t]
            stored = rows.fetchone()
            seen[t] += 1
            if stored is None:
                diverged.add(
                    f"log line {lineno} ({t} {row[0]}) has no index row — the "
                    f"index holds only {seen[t] - 1} {t}(s)",
                    beyond(end),
                    behind_by=1 if beyond(end) else 0,
                )
            elif tuple(stored) != _trim(row, arity):
                diverged.add(
                    f"log line {lineno} ({t} {row[0]}) disagrees with index "
                    f"{t} {stored[0]} at the same position"
                    + (
                        ""
                        if stored[0] == row[0]
                        else " — the index rows are out of log order"
                    ),
                    False,
                )
            chain.feed(lineno, t, row)

    if diverged:
        content = diverged.verdict()
    else:
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


class _ChainWalkJsonl:
    def __init__(self) -> None:
        self._fact_ids: list[str] = []
        self._fact_hashes: list[bytes] = []
        self._pos: dict[str, int] = {}
        self._prev_row: tuple | None = None
        self._last_cursor: str | None = None
        self._breaks: list[str] = []
        self._chained = 0
        self._aborted: int | None = None

    def abort(self, lineno: int) -> None:
        self._aborted = lineno

    def feed(self, lineno: int, t: str, row: tuple) -> None:
        if t == "fact":
            self._pos.setdefault(row[0], len(self._fact_ids))
            self._fact_ids.append(row[0])
            self._fact_hashes.append(bytes.fromhex(_fact_row_hash(row)))
            return
        self._tick(lineno, row)

    def _tick(self, lineno: int, row: tuple) -> None:
        if row[9] is None:
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
        if self._aborted is not None:
            return Check(
                "chain", False,
                f"chain walk aborted at log line {self._aborted} — "
                f"{self._chained} tick(s) re-derived before it, the rest of "
                "the log was unreadable and is unjudged",
            )
        return Check(
            "chain", True,
            f"{self._chained} chained tick(s) re-derived from canonical content",
        )


