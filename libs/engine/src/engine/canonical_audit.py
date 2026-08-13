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
    beyond_offset: bool = False
    """Does this divergence lie past the prefix the index claims to have consumed?

    A SCOPE STATEMENT, NOT AN INNOCENCE CLAIM. ``JsonlStore`` fsyncs the log
    BEFORE it commits the index rows and the markers (``jsonl_store.py``), so
    a crash in that window leaves a durable log ahead of a truthful-but-behind
    index — and an interrupted append leaves a torn final line the next open
    truncates. Both states put their divergence here. But so does an attacker
    who rewinds the marker and then edits the suffix: L1 corroborates only the
    FIRST line past the offset (:func:`_suffix_unindexed`), which is enough to
    refuse the marker's bare word and no more. Full corroboration of an
    unindexed suffix is definitionally :func:`audit_deep`'s job, so no caller
    may turn this flag into "not tampering" — only into "the disagreement is
    in bytes the index never claimed, which an interrupted append also
    produces; run ``--deep`` to rule the rest out".

    NEVER decided by the offset marker alone. That marker lives inside the
    very sqlite file this audit exists to judge, so trusting it would let an
    attacker rewind one integer to move a divergence out of scope (rewind the
    marker below an edited interior row and every other L1 check still
    passes). An index that already holds a row for the first line the marker
    calls unconsumed is not behind at all; its marker was moved, and that is
    not the writer's shape — that detection is exact, and it stays.
    """

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "ok": self.ok,
            "detail": self.detail,
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
        """Diverged, but only past the prefix the index claims to have consumed.

        True when every divergence is :attr:`Check.beyond_offset`. That is
        what an interrupted append looks like — and it is ALSO what a rewound
        marker plus a doctored suffix looks like to L1, which corroborates
        only the first unindexed line. So this narrows where to look; it never
        licenses "not tampering". Callers report it as "the index is behind
        the log", offer ``loops read`` as the catch-up route, and point at
        ``--deep`` for the ruling L1 cannot make.
        """
        d = self.divergences
        return bool(d) and all(c.beyond_offset for c in d)

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
        checks.append(_check_offset(conn, canonical, offset, size))
        checks.append(_check_counts(conn, counts))
        checks.append(_check_last_line(conn, canonical, size, offset))
        return AgreementReport(tuple(checks), counts=counts)
    finally:
        conn.close()


def _row_counts(conn) -> dict[str, int]:
    return {
        "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
        "ticks": conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0],
    }


def _index_has_row(conn, t: str, row_id: str) -> bool:
    table = "facts" if t == "fact" else "ticks"
    try:
        return bool(
            conn.execute(
                f"SELECT EXISTS(SELECT 1 FROM {table} WHERE id = ?)", (row_id,)
            ).fetchone()[0]
        )
    except Exception:  # noqa: BLE001 — an unreadable index vouches for nothing
        return True


def _suffix_unindexed(conn, canonical: Path, offset: int, size: int) -> bool:
    """Does the log past ``offset`` START with a genuinely unindexed line?

    The corroboration behind :attr:`Check.beyond_offset`, and no more than
    that. The writer's crash window has one shape: the log holds durable bytes
    the index has NOT consumed, so the first line past the stamped offset has
    no row in the index. Reading that one line is O(1) and turns "the
    suspect's own marker says so" into a claim the log supports — but it says
    NOTHING about the rest of the suffix, which is why no caller may read a
    True here as innocence. Corroborating every suffix line is
    :func:`audit_deep`'s scope, by construction: it already streams them.

    False (the marker is not merely behind) when the offset does not land on a
    line boundary, when the first line does not decode, or when the index
    already holds a row for it — the marker was rewound below rows the index
    consumed, which no writer produces. True for a torn final line: those
    bytes were never indexed, which is precisely the interrupted-append window.
    """
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
                return False  # nothing but blank bytes past the offset
            if not raw.endswith(b"\n"):
                return True  # torn tail — never indexed, by construction
            text = raw[:-1].decode("utf-8", "replace").strip()
            if text:
                break
    try:
        records = deserialize_records(text)
    except (JsonlCodecError, UnicodeError):
        return False  # garbage past the offset is not an innocence claim
    # A batch line is judged by its first inner row — the writer's crash
    # window leaves the WHOLE ceremony line unindexed, so one probe is the
    # same O(1) corroboration a plain line gets.
    t, row = records[0]
    return not _index_has_row(conn, t, row[0])


def _check_offset(conn, canonical: Path, offset: int | None, size: int) -> Check:
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
        if _suffix_unindexed(conn, canonical, offset, size):
            return Check(
                "offset", False,
                f"index is behind the log by {size - offset} byte(s) "
                f"(offset {offset}, log {size}), and the first unindexed line "
                "is genuinely unindexed — consistent with an interrupted "
                "append; run --deep to judge the rest of that suffix",
                beyond_offset=True,
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


def _check_last_line(conn, canonical: Path, size: int, offset: int | None) -> Check:
    """Judge the last line the index CONSUMED — not the last line on disk.

    The bound is the stamped offset, because that is the only prefix of the
    log the index ever claimed to account for. Judging the file's final line
    instead accuses the index of an out-of-band edit every time the writer
    crashes between the log's fsync and the index commit, or leaves a torn
    tail — the two states the writer itself documents as normal, where the
    unindexed bytes have no index row to match by construction. The offset
    check already reports the shortfall once; reporting it again as tampering is a
    false accusation inside the feature that exists to attest honestly.
    """
    bound = size if offset is None else min(offset, size)
    scope = "final" if bound == size else "last consumed"
    if bound == 0:
        return Check(
            "last-line", True,
            "empty log" if size == 0 else "index has consumed no lines yet",
        )
    line = _last_line(canonical, bound)
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
    # A batch line expands to N rows; EVERY one must match its index row, so
    # an index-side edit to any row of the last ceremony is detected. Cost is
    # bounded by ceremony size, not log size.
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
        offset = _meta_int(conn, OFFSET_KEY)
        # The same corroboration L1 made: a content failure is only excusable
        # as beyond-the-consumed-prefix when the log suffix past the offset
        # really starts unindexed. Reading the flag off the marker alone would
        # let a rewind stamp ``"beyond_offset": true`` onto a tampered line in
        # ``--json``.
        unconsumed = offset is not None and _suffix_unindexed(
            conn, canonical, offset, _log_size(canonical)
        )
        checks = [
            *base.checks,
            *_deep_checks(conn, canonical, offset if unconsumed else None),
        ]
        return AgreementReport(tuple(checks), deep=True, counts=base.counts)
    finally:
        conn.close()


def _index_cursor(conn, table: str, columns: tuple[str, ...]):
    cols = _present(conn, table, columns)
    return len(cols), conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} ORDER BY rowid"
    )


def _deep_checks(conn, canonical: Path, offset: int | None) -> list[Check]:
    """Compare every log line against the index, in order.

    ``offset`` is the prefix the index claims to have consumed, passed in only
    when that claim was CORROBORATED against the log (:func:`_suffix_unindexed`
    — a rewound marker arrives here as ``None``). A failure on a line that ends
    BEYOND it is in bytes that were never meant to have an index row yet (see
    :attr:`Check.beyond_offset`). Failures inside the consumed prefix are the
    real thing and stay unflagged.

    The walk does not stop at the first divergence. Every divergence is a fact
    about a different line, and the chain verdict is derived from LOG content —
    so stopping early would trade a real answer ("the chain re-derives" /
    "these ticks broke") for a vacuous one over zero ticks. Divergences
    accumulate (the reported list is capped; the count is not) and every
    decodable canonical row keeps feeding the chain. Only an undecodable line
    truly ends the walk, and then the chain says it ABORTED rather than ``ok``.
    """

    def beyond(end: int) -> bool:
        return offset is not None and end > offset

    fact_arity, fact_rows = _index_cursor(conn, "facts", FACT_COLUMNS)
    tick_arity, tick_rows = _index_cursor(conn, "ticks", TICK_COLUMNS)
    cursors = {"fact": (fact_arity, fact_rows), "tick": (tick_arity, tick_rows)}
    seen = {"fact": 0, "tick": 0}

    chain = _ChainWalk()
    diverged = _Divergences()

    for lineno, end, line in _iter_lines(canonical):
        try:
            records = deserialize_records(line)
        except (JsonlCodecError, UnicodeError) as exc:
            diverged.add(
                f"log line {lineno} does not decode: {exc}", beyond(end)
            )
            chain.abort(lineno)
            break
        # D1 boundary: same-ts across a batch is the declaration ceremony's
        # invariant, not a codec rule. absorb_edit stamps one ts; a batch
        # whose rows are all _decl.* kinds but carry mixed ts is therefore an
        # audit divergence here — never a decode error at the codec gate.
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
            # The chain is re-derived from the LOG, so an index divergence on
            # this line says nothing about whether the log's own chain holds.
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


class _Divergences:
    """Content divergences found by the deep walk — all of them, capped report.

    Reporting only the first divergence made "one edited row" and "the whole
    index rewritten" print identically. The count is exact; the enumerated
    detail stops at :attr:`_CAP` so a wholesale divergence cannot flood a
    terminal.
    """

    _CAP = 10

    def __init__(self) -> None:
        self._details: list[str] = []
        self._n = 0
        self._all_beyond = True

    def __bool__(self) -> bool:
        return self._n > 0

    def add(self, detail: str, beyond_offset: bool) -> None:
        self._n += 1
        if len(self._details) < self._CAP:
            self._details.append(detail)
        self._all_beyond = self._all_beyond and beyond_offset

    def verdict(self) -> Check:
        detail = "; ".join(self._details)
        if self._n > len(self._details):
            detail += f"; (+{self._n - len(self._details)} more)"
        return Check("content", False, detail, beyond_offset=self._all_beyond)


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
        self._aborted: int | None = None

    def abort(self, lineno: int) -> None:
        """The log stopped being readable here — the chain verdict is unknown.

        Saying ``ok`` after the walk was cut short would attest to ticks that
        were never examined. An aborted walk fails and says where it stopped.
        """
        self._aborted = lineno

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
