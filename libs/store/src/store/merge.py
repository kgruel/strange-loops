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

# The admission half of the arrival arm lives in `engine.admission` as of
# slice 2 (design:arrival-break-slice2-backend-contract §C.3): the decision
# about what a foreign row is allowed to become is backend-neutral policy,
# and `engine` may not import `store`, so the refusals it raises live there
# too. Re-exported here because `store.MergeDivergence` is this lib's public
# name for the refusal and callers keep catching it by that name.
from engine.admission import AdmissionUnverified, MergeDivergence, SourceRows

from ._conn import _open

if TYPE_CHECKING:
    from engine.arrival import ArrivalLog, Verify
    from engine.arrival_contract import Head

__all__ = ["AdmissionUnverified", "MergeDivergence", "MergeResult", "merge_store"]


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
            ``engine.admission._verify_admitted_rows`` checks the ADMITTED rows'
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
    """Read both sides, hand them to admission, report the counts.

    What stays here is what admission is not allowed to know: how to read a
    source (:func:`_read_source`), how to read the target's INDEX and how to
    rebuild it (:func:`_target_state`, :func:`_rederive_after_append`). Both
    of those are the projection half's obligation, and ``engine`` cannot
    import this lib to reach them — so they cross as the two callbacks
    :func:`engine.admission.admit_records` documents, re-invoked per attempt.

    In order, with the steps admission owns named where they land:

    1. **Bring the index current first**, by opening the target through
       ``open_canonical_store`` so catch-up runs. If catch-up refuses, the
       merge refuses — merging into an index that does not account for its
       log would dedup against a lie. That is inside ``target_state`` below,
       so it re-runs on every attempt.
    2. Read the source in its own deterministic order (ordinal for an arrival
       source, ``rowid`` for a sqlite/jsonl one).
    3. Dedup, verify the admission set, append under one lock acquisition
       pinned to the head the dedup snapshot accounts for, retry on refusal
       — all of it ``admit_records``.
    4. Re-derive both projections: the index by consume-forward catch-up
       (the appended records are a suffix, so this appends rows and never
       clears), the derived log by regeneration. That is ``rederive``, which
       admission calls once an append lands.

    ``dry_run`` reports the counts and appends nothing — the log never
    rewrites, so a rollback is neither available nor needed, which is cleaner
    than the savepoint the sqlite arm needs. It verifies too: a dry run
    answers "what would this merge do", and reporting clean counts for a
    merge that would refuse is a lie.
    """
    from engine.admission import admit_records
    from engine.arrival import ArrivalLog

    log = ArrivalLog(canonical)
    if not log.exists() or log.size() == 0:
        raise FileNotFoundError(
            f"{canonical} holds no arrival genesis — an unminted log is not a "
            "merge target; mint it (movement 1) before receiving records"
        )

    def target_state() -> tuple[dict[str, tuple], Head | None]:
        held, consumed = _target_state(canonical)
        return held, _pinned_head(log, consumed)

    counts = admit_records(
        log,
        _read_source(source),
        target_state=target_state,
        rederive=lambda: _rederive_after_append(canonical),
        dry_run=dry_run,
        verify=verify,
    )
    return MergeResult(
        facts_added=counts.facts_added,
        facts_skipped=counts.facts_skipped,
        ticks_added=counts.ticks_added,
        ticks_skipped=counts.ticks_skipped,
    )


def _pinned_head(log: ArrivalLog, consumed) -> Head | None:
    """The full head the dedup snapshot accounts for, or None when unmarked.

    The compare-and-swap pins all three head fields, and the index's resume
    mark carries only a coordinate and a seek hint — so the record the mark
    names is read back through ``anchor`` (a seek, not a walk) to supply the
    record hash. What that buys over the ordinal-only pin this replaced: a
    target truncated and rewritten to the same height passes an ordinal
    compare and fails this one, so a stale dedup can no longer decide what to
    append onto a rolled-back log.

    A mark the log will not vouch for REFUSES rather than falling back to an
    unpinned append — completing a pin by dropping it is the weakening the
    full-head compare exists to prevent. ``None`` in, ``None`` out stays
    legal: an index with no mark has nothing to be stale about.
    """
    from engine.arrival_contract import Head

    if consumed is None:
        return None
    anchor = log.anchor(consumed)
    if anchor is None:
        raise RuntimeError(
            f"the merge target's index reconciled against arrival ordinal "
            f"{consumed.arrival_ordinal} of lineage "
            f"{consumed.arrival_lineage}, but {log.path} does not vouch for a "
            "record there — the index and the log disagree, and a merge "
            "cannot pin an append onto that disagreement"
        )
    return Head(
        lineage=anchor["lin"], ordinal=anchor["ord"], record_hash=anchor["rh"]
    )


def _target_state(canonical: Path):
    """The target's held rows as ``id -> comparable body``, and the resume
    mark naming the log prefix it accounts for. Opening runs catch-up, so a
    target that cannot account for its own log refuses HERE rather than being
    deduped against.

    The mark rather than its bare ordinal, because the compare-and-swap pin
    is the full head now and completing it needs the mark's offset — see
    :func:`_pinned_head`.

    The comparable is what dedup compares an incoming row against (see
    ``engine.admission._comparable``): facts on their full authored body,
    ticks on the chainless base — chain columns and the tick signature are
    store-local custody the merge strips anyway, so they can never be grounds
    for a divergence claim."""
    from engine.arrival import ResumeMark
    from engine.arrival_store import (
        ARRIVAL_LINEAGE_KEY,
        ARRIVAL_OFFSET_KEY,
        ARRIVAL_ORDINAL_KEY,
    )
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
        # All three mark fields or nothing — a partial mark is not a
        # position, and ``anchor`` re-validates whatever this returns at the
        # site that trusts it.
        marks = {
            key: conn.execute(
                "SELECT value FROM store_meta WHERE key = ?", (key,)
            ).fetchone()
            for key in (
                ARRIVAL_LINEAGE_KEY, ARRIVAL_OFFSET_KEY, ARRIVAL_ORDINAL_KEY
            )
        }
    finally:
        conn.close()
    if any(row is None for row in marks.values()):
        return held, None
    return held, ResumeMark(
        arrival_lineage=marks[ARRIVAL_LINEAGE_KEY][0],
        arrival_offset=int(marks[ARRIVAL_OFFSET_KEY][0]),
        arrival_ordinal=int(marks[ARRIVAL_ORDINAL_KEY][0]),
    )


def _read_source(source: Path) -> SourceRows:
    from engine.probe import probe_target

    info = probe_target(source)
    if (
        info.canonical_mode == "arrival"
        and info.canonical_path is not None
        and info.canonical_path.is_file()
    ):
        return _read_arrival_source(info.canonical_path)
    return _read_index_source(source)


def _read_arrival_source(canonical: Path) -> SourceRows:
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
    return SourceRows(
        groups=groups, fact_count=facts, tick_count=ticks, canonical=canonical
    )


def _read_index_source(source: Path) -> SourceRows:
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
    # immediately: admission's draft constructor strips the chain off every
    # tick it sees.
    groups.extend(("tick", [("tick", tuple(row))], None) for row in tick_rows)
    return SourceRows(
        groups=groups, fact_count=len(fact_rows), tick_count=len(tick_rows)
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
