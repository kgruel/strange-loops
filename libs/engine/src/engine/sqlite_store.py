"""SqliteStore — SQLite-backed append-only event store.

Implements the Store protocol with durable persistence. Facts are stored
with kind, ts, observer as real columns (SQL-queryable) and payload as
JSON text (queryable via json_extract()).

Uses WAL mode for concurrent reads during folds. IDs are ULIDs generated
Python-side via python-ulid (26-char Crockford base32, time-sortable to the
millisecond — but NOT within-ms monotonic; see ``gen_id``). Ms-granular
time-sortability is load-bearing for cross-store fact interleaving (ORDER BY
id ≈ chronological) and for merge dedup on slice→merge round-trips via INSERT
OR IGNORE on the id PK. Receipt order is always rowid (append order), never
id order.

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

import rfc8785
import sqlite3

from ulid import ULID

# Pre-created decoder for faster JSON parsing in hot paths.
# raw_decode skips strip() and end-position validation — safe for SQLite
# payloads which are always well-formed JSON without whitespace padding.
_raw_decode = json.JSONDecoder().raw_decode


def gen_id() -> str:
    """Generate a unique ID for store records.

    Uses python-ulid: 26-char Crockford base32 ULID. Guaranteed:

    - **Unique** — 48-bit millisecond timestamp + 80 bits of randomness.
    - **Time-sortable to the millisecond** — lexicographic order matches
      generation time across *different* milliseconds (the timestamp prefix
      dominates). Load-bearing for cross-store interleaving (``ORDER BY id`` ≈
      chronological at ms granularity) and merge dedup on the id PK.

    NOT guaranteed: **within-millisecond ordering**. python-ulid draws a fresh
    random 80-bit component per id (it is not a monotonic factory), so two ids
    minted in the same millisecond have NO order relation — adjacent calls can
    invert (empirically ~1/5000 in a tight loop). Any code that needs receipt
    order MUST use rowid (append order), never id order — see the ORDERING
    AUTHORITY note on ``append_tick`` and the WitnessPosition A3 rule. Pure
    Python — no C extension, no dlopen cost.
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
    """Canonical encoding for commitment hashing: JCS, RFC 8785.

    Upgraded from implementation-local json.dumps 2026-06-12
    (decision design/attestation-canonicalization-jcs): the Go conformance
    oracle is the federation-facing consumer the original docstring named
    as the upgrade trigger, and cross-implementation hash divergence
    renders as a false tamper alarm. Pre-JCS chains were re-anchored at
    the swap (sl store reanchor), not grandfathered — SPEC §8.1.

    Stored payload TEXT is still embedded verbatim as a string value, so
    hashes detect byte-level tampering without re-serialization concerns
    leaking in from payload content.
    """
    return rfc8785.dumps(obj)


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
    """Era-aware hash of one persisted fact row.

    Row shape: (id, kind, ts, observer, origin, payload[, signature]).
    The signature key is included only when the row carries one, so every
    pre-signature fact row hashes byte-identically to delta 1/2 — already-
    sealed window hashes never re-anchor. For signed facts the window
    commits over content+signature, making fact-signature-stripping a
    detectable break in any sealed window (delta-2 envelope trick, one
    layer down — design/fact-signing-per-observer-keys).
    """
    envelope = {
        "id": row[0], "kind": row[1], "ts": row[2],
        "observer": row[3], "origin": row[4], "payload": row[5],
    }
    if len(row) > 6 and row[6] is not None:
        envelope["signature"] = row[6]
    return hashlib.sha256(_canonical_bytes(envelope)).hexdigest()


def _fact_commitment_hash(
    kind: str, ts: float, observer: str, origin: str, payload_text: str
) -> str:
    """Hash the fact's CONTENT commitment — what the fact signer signs.

    Content-only by design (design/fact-signature-at-store-column):
    excludes id and rowid, which are custody context, not authored
    content. This is what makes the signature transport-stable — any
    store holding the row can re-derive the commitment and verify
    authorship against the observer registry without trusting the
    sender. Stored payload TEXT is embedded verbatim (same posture as
    the tick envelope: byte-level tamper detection, no re-serialization).
    Never includes the signature (a signature cannot sign itself).
    """
    envelope = {
        "kind": kind, "ts": ts, "observer": observer,
        "origin": origin, "payload": payload_text,
    }
    return hashlib.sha256(_canonical_bytes(envelope)).hexdigest()


# Public name: the content commitment is a cross-lib contract —
# libs/store's transport paths and any receive-side verifier must hash
# the same envelope the signer signed. Same function, two names.
def fact_commitment_hash(
    kind: str, ts: float, observer: str, origin: str, payload_text: str
) -> str:
    """Content commitment hash for fact signing (see _fact_commitment_hash)."""
    return _fact_commitment_hash(kind, ts, observer, origin, payload_text)


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
        payload  TEXT NOT NULL CHECK (json_valid(payload)),
        signature TEXT
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


class UnsignedTickInSignedEra(Exception):
    """``append_tick`` was asked to append an unsigned tick to a store already
    in the signed era — the tick-signing floor (decision design/tick-signing
    -era-is-a-floor). Minting it would break chain era-monotonicity
    (verify_chain flags "unsigned tick after signed era").

    The floor is enforced BY DEFAULT (``enforce_floor=True``): the invariant
    lives on the store mint, so every caller — every verb that fires a boundary
    AND every other live mint (e.g. the tasks harness) — is fail-safe without
    having to opt in. Only re-mint paths that legitimately reconstruct history
    under their own signer wiring (rebirth/slice/replay) opt OUT explicitly
    with ``enforce_floor=False``; the exemptions are named, not the enforcement.

    The signed-era predicate matches verify_chain exactly: a *chained* signed
    tick (``signature IS NOT NULL AND window_hash IS NOT NULL``) — a legacy
    pre-chain signed row does not open the era.
    """


class GenesisExists(Exception):
    """``absorb_genesis`` found a ``_decl.genesis`` row already in the store.

    Genesis is identity, not fold state (SPEC §9.2): a store's OWN lineage is
    opened exactly once, so re-absorption is refused rather than last-write-
    wins. Scoped by the ``store_meta.own_lineage`` marker — a merged foreign
    genesis does NOT block minting our own; only an already-open own lineage
    (marker present, or a single pre-marker genesis adopted as self) refuses.
    Re-absorb over an open lineage is the edit ceremony (``absorb_edit``).
    """


class UnsignableGenesis(Exception):
    """``absorb_genesis`` could not sign the genesis event.

    A genesis is the lineage's attestation root — an unsigned one is a hole
    in the store's attestation story (SPEC §9.2 / §9.4), so absorb refuses
    (rollback, no write) rather than append an unsigned root. Raised when the
    injected ``fact_signer`` is absent or returns no signature for the
    recording observer. The signature that matters is over the ACTUAL final
    payload, verified before commit — never a throwaway probe digest.
    """


class NoGenesis(Exception):
    """``absorb_edit`` found no ``_decl.genesis`` row — the store is unabsorbed.

    The edit ceremony (SPEC §9.2, S4) re-emits changed subjects over an
    already-opened lineage; there is nothing to diff against before genesis.
    Opening the lineage is the genesis path (``absorb_genesis``), not an edit.
    """


class AmbiguousGenesis(Exception):
    """No ``own_lineage`` marker and more than one ``_decl.genesis`` row.

    Without the store-local marker (pre-marker stores) the self-lineage id a
    write ceremony must stamp is indeterminate among several genesis rows.
    Conservative refusal, mirroring the resolver's ``AmbiguousLineage``
    (SPEC §9.2 Lineage). A marked store never raises this.
    """


class UnsignableEdit(Exception):
    """``absorb_edit`` could not sign a change event.

    Declaration events must be attestable (SPEC §9.4); an edit rides the same
    signing posture as genesis (an absorbed store already had a key at genesis),
    so an unsignable change refuses the WHOLE batch (rollback, no partial write)
    rather than append an unsigned declaration row.
    """


class StaleDeclarationHead(Exception):
    """``absorb_edit``'s ``expected_head`` no longer matches the store.

    The caller diffed the file against a declaration head that has since
    moved (a concurrent re-absorb landed). Applying the stale diff could
    leave the store's fold matching neither author's file, with both
    reporting success — so the edit refuses (rollback) and the caller re-runs
    against the current head. Compare-and-swap, not last-write-wins.
    """


class ReservedKindViolation(Exception):
    """``absorb_edit`` was handed a kind outside the frozen edit vocabulary.

    The edit ceremony emits only ``*-defined``/``*-retired``/``*-removed``
    declaration events (SPEC §9.2 table). This primitive is not a general
    ``_decl.*`` (or domain-kind) append escape: genesis has its own primitive,
    receipts are the transport layer's (S6), and user facts go through the
    emit path with its write-time reservation.
    """


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
        fact_signer: Callable[[str, str], str | None] | None = None,
    ) -> None:
        """tick_signer: optional callable (commitment digest str -> signature
        str, e.g. base64 Ed25519). Injected, never imported — custody is a
        property of the store handle (the key lives next to the db), so the
        signer rides the constructor rather than each append_tick call.
        None = ticks append unsigned (pre-signature era, honest NULL).

        fact_signer (delta 3): optional callable (observer str, content
        commitment digest str -> signature str | None). Per-observer
        authorship (design/fact-signing-per-observer-keys): the callable
        selects a key by observer and returns None for observers without
        one — those facts append unsigned (honest NULL, a per-observer
        era rather than a per-store epoch). Injected, never imported.
        """
        self._path = Path(path)
        self._serialize = serialize
        self._deserialize = deserialize
        self._tick_signer = tick_signer
        self._fact_signer = fact_signer
        self._direct_fact_build: bool | None = None  # lazy detection
        self._fact_class: type | None = None

        try:
            is_new = self._path.stat().st_size == 0
        except OSError:
            is_new = True
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._chain_ready = is_new  # new DBs get chain columns in schema
        self._fact_sig_ready = is_new  # new DBs get facts.signature in schema
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

    def append(
        self,
        event: T,
        *,
        id_override: str | None = None,
        signature_override: str | None = None,
    ) -> str:
        """Append one event to the store. Returns the ID assigned.

        If id_override is provided, that ID is used; otherwise a new ID
        is generated via gen_id(). The ID is returned in either case so
        callers (e.g. emit's receipt path) can reference the stored row.

        Signature (delta 3): when a fact_signer was injected, signs the
        CONTENT commitment of the new row under the fact's own observer;
        NULL when the signer returns None for that observer (per-observer
        pre-signature era). signature_override carries an EXISTING
        signature verbatim — replay/rebirth/transport paths must preserve
        the original authorship signature, never re-sign (re-signing
        another observer's fact under a local key would be forgery; the
        override bypasses the signer entirely).
        """
        if self._conn is None:
            # close() is part of the public lifecycle now — use-after-close
            # gets a named error, not AttributeError on a None connection.
            raise RuntimeError(f"store closed: {self._path}")
        self._ensure_sync()
        self._ensure_fact_signature_column()
        d = self._serialize(event)
        fact_id = id_override if id_override is not None else gen_id()
        observer = d["observer"]
        origin = d.get("origin", "")
        payload_text = json.dumps(d["payload"])
        if signature_override is not None:
            signature = signature_override
        elif self._fact_signer is not None:
            signature = self._fact_signer(
                observer,
                _fact_commitment_hash(d["kind"], d["ts"], observer, origin, payload_text),
            )
        else:
            signature = None
        self._conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fact_id, d["kind"], d["ts"], observer, origin, payload_text, signature),
        )
        self._conn.commit()
        return fact_id

    def current_chain_head(self) -> str | None:
        """The row-identity hash of the latest *chained* tick, or None.

        What a successor tick's ``prev_hash`` commits to (era-aware
        ``_tick_row_hash``) — the "chain head" a genesis pins. None when the
        store has no chained tick (a pre-chain-only or empty store pins on
        the fact cursor instead). Read-only; never migrates schema.
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(ticks)")}
        if "window_hash" not in cols:
            return None
        row_sql = _TICK_ROW_SQL if "signature" in cols else _TICK_ROW_SQL_V1
        row = self._conn.execute(
            f"SELECT {row_sql} FROM ticks "
            "WHERE window_hash IS NOT NULL ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        # _tick_row_hash reads an 11-field row (signature at [10]); a delta-1
        # schema yields 10 — pad the signature slot NULL.
        return _tick_row_hash(row if len(row) > 10 else (*row, None))

    def absorb_genesis(
        self,
        documents: list,
        *,
        observer: str,
        origin: str = "",
        fact_signer: Callable[[str, str], str | None] | None,
        protocol: int | None = None,
    ) -> dict[str, Any]:
        """Open the store's declaration lineage — the atomic genesis primitive.

        The lineage-opening ceremony's write half (SPEC §9.2 era rule),
        performed as ONE ``BEGIN IMMEDIATE`` transaction so the identity check,
        the era pins, and the append are indivisible: a concurrent emit cannot
        falsify a pin between read and write, and two concurrent absorbs cannot
        both mint a genesis (the second blocks on the write lock, then sees the
        first's row and refuses).

        Steps, all inside the transaction:

        1. Refuse (``GenesisExists``) if the store's OWN lineage is already
           open: the ``store_meta.own_lineage`` marker exists, or (pre-marker
           compat) exactly one ``_decl.genesis`` row exists — that row is
           adopted as self and the marker backfilled before refusing. Foreign
           genesis rows (marker present, ids differ) do NOT block: merge
           legitimately carries them as inert citizens (§9.2 Lineage), and a
           store that received one must still be able to mint its own
           identity. No marker + several genesis rows refuses as ambiguous.
        2. Read the era pins — chain head (latest chained tick's row hash) and
           fact cursor (newest fact by WITNESS order / rowid) — so
           "everything before me predates historization" is verifiable.
        3. Build the whole payload (``documents`` + ``protocol`` + pins), sign
           its CONTENT commitment under ``observer`` via ``fact_signer``, and
           refuse (``UnsignableGenesis``, rollback) if no signature is
           produced. The signed commitment is over the ACTUAL final payload,
           never a throwaway probe — genesis is the attestation root.
        4. Append the ``_decl.genesis`` row, stamp ``store_meta.own_lineage``
           with its id (the store-local identity marker — merge copies facts,
           never meta, so identity cannot arrive from outside), and commit.
           The genesis row's own id IS the lineage id (§9.2), returned in the
           receipt.

        This is protocol surface the Go conformance oracle mirrors: the payload
        shape (``protocol``, ``documents``, ``chain_head``, ``fact_cursor``),
        the witness-order cursor, and the sign-final-payload rule are the
        contract. ``documents`` are the subject-scoped declaration documents
        (from ``lang.document.vertex_to_documents``); this method stamps the
        protocol and pins around them.

        Returns a receipt dict: ``{lineage, protocol, documents, chain_head,
        fact_cursor, observer, signed}``.
        """
        from lang.document import DECL_GENESIS, DECLARATION_PROTOCOL_VERSION

        if protocol is None:
            protocol = DECLARATION_PROTOCOL_VERSION

        # Prepare schema OUTSIDE the transaction (these commit): the genesis
        # write and the chain-head read need the signature and chain columns
        # present. Safe pre-work — they mutate no facts.
        self._ensure_sync()
        self._ensure_fact_signature_column()
        self._ensure_chain_columns()
        self._ensure_meta_table()

        conn = self._conn
        prev_iso = conn.isolation_level
        conn.isolation_level = None  # autocommit — explicit transaction control
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                own = self._own_lineage_in_txn(conn)
                if own is not None:
                    raise GenesisExists(
                        "the store's own lineage is already open "
                        f"(own_lineage {own}) — re-absorb/edit is a later "
                        "ceremony (no --force)"
                    )

                chain_head = self.current_chain_head()
                frow = conn.execute(
                    "SELECT id FROM facts ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                fact_cursor = frow[0] if frow else None

                payload = {
                    "protocol": protocol,
                    "documents": list(documents),
                    "chain_head": chain_head,
                    "fact_cursor": fact_cursor,
                }
                ts = datetime.now(_UTC).timestamp()
                lineage_id = gen_id()
                payload_text = json.dumps(payload)
                signature = (
                    fact_signer(
                        observer,
                        _fact_commitment_hash(
                            DECL_GENESIS, ts, observer, origin, payload_text
                        ),
                    )
                    if fact_signer is not None
                    else None
                )
                if signature is None:
                    raise UnsignableGenesis(
                        f"no signature produced for observer {observer!r} — a "
                        "genesis must be signed (it is the lineage's "
                        "attestation root); set up signing first"
                    )

                conn.execute(
                    "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (lineage_id, DECL_GENESIS, ts, observer, origin, payload_text, signature),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO store_meta (key, value) "
                    "VALUES ('own_lineage', ?)",
                    (lineage_id,),
                )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.isolation_level = prev_iso

        return {
            "lineage": lineage_id,
            "protocol": protocol,
            "documents": len(payload["documents"]),
            "chain_head": chain_head,
            "fact_cursor": fact_cursor,
            "observer": observer,
            "signed": True,
        }

    def absorb_edit(
        self,
        changes: list,
        *,
        observer: str,
        origin: str = "",
        fact_signer: Callable[[str, str], str | None] | None,
        expected_head: tuple[float, str] | None = None,
    ) -> dict[str, Any]:
        """Re-emit changed declaration subjects over an open lineage (S4).

        The edit ceremony's write half (SPEC §9.2). Each ``change`` is a
        subject-granular whole-document delta (from
        ``lang.document.diff_documents``), duck-typed by four attributes:
        ``kind`` (the final ``_decl.*-defined`` or ``*-retired`` event kind),
        ``subject``, ``payload`` (the whole document payload for a definition,
        ``None`` for a removal), and ``annotation`` (``added``/``modified``/
        ``removed`` — rides the row as ``change=``).

        Performed as ONE ``BEGIN IMMEDIATE`` transaction so the batch is
        all-or-nothing (a half-applied ontology change is the §9.1 lie
        mid-flight) and the lineage id is read consistently:

        1. Resolve the store's OWN lineage: the ``store_meta.own_lineage``
           marker, or (pre-marker compat) a single genesis row adopted as self
           with the marker backfilled in this transaction. None →
           :class:`NoGenesis`; unmarked + several → :class:`AmbiguousGenesis`.
        2. If ``expected_head`` is given, compare it against the store's
           current declaration head — the ``(ts, id)`` of the newest
           self-lineage ``_decl.*`` row (genesis included). A mismatch raises
           :class:`StaleDeclarationHead` (rollback): the caller diffed against
           a head that has since moved (concurrent re-absorb), and applying a
           stale diff could leave the store matching neither input file.
        3. Every row in the ceremony shares ONE effective ``ts``, stamped
           once — the ceremony is a single ontology transition. Without this,
           a historical ``as_of`` cursor could land *between* the rows of one
           edit and observe a half-applied ontology (e.g. a rename showing
           both old and new kinds) — transaction atomicity protects live
           readers, not rewound ones.
        4. Kinds are allowlisted to the frozen definition/tombstone vocabulary
           (:class:`ReservedKindViolation` otherwise) — this primitive is the
           edit ceremony's write half, not a general ``_decl.*`` append escape.
        5. For each change, build the resolver's overlay/tombstone contract
           payload — ``{lineage, subject, payload, change}`` for a definition,
           ``{lineage, subject, change}`` for a tombstone — sign its CONTENT
           commitment under ``observer``, and refuse (:class:`UnsignableEdit`,
           rollback) if any is unsigned. Append every row and commit.

        An empty ``changes`` list is a no-op (no transaction, empty receipt) —
        the idempotence guarantee: re-absorbing an unchanged file writes nothing.

        The row shape is the provisional contract the S2 resolver already
        consumes (``engine.declaration``); the Go conformance oracle mirrors it.
        Returns a receipt: ``{lineage, defined, retired, observer, signed}``.
        """
        from lang.document import (
            DECL_GENESIS,
            DECL_LENS_DEFINED,
            DECL_VERTEX_DEFINED,
            DEFINED_TO_TOMBSTONE,
        )

        # The frozen edit vocabulary: every tombstonable *-defined/-retired
        # pair PLUS the two singletons (vertex, lens) that are replaced by
        # re-definition and have no tombstone. Omitting the singletons broke
        # legitimate edits (flipping strict, editing a lens) — re-review #5.
        allowed_kinds = (
            set(DEFINED_TO_TOMBSTONE)
            | set(DEFINED_TO_TOMBSTONE.values())
            | {DECL_VERTEX_DEFINED, DECL_LENS_DEFINED}
        )

        self._ensure_sync()
        self._ensure_fact_signature_column()
        self._ensure_meta_table()

        if not changes:
            return {
                "lineage": None,
                "defined": 0,
                "retired": 0,
                "observer": observer,
                "signed": True,
            }

        conn = self._conn
        prev_iso = conn.isolation_level
        conn.isolation_level = None  # autocommit — explicit transaction control
        defined = retired = 0
        lineage_id: str | None = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                lineage_id = self._own_lineage_in_txn(conn)
                if lineage_id is None:
                    raise NoGenesis(
                        "no _decl.genesis event — the store's lineage is not "
                        "open; run absorb to open it (there is nothing to edit "
                        "against before genesis)"
                    )

                if expected_head is not None:
                    head = self._declaration_head_in_txn(conn, lineage_id)
                    if head != tuple(expected_head):
                        raise StaleDeclarationHead(
                            f"declaration head moved: expected {expected_head}, "
                            f"store is at {head} — another edit landed since "
                            "the diff was computed; re-run absorb against the "
                            "current head"
                        )

                # ONE effective ts for the whole ceremony (step 3).
                ts = datetime.now(_UTC).timestamp()

                for ch in changes:
                    kind = ch.kind
                    subject = ch.subject
                    payload_doc = ch.payload
                    annotation = ch.annotation
                    if kind not in allowed_kinds:
                        raise ReservedKindViolation(
                            f"absorb_edit refuses kind {kind!r} — only the "
                            "frozen definition/tombstone vocabulary may ride "
                            "the edit ceremony"
                        )
                    row_payload: dict[str, Any] = {
                        "lineage": lineage_id,
                        "subject": subject,
                        "change": annotation,
                    }
                    if payload_doc is not None:
                        # A tombstone carries no document payload; a definition
                        # carries the whole subject document.
                        row_payload["payload"] = payload_doc
                        defined += 1
                    else:
                        retired += 1

                    fact_id = gen_id()
                    payload_text = json.dumps(row_payload)
                    signature = (
                        fact_signer(
                            observer,
                            _fact_commitment_hash(
                                kind, ts, observer, origin, payload_text
                            ),
                        )
                        if fact_signer is not None
                        else None
                    )
                    if signature is None:
                        raise UnsignableEdit(
                            f"no signature produced for observer {observer!r} — "
                            "a declaration edit must be signed (it enters the "
                            "attestation tier); set up signing first"
                        )
                    conn.execute(
                        "INSERT INTO facts "
                        "(id, kind, ts, observer, origin, payload, signature) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (fact_id, kind, ts, observer, origin, payload_text, signature),
                    )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.isolation_level = prev_iso

        return {
            "lineage": lineage_id,
            "defined": defined,
            "retired": retired,
            "observer": observer,
            "signed": True,
        }

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

    def _ensure_meta_table(self) -> None:
        """Idempotent: create the store-local ``store_meta`` key/value table.

        Holds identity that is NOT a fact — ``own_lineage`` (which
        ``_decl.genesis`` row is *self*, SPEC §9.2). Merge copies facts and
        ticks, never this table, so a store's identity cannot arrive from (or
        leak to) another store. Dump/rebuild (S6) must carry it explicitly.
        """
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        self._conn.commit()

    def _own_lineage_in_txn(self, conn: Any) -> str | None:
        """Resolve the store's own lineage id inside an open write transaction.

        Marker present → its value. No marker + no genesis rows → ``None``
        (lineage not open). No marker + ANY genesis rows →
        :class:`AmbiguousGenesis`: facts alone cannot prove which genesis is
        self (a singleton heuristic is the hijack vector — closing re-review
        #1), so identity is claimed only by the explicit adopt ceremony
        (:meth:`adopt_lineage`), never inferred.
        """
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'own_lineage'"
        ).fetchone()
        if row is not None:
            return row[0]
        from lang.document import DECL_GENESIS

        genesis_rows = conn.execute(
            "SELECT id FROM facts WHERE kind = ? ORDER BY rowid",
            (DECL_GENESIS,),
        ).fetchall()
        if not genesis_rows:
            return None
        raise AmbiguousGenesis(
            f"{len(genesis_rows)} _decl.genesis row(s) and no own_lineage "
            "marker — identity cannot be inferred from facts; run "
            "`loops store adopt` to explicitly claim the store's own lineage"
        )

    def adopt_lineage(self, lineage_id: str | None = None) -> dict[str, Any]:
        """Explicitly claim a genesis row as the store's own lineage.

        The one legitimate way an unmarked store (pre-marker era, or one that
        received genesis rows via merge) gains identity: a human names which
        genesis is self and the marker is stamped. With one genesis row,
        ``lineage_id`` may be omitted; with several it is required (exact id
        or unique prefix). Refuses if a marker already exists.

        Returns a receipt: ``{lineage, observer, ts, genesis_count}`` — the
        adopted row's observer and timestamp are surfaced so the adopter can
        eyeball that the claimed genesis is plausibly their own.
        """
        from lang.document import DECL_GENESIS

        self._ensure_meta_table()
        conn = self._conn
        prev_iso = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT value FROM store_meta WHERE key = 'own_lineage'"
                ).fetchone()
                if row is not None:
                    raise GenesisExists(
                        f"own_lineage already claimed ({row[0]}) — adopt is a "
                        "one-time ceremony for unmarked stores"
                    )
                genesis_rows = conn.execute(
                    "SELECT id, observer, ts FROM facts WHERE kind = ? "
                    "ORDER BY rowid",
                    (DECL_GENESIS,),
                ).fetchall()
                if not genesis_rows:
                    raise NoGenesis(
                        "no _decl.genesis rows — nothing to adopt; run "
                        "absorb to open a fresh lineage"
                    )
                if lineage_id is None:
                    if len(genesis_rows) > 1:
                        ids = ", ".join(r[0] for r in genesis_rows)
                        raise AmbiguousGenesis(
                            f"{len(genesis_rows)} genesis rows ({ids}) — name "
                            "the one that is self via the lineage id"
                        )
                    chosen = genesis_rows[0]
                else:
                    matches = [
                        r for r in genesis_rows if r[0].startswith(lineage_id)
                    ]
                    if len(matches) != 1:
                        raise AmbiguousGenesis(
                            f"lineage {lineage_id!r} matches "
                            f"{len(matches)} genesis rows — need a unique "
                            "id/prefix"
                        )
                    chosen = matches[0]
                conn.execute(
                    "INSERT OR REPLACE INTO store_meta (key, value) "
                    "VALUES ('own_lineage', ?)",
                    (chosen[0],),
                )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.isolation_level = prev_iso
        return {
            "lineage": chosen[0],
            "observer": chosen[1],
            "ts": chosen[2],
            "genesis_count": len(genesis_rows),
        }

    def _declaration_head_in_txn(
        self, conn: Any, lineage_id: str
    ) -> tuple[float, str] | None:
        """The ``(ts, id)`` of the newest self-lineage declaration row.

        Genesis included; foreign-lineage ``_decl.*`` rows excluded (their
        payload stamps a different lineage). This is the CAS token
        ``absorb_edit`` compares ``expected_head`` against — replay-ordered
        ``(ts, id)``, the same axis the resolver folds on.
        """
        best: tuple[float, str] | None = None
        rows = conn.execute(
            "SELECT id, kind, ts, payload FROM facts WHERE kind GLOB '_decl.*'"
        ).fetchall()
        for fact_id, kind, ts, payload_text in rows:
            if fact_id == lineage_id:
                pass  # own genesis participates
            else:
                try:
                    payload = json.loads(payload_text)
                except (json.JSONDecodeError, TypeError):
                    continue
                if payload.get("lineage") != lineage_id:
                    continue
            candidate = (ts, fact_id)
            if best is None or candidate > best:
                best = candidate
        return best

    def declaration_head(self) -> tuple[float, str] | None:
        """Public read of the self-lineage declaration head (CAS token).

        Captured by the CLI at diff time and passed back as ``absorb_edit``'s
        ``expected_head`` so a concurrent re-absorb between diff and apply is
        refused instead of silently interleaved. None when the lineage is not
        open (or unmarked-ambiguous — the write ceremony will refuse anyway).
        """
        self._ensure_meta_table()
        conn = self._conn
        try:
            lineage = self._own_lineage_in_txn(conn)
        except AmbiguousGenesis:
            return None
        if lineage is None:
            return None
        return self._declaration_head_in_txn(conn, lineage)

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

    def _ensure_fact_signature_column(self) -> None:
        """Idempotent migration: add the signature column to a pre-delta-3
        facts table. Existing rows keep NULL — the pre-signature fact era
        stays visible, never retro-claimed (same posture as the chain
        columns and the uuid4 id wedge)."""
        if self._fact_sig_ready:
            return
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)")}
        if "signature" not in cols:
            self._conn.execute("ALTER TABLE facts ADD COLUMN signature TEXT")
            self._conn.commit()
        self._fact_sig_ready = True

    def _facts_have_signature_column(self) -> bool:
        """Read-only column probe for verify paths (never migrates)."""
        if self._fact_sig_ready:
            return True
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(facts)")}
        return "signature" in cols

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
        # Era-aware row hash: include the signature column when it exists.
        # Unsigned rows hash identically either way (the signature key is
        # only added when non-NULL), so pre-delta-3 sealed windows verify
        # unchanged; signed facts are strip-detectable once sealed.
        cols = "id, kind, ts, observer, origin, payload"
        if self._facts_have_signature_column():
            cols += ", signature"
        for row in self._conn.execute(
            f"SELECT {cols} FROM facts "
            "WHERE rowid > ? AND rowid <= ? ORDER BY rowid",
            (lo, hi),
        ):
            h.update(_fact_row_hash(row).encode())
        return h.hexdigest()

    def append_tick(self, tick: Tick, *, enforce_floor: bool = True) -> None:
        """Append a tick to the ticks table, extending the hash chain.

        ``enforce_floor`` (the tick-signing floor, decision design/tick-signing
        -era-is-a-floor) is ON BY DEFAULT: when no signature was produced AND
        the store is already in the signed era, refuse — raise
        ``UnsignedTickInSignedEra`` BEFORE writing, so no unsigned tick is
        appended and the chain's era-monotonicity holds. Default-on makes the
        invariant fail-safe: every live mint (each verb that fires a boundary —
        ``sl seal``, ``sl emit <v> seal``, count/predicate boundaries — and any
        other live caller such as the tasks harness) is protected without
        opting in. Only re-mint paths that reconstruct history under their own
        signer wiring (rebirth/slice/replay) pass ``enforce_floor=False`` — the
        exemptions are named, not the enforcement.

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

        if enforce_floor and signature is None:
            # Floor: don't regress out of the signed era. Keyed off the actual
            # signature outcome (covers no-signer AND signer-returned-None), and
            # the predicate matches verify_chain's era boundary (chained signed
            # tick), so the guard refuses exactly what verify would condemn.
            prior_signed = self._conn.execute(
                "SELECT EXISTS(SELECT 1 FROM ticks "
                "WHERE signature IS NOT NULL AND window_hash IS NOT NULL)"
            ).fetchone()
            if prior_signed and prior_signed[0]:
                raise UnsignedTickInSignedEra(
                    "refusing to mint an unsigned tick: the store is in the "
                    "signed era (prior signed ticks exist) and no signing key "
                    "is available — minting would break chain era-monotonicity"
                )

        self._conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, "
            "prev_hash, window_start, fact_cursor, window_hash, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*row, signature),
        )
        self._conn.commit()

    def reanchor(self) -> dict[str, Any]:
        """Recompute every commitment under the CURRENT canonical encoding.

        The canon-migration ceremony (SPEC §8.1: pre-migration chains are
        re-anchored, not grandfathered). Walks the store once and re-derives
        the attestation layer: signed facts get fresh signatures over their
        JCS commitment, chained ticks get recomputed window hashes, re-linked
        prev_hash, and (when previously signed) fresh tick signatures.

        Append-only boundary: facts' EVENT columns (id, kind, ts, observer,
        origin, payload) and ticks' event fields are never touched. The
        attestation columns (signature, prev_hash, window_hash) are DERIVED
        data — a commitment computed over events. Re-deriving them under a
        new canon is replay at the attestation layer, not mutation of
        history. (Window cursors are fact ids — event-layer references —
        and are preserved verbatim.)

        Era rules hold: pre-chain ticks and unsigned rows are untouched —
        absence stays absent, nothing is retro-claimed. Refuses to proceed
        (raises ValueError, no partial write) when a signed row exists whose
        key is unavailable: a partial re-anchor would strip authorship.

        Requires the store be constructed WITH its signers (tick_signer /
        fact_signer) when signed rows exist. Returns a receipt dict:
        {facts_resigned, ticks_rechained, ticks_resigned, head} where head
        is the new chain-head row hash.
        """
        self._ensure_sync()
        self._ensure_chain_columns()

        # --- Pass 1: re-sign signed facts (commitments change under the
        # new canon; window hashes below must seal the NEW signatures). ---
        facts_resigned = 0
        if self._facts_have_signature_column():
            signed = self._conn.execute(
                "SELECT rowid, kind, ts, observer, origin, payload "
                "FROM facts WHERE signature IS NOT NULL ORDER BY rowid"
            ).fetchall()
            updates = []
            for rowid, kind, ts, observer, origin, payload in signed:
                digest = _fact_commitment_hash(kind, ts, observer, origin, payload)
                sig = (self._fact_signer(observer, digest)
                       if self._fact_signer is not None else None)
                if sig is None:
                    raise ValueError(
                        f"reanchor: no signing key for observer {observer!r} "
                        "(fact rowid {0}) — refusing partial re-anchor; a "
                        "signed fact must not lose authorship".format(rowid)
                    )
                updates.append((sig, rowid))
            self._conn.executemany(
                "UPDATE facts SET signature = ? WHERE rowid = ?", updates
            )
            facts_resigned = len(updates)

        # --- Pass 2: walk ticks in witness order, re-deriving the chain. ---
        ticks_rechained = 0
        ticks_resigned = 0
        running_hash: str | None = None
        rows = self._conn.execute(
            f"SELECT rowid, {_TICK_ROW_SQL} FROM ticks ORDER BY rowid"
        ).fetchall()
        for raw in rows:
            rowid, row10, old_sig = raw[0], raw[1:11], raw[11]
            if row10[9] is None:  # pre-chain era: untouched, but its row
                running_hash = _tick_row_hash(row10)  # hash anchors successors
                continue
            new_row = (*row10[:6], running_hash, row10[7], row10[8],
                       self._window_hash(row10[7], row10[8]))
            new_sig = None
            if old_sig is not None:
                if self._tick_signer is None:
                    raise ValueError(
                        "reanchor: store has signed ticks but no tick_signer "
                        "— refusing partial re-anchor"
                    )
                new_sig = self._tick_signer(_tick_commitment_hash(new_row))
                ticks_resigned += 1
            self._conn.execute(
                "UPDATE ticks SET prev_hash = ?, window_hash = ?, "
                "signature = ? WHERE rowid = ?",
                (new_row[6], new_row[9], new_sig, rowid),
            )
            ticks_rechained += 1
            running_hash = _tick_row_hash(
                (*new_row, new_sig) if new_sig is not None else new_row
            )
        self._conn.commit()
        return {
            "facts_resigned": facts_resigned,
            "ticks_rechained": ticks_rechained,
            "ticks_resigned": ticks_resigned,
            "head": running_hash,
        }

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

    def verify_facts(
        self,
        *,
        verifier: Callable[[str, str, str], bool] | None = None,
        max_breaks: int = 10,
    ) -> dict[str, Any]:
        """Verify fact authorship signatures (delta 3).

        A fact signature is a per-observer AUTHORSHIP claim over the
        content commitment (kind, ts, observer, origin, payload) — a
        different claim from the tick chain's receipt attestation, and
        transport-stable because it commits to nothing store-local
        (design/fact-signature-at-store-column).

        ``verifier`` is an injected callable (observer str, signature str,
        commitment digest str) -> bool — apps/loops composes it from the
        observer-key registry, checking against THAT observer's declared
        key exactly (authorship, not the tick path's any-key receipt
        relaxation). When None, signatures are counted but not checked.

        Tamper coverage note: an invalid signature here means content or
        signature was altered. STRIPPING a signature is not detectable at
        this layer alone (NULL is also the honest pre-signature era); the
        sealed-window hashes walked by verify_chain catch strips, since
        the fact row hash is era-aware. Live-edge facts (not yet sealed
        by a tick) are strippable without trace until the next boundary —
        the same custody boundary delta 2 accepted for ticks.

        Returns a report dict:
            ok            True when no breaks found
            facts         total fact rows
            signed        rows carrying a signature
            unsigned      rows without (pre-signature era / unkeyed observers)
            sig_checked   True when a verifier was provided
            observers     {observer: {"signed": n, "unsigned": n}}
            breaks        list of {fact, observer, kind, reason} (capped)
            truncated     True if the walk stopped at max_breaks

        Read-only: never migrates schema. A pre-delta-3 facts table (no
        signature column) reports everything unsigned.
        """
        sig_checked = verifier is not None
        observers: dict[str, dict[str, int]] = {}
        breaks: list[dict[str, str]] = []
        truncated = False

        def _obs(name: str) -> dict[str, int]:
            return observers.setdefault(name, {"signed": 0, "unsigned": 0})

        if not self._facts_have_signature_column():
            for name, n in self._conn.execute(
                "SELECT observer, COUNT(*) FROM facts GROUP BY observer"
            ):
                _obs(name)["unsigned"] = n
            total = self.total
            return {
                "ok": True, "facts": total, "signed": 0, "unsigned": total,
                "sig_checked": sig_checked, "observers": observers,
                "breaks": [], "truncated": False,
            }

        signed = unsigned = 0
        for row in self._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload, signature "
            "FROM facts ORDER BY rowid"
        ):
            fact_id, kind, ts, observer, origin, payload_text, signature = row
            if signature is None:
                unsigned += 1
                _obs(observer)["unsigned"] += 1
                continue
            signed += 1
            _obs(observer)["signed"] += 1
            if verifier is not None and not verifier(
                observer, signature,
                _fact_commitment_hash(kind, ts, observer, origin, payload_text),
            ):
                breaks.append({
                    "fact": fact_id, "observer": observer, "kind": kind,
                    "reason": "signature invalid — content does not match "
                              "the observer's authorship signature",
                })
                if len(breaks) >= max_breaks:
                    truncated = True
                    break

        return {
            "ok": not breaks,
            "facts": self.total,  # signed/unsigned are partial when truncated
            "signed": signed,
            "unsigned": unsigned,
            "sig_checked": sig_checked,
            "observers": observers,
            "breaks": breaks,
            "truncated": truncated,
        }

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
