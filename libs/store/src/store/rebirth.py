"""Rebirth — replay a store through a transform into a new store, with receipt.

A rebirth is a NEW CUSTODY CONTEXT (same posture as slice/merge: chain
columns are never copied) that carries the source's entire witness
history forward as data:

- **facts** replay in witness order — source rowid order becomes target
  rowid order — through a deterministic transform;
- **old ticks re-enter as facts** with kind ``tick.<name>`` (the shape
  a child's tick takes when it re-enters the parent vertex, one level
  up: the whole previous incarnation is the child). The old chain
  envelope rides the payload VERBATIM — original payload TEXT, cursors,
  signature — so a signed old tick still verifies against its original
  bytes after the ids around it have migrated;
- a **receipt fact** (kind ``rebirth``) lands LAST: source content hash,
  source file hash, source chain head (``engine.tick_row_hash`` — THE
  chain's row-identity function, not a reimplementation), transform
  rule, counts;
- a **genesis tick** seals everything. The first tick in a new store
  gets ``window_start ""`` (engine.append_tick), so its window covers
  every row above — including the receipt. ``fact_cursor`` points at
  the receipt: the attestation covers its own justification, the same
  property ``sl seal`` has.

Receipt verification is an OPERATION, not a promise: transforms are
deterministic, so :func:`verify_rebirth` re-runs the transform against
the source and diffs the target row by row. The id recipe for migrated
facts is ``ULID(ms(fact.ts) || sha256(old_id)[:10])`` — event-time
sortable, recomputable from the source alone, collision-free for
distinct old ids.

Deliberately NOT here:

- **ref rewriting** — payload refs are entity-keyed (``kind:key``) and
  resolve at read time; raw old ids appear only in prose, and rewriting
  prose would falsify history (observation
  design/rebirth-ref-rewrite-dissolves). The old→new id map needs no
  storage: the transform is deterministic, recompute when needed.
- **interleave** (multi-source rebirth) — merge-shaped, different
  arity; compose with merge_store when the need is live.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from ulid import ULID

from ._conn import _create, _open

_CROCKFORD = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

_TICK_BASE_COLS = ("id", "name", "ts", "since", "origin", "payload")
_TICK_CHAIN_COLS = ("prev_hash", "window_start", "fact_cursor", "window_hash",
                    "signature")


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactRow:
    """One source fact row. ``payload`` is the stored JSON TEXT, verbatim.

    ``signature`` is the fact's authorship signature (delta 3), carried
    verbatim through rebirth — it commits to content only (no id), so an
    id migration preserves its validity. The replay spine drops it to
    None when a transform alters any CONTENT field (kind, ts, observer,
    origin, payload): the original authorship claim no longer holds and
    rebirth must not re-assert it.
    """

    id: str
    kind: str
    ts: float
    observer: str
    origin: str
    payload: str
    signature: str | None = None


@dataclass(frozen=True)
class Transform:
    """A deterministic per-fact mapping.

    ``rule`` is the receipt-citable name — it is recorded in the receipt
    fact and used by verify_rebirth to reconstruct built-in transforms.
    ``map_fact`` returns the (possibly modified) row, or None to drop it.

    Determinism is load-bearing: re-running the transform over the same
    source must reproduce the target byte for byte — that re-run IS the
    receipt verification.
    """

    rule: str
    map_fact: Callable[[FactRow], FactRow | None]


def is_ulid(value: str) -> bool:
    """True when value has ULID shape (26 chars, Crockford base32)."""
    return len(value) == 26 and all(c in _CROCKFORD for c in value)


def deterministic_ulid(ts: float, seed: str) -> str:
    """Build a ULID from an event timestamp and a deterministic seed.

    48-bit millisecond timestamp from ``ts``, 80-bit entropy from
    ``sha256(seed)``. Same inputs, same ULID — this is what makes
    rebirth re-runnable and therefore verifiable.
    """
    ms = int(ts * 1000)
    entropy = hashlib.sha256(seed.encode()).digest()[:10]
    return str(ULID.from_bytes(ms.to_bytes(6, "big") + entropy))


def identity() -> Transform:
    """Pass every fact through unchanged (cleanup/re-seal rebirth)."""
    return Transform(rule="identity", map_fact=lambda row: row)


def ulid_migration() -> Transform:
    """Migrate non-canonical ids to deterministic ULIDs; canonical ids pass.

    Canonical = uppercase Crockford ULID, the only form whose
    lexicographic order matches event time. One uniform rule covers
    every broken era — live stores turned out to have THREE:

    - uuid4 era (2026-03-15..05-16): hex ids sort above every ULID;
    - lowercase-ULID era (sqlite-ulid C extension): time-correct values,
      but lowercase sorts above uppercase in ASCII, so the whole era
      sorts out of order against canonical ids;
    - canonical ULIDs (python-ulid): pass through untouched — merge
      dedup and external citations key on them.

    Migrated id: ``ULID(ms(fact.ts) || sha256(old_id)[:10])`` —
    event-time sortable, so ORDER BY id finally approximates event
    order across the whole store.
    """

    def map_fact(row: FactRow) -> FactRow:
        if is_ulid(row.id):
            return row
        return replace(row, id=deterministic_ulid(row.ts, row.id))

    return Transform(rule="ulid-migration", map_fact=map_fact)


def filtered(predicate: Callable[[FactRow], bool], *, rule: str) -> Transform:
    """Keep facts matching predicate (review-pass rebirth).

    ``rule`` must describe the predicate (e.g. ``"filter:kind!=scratch"``)
    — verify_rebirth cannot reconstruct an arbitrary predicate from the
    receipt, so re-verification requires passing the same Transform.
    """
    return Transform(
        rule=rule,
        map_fact=lambda row: row if predicate(row) else None,
    )


_BUILTIN_RULES: dict[str, Callable[[], Transform]] = {
    "identity": identity,
    "ulid-migration": ulid_migration,
}


# ---------------------------------------------------------------------------
# Source identity — the claims the receipt makes
# ---------------------------------------------------------------------------

def _tick_columns(conn: sqlite3.Connection) -> list[str]:
    """Tick columns present in this store, canonical order, era-aware."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
    return [c for c in (*_TICK_BASE_COLS, *_TICK_CHAIN_COLS) if c in have]


def _facts_have_signature(conn: sqlite3.Connection) -> bool:
    """Whether this store's facts table carries the delta-3 signature column."""
    return "signature" in {
        r[1] for r in conn.execute("PRAGMA table_info(facts)")
    }


def _content_sha256(conn: sqlite3.Connection) -> str:
    """Witness-order content hash: every fact row, then every tick row.

    This is the VERIFIABLE identity of a store's contents. The file
    hash is not — WAL checkpoints, VACUUM, and page layout change bytes
    without changing content, so a later re-hash of an untouched store
    could false-alarm. Two claims, two fields (see receipt payload).
    """
    h = hashlib.sha256()
    sig_col = _facts_have_signature(conn)
    for row in conn.execute(
        "SELECT id, kind, ts, observer, origin, payload"
        + (", signature" if sig_col else "")
        + " FROM facts ORDER BY rowid"
    ):
        # Era-aware: the signature joins the row hash only when non-NULL,
        # so a store's content hash is stable across the column's arrival
        # (same posture as engine's fact row hash).
        if sig_col and row[6] is None:
            row = row[:6]
        h.update(json.dumps(list(row), separators=(",", ":")).encode())
    cols = _tick_columns(conn)
    for row in conn.execute(
        f"SELECT {', '.join(cols)} FROM ticks ORDER BY rowid"
    ):
        h.update(json.dumps(list(row), separators=(",", ":")).encode())
    return h.hexdigest()


def _chain_head(conn: sqlite3.Connection) -> str | None:
    """Row-identity hash of the source's newest tick (None if no ticks).

    Uses engine.tick_row_hash — the same function verify_chain walks
    with — over the row padded to full chain width (missing era columns
    hash as NULL, exactly as engine sees them).
    """
    from engine import tick_row_hash

    cols = _tick_columns(conn)
    row = conn.execute(
        f"SELECT {', '.join(cols)} FROM ticks ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    d = dict(zip(cols, row, strict=True))
    padded = tuple(d.get(c) for c in (*_TICK_BASE_COLS, *_TICK_CHAIN_COLS))
    return tick_row_hash(padded)


# ---------------------------------------------------------------------------
# Tick re-entry
# ---------------------------------------------------------------------------

def _tick_fact_row(d: dict, source_name: str) -> FactRow:
    """Convert one source tick row into a fact for the new store.

    The envelope is preserved VERBATIM — payload as stored TEXT, cursors
    as old ids, signature untouched — because a signed tick's signature
    only verifies against its original bytes. Dereferencing old cursor
    ids after a migration is a read-path concern; the deterministic
    transform makes old→new recomputable without storing a map.
    """
    payload = {
        "tick_id": d["id"],
        "name": d["name"],
        "since": d.get("since"),
        "payload": d["payload"],
        "prev_hash": d.get("prev_hash"),
        "window_start": d.get("window_start"),
        "fact_cursor": d.get("fact_cursor"),
        "window_hash": d.get("window_hash"),
        "signature": d.get("signature"),
    }
    return FactRow(
        id=deterministic_ulid(d["ts"], "tick:" + d["id"]),
        kind=f"tick.{d['name']}",
        ts=d["ts"],
        observer=source_name,
        origin=d.get("origin", ""),
        payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def _expected_rows(
    src: sqlite3.Connection, transform: Transform, source_name: str
) -> tuple[list[FactRow], int, int, int]:
    """Run the transform over the source. Returns (rows, facts_in,
    filtered, ids_migrated) — rows include tick re-entry facts, in the
    exact order rebirth writes them. This is the shared spine of
    rebirth_store and verify_rebirth: same function, write then check.
    """
    rows: list[FactRow] = []
    facts_in = dropped = migrated = 0
    sig_col = _facts_have_signature(src)
    for raw in src.execute(
        "SELECT id, kind, ts, observer, origin, payload"
        + (", signature" if sig_col else "")
        + " FROM facts ORDER BY rowid"
    ):
        facts_in += 1
        row = FactRow(*raw) if sig_col else FactRow(*raw, signature=None)
        mapped = transform.map_fact(row)
        if mapped is None:
            dropped += 1
            continue
        if mapped.id != row.id:
            migrated += 1
        if mapped.signature is not None and (
            (mapped.kind, mapped.ts, mapped.observer,
             mapped.origin, mapped.payload)
            != (row.kind, row.ts, row.observer, row.origin, row.payload)
        ):
            # Content changed: the authorship signature no longer matches
            # its commitment. Drop rather than carry a stale claim —
            # rebirth cannot re-sign on another observer's behalf.
            mapped = replace(mapped, signature=None)
        rows.append(mapped)
    cols = _tick_columns(src)
    for raw in src.execute(
        f"SELECT {', '.join(cols)} FROM ticks ORDER BY rowid"
    ):
        rows.append(_tick_fact_row(dict(zip(cols, raw, strict=True)), source_name))
    return rows, facts_in, dropped, migrated


# ---------------------------------------------------------------------------
# Rebirth
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RebirthResult:
    """Counts and identities from a rebirth operation."""

    facts_in: int
    facts_out: int
    filtered: int
    ids_migrated: int
    ticks_in: int
    tick_facts: int
    receipt_id: str
    tick_signed: bool
    size_bytes: int


def rebirth_store(
    source: Path,
    target: Path,
    *,
    transform: Transform | None = None,
    tick_signer: Callable[[str], str] | None = None,
    observer: str = "rebirth",
    source_name: str | None = None,
) -> RebirthResult:
    """Replay source through a transform into a new store, with receipt.

    Args:
        source: Existing store database. Never modified.
        target: Path for the reborn store. Must not exist.
        transform: Deterministic per-fact mapping (default: identity).
        tick_signer: Optional signing callable injected into the genesis
            tick (same posture as engine.SqliteStore — injected, never
            imported). None = unsigned genesis (honest NULL).
        observer: Who performed the rebirth — observer on the receipt
            fact, origin on the genesis tick.
        source_name: Name of the source incarnation (default: source
            file stem). Becomes the observer on tick re-entry facts.

    Returns:
        RebirthResult with counts, receipt id, and target size.

    Raises:
        FileNotFoundError: If source does not exist.
        FileExistsError: If target already exists.
    """
    source = Path(source)
    target = Path(target)
    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")
    transform = transform if transform is not None else identity()
    name = source_name or source.stem

    src = _open(source, read_only=True)
    try:
        # Source identity, captured before anything else: the verifiable
        # claim (content hash), the forensic claim (file bytes at this
        # moment), and the chain head the new store descends from.
        file_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        content_sha = _content_sha256(src)
        chain_head = _chain_head(src)
        rows, facts_in, dropped, migrated = _expected_rows(
            src, transform, name
        )
        ticks_in = src.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
    finally:
        src.close()

    tick_facts = ticks_in  # every source tick re-enters
    facts_out = len(rows) - tick_facts

    now = datetime.now(UTC)
    receipt_id = _gen_id()
    receipt_payload = {
        "message": (
            f"rebirth of {name}: rule={transform.rule}, "
            f"{facts_in} facts in, {facts_out} out "
            f"({migrated} ids migrated, {dropped} filtered), "
            f"{ticks_in} ticks re-entered as facts"
        ),
        "rule": transform.rule,
        "source_path": str(source),
        "source_file_sha256": file_sha,
        "source_content_sha256": content_sha,
        "source_chain_head": chain_head,
        "source_facts": facts_in,
        "source_ticks": ticks_in,
        "facts_out": facts_out,
        "ids_migrated": migrated,
        "filtered": dropped,
        "tick_facts": tick_facts,
    }

    dst = _create(target)
    try:
        # Fact signatures ride VERBATIM (never re-signed — see FactRow);
        # the spine already dropped any signature whose content changed.
        dst.executemany(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r.id, r.kind, r.ts, r.observer, r.origin, r.payload, r.signature)
             for r in rows],
        )
        dst.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (receipt_id, "rebirth", now.timestamp(), observer, "rebirth",
             json.dumps(receipt_payload, sort_keys=True,
                        separators=(",", ":"))),
        )
        dst.commit()
    finally:
        dst.close()

    # Genesis tick through engine.SqliteStore — the chain logic stays
    # single-sourced. prev_row None → window_start "" covers every fact
    # above, fact_cursor lands on the receipt: seal semantics.
    from engine import SqliteStore, Tick

    estore = SqliteStore(
        path=target,
        serialize=lambda d: d,        # append() is never called here
        deserialize=lambda d: d,
        tick_signer=tick_signer,
    )
    try:
        # Named exemption from the tick-signing floor (decision design/tick
        # -signing-era-is-a-floor): rebirth reconstructs a FRESH lineage whose
        # genesis tick may legitimately start unsigned (keyless rebirth) — it is
        # not a regression within an existing signed chain. The genesis tick's
        # signed-ness is governed by the injected tick_signer above, separately
        # (see thread:rebirth-keyless-attestation-drop).
        estore.append_tick(Tick(
            name="rebirth",
            ts=now,
            origin=observer,
            payload={
                "rule": transform.rule,
                "source": name,
                "receipt": receipt_id,
                "facts": facts_out + tick_facts + 1,
            },
        ), enforce_floor=False)
    finally:
        estore.close()

    return RebirthResult(
        facts_in=facts_in,
        facts_out=facts_out,
        filtered=dropped,
        ids_migrated=migrated,
        ticks_in=ticks_in,
        tick_facts=tick_facts,
        receipt_id=receipt_id,
        tick_signed=tick_signer is not None,
        size_bytes=target.stat().st_size,
    )


def _gen_id() -> str:
    from engine import gen_id

    return gen_id()


# ---------------------------------------------------------------------------
# Verification — re-run the transform, diff
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RebirthVerification:
    """Outcome of re-running a rebirth and diffing the target.

    ``ok`` requires every claim to hold: receipt present and counted
    correctly, every replayed row byte-identical to the re-run, source
    content unchanged since the rebirth, and the target chain clean.
    The individual fields name which claim failed.
    """

    ok: bool
    facts_checked: int
    mismatches: tuple[str, ...]
    receipt_found: bool
    counts_match: bool
    source_content_match: bool
    chain_ok: bool


def verify_rebirth(
    source: Path,
    target: Path,
    *,
    transform: Transform | None = None,
    verifier: Callable[[str, str], bool] | None = None,
    max_mismatches: int = 10,
) -> RebirthVerification:
    """Verify a rebirth receipt by re-running its transform and diffing.

    Args:
        source: The source store the rebirth claims descent from.
        target: The reborn store carrying the receipt.
        transform: The transform used at rebirth. Built-in rules
            (identity, ulid-migration) are reconstructed from the
            receipt automatically; filter transforms must be passed
            explicitly (a predicate is not serializable).
        verifier: Optional signature verifier forwarded to the target's
            chain verification.
        max_mismatches: Cap on reported row diffs.

    Raises:
        ValueError: If no transform is given and the receipt's rule is
            not a reconstructable built-in.
    """
    source = Path(source)
    target = Path(target)
    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")
    if not target.exists():
        raise FileNotFoundError(f"Target store not found: {target}")

    mismatches: list[str] = []

    tgt = _open(target, read_only=True)
    try:
        receipt_row = tgt.execute(
            "SELECT id, kind, payload FROM facts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        receipt_found = False
        receipt: dict = {}
        if receipt_row is not None and receipt_row[1] == "rebirth":
            receipt_found = True
            receipt = json.loads(receipt_row[2])

        if transform is None:
            rule = receipt.get("rule", "")
            factory = _BUILTIN_RULES.get(rule)
            if factory is None:
                raise ValueError(
                    f"Cannot reconstruct transform for rule {rule!r} — "
                    "pass the original Transform explicitly"
                )
            transform = factory()

        tgt_sig = _facts_have_signature(tgt)
        fetched = tgt.execute(
            "SELECT id, kind, ts, observer, origin, payload"
            + (", signature" if tgt_sig else "")
            + " FROM facts ORDER BY rowid"
        ).fetchall()
        actual_rows: list[tuple] = (
            fetched if tgt_sig else [(*r, None) for r in fetched]
        )
        if receipt_found:
            actual_rows = actual_rows[:-1]  # receipt is checked separately
    finally:
        tgt.close()

    src = _open(source, read_only=True)
    try:
        content_sha = _content_sha256(src)
        # Tick re-entry facts carry the source name as observer; recover
        # it from the target rather than guessing from the path.
        name = source.stem
        for row in actual_rows:
            if row[1].startswith("tick."):
                name = row[3]
                break
        expected, facts_in, dropped, migrated = _expected_rows(
            src, transform, name
        )
    finally:
        src.close()

    if len(expected) != len(actual_rows):
        mismatches.append(
            f"row count: re-run produced {len(expected)}, "
            f"target has {len(actual_rows)} (excluding receipt)"
        )
    for i, (exp, act) in enumerate(zip(expected, actual_rows, strict=False)):
        if len(mismatches) >= max_mismatches:
            break
        exp_tuple = (exp.id, exp.kind, exp.ts, exp.observer, exp.origin,
                     exp.payload, exp.signature)
        if exp_tuple != tuple(act):
            fields = ("id", "kind", "ts", "observer", "origin", "payload",
                      "signature")
            diffs = [
                f"{f}: expected {e!r}, got {a!r}"
                for f, e, a in zip(fields, exp_tuple, act, strict=True)
                if e != a
            ]
            mismatches.append(f"row {i + 1}: " + "; ".join(diffs))

    counts_match = receipt_found and all((
        receipt.get("source_facts") == facts_in,
        receipt.get("facts_out") == facts_in - dropped,
        receipt.get("filtered") == dropped,
        receipt.get("ids_migrated") == migrated,
    ))
    source_content_match = (
        receipt.get("source_content_sha256") == content_sha
    )

    from engine import SqliteStore

    estore = SqliteStore(
        path=target,
        serialize=lambda d: d,
        deserialize=lambda d: d,
    )
    try:
        chain_report = estore.verify_chain(verifier=verifier)
    finally:
        estore.close()
    chain_ok = bool(chain_report["ok"])

    return RebirthVerification(
        ok=(receipt_found and not mismatches and counts_match
            and source_content_match and chain_ok),
        facts_checked=len(actual_rows),
        mismatches=tuple(mismatches),
        receipt_found=receipt_found,
        counts_match=counts_match,
        source_content_match=source_content_match,
        chain_ok=chain_ok,
    )
