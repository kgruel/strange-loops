"""Declared admission policy, resolved at the engine boundary.

A ``.vertex`` declaration can carry admission policy in two places:

* ``observers { name { grant { potential ... } } }`` — per-observer
  emission constraints (``ObserverDecl.grant.potential``);
* ``strict true`` — vertex-wide refusal of undeclared kinds.

Historically both were parsed and historized but only enforced by
whichever *caller* remembered to build a :class:`~engine.peer.Grant`
by hand — declared policy was silently bypassable by omission. This
module is the enforcement seam: :func:`grant_for_observer` resolves the
declared policy for an observer, and ``VertexProgram.receive_as`` /
``VertexHandle.receive_as`` apply it automatically. Bypassing declared
policy is still possible, but only through an *explicit* entry point
(the raw ``receive``, documented as the bypass) — never by omission.

Strict enforcement lives in :meth:`engine.vertex.Vertex.receive_receipt`
(the engine floor; see decision:design/strict-enforcement-at-engine-receive);
this module supplies its typed rejection, :class:`UndeclaredKind`.

The admission op (slice 2)
--------------------------
Slice 2 of the arrival break grows this module into the backend-neutral half
of the contract's §04 append transaction — step 4, "validate drafts … the
admission decision" — plus the caller-side orchestration that carries a batch
of drafts from a source through dedup, verification, and the compare-and-swap
append. :func:`admit_records` is that op.

What is deliberately NOT here is the fence and the coordinate assignment
(§04 steps 1, 3, 5-8). The fence is backend-specific by definition — ``flock``
for the file backend, a row lock in a database, a consensus step in a service
— so lifting it into a shared module would be lifting the one thing that
cannot be shared. The op reaches the fence through
:meth:`engine.arrival.ArrivalLog.append_marked_many`, and reaches the caller's
own projection through two callbacks it is handed rather than through any
store this lib is not allowed to import.

The fact-domain content commitment (:func:`fact_commitment_hash`, and the
canonical encoding under it) lives here for the same reason: it is the inner
signature that travels through re-custody (decision:design/arrival-wire-v1-pin,
ruling 5), so it belongs beside the policy that checks it rather than in the
module that becomes a projection engine.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import rfc8785

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from lang.ast import VertexFile

    from .arrival import ArrivalLog, KeyRegistry, Verify
    from .arrival_contract import Head, RecordDraft
    from .peer import Grant

# How many times the append phase re-reads and retries after another writer
# lands records in the compare-and-swap window. Each retry consumes the other
# process's appends and re-runs dedup, so progress is guaranteed and a bound
# is only a guard against a pathological hot loop.
APPEND_ATTEMPTS = 8


class AdmissionError(Exception):
    """Base for declared-admission-policy refusals at the engine boundary."""


class UnknownObserver(AdmissionError):
    """The vertex declares observers, and this observer is not one of them.

    Raised by :func:`grant_for_observer` only when an ``observers`` block
    exists — a vertex with no observers block has no declared policy, and
    every observer resolves to unrestricted (``None``).
    """

    def __init__(self, observer: str, vertex: str) -> None:
        super().__init__(
            f"observer {observer!r} is not declared in vertex {vertex!r} — "
            f"declared admission policy admits only declared observers. "
            f"Declare the observer, or use the raw receive entry point to "
            f"bypass declared policy explicitly."
        )
        self.observer = observer
        self.vertex = vertex


class UndeclaredKind(AdmissionError):
    """A strict vertex refused a fact whose kind is not declared.

    Raised by ``Vertex.receive_receipt`` *before* storage when the resolved
    declaration says ``strict`` — nothing is appended. Bypass is the
    explicit ``admit_undeclared=True`` parameter, never an omission.
    """

    def __init__(self, kind: str, vertex: str) -> None:
        super().__init__(
            f"vertex {vertex!r} declares strict — kind {kind!r} is not "
            f"declared, fact refused before storage. Declare the kind in "
            f"the vertex file, or pass admit_undeclared=True to bypass "
            f"strict admission explicitly."
        )
        self.kind = kind
        self.vertex = vertex


class AggregateAdmissionUnsupported(AdmissionError):
    """Admission policy cannot be resolved against an aggregate vertex.

    Combine/discover aggregates are read-path compositions over member
    stores; writes target a member directly, and each member's own
    declaration is the admission authority. Resolving a grant against the
    aggregate would invent a policy no member declared.
    """

    def __init__(self, vertex: str) -> None:
        super().__init__(
            f"vertex {vertex!r} is a combine/discover aggregate — admission "
            f"policy resolves against a member declaration, not the "
            f"aggregate. Write to the member vertex directly."
        )
        self.vertex = vertex


def grant_for_observer(ast: "VertexFile", observer: str) -> "Grant | None":
    """Resolve the declared admission policy for ``observer`` to a Grant.

    The five contract cases (LIBS_CHANGES P1, observer admission):

    * **aggregate vertex** (``combine``/``discover`` set) — raises
      :class:`AggregateAdmissionUnsupported`; members own admission.
    * **no observers block** — returns ``None``: the declaration carries
      no observer policy, admission is unrestricted.
    * **unknown observer** (observers declared, this one absent) — raises
      :class:`UnknownObserver`: a declared-policy vertex admits only
      declared observers.
    * **declared observer without a grant** — returns ``None``: declared,
      unconstrained (same admission as no-policy, reached deliberately).
    * **declared observer with a potential set** — returns a
      :class:`~engine.peer.Grant` carrying that ``potential`` frozenset.

    Returns:
        ``Grant | None`` suitable for ``Vertex.receive(fact, grant)``.
    """
    if ast.combine is not None or ast.discover is not None:
        raise AggregateAdmissionUnsupported(ast.name)

    if not ast.observers:
        return None

    for decl in ast.observers:
        if decl.name == observer:
            if decl.grant is None:
                return None
            from .peer import Grant

            return Grant(potential=frozenset(decl.grant.potential))

    raise UnknownObserver(observer, ast.name)


# ---------------------------------------------------------------------------
# The fact-domain content commitment
# ---------------------------------------------------------------------------


def _canonical_bytes(obj: object) -> bytes:
    """Canonical encoding for commitment hashing: JCS, RFC 8785.

    The fact domain's canonical encoding, and the surviving spelling of it
    (decision design/attestation-canonicalization-jcs, 2026-06-12). The
    upgrade off an implementation-local ``json.dumps`` was forced by the Go
    conformance oracle — the federation-facing consumer — because
    cross-implementation hash divergence renders as a false tamper alarm.

    Stored payload TEXT is embedded verbatim as a string value, so hashes
    detect byte-level tampering without re-serialization concerns leaking in
    from payload content.

    Chains predating the swap were migrated at it rather than grandfathered
    (SPEC §8.1). The legacy migration op that did that is ``SqliteStore``'s
    and stays named there: this module sits on the arrival surface, and the
    retired vocabulary does not follow a function across (Rule 18).
    """
    return rfc8785.dumps(obj)


def fact_commitment_hash(
    kind: str, ts: float, observer: str, origin: str, payload_text: str
) -> str:
    """Hash the fact's CONTENT commitment — what the fact signer signs.

    Content-only by design (design/fact-signature-at-store-column): excludes
    id and arrival coordinates, which are custody context, not authored
    content. This is what makes the signature transport-stable — any store
    holding the row can re-derive the commitment and verify authorship
    against the observer registry without trusting the sender. Stored payload
    TEXT is embedded verbatim (same posture as the tick envelope: byte-level
    tamper detection, no re-serialization). Never includes the signature (a
    signature cannot sign itself).

    A cross-lib contract: the transport paths in ``libs/store`` and any
    receive-side verifier must hash the same envelope the signer signed, so
    this is one function with one definition. ``engine.sqlite_store`` binds it
    under both its historical names for the mint paths that still call it.
    """
    envelope = {
        "kind": kind, "ts": ts, "observer": observer,
        "origin": origin, "payload": payload_text,
    }
    return hashlib.sha256(_canonical_bytes(envelope)).hexdigest()


# ---------------------------------------------------------------------------
# Admission refusals
# ---------------------------------------------------------------------------


class MergeDivergence(Exception):
    """The same id carries DIFFERENT content on the two sides of an admission.

    The admission table (decision:design/arrival-substrate-laws) is explicit:
    id collision with different bytes is identity corruption and is REJECTED,
    never resolved silently in either side's favour. Kyle's whole-branch r1
    ruling (CX-BR-01, decision:design/arrival-branch-r1-rulings) applies that
    law to the arrival arm. The target-wins conformance vector pins the
    LEGACY SQLITE arm only (its harness populates plain SqliteStores) and
    its description now says so; the arrival arm's refusal is pinned by
    TestDivergenceRefusal.

    Comparison is deliberately strict — the fact signature included, so an
    era-mixed pair (the same authored fact carried once with its signature
    and once through a pre-signature-era slice) also refuses. Decided, not
    accidental: admission cannot tell that case apart from a stripped
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
    different question, answered against the TARGET's key chain, and this op
    carries no key introductions across, so the target has nothing to
    answer it with. It is also not a claim about rows that were not
    admitted: a deduplicated row is no part of the admission set and is never
    verified, so a bad signature on a record the target already holds cannot
    refuse an admission it is not part of.
    """


# ---------------------------------------------------------------------------
# What arrives, and what admitting it reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRows:
    """The source's rows, already in the order they will be replayed.

    Built by the caller — reading a source is the caller's business, and the
    two shapes it reads (an arrival log in ordinal order, a transport index in
    ``rowid`` order) are the caller's to tell apart. What crosses into
    admission is only the result.
    """

    groups: list[tuple[str, list[tuple[str, tuple]], int | None]]
    """``(record class, rows, source ordinal)`` — one entry per record that
    will be appended. A ``batch`` group carries the rows of one ceremony, so
    an atomic ceremony stays atomic across the admission. The ordinal is the
    POSITION the row occupied in the source's arrival log, which is what the
    key-validity clause is stated in terms of; ``None`` for a source that
    has no arrival log and therefore no positions."""
    fact_count: int
    tick_count: int
    canonical: Path | None = None
    """The source's arrival log, when it has one. The key history admission
    verification reads is the SOURCE's, so this is where it comes from."""


@dataclass(frozen=True)
class AdmissionResult:
    """How many of the source's rows were admitted, and how many were held.

    Skipped is dedup, not refusal: a row whose id and content the target
    already holds is no part of the admission set, and saying so in a count
    is the whole report an idempotent replay owes its caller.
    """

    facts_added: int
    facts_skipped: int
    ticks_added: int
    ticks_skipped: int


# ---------------------------------------------------------------------------
# The admission decision (§04 step 4)
# ---------------------------------------------------------------------------


def _comparable(t: str, row: tuple) -> tuple:
    """One row's dedup-comparison body, shared by both sides of the compare.

    Facts compare on the full authored 7-column body minus id. Ticks compare
    on the chainless base minus id: chain columns and the tick signature are
    store-local custody stripped by ``_draft_for`` on every admission, so the
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
        "of them is what an arrival log says, and admitting a side would "
        "re-mint identity. Nothing was appended. Resolve the "
        "contradiction at its source before merging."
    )


def _drafts_for(source: SourceRows, held: dict[str, tuple], custodian: str):
    """The records to append, after dedup.

    ``custodian`` is the TARGET log's genesis observer, threaded through to
    :func:`_draft_for` for the tick envelopes it mints. It is read once per
    attempt at the call site, where the target log is already open, rather
    than re-derived per record.

    Returns ``(drafts, facts, ticks, admitted)``, where ``admitted`` is the
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
    drafts: list[RecordDraft] = []
    admitted: list[tuple[int | None, tuple]] = []
    facts = ticks = 0
    for kind, rows, ordinal in source.groups:
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
        drafts.append(_draft_for(kind, fresh, custodian))
    return drafts, facts, ticks, admitted


def _draft_for(
    kind: str, rows: list[tuple[str, tuple]], custodian: str
) -> RecordDraft:
    """One :class:`~engine.arrival_contract.RecordDraft` for a group of rows.

    A draft and not a coordinated record: the coordinate is the ledger's to
    assign inside the fence (§04 step 5), so what admission produces names
    only what its author owns. The tick-chain nulling below is what makes
    this an admission step rather than a re-encoding — it is where a foreign
    row stops carrying the source's custody.

    Record shape, asymmetric between facts and ticks, and the asymmetry is
    inherited from the live write path rather than invented here:

    * ``kind`` is the row class, never a fact's own kind. Since wire v1
      dropped ``body.t``, it is the only place that class is written.
    * ``origin``/``authored_at`` mirror the row's own columns. ``observer``
      splits by kind, exactly as the live write path splits it
      (:meth:`engine.arrival_store.ArrivalStore._custodian`, ruling 2 of
      decision:design/arrival-wire-v1-seam-triage). An admitted FACT's record
      claims its ORIGINAL observer — the record describes the authored row,
      not the operator who admitted it. An admitted TICK has no author, so its
      record names THIS log's custodian: ``custodian`` is the TARGET's
      genesis observer, not the source's, because the record being minted
      is the target's own. This is the second, independently-encoded tick
      mint site; a respell that landed only at the live path would leave
      admission committing the retired convention with nothing to catch it.
    * **Fact bodies ride verbatim, the row's own signature included.** The
      fact signature is a per-observer authorship claim over content only,
      carried verbatim and never re-signed; era-aware NULL for a
      pre-signature source.
    * **Tick bodies carry chain columns and the tick signature as
      NULL/absent.** ``prev_hash``/``window_start``/``fact_cursor``/
      ``window_hash`` are store-local custody: carrying them verbatim would
      put ticks in the target whose links reference the SOURCE's chain, so
      the target's chain verification would break on every admitted tick. And
      keeping the tick signature while nulling the chain would be a
      verification lie, because the tick signature covers the chain fields.
      The codec accepts all five as nullable — this is the pre-chain era
      shape, honestly claimed.

    ``RecordDraft.signature`` stays ``None``: that field is the RECORD-level
    signature, and admission holds no key to fill it. :func:`admit_records`
    takes no signer and never will — the target's operator holds no key for a
    foreign observer. The authorship claim that survives is the fact row's own
    signature, riding in the body. An ADMISSION attestation — the target
    custodian's own claim that it admitted this record — is a later cut's.

    Not signing is separate from not CHECKING: the op's opt-in ``verify``
    holds these carried signatures to the source's own key history before any
    of this is assembled (:class:`AdmissionUnverified`). Whether they were
    checked or not, they ride verbatim — verification decides whether the
    admission happens, never what a record says.
    """
    from .arrival_body import body_of_batch, body_of_fact_row, body_of_tick_row
    from .arrival_contract import RecordDraft
    from .jsonl_codec import TICK_CHAIN_FIELDS, TICK_FIELDS

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
        return RecordDraft(
            kind="tick",
            body=body_of_tick_row(stripped),
            observer=custodian,
            origin=stripped[4],
            authored_at=stripped[2],
        )

    fact_rows = [row for _t, row in rows]
    first = fact_rows[0]
    k = "batch" if len(fact_rows) > 1 else "fact"
    body = body_of_batch(fact_rows) if k == "batch" else body_of_fact_row(first)
    return RecordDraft(
        kind=k, body=body, observer=first[3], origin=first[4], authored_at=first[2]
    )


# ---------------------------------------------------------------------------
# Opt-in admission verification
# ---------------------------------------------------------------------------


def _source_registry(
    source: SourceRows, verify: Verify | None
) -> KeyRegistry | None:
    """The source's own key history, or ``None`` when there is no claim.

    ``None`` in two cases, which the caller cannot tell apart and does not
    need to: verification was not requested, or the source has no arrival
    log. The second is the ruled D4-Q1 posture — a transport ``.db`` carries
    rows and no key history, so there is nothing to verify them against and
    the op ADMITS THEM, making no authorship claim at all, rather than
    refusing a source whose only fault is its era.
    """
    if verify is None or source.canonical is None:
        return None

    from .arrival import ArrivalLog, AuthorshipUnverified, key_registry

    try:
        return key_registry(ArrivalLog(source.canonical), verify)
    except AuthorshipUnverified as exc:
        raise AdmissionUnverified(
            f"the source's key history does not verify at ordinal "
            f"{exc.ordinal}: {exc.args[0]}. A registry-forming record — the "
            "genesis or a key introduction — is what makes the source's "
            "later authorship claims checkable, so a key history that does "
            "not hold cannot be used to admit anything. Nothing was "
            "appended. Note the scope this admission was asked for: source "
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

    Per row, against :func:`fact_commitment_hash` — the same content-only
    commitment the live emit path signs, which is what makes a fact signature
    transport-stable in the first place. The key must be one the source's log
    made valid for the ROW's OWN observer at the position the row arrived at;
    a key valid for someone else, or introduced only later, is no key at all
    here.

    Unsigned admitted rows pass without a claim being made about them —
    the same era-aware NULL posture the op already documents for
    pre-signature sources. Verifying nothing is honest; pretending an absent
    signature is a failed one is not.
    """
    from .sqlite_store import FACT_COLUMN_INDEX

    # Derived, not hardcoded (WP-1a F-4 / WP-5 W5-1).
    col = FACT_COLUMN_INDEX
    _kind, _ts, _observer, _origin, _payload, _sig = (
        col["kind"], col["ts"], col["observer"], col["origin"],
        col["payload"], col["signature"],
    )

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


# ---------------------------------------------------------------------------
# The op (§04 steps 1-8, caller side)
# ---------------------------------------------------------------------------


def admit_records(
    log: ArrivalLog,
    source: SourceRows,
    *,
    target_state: Callable[[], tuple[dict[str, tuple], Head | None]],
    rederive: Callable[[], None],
    dry_run: bool = False,
    verify: Verify | None = None,
    attempts: int = APPEND_ATTEMPTS,
) -> AdmissionResult:
    """Admit ``source``'s rows into ``log``, then bring the caller current.

    In order:

    1. Read the source's key history ONCE, before the loop — it is a property
       of the source, not of an attempt, and re-forming it per retry would
       re-walk the source's whole log for an answer that cannot have changed.
    2. Per attempt: ask the caller for the state it deduped against — its held
       rows, and the FULL head that snapshot accounts for.
    3. Dedup against those held rows. **The arrival log must never carry one
       row id twice** — both the index primary key and the legacy log indexer
       refuse such a log, and no verb in this design can consume it.
    4. Verify the admission set, when a verifier was supplied. INSIDE the
       loop, because a retry re-runs dedup and the admission set it produces
       is the set the claim is about.
    5. Append the whole phase under ONE lock acquisition, pinned with
       compare-and-swap to the head the caller deduped against, retrying on
       refusal.
    6. Ask the caller to bring its projections current.

    ``target_state`` and ``rederive`` are callbacks and not paths because the
    projection is the CALLER's — reading a sqlite index and rebuilding it is
    the projection half's obligation (§07), and this lib may not import the
    one that owns it. Their contract: ``target_state`` returns the held rows
    as ``id -> comparable body`` (see :func:`_comparable`) together with the
    complete head that snapshot accounts for, or ``None`` when nothing is
    marked; ``rederive`` runs after a successful append and returns nothing.
    Both are re-invoked per attempt, which is what makes a retry make
    progress: it consumes the other writer's appends and skips whatever they
    already added.

    ``dry_run`` runs steps 1-4 and reports the counts. It appends nothing and
    re-derives nothing — the log never rewrites, so a rollback is neither
    available nor needed. It verifies too: a dry run answers "what would this
    do", and reporting clean counts for an admission that would refuse is a
    lie.

    Raises:
        MergeDivergence: An id arrived carrying different content than the
            target holds under it. Nothing was appended.
        AdmissionUnverified: ``verify`` was supplied and either the source's
            key history or an admitted signed row failed to verify. Nothing
            was appended.
        RuntimeError: The append phase was outrun ``attempts`` times.
    """
    from .arrival import AppendRejected

    registry = _source_registry(source, verify)

    for _ in range(attempts):
        held, pin = target_state()
        drafts, added_facts, added_ticks, admitted = _drafts_for(
            source, held, log.genesis()["observer"]
        )
        result = AdmissionResult(
            facts_added=added_facts,
            facts_skipped=source.fact_count - added_facts,
            ticks_added=added_ticks,
            ticks_skipped=source.tick_count - added_ticks,
        )
        if registry is not None and verify is not None:
            _verify_admitted_rows(admitted, registry, verify)
        if dry_run or not drafts:
            return result
        try:
            log.append_marked_many(_entries_of(drafts), following=pin)
        except AppendRejected:
            # Another writer landed records in the compare-and-swap window,
            # so our dedup is stale. Re-read, re-dedup, retry: the next pass
            # sees their appends and skips whatever they already added. This
            # loop is what makes concurrent admissions exactly-once — the lock
            # alone would not, because a second process that deduped against
            # the pre-append snapshot can append the moment the lock is
            # released.
            continue
        rederive()
        return result

    raise RuntimeError(
        f"the append phase of a merge into {log.path} was outrun "
        f"{attempts} times — another writer is appending faster than "
        "this merge can reconcile"
    )


def _entries_of(drafts: Sequence[RecordDraft]) -> list:
    """Drafts in the file log's own append vocabulary.

    The one seam between the contract's :class:`RecordDraft` and
    :class:`engine.arrival.Entry`, which name the same thing — everything a
    record carries except the coordinate the fence assigns. It exists because
    the op still calls ``append_marked_many`` directly rather than an
    :class:`~engine.arrival_contract.ArrivalLedger`; when slice 5 routes this
    through the ledger, the conversion moves behind it and this dies.
    """
    from .arrival import Entry

    return [
        Entry(
            k=draft.kind,
            body=dict(draft.body),
            observer=draft.observer,
            origin=draft.origin,
            at=draft.authored_at,
        )
        for draft in drafts
    ]


__all__ = [
    "APPEND_ATTEMPTS",
    "AdmissionError",
    "AdmissionResult",
    "AdmissionUnverified",
    "AggregateAdmissionUnsupported",
    "MergeDivergence",
    "SourceRows",
    "UndeclaredKind",
    "UnknownObserver",
    "admit_records",
    "fact_commitment_hash",
    "grant_for_observer",
]
