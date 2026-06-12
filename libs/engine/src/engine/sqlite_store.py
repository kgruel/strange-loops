"""SqliteStore — SQLite-backed append-only event store.

Implements the Store protocol with durable persistence. Facts are stored
with kind, ts, observer as real columns (SQL-queryable) and payload as
JSON text (queryable via json_extract()).

Uses WAL mode for concurrent reads during folds. IDs are ULIDs generated
Python-side via python-ulid (26-char Crockford base32, time-sortable,
within-ms monotonic). Time-sortability is load-bearing for cross-store
fact interleaving (ORDER BY id ≈ chronological) and for merge dedup
on slice→merge round-trips via INSERT OR IGNORE on the id PK.

History: 2026-03-15 to 2026-05-16 a perf-driven change swapped to
uuid.uuid4() to avoid loading the sqlite-ulid C extension per connection
(~0.5ms dlopen). That swap dropped the time-sortable property without
naming the substrate contract. Restored 2026-05-16 via pure-Python
python-ulid (no dlopen, ~2.3μs/id, negligible at this scale). See
project decision architecture/id-primitive-python-ulid.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from ulid import ULID

# Pre-created decoder for faster JSON parsing in hot paths.
# raw_decode skips strip() and end-position validation — safe for SQLite
# payloads which are always well-formed JSON without whitespace padding.
_raw_decode = json.JSONDecoder().raw_decode


def gen_id() -> str:
    """Generate a unique ID for store records.

    Uses python-ulid: 26-char Crockford base32 ULID, time-sortable
    (lexicographic order matches generation time), within-ms monotonic
    (sequential calls within the same millisecond have incrementing
    suffixes). Pure Python — no C extension, no dlopen cost.
    """
    return str(ULID())


# --- Tick hash chain -------------------------------------------------------
#
# The chain is a STORE-LAYER property, not a Tick-atom property (project
# decision design/tick-chain-at-store-layer). Each persisted tick row commits
# to (a) the previous tick row via prev_hash and (b) the fact window
# (window_start, fact_cursor] via window_hash — making both the tick sequence
# and the fact stream tamper-evident under verification. The Tick dataclass
# stays pure; merged/transported stores start fresh chains (new custody
# context). Rows written before the chain existed keep NULL chain columns —
# a visible pre-chain era, never retro-claimed.
#
# ORDERING AUTHORITY (observation design/event-order-vs-witness-order): window
# cursors are fact IDS (portable handles), but window MEMBERSHIP and hashing
# follow APPEND ORDER (rowid) — never id order. The chain's claim is receipt-
# integrity ("this store received these facts and nothing changed after
# sealing"), not chronology. Two reasons id order is the wrong authority here:
# (1) mixed-id-era stores — uuid4-era ids (2026-03-15..05-16) sort above every
# ULID, so MAX(id) pins to a mid-history fact forever and every window minted
# after is empty (friction chain-cursor-assumes-ulid-order); (2) late arrival —
# a backfilled/synced fact honestly carrying an old event timestamp would land
# INSIDE a sealed id-window and raise a false tamper alarm, where in witness
# order it lands on the live edge and the next tick seals it as received-now.
# Event order (ULID, fact.ts) remains the READ path's order; the two orders
# answer different questions and neither substitutes for the other.
#
# Delta 2 (design/tick-signature-on-every-tick): each tick row may carry an
# Ed25519 signature over its COMMITMENT hash (the 10 chain fields). Signing
# is injected, never imported — the store takes an optional signer callable
# (digest str -> signature str); verify_chain takes an optional verifier
# (signature str, digest str -> bool). apps/loops composes both with
# libs/sign. Pre-signature rows keep NULL — a visible era, same posture as
# the pre-chain era. The successor's prev_hash commits to the signature
# (design/tick-signature-in-chain-envelope): the row-IDENTITY hash is
# era-aware (includes the signature key only when non-NULL), so stripping a
# signature breaks the successor's link and a forger must rewrite the whole
# chain ahead — at which point only the registry outside the store (and
# external witnessing, a later delta) anchors the truth.

_CHAIN_COLUMNS = ("prev_hash", "window_start", "fact_cursor", "window_hash",
                  "signature")

_TICK_ROW_SQL = (
    "id, name, ts, since, origin, payload, "
    "prev_hash, window_start, fact_cursor, window_hash, signature"
)

# Delta-1 column set — used by the read-only verify path against stores that
# predate the signature column (verify never migrates schema).
_TICK_ROW_SQL_V1 = (
    "id, name, ts, since, origin, payload, "
    "prev_hash, window_start, fact_cursor, window_hash"
)


def _canonical_bytes(obj: object) -> bytes:
    """Deterministic encoding for chain hashing: sorted keys, compact separators.

    Deliberately NOT RFC 8785 (JCS): chain integrity needs determinism within
    this implementation, not cross-implementation interop. Stored payload TEXT
    is embedded verbatim as a string value, so hashes detect byte-level
    tampering without float/unicode re-serialization concerns. If a
    federation-facing consumer ever needs interop hashing, upgrade here and
    re-anchor the chain — the JCS pin (RFC 8785) belongs to the manifest
    layer, not this one.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _tick_envelope(row: tuple) -> dict:
    """The 10 commitment fields of a tick row (column order: _TICK_ROW_SQL)."""
    return {
        "id": row[0], "name": row[1], "ts": row[2], "since": row[3],
        "origin": row[4], "payload": row[5], "prev_hash": row[6],
        "window_start": row[7], "fact_cursor": row[8], "window_hash": row[9],
    }


def _tick_commitment_hash(row: tuple) -> str:
    """Hash the commitment fields — what the signer signs.

    Never includes the signature (sign-the-content; a signature cannot
    sign itself).
    """
    return hashlib.sha256(_canonical_bytes(_tick_envelope(row))).hexdigest()


def cursor_fact_summary(conn, fact_id: str) -> dict:
    """Resolve a fact_cursor id to a terse summary of its target fact.

    Read-path affordance, NOT part of any commitment — the chain commits
    to ids and hashes; this is the human-facing dereference. Returns
    ``{"cursor_kind": str, "cursor_preview": str}``. An empty cursor
    resolves to empty fields; a dangling cursor (fact deleted) is named
    explicitly rather than silently blank — verify reports that case as
    a break, but read paths still render honestly.
    """
    if not fact_id:
        return {"cursor_kind": "", "cursor_preview": ""}
    row = conn.execute(
        "SELECT kind, payload FROM facts WHERE id = ?", (fact_id,)
    ).fetchone()
    if row is None:
        return {"cursor_kind": "", "cursor_preview": "(cursor fact missing)"}
    try:
        payload = json.loads(row[1])
    except (TypeError, ValueError):
        payload = {}
    preview = ""
    if isinstance(payload, dict):
        for key in ("message", "topic", "name", "status"):
            val = payload.get(key)
            if isinstance(val, str) and val:
                preview = val
                break
    if len(preview) > 80:
        preview = preview[:79] + "…"
    return {"cursor_kind": row[0], "cursor_preview": preview}


def _tick_row_hash(row: tuple) -> str:
    """Era-aware identity hash — what the successor's prev_hash commits to.

    Includes the signature key only when the row carries one, so every
    pre-signature row (and every pre-chain row) hashes byte-identically to
    delta 1 — no re-anchoring. For signed rows the successor chains over
    content+signature, making signature-stripping a detectable break
    (design/tick-signature-in-chain-envelope).
    """
    envelope = _tick_envelope(row)
    if len(row) > 10 and row[10] is not None:
        envelope["signature"] = row[10]
    return hashlib.sha256(_canonical_bytes(envelope)).hexdigest()


# Public name: the row-identity hash is a cross-lib contract. libs/store's
# rebirth receipt records the source chain head with THE chain's hash
# function — a reimplementation could silently diverge from what verify
# walks. Same function, two names: _tick_row_hash stays the internal
# spelling, tick_row_hash is the exported contract.
def tick_row_hash(row: tuple) -> str:
    """Era-aware tick row-identity hash (see _tick_row_hash)."""
    return _tick_row_hash(row)


def _fact_row_hash(row: tuple) -> str:
    """Hash one persisted fact row: (id, kind, ts, observer, origin, payload)."""
    envelope = {
        "id": row[0], "kind": row[1], "ts": row[2],
        "observer": row[3], "origin": row[4], "payload": row[5],
    }
    return hashlib.sha256(_canonical_bytes(envelope)).hexdigest()


from datetime import datetime, timezone as _tz

_UTC = _tz.utc
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

# IDs generated Python-side via python-ulid (see gen_id above).
# The sqlite-ulid C extension is not a dependency — id generation lives
# entirely in Python. All INSERTs supply id explicitly, so no SQL-callable
# ulid() function is needed.


def _mapping_proxy_default(obj: object) -> object:
    """Handle MappingProxyType in JSON serialization."""
    from types import MappingProxyType
    if isinstance(obj, MappingProxyType):
        return dict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

from .tick import Tick

T = TypeVar("T")

_SCHEMA_STMTS = (
    """CREATE TABLE IF NOT EXISTS facts (
        id       TEXT NOT NULL PRIMARY KEY,
        kind     TEXT NOT NULL,
        ts       REAL NOT NULL,
        observer TEXT NOT NULL,
        origin   TEXT NOT NULL DEFAULT '',
        payload  TEXT NOT NULL CHECK (json_valid(payload))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind)",
    "CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts)",
    """CREATE TABLE IF NOT EXISTS ticks (
        id           TEXT NOT NULL PRIMARY KEY,
        name         TEXT NOT NULL,
        ts           REAL NOT NULL,
        since        REAL,
        origin       TEXT NOT NULL,
        payload      TEXT NOT NULL CHECK (json_valid(payload)),
        prev_hash    TEXT,
        window_start TEXT,
        fact_cursor  TEXT,
        window_hash  TEXT,
        signature    TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name)",
    "CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts)",
)


class SqliteStore(Generic[T]):
    """Append-only SQLite event store.

    Cursor semantics: since(cursor) returns rows with rowid > cursor,
    matching EventStore's logical index behavior (0 = all events).
    """

    def __init__(
        self,
        *,
        path: Path,
        serialize: Callable[[T], dict],
        deserialize: Callable[[dict], T],
        tick_signer: Callable[[str], str] | None = None,
    ) -> None:
        """tick_signer: optional callable (commitment digest str -> signature
        str, e.g. base64 Ed25519). Injected, never imported — custody is a
        property of the store handle (the key lives next to the db), so the
        signer rides the constructor rather than each append_tick call.
        None = ticks append unsigned (pre-signature era, honest NULL).
        """
        self._path = Path(path)
        self._serialize = serialize
        self._deserialize = deserialize
        self._tick_signer = tick_signer
        self._direct_fact_build: bool | None = None  # lazy detection
        self._fact_class: type | None = None

        try:
            is_new = self._path.stat().st_size == 0
        except OSError:
            is_new = True
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._chain_ready = is_new  # new DBs get chain columns in schema
        if is_new:
            # New DB — set WAL (persistent) and synchronous, create schema
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            for stmt in _SCHEMA_STMTS:
                self._conn.execute(stmt)
            self._sync_set = True
        else:
            # Existing DB: skip schema + pragmas — WAL is persistent,
            # schema already exists, first real query triggers schema load.
            # Defer synchronous=NORMAL to first write (after schema is loaded).
            self._sync_set = False

    def _detect_fact_build(self) -> None:
        """Detect if deserializer is Fact.from_dict for direct construction."""
        self._direct_fact_build = False
        deserialize = self._deserialize
        if hasattr(deserialize, '__self__') and hasattr(deserialize.__self__, '__name__'):
            self._fact_class = deserialize.__self__
            self._direct_fact_build = True
        elif hasattr(deserialize, '__func__'):
            try:
                from atoms import Fact
                if deserialize.__func__ is Fact.from_dict.__func__:
                    self._fact_class = Fact
                    self._direct_fact_build = True
            except (ImportError, AttributeError):
                pass

    def _ensure_sync(self) -> None:
        """Set synchronous=NORMAL before first write. Deferred so schema load
        happens on first read (replay_into) rather than on pragma."""
        if not self._sync_set:
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._sync_set = True

    def append(self, event: T, *, id_override: str | None = None) -> str:
        """Append one event to the store. Returns the ID assigned.

        If id_override is provided, that ID is used; otherwise a new ID
        is generated via gen_id(). The ID is returned in either case so
        callers (e.g. emit's receipt path) can reference the stored row.
        """
        self._ensure_sync()
        d = self._serialize(event)
        fact_id = id_override if id_override is not None else gen_id()
        self._conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (fact_id, d["kind"], d["ts"], d["observer"], d.get("origin", ""), json.dumps(d["payload"])),
        )
        self._conn.commit()
        return fact_id

    async def consume(self, event: T, *, id_override: str | None = None) -> None:
        """Consumer protocol: append event to store."""
        self.append(event, id_override=id_override)

    def since(self, cursor: int) -> list[T]:
        """Return events with rowid > cursor.

        cursor=0 returns all events (rowid starts at 1 in SQLite).
        """
        rows = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts WHERE rowid > ? ORDER BY ts, id",
            (cursor,),
        ).fetchall()
        loads = _raw_decode
        # Fast path: build Facts directly when deserializer is Fact.from_dict
        # Avoids intermediate dict allocation per row
        if self._direct_fact_build is None:
            self._detect_fact_build()
        if self._direct_fact_build:
            return [
                self._fact_class(kind=r[0], ts=r[1], observer=r[2], origin=r[3], payload=loads(r[4])[0])
                for r in rows
            ]
        deserialize = self._deserialize
        return [
            deserialize(
                {"kind": r[0], "ts": r[1], "observer": r[2], "origin": r[3], "payload": loads(r[4])[0]}
            )
            for r in rows
        ]

    def since_raw(self, cursor: int) -> list[tuple[str, dict]]:
        """Return (kind, payload) tuples for replay — no Fact construction.

        Avoids MappingProxyType wrapping and full Fact dataclass overhead.
        Only returns the fields needed for fold replay. The event timestamp
        is injected as ``_ts`` (Latest folds consume it — replay must never
        consult the wall clock).

        FOLD REPLAY ORDER is (ts, id) — event order, deterministic across
        custody contexts, so merge(A,B) and merge(B,A) re-fold to the same
        state. Witness order (rowid) remains the chain/window authority;
        the two orders answer different questions (see ORDERING AUTHORITY
        on append_tick).
        """
        rows = self._conn.execute(
            "SELECT kind, ts, payload FROM facts WHERE rowid > ? ORDER BY ts, id",
            (cursor,),
        ).fetchall()
        loads = _raw_decode
        out = []
        for r in rows:
            payload = loads(r[2])[0]
            payload["_ts"] = r[1]
            out.append((r[0], payload))
        return out

    def replay_cursor(self, cursor: int):
        """Yield (kind, payload) pairs by streaming from the SQL cursor.

        No intermediate list allocation — rows are decoded and yielded
        one at a time. The caller handles fold dispatch; the store just
        provides data. This keeps fold logic in the Projection layer
        where it belongs. Same (ts, id) fold-replay order and ``_ts``
        injection as since_raw.
        """
        loads = _raw_decode
        for r in self._conn.execute(
            "SELECT kind, ts, payload FROM facts WHERE rowid > ? ORDER BY ts, id",
            (cursor,),
        ):
            payload = loads(r[2])[0]
            payload["_ts"] = r[1]
            yield r[0], payload

    def last_tick_ts(self, name: str) -> datetime | None:
        """Return the timestamp of the most recent tick with the given name.

        Optimized query for replay period tracking — avoids loading all ticks.
        """
        row = self._conn.execute(
            "SELECT ts FROM ticks WHERE name = ? ORDER BY rowid DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromtimestamp(row[0], tz=_UTC)

    def between(self, start: datetime | float, end: datetime | float) -> list[T]:
        """Return events in the time range [start, end]."""
        start_ts = start.timestamp() if isinstance(start, datetime) else start
        end_ts = end.timestamp() if isinstance(end, datetime) else end

        rows = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts WHERE ts >= ? AND ts <= ? ORDER BY rowid",
            (start_ts, end_ts),
        ).fetchall()
        return [
            self._deserialize(
                {"kind": r[0], "ts": r[1], "observer": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    @property
    def total(self) -> int:
        """Total number of events in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()
        return row[0]

    def _ensure_chain_columns(self) -> None:
        """Idempotent migration: add chain columns to a pre-chain ticks table.

        Existing rows keep NULL chain columns — the pre-chain era stays
        visible as an era (same posture as the uuid4 id wedge: historical
        fact, not retroactively rewritten).
        """
        if self._chain_ready:
            return
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(ticks)")}
        for col in _CHAIN_COLUMNS:
            if col not in cols:
                self._conn.execute(f"ALTER TABLE ticks ADD COLUMN {col} TEXT")
        self._conn.commit()
        self._chain_ready = True

    def _cursor_rowid(self, fact_id: str) -> int | None:
        """Resolve a window cursor (fact id) to its rowid — witness order.

        "" (start-of-store / empty-store sentinel) resolves to 0, before the
        first rowid. A cursor whose fact no longer exists resolves to None:
        the window is unresolvable and hashes as empty — any non-empty
        commitment over it then mismatches. (Deleting a cursor fact that was
        itself inside a covered window already breaks THAT window's hash.)
        """
        if fact_id == "":
            return 0
        row = self._conn.execute(
            "SELECT rowid FROM facts WHERE id = ?", (fact_id,)
        ).fetchone()
        return row[0] if row else None

    def _window_hash(self, start: str, end: str) -> str:
        """Hash the fact window (start, end] in witness order (rowid).

        Cursors are fact ids; ordering and membership are append order — see
        the ORDERING AUTHORITY note in the chain comment block. Id order is
        not append order in mixed-id-era stores, and a late-arriving fact
        with an old event-time id must not retroactively enter a sealed
        window.
        """
        h = hashlib.sha256()
        lo = self._cursor_rowid(start)
        hi = self._cursor_rowid(end)
        if lo is None or hi is None:
            return h.hexdigest()  # unresolvable cursor → empty commitment
        for row in self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts "
            "WHERE rowid > ? AND rowid <= ? ORDER BY rowid",
            (lo, hi),
        ):
            h.update(_fact_row_hash(row).encode())
        return h.hexdigest()

    def append_tick(self, tick: Tick) -> None:
        """Append a tick to the ticks table, extending the hash chain.

        Chain semantics (see design/tick-chain-at-store-layer):
        - prev_hash: sha256 of the previous tick row (any era) — None for
          the first row in the store.
        - window bounds are explicit fact ids; membership and ordering are
          APPEND ORDER (rowid), never id order — the cursor is the id of the
          newest fact BY ROWID, not MAX(id) (see ORDERING AUTHORITY above):
          - first tick in a new store: window_start "" (covers all facts);
          - first chained tick after pre-chain rows: window_start =
            current append edge (epoch marker — claims no coverage of
            history it cannot vouch for);
          - otherwise: window_start = previous tick's fact_cursor.
        - window_hash commits to every fact row in (window_start, fact_cursor].
        - signature (delta 2): when a tick_signer was injected, signs the
          commitment hash of the new row; NULL otherwise (pre-signature era).
        """
        self._ensure_sync()
        self._ensure_chain_columns()
        d = tick.to_dict()
        payload_text = json.dumps(d["payload"], default=_mapping_proxy_default)

        prev_row = self._conn.execute(
            f"SELECT {_TICK_ROW_SQL} FROM ticks ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        prev_hash = _tick_row_hash(prev_row) if prev_row is not None else None

        edge_row = self._conn.execute(
            "SELECT id FROM facts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        fact_cursor = edge_row[0] if edge_row else ""
        if prev_row is None:
            window_start = ""  # new store: cover everything emitted so far
        elif prev_row[9] is None:
            window_start = fact_cursor  # pre-chain predecessor: epoch marker
        else:
            window_start = prev_row[8]
        window_hash = self._window_hash(window_start, fact_cursor)

        row = (gen_id(), d["name"], d["ts"], d["since"], d["origin"],
               payload_text, prev_hash, window_start, fact_cursor, window_hash)
        signature = (
            self._tick_signer(_tick_commitment_hash(row))
            if self._tick_signer is not None else None
        )

        self._conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, "
            "prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*row, signature),
        )
        self._conn.commit()

    def verify_chain(
        self,
        *,
        max_breaks: int = 10,
        verifier: Callable[[str, str], bool] | None = None,
        include_ticks: bool = False,
    ) -> dict[str, Any]:
        """Verify the tick hash chain, fact-window commitments, and signatures.

        Walks ticks in append order recomputing prev_hash linkage,
        window_start continuity, and window_hash contents. Any modified,
        deleted, or displaced fact inside a covered window breaks
        verification; facts emitted after the last tick are the uncovered
        live edge (reported, not an error).

        Windows are WITNESS-ORDER (rowid) ranges — see ORDERING AUTHORITY
        in the chain comment block. A late-arriving fact carrying an old
        event timestamp (backfill, peer sync) lands on the live edge and is
        sealed by the next tick as received-now: honest history, not a
        break. The chain attests receipt order; event order is the read
        path's concern.

        Signatures (delta 2): ``verifier`` is an injected callable
        (signature str, commitment digest str) -> bool — apps/loops composes
        it from the observer-key registry in the .vertex. When provided,
        every signed tick's signature is checked against its commitment
        hash. Two checks run regardless of verifier presence, because they
        are structural properties of the store:
        - the successor's prev_hash commits to the signature (era-aware row
          hash), so a stripped/altered signature breaks the link;
        - signature era-monotonicity — an unsigned chained tick after a
          signed one is a break (signing is structural from the moment it
          starts, never quietly regressed).

        KNOWN SCOPE BOUNDARY (delta 2): a TOTAL rewrite — stripping every
        signature and recomputing every hash forward — renders as a clean
        pre-signature store. A self-contained chain cannot distinguish that
        from honest history; the anchor is the key registry in the .vertex
        (outside the store; a declared key with zero signed ticks is the
        tripwire, checked at the CLI layer) and external witnessing (a
        later delta).

        Returns a report dict:
            ok              True when no breaks found
            ticks           total tick rows
            chained         rows carrying chain commitments
            legacy          pre-chain rows (NULL chain columns)
            signed          chained rows carrying a signature
            sig_checked     True when a verifier was provided
            covered_facts   facts inside verified windows
            uncovered_facts facts outside any chained window
            breaks          list of {tick, name, reason} (capped at max_breaks)
            truncated       True if the walk stopped at max_breaks
            tick_detail     (only when ``include_ticks``) per-chained-tick
                            attestation rows in append order: {tick, name,
                            ts, signed, sig_ok, ok, fact_cursor,
                            window_facts, cursor_kind, cursor_preview}.
                            ``sig_ok`` is True/False when a verifier checked
                            a signed tick, None otherwise. ``window_facts``
                            is the fact count in this tick's window — the
                            number whose wrongness surfaced the witness-order
                            bug. Legacy ticks stay aggregate-only (they have
                            no envelope to detail).

        Read-only: never migrates schema. A pre-chain database (no chain
        columns yet) reports all ticks as legacy rather than being ALTERed;
        a delta-1 database (no signature column) verifies with all ticks
        unsigned — migration happens only on the write path (append_tick).
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(ticks)")}
        sig_checked = verifier is not None
        if "window_hash" not in cols:
            tick_count = self.tick_total
            report: dict[str, Any] = {
                "ok": True, "ticks": tick_count, "chained": 0,
                "legacy": tick_count, "signed": 0, "sig_checked": sig_checked,
                "covered_facts": 0,
                "uncovered_facts": self.total, "breaks": [], "truncated": False,
            }
            if include_ticks:
                report["tick_detail"] = []
            return report
        row_sql = _TICK_ROW_SQL if "signature" in cols else _TICK_ROW_SQL_V1
        rows = [
            r if len(r) > 10 else (*r, None)
            for r in self._conn.execute(
                f"SELECT {row_sql} FROM ticks ORDER BY rowid"
            )
        ]

        breaks: list[dict[str, str]] = []
        tick_detail: list[dict[str, Any]] = []
        legacy = chained = signed = 0
        prev_row = None
        last_cursor: str | None = None   # previous chained tick's fact_cursor
        first_start: str | None = None   # first chained tick's window_start
        saw_signature = False
        truncated = False

        for row in rows:
            if row[9] is None:  # window_hash NULL = pre-chain era
                legacy += 1
                prev_row = row
                continue
            chained += 1
            breaks_before = len(breaks)
            sig_ok: bool | None = None
            expected_prev = _tick_row_hash(prev_row) if prev_row is not None else None
            if row[6] != expected_prev:
                breaks.append({"tick": row[0], "name": row[1],
                               "reason": "prev_hash mismatch — tick sequence altered"})
            if last_cursor is not None and row[7] != last_cursor:
                breaks.append({"tick": row[0], "name": row[1],
                               "reason": "window_start does not continue previous "
                                         "fact_cursor — coverage gap"})
            if self._window_hash(row[7], row[8]) != row[9]:
                breaks.append({"tick": row[0], "name": row[1],
                               "reason": "window_hash mismatch — facts in window altered"})
            if row[10] is not None:
                signed += 1
                saw_signature = True
                if verifier is not None:
                    sig_ok = verifier(row[10], _tick_commitment_hash(row))
                    if not sig_ok:
                        breaks.append({"tick": row[0], "name": row[1],
                                       "reason": "signature invalid — tick contents "
                                                 "do not match signature"})
            elif saw_signature:
                breaks.append({"tick": row[0], "name": row[1],
                               "reason": "unsigned tick after signed era — "
                                         "signature stripped or era regressed"})
            if include_ticks:
                lo = self._cursor_rowid(row[7])
                hi = self._cursor_rowid(row[8])
                window_facts = 0
                if lo is not None and hi is not None:
                    window_facts = self._conn.execute(
                        "SELECT COUNT(*) FROM facts WHERE rowid > ? AND rowid <= ?",
                        (lo, hi),
                    ).fetchone()[0]
                tick_detail.append({
                    "tick": row[0], "name": row[1], "ts": row[2],
                    "signed": row[10] is not None,
                    "sig_ok": sig_ok,
                    "ok": len(breaks) == breaks_before,
                    "fact_cursor": row[8],
                    "window_facts": window_facts,
                    **cursor_fact_summary(self._conn, row[8]),
                })
            if first_start is None:
                first_start = row[7]
            last_cursor = row[8]
            prev_row = row
            if len(breaks) >= max_breaks:
                truncated = True
                break

        covered = 0
        if first_start is not None and last_cursor:
            lo = self._cursor_rowid(first_start)
            hi = self._cursor_rowid(last_cursor)
            if lo is not None and hi is not None:
                covered = self._conn.execute(
                    "SELECT COUNT(*) FROM facts WHERE rowid > ? AND rowid <= ?",
                    (lo, hi),
                ).fetchone()[0]
        total_facts = self.total

        report = {
            "ok": not breaks,
            "ticks": len(rows),
            "chained": chained,
            "legacy": legacy,
            "signed": signed,
            "sig_checked": sig_checked,
            "covered_facts": covered,
            "uncovered_facts": total_facts - covered,
            "breaks": breaks,
            "truncated": truncated,
        }
        if include_ticks:
            report["tick_detail"] = tick_detail
        return report

    def ticks_since(self, cursor: int) -> list[Tick]:
        """Return ticks with rowid > cursor."""
        rows = self._conn.execute(
            "SELECT name, ts, since, origin, payload FROM ticks WHERE rowid > ? ORDER BY rowid",
            (cursor,),
        ).fetchall()
        return [
            Tick.from_dict(
                {"name": r[0], "ts": r[1], "since": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    def ticks_between(self, start: datetime | float, end: datetime | float) -> list[Tick]:
        """Return ticks in the time range [start, end]."""
        start_ts = start.timestamp() if isinstance(start, datetime) else start
        end_ts = end.timestamp() if isinstance(end, datetime) else end
        rows = self._conn.execute(
            "SELECT name, ts, since, origin, payload FROM ticks WHERE ts >= ? AND ts <= ? ORDER BY rowid",
            (start_ts, end_ts),
        ).fetchall()
        return [
            Tick.from_dict(
                {"name": r[0], "ts": r[1], "since": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    @property
    def tick_total(self) -> int:
        """Total number of ticks in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM ticks").fetchone()
        return row[0]

    def latest_by_kind(self, kind: str) -> T | None:
        """Return the most recent fact of a given kind, or None."""
        row = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts WHERE kind = ? ORDER BY ts DESC, id DESC LIMIT 1",
            (kind,),
        ).fetchone()
        if row is None:
            return None
        return self._deserialize(
            {"kind": row[0], "ts": row[1], "observer": row[2], "origin": row[3], "payload": json.loads(row[4])}
        )

    def latest_by_kind_where(self, kind: str, key: str, value: Any) -> T | None:
        """Return the most recent fact of kind where payload[key] == value."""
        path = "$." + key
        row = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts "
            "WHERE kind = ? AND json_extract(payload, ?) = ? "
            "ORDER BY ts DESC, id DESC LIMIT 1",
            (kind, path, value),
        ).fetchone()
        if row is None:
            return None
        return self._deserialize(
            {"kind": row[0], "ts": row[1], "observer": row[2], "origin": row[3], "payload": json.loads(row[4])}
        )

    def has_kind_since(self, kind: str, ts: float) -> bool:
        """True if any fact of kind exists with ts > the given timestamp."""
        row = self._conn.execute(
            "SELECT 1 FROM facts WHERE kind = ? AND ts > ? LIMIT 1",
            (kind, ts),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SqliteStore[T]:
        return self

    def __exit__(self, *args) -> None:
        self.close()
