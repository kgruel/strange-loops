"""Merge stores with id-PK deduplication, dispatching on the target's custody.

Three arms, chosen by what the TARGET's canonical artifact is
(:func:`engine.probe.probe_target` — the ratified home for existence-based
disambiguation, because under three modes a bare ``.db`` cannot answer its
own mode from its path):

===========  ================================================================
``sqlite``   Unchanged, byte-identical to the pre-arrival ceremony: ATTACH +
             ``INSERT OR IGNORE``. Every change in this cut is conditional on
             the declared locator.
``arrival``  The arrival log is the store, so a merge APPENDS INTO IT and
             then re-derives the projections. Nothing here ever INSERTs into
             the index.
``jsonl``    REFUSED, naming the export-and-reopen recovery. A merge into a
             log-canonical store succeeds today and then bricks the store at
             its next open; refusing at the site is the same verdict,
             delivered where it is attributable, and it destroys nothing.
===========  ================================================================

The id primary key is the globally unique identity — a fact retains its id
through slice/merge round-trips, so a row whose id the target already holds
appends nothing. Independently-emitted facts (same content, different stores)
get different ids and are correctly NOT deduplicated.

What a merged store claims about order
--------------------------------------
For an arrival target: **the target's arrival ordinal — the order records
arrived at the target — and nothing else.** No claim is made about event
time, about rowids as a primitive, or about the relationship between
``merge(A,B)`` and ``merge(B,A)``. The two merges are different custody
events and the ordinal says so; what survives is determinism per direction
and equality of content.

An arrival source replays in ORDINAL order — merging is replaying the
source's arrival into the target's, and it consumes no event-time input at
all. A sqlite/jsonl source (the transport case, where ``slice_store`` emits a
``.db``) replays facts then ticks in ``rowid`` order: deterministic, and
deliberately not routed through any event-time sort.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._conn import _open

if TYPE_CHECKING:
    from engine.arrival import KeyRegistry, Verify

# How many times the append phase re-reads and retries after another merger
# lands records in the compare-and-swap window. Each retry consumes the
# other process's appends and re-runs dedup, so progress is guaranteed and a
# bound is only a guard against a pathological hot loop.
_APPEND_ATTEMPTS = 8


@dataclass(frozen=True)
class MergeResult:
    """Counts from a merge operation."""

    facts_added: int
    facts_skipped: int
    ticks_added: int
    ticks_skipped: int


def merge_store(
    target: Path,
    source: Path,
    *,
    dry_run: bool = False,
    verify: Verify | None = None,
) -> MergeResult:
    """Merge source facts/ticks into target with deduplication.

    Args:
        target: Path to the target store database (receives new facts).
        source: Path to the source store database (provides facts).
        dry_run: If True, compute counts but write nothing.
        verify: OPT-IN admission verification. Omitted — the default — a
            merge admits foreign rows without checking any signature, which
            is what every merge did before this parameter existed and what
            every merge that does not pass it still does, byte for byte.
            Supplied, it is the injected signature verifier
            (:data:`engine.arrival.Verify`) that
            :func:`_verify_admitted_rows` checks the ADMITTED rows'
            carried authorship claims with. **Exactly what a supplied
            verifier establishes: every admitted signed fact row's
            authorship claim verifies under the SOURCE's own key history.**
            That is source self-consistency and nothing more — it is not a
            statement that the target's operator trusts the source's keys,
            which would require the target's key chain and a key-
            introduction transport this merge does not have. A source with
            no arrival log (a transport ``.db``) carries no key history to
            check against, so it is admitted making NO such claim.

    Returns:
        MergeResult with counts of added and skipped facts/ticks.

    Raises:
        FileNotFoundError: If either store does not exist.
        ValueError: If ``verify`` is supplied for a target whose canonical
            artifact is not an arrival log. The admission set only exists as
            a computable thing on the arrival arm; the sqlite arm decides it
            inside ``INSERT OR IGNORE``. Refusing is the honest answer —
            accepting the verifier and skipping the work would report a
            verification that never ran.
        AdmissionUnverified: If ``verify`` is supplied and either the
            source's key history or an admitted signed row fails to verify.
        The legacy log-canonical store's refusal: if the target's canonical
            artifact is a legacy ``.jsonl`` log. (Named by class at the raise
            site below rather than here — Rule 18 judges a docstring's
            identifiers, and the retired vocabulary earns exactly one excused
            mention in this module, at the line that cannot avoid it.)
    """
    from engine.probe import probe_target

    target = Path(target)
    source = Path(source)

    info = probe_target(target)
    arrival = (
        info.canonical_mode == "arrival"
        and info.canonical_path is not None
        and info.canonical_path.is_file()
    )
    # An arrival target's custody is the log, and the .db beside it is a
    # rebuildable projection that an open builds when absent — so the store
    # exists whenever the log does, even on a fresh clone with no index yet.
    if not arrival and not target.exists():
        raise FileNotFoundError(f"Target store not found: {target}")
    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")

    if arrival:
        assert info.canonical_path is not None
        return _merge_into_arrival(
            info.canonical_path, source, dry_run=dry_run, verify=verify
        )
    if verify is not None:
        raise ValueError(
            f"admission verification was requested for {target}, whose "
            "canonical artifact is not an arrival log. Verification checks "
            "the POST-DEDUP admission set, and only the arrival arm has one "
            "to check: the sqlite arm's admission set is decided inside "
            "INSERT OR IGNORE, and holding that arm byte-identical is a seam "
            "rule of this cut. Merge without the verifier, or merge into an "
            "arrival-canonical target."
        )
    if info.canonical_mode == "jsonl":
        from engine import jsonl_store

        raise jsonl_store.JsonlCanonicalUnsupported(
            f"{target} is the derived index of the canonical log at "
            f"{info.canonical_path} — merging here would INSERT rows the log "
            "cannot account for, and the store would refuse at its next open. "
            "Recovery: migrate it to an arrival log "
            "(engine.arrival_store.ArrivalStore), the canonical-log family "
            "that merge does support. JSONL-canonical is frozen legacy — the "
            "sqlite-to-JSONL export bridge is gone, so there is no supported "
            "way back into this shape."
        )
    return _merge_into_sqlite(target, source, dry_run=dry_run)


# --- the sqlite arm — byte-identical to the pre-arrival ceremony -------------


def _merge_into_sqlite(target: Path, source: Path, *, dry_run: bool) -> MergeResult:
    """ATTACH DATABASE + INSERT OR IGNORE, unchanged.

    Seam rule S3: every change in the arrival wave is conditional on the
    declared locator, so a sqlite-canonical store merges exactly as it did.
    """
    conn = _open(target)
    try:
        from engine.sqlite_store import ensure_coordinate_schema

        ensure_coordinate_schema(conn, mode="mirrored")
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))

        src_facts = conn.execute("SELECT COUNT(*) FROM src.facts").fetchone()[0]
        src_ticks = conn.execute("SELECT COUNT(*) FROM src.ticks").fetchone()[0]

        if dry_run:
            conn.execute("SAVEPOINT merge_dry_run")

        # The fact SIGNATURE travels (design/fact-signature-at-store-column):
        # it is a per-observer authorship claim over content only — unlike
        # the tick chain columns (store-local custody, stripped below).
        # Carried verbatim, never re-signed. Era-aware: a source predating
        # the column merges as NULL (honest pre-signature era).
        src_cols = {r[1] for r in conn.execute("PRAGMA src.table_info(facts)")}
        tgt_cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        if "signature" in src_cols and "signature" not in tgt_cols:
            conn.execute("ALTER TABLE facts ADD COLUMN signature TEXT")
            tgt_cols.add("signature")
        if "signature" in tgt_cols:
            sig_src = "signature" if "signature" in src_cols else "NULL"
            ins_cols, sel_cols = (
                "id, kind, ts, observer, origin, payload, signature",
                f"id, kind, ts, observer, origin, payload, {sig_src}",
            )
        else:  # both pre-delta-3
            ins_cols = sel_cols = "id, kind, ts, observer, origin, payload"
        conn.execute(f"""
            INSERT OR IGNORE INTO facts ({ins_cols}, arrival_ordinal, arrival_seq)
            SELECT {sel_cols}, COALESCE((SELECT MAX(arrival_ordinal) FROM facts), 0) + ROW_NUMBER() OVER (ORDER BY ts, id), 0
            FROM src.facts ORDER BY ts, id
        """)
        facts_added = conn.execute("SELECT changes()").fetchone()[0]

        conn.execute("""
            INSERT OR IGNORE INTO ticks (id, name, ts, since, origin, payload, arrival_ordinal, arrival_seq)
            SELECT id, name, ts, since, origin, payload, COALESCE((SELECT MAX(arrival_ordinal) FROM ticks), 0) + ROW_NUMBER() OVER (ORDER BY ts, id), 0
            FROM src.ticks ORDER BY ts, id
        """)
        ticks_added = conn.execute("SELECT changes()").fetchone()[0]

        if dry_run:
            conn.execute("ROLLBACK TO merge_dry_run")
            conn.execute("RELEASE merge_dry_run")
        else:
            conn.commit()

        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()

    return MergeResult(
        facts_added=facts_added,
        facts_skipped=src_facts - facts_added,
        ticks_added=ticks_added,
        ticks_skipped=src_ticks - ticks_added,
    )


# --- the arrival arm ---------------------------------------------------------


def _merge_into_arrival(
    canonical: Path, source: Path, *, dry_run: bool, verify: Verify | None
) -> MergeResult:
    """Append the source's rows into the target's arrival log, then re-derive.

    In order:

    1. **Bring the index current first**, by opening the target through
       ``open_canonical_store`` so catch-up runs. If catch-up refuses, the
       merge refuses — merging into an index that does not account for its
       log would dedup against a lie.
    2. Read the source in its own deterministic order (ordinal for an arrival
       source, ``rowid`` for a sqlite/jsonl one).
    3. Dedup against what the target's index already holds. **The arrival log
       must never carry one row id twice** — both the index primary key and
       the legacy log indexer refuse such a log, and no verb in this design
       can consume it.
    4. Append the whole phase under ONE lock acquisition, pinned with
       compare-and-swap to the head we deduped against, retrying on refusal.
    5. Re-derive both projections: the index by consume-forward catch-up
       (the appended records are a suffix, so this appends rows and never
       clears), the derived log by regeneration.

    With a ``verify`` supplied, step 3 is followed by admission verification
    (:func:`_verify_admitted_rows`) — INSIDE the retry loop, because a retry
    re-runs dedup and the admission set it produces is the set the claim is
    about. ``dry_run`` verifies too: a dry run answers "what would this merge
    do", and reporting clean counts for a merge that would refuse is a lie.

    ``dry_run`` runs steps 1–3 and reports the counts. It appends nothing —
    the log never rewrites, so a rollback is neither available nor needed,
    which is cleaner than the savepoint the sqlite arm needs.
    """
    from engine.arrival import AppendRejected, ArrivalLog

    log = ArrivalLog(canonical)
    if not log.exists() or log.size() == 0:
        raise FileNotFoundError(
            f"{canonical} holds no arrival genesis — an unminted log is not a "
            "merge target; mint it (movement 1) before receiving records"
        )

    source_rows = _read_source(source)
    registry = _source_registry(source_rows, verify)

    for _ in range(_APPEND_ATTEMPTS):
        held, ordinal = _target_state(canonical)
        entries, added_facts, added_ticks, admitted = _entries_for(source_rows, held)
        skipped_facts = source_rows.fact_count - added_facts
        skipped_ticks = source_rows.tick_count - added_ticks
        result = MergeResult(
            facts_added=added_facts,
            facts_skipped=skipped_facts,
            ticks_added=added_ticks,
            ticks_skipped=skipped_ticks,
        )
        if registry is not None and verify is not None:
            _verify_admitted_rows(admitted, registry, verify)
        if dry_run or not entries:
            return result
        try:
            log.append_marked_many(entries, following=ordinal)
        except AppendRejected:
            # Another merger landed records in the compare-and-swap window,
            # so our dedup is stale. Re-read, re-dedup, retry: the next pass
            # sees their appends and skips whatever they already added. This
            # loop is what makes concurrent merges exactly-once — the lock
            # alone would not, because a second process that deduped against
            # the pre-merge snapshot can append the moment the lock is
            # released.
            continue
        _rederive_after_append(canonical)
        return result

    raise RuntimeError(
        f"the append phase of a merge into {canonical} was outrun "
        f"{_APPEND_ATTEMPTS} times — another writer is appending faster than "
        "this merge can reconcile"
    )


def _target_state(canonical: Path) -> tuple[dict[str, tuple], int | None]:
    """The target's held rows as ``id -> comparable body``, and the log head
    it accounts for. Opening runs catch-up, so a target that cannot account
    for its own log refuses HERE rather than being deduped against.

    The comparable is what dedup compares an incoming row against (see
    :func:`_comparable`): facts on their full authored body, ticks on the
    chainless base — chain columns and the tick signature are store-local
    custody the merge strips anyway, so they can never be grounds for a
    divergence claim."""
    from engine.arrival_store import ARRIVAL_ORDINAL_KEY
    from engine.jsonl_store import open_canonical_store
    from engine.residence import index_path_for

    open_canonical_store(
        canonical, serialize=lambda d: d, deserialize=lambda d: d
    ).close()

    conn = _open(index_path_for(canonical), read_only=True)
    try:
        fact_cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        signature = "signature" if "signature" in fact_cols else "NULL"
        held: dict[str, tuple] = {
            row[0]: ("fact", *row[1:])
            for row in conn.execute(
                "SELECT id, kind, ts, observer, origin, payload, "
                f"{signature} FROM facts"
            )
        }
        held.update(
            (row[0], ("tick", *row[1:]))
            for row in conn.execute(
                "SELECT id, name, ts, since, origin, payload FROM ticks"
            )
        )
        marker = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (ARRIVAL_ORDINAL_KEY,)
        ).fetchone()
    finally:
        conn.close()
    return held, None if marker is None else int(marker[0])


@dataclass(frozen=True)
class _SourceRows:
    """The source's rows, already in the order they will be replayed."""

    groups: list[tuple[str, list[tuple[str, tuple]], int | None]]
    """``(record class, rows, source ordinal)`` — one entry per record that
    will be appended. A ``batch`` group carries the rows of one ceremony, so
    an atomic ceremony stays atomic across the merge. The ordinal is the
    POSITION the row occupied in the source's arrival log, which is what the
    key-validity clause is stated in terms of; ``None`` for a source that
    has no arrival log and therefore no positions."""
    fact_count: int
    tick_count: int
    canonical: Path | None = None
    """The source's arrival log, when it has one. The key history admission
    verification reads is the SOURCE's, so this is where it comes from."""


def _read_source(source: Path) -> _SourceRows:
    from engine.probe import probe_target

    info = probe_target(source)
    if (
        info.canonical_mode == "arrival"
        and info.canonical_path is not None
        and info.canonical_path.is_file()
    ):
        return _read_arrival_source(info.canonical_path)
    return _read_index_source(source)


def _read_arrival_source(canonical: Path) -> _SourceRows:
    """Walk the source's arrival log from ordinal 0, in ORDINAL order.

    NON-NEGOTIABLE. Merging is replaying the source's arrival into the
    target's arrival; it consumes no event-time input at all. Structural
    records expand to no rows and so contribute no group — a lineage's
    genesis and its key introductions belong to that lineage, and carrying
    them across would claim the target's log opened them.
    """
    from engine.arrival import ArrivalLog
    from engine.arrival_projection import rows_of_record

    groups: list[tuple[str, list[tuple[str, tuple]], int | None]] = []
    facts = ticks = 0
    for record in ArrivalLog(canonical).walk():
        rows = rows_of_record(record)
        if not rows:
            continue
        groups.append((record["k"], rows, record["ord"]))
        for t, _row in rows:
            if t == "fact":
                facts += 1
            else:
                ticks += 1
    return _SourceRows(
        groups=groups, fact_count=facts, tick_count=ticks, canonical=canonical
    )


def _read_index_source(source: Path) -> _SourceRows:
    """Facts in ``rowid`` order, then ticks in ``rowid`` order — two passes.

    The transport case: ``slice_store`` emits a plain ``.db``. Deterministic,
    and deliberately NOT routed through any event-time sort. Ticks after
    facts is safe because ticks never feed fold state.
    """
    conn = _open(source, read_only=True)
    try:
        fact_cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        signature = "signature" if "signature" in fact_cols else "NULL"
        fact_order = (
            "arrival_ordinal, arrival_seq"
            if "arrival_ordinal" in fact_cols
            else "rowid"
        )
        fact_rows = conn.execute(
            "SELECT id, kind, ts, observer, origin, payload, "
            f"{signature} FROM facts ORDER BY {fact_order}"
        ).fetchall()
        tick_cols = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
        tick_order = (
            "arrival_ordinal, arrival_seq"
            if "arrival_ordinal" in tick_cols
            else "rowid"
        )
        tick_rows = conn.execute(
            f"SELECT id, name, ts, since, origin, payload FROM ticks ORDER BY {tick_order}"
        ).fetchall()
    finally:
        conn.close()

    # No arrival log, so no positions: every group's ordinal is None, which
    # is the shape the no-claim admission is expressed in.
    groups: list[tuple[str, list[tuple[str, tuple]], int | None]] = [
        ("fact", [("fact", tuple(row))], None) for row in fact_rows
    ]
    # The tick rows ride at BASE arity, chainless — this source shape has no
    # chain to carry, because chain state is store-local and a transport
    # slice never brought it. Padding to full arity here would be undone
    # immediately: _entry_for strips the chain off every tick it sees.
    groups.extend(("tick", [("tick", tuple(row))], None) for row in tick_rows)
    return _SourceRows(
        groups=groups, fact_count=len(fact_rows), tick_count=len(tick_rows)
    )


class MergeDivergence(Exception):
    """The same id carries DIFFERENT content on the two sides of a merge.

    The admission table (decision:design/arrival-substrate-laws) is explicit:
    id collision with different bytes is identity corruption and is REJECTED,
    never resolved silently in either side's favour. Kyle's whole-branch r1
    ruling (CX-BR-01, decision:design/arrival-branch-r1-rulings) applies that
    law to this merge arm. The target-wins conformance vector pins the
    LEGACY SQLITE arm only (its harness populates plain SqliteStores) and
    its description now says so; this arrival arm's refusal is pinned by
    TestDivergenceRefusal.

    Comparison is deliberately strict — the fact signature included, so an
    era-mixed pair (the same authored fact carried once with its signature
    and once through a pre-signature-era slice) also refuses. Decided, not
    accidental: a merge cannot tell that case apart from a stripped
    signature, and the refusal message names the diverging field so the era
    case is diagnosable at the site.
    """


class AdmissionUnverified(Exception):
    """An opt-in admission verification failed. NOTHING was appended.

    Raised for both halves of the one claim, because they are one claim:
    the source's key history did not verify (a registry-forming record —
    genesis or key introduction — whose signature no already-valid key
    verifies), or an admitted signed fact row's carried authorship claim did
    not verify under that history.

    **The scope, exactly.** What the verifier establishes when it does NOT
    raise is that every admitted signed row's authorship claim verifies
    under the source's own key history — source self-consistency. It is NOT
    a claim that the target's operator trusts those keys: that is a
    different question, answered against the TARGET's key chain, and this
    merge carries no key introductions across, so the target has nothing to
    answer it with. It is also not a claim about rows the merge did not
    admit: a deduplicated row is no part of the admission set and is never
    verified, so a bad signature on a record the target already holds cannot
    refuse a merge it is not part of.
    """


def _source_registry(
    source_rows: _SourceRows, verify: Verify | None
) -> KeyRegistry | None:
    """The source's own key history, or ``None`` when there is no claim.

    ``None`` in two cases, which the caller cannot tell apart and does not
    need to: verification was not requested, or the source has no arrival
    log. The second is the ruled D4-Q1 posture — a transport ``.db`` carries
    rows and no key history, so there is nothing to verify them against and
    the merge ADMITS THEM, making no authorship claim at all, rather than
    refusing a source whose only fault is its era.
    """
    if verify is None or source_rows.canonical is None:
        return None

    from engine.arrival import ArrivalLog, AuthorshipUnverified, key_registry

    try:
        return key_registry(ArrivalLog(source_rows.canonical), verify)
    except AuthorshipUnverified as exc:
        raise AdmissionUnverified(
            f"the source's key history does not verify at ordinal "
            f"{exc.ordinal}: {exc.args[0]}. A registry-forming record — the "
            "genesis or a key introduction — is what makes the source's "
            "later authorship claims checkable, so a key history that does "
            "not hold cannot be used to admit anything. Nothing was "
            "appended. Note the scope this merge was asked for: source "
            "self-consistency (every admitted signed row's authorship claim "
            "verifies under the source's own key history), not target-"
            "operator trust in the source's keys."
        ) from exc


def _verify_admitted_rows(
    admitted: list[tuple[int | None, tuple]],
    registry: KeyRegistry,
    verify: Verify,
) -> None:
    """Hold every ADMITTED signed fact row to its carried authorship claim.

    Per row, against :func:`engine.sqlite_store.fact_commitment_hash` — the
    same content-only commitment the live emit path signs, which is what
    makes a fact signature transport-stable in the first place. The key must
    be one the source's log made valid for the ROW's OWN observer at the
    position the row arrived at; a key valid for someone else, or introduced
    only later, is no key at all here.

    Unsigned admitted rows pass without a claim being made about them —
    the same era-aware NULL posture the merge already documents for
    pre-signature sources. Verifying nothing is honest; pretending an absent
    signature is a failed one is not.
    """
    from engine.sqlite_store import FACT_CONTENT_COLUMNS, fact_commitment_hash

    # Derived, not hardcoded (WP-1a F-4 / WP-5 W5-1): positional constants
    # silently rot the next time a content column lands.
    _kind = FACT_CONTENT_COLUMNS.index("kind")
    _ts = FACT_CONTENT_COLUMNS.index("ts")
    _observer = FACT_CONTENT_COLUMNS.index("observer")
    _origin = FACT_CONTENT_COLUMNS.index("origin")
    _payload = FACT_CONTENT_COLUMNS.index("payload")
    _sig = FACT_CONTENT_COLUMNS.index("signature")

    for ordinal, row in admitted:
        signature = row[_sig] if len(row) > _sig else None
        if signature is None:
            continue
        observer = row[_observer]
        digest = fact_commitment_hash(
            row[_kind], row[_ts], observer, row[_origin], row[_payload]
        )
        candidates = (
            () if ordinal is None else registry.keys_valid_at(observer, ordinal)
        )
        if any(verify(key, signature, digest) for key, _introduced in candidates):
            continue
        raise AdmissionUnverified(
            f"fact id {row[0]!r} is admitted by this merge and carries an "
            f"authorship claim for observer {observer!r} that verifies under "
            f"none of the {len(candidates)} key(s) the source's log made "
            f"valid for that observer at its position ({ordinal}). Nothing "
            "was appended. The scope of this check is source "
            "self-consistency — every admitted signed row's authorship claim "
            "verifies under the source's own key history — not target-"
            "operator trust in the source's keys."
        )


def _comparable(t: str, row: tuple) -> tuple:
    """One row's dedup-comparison body, shared by both sides of the merge.

    Facts compare on the full authored 7-column body minus id. Ticks compare
    on the chainless base minus id: chain columns and the tick signature are
    store-local custody stripped by ``_entry_for`` on every merge, so the
    target's chain can never ground a divergence claim against a source
    tick that legitimately carries a different (or no) chain.
    """
    if t == "fact":
        return ("fact", *row[1:7])
    return ("tick", *row[1:6])


_COMPARED_FIELDS = {
    "fact": ("kind", "ts", "observer", "origin", "payload", "signature"),
    "tick": ("name", "ts", "since", "origin", "payload"),
}


def _refuse_divergence(t: str, row: tuple, held_body: tuple) -> None:
    incoming = _comparable(t, row)
    if held_body[0] != incoming[0]:
        diverging = ["row class"]
    else:
        diverging = [
            name
            for name, ours, theirs in zip(
                _COMPARED_FIELDS[t], held_body[1:], incoming[1:], strict=True
            )
            if ours != theirs
        ]
    raise MergeDivergence(
        f"{t} id {row[0]!r} exists on both sides with different content "
        f"(diverging: {', '.join(diverging) or 'row class'}) — at most one "
        "of them is what an arrival log says, and a merge that picked a "
        "side would re-mint identity. Nothing was appended. Resolve the "
        "contradiction at its source before merging."
    )


def _entries_for(source_rows: _SourceRows, held: dict[str, tuple]):
    """The records to append, after dedup.

    Returns ``(entries, facts, ticks, admitted)``, where ``admitted`` is the
    surviving FACT rows paired with the source position they arrived at —
    the admission set, which is exactly what admission verification is a
    claim about, and exactly what a deduplicated row is not in.

    A row whose id the target holds is skipped ONLY when its comparison body
    matches the target's (:func:`_comparable`); the same id over different
    content raises :class:`MergeDivergence` before anything is appended.
    A group whose rows are ALL already in the target contributes no record.
    A batch group that is partly deduped contributes its remainder: two or
    more surviving rows still ride as one batch (the ceremony's atomicity is
    the reason the batch exists), a single survivor rides as a plain fact
    line, because a one-row batch is a second spelling the codec refuses.
    A split batch needs no special handling for verification: the admission
    set is per-ROW, so the remainder is simply the rows that are in it.
    """
    from engine.arrival import Entry

    entries: list[Entry] = []
    admitted: list[tuple[int | None, tuple]] = []
    facts = ticks = 0
    for kind, rows, ordinal in source_rows.groups:
        fresh = []
        for t, row in rows:
            body = held.get(row[0])
            if body is not None:
                if body != _comparable(t, row):
                    _refuse_divergence(t, row, body)
                continue
            fresh.append((t, row))
        if not fresh:
            continue
        for t, row in fresh:
            held[row[0]] = _comparable(t, row)
            if t == "fact":
                facts += 1
                admitted.append((ordinal, row))
            else:
                ticks += 1
        entries.append(_entry_for(kind, fresh))
    return entries, facts, ticks, admitted


def _entry_for(kind: str, rows: list[tuple[str, tuple]]):
    """One record for a group of surviving rows.

    Record shape, asymmetric between facts and ticks, and the asymmetry is
    inherited from the live write path rather than invented here:

    * ``k`` is the row class, never a fact's own kind.
    * ``observer``/``origin``/``at`` mirror the row's own columns, exactly as
      the live path does. A merged fact's record claims its ORIGINAL
      observer — the record describes the authored row, not the operator who
      admitted it. A tick has no observer, so its record carries the tick's
      name there, which is the authorship a tick has.
    * **Fact bodies ride verbatim, the row's own signature included.** The
      fact signature is a per-observer authorship claim over content only,
      carried verbatim and never re-signed; era-aware NULL for a
      pre-signature source.
    * **Tick bodies carry chain columns and the tick signature as
      NULL/absent.** ``prev_hash``/``window_start``/``fact_cursor``/
      ``window_hash`` are store-local custody: carrying them verbatim would
      put ticks in the target whose links reference the SOURCE's chain, so
      the target's chain verification would break on every merged tick. And
      keeping the tick signature while nulling the chain would be a
      verification lie, because the tick signature covers the chain fields.
      The codec accepts all five as nullable — this is the pre-chain era
      shape, honestly claimed.

    There is no record-level signature. ``merge_store`` takes no signer and
    never will: there is no key to sign with, and the target's operator holds
    no key for a foreign observer anyway. The authorship claim that survives
    is the fact row's own signature, riding in the body. An ADMISSION
    attestation — the target custodian's own claim that it admitted this
    record — is a later cut's.

    Not signing is separate from not CHECKING: ``merge_store``'s opt-in
    ``verify`` holds these carried signatures to the source's own key
    history before any of this is assembled (:class:`AdmissionUnverified`).
    Whether they were checked or not, they ride verbatim — verification
    decides whether the merge happens, never what a record says.
    """
    from engine.arrival import Entry
    from engine.jsonl_codec import (
        TICK_CHAIN_FIELDS,
        TICK_FIELDS,
        object_of_batch,
        object_of_fact_row,
        object_of_tick_row,
    )

    if kind == "tick":
        _t, row = rows[0]
        # Nulling the chain is THIS module's decision (see above); how many
        # columns that is, and where they sit, is the codec's — so the width
        # is derived from its field tuples rather than counted here. The
        # slice reads Nones back in, the source arrival row has them
        # overwritten; both land at the codec's tick arity, signature
        # dropped by riding one short of it.
        base = len(TICK_FIELDS) - len(TICK_CHAIN_FIELDS)
        stripped = (*row[:base], *(None,) * len(TICK_CHAIN_FIELDS))
        return Entry(
            k="tick",
            body=object_of_tick_row(stripped),
            observer=stripped[1],
            origin=stripped[4],
            at=stripped[2],
        )

    fact_rows = [row for _t, row in rows]
    first = fact_rows[0]
    k = "batch" if len(fact_rows) > 1 else "fact"
    body = object_of_batch(fact_rows) if k == "batch" else object_of_fact_row(first)
    return Entry(
        k=k, body=body, observer=first[3], origin=first[4], at=first[2]
    )


def _rederive_after_append(canonical: Path) -> None:
    """Bring both projections current after the append phase.

    The index by CONSUME-FORWARD catch-up, not by re-derivation: the records
    just appended are a suffix, so opening the store appends their rows and
    never clears anything. Re-deriving the whole index per merge would be
    O(n) for no reason, and it would renumber nothing but it would still
    drop the search index.

    The derived log by regeneration, because it is byte-sorted and an append
    to a sorted file is not an append. It is written whether or not one was
    there before: an ABSENT projection builds automatically, because
    building it destroys nothing.
    """
    from engine.arrival_projection import write_derived_log
    from engine.jsonl_store import open_canonical_store

    open_canonical_store(
        canonical, serialize=lambda d: d, deserialize=lambda d: d
    ).close()
    write_derived_log(canonical)
