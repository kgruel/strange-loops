"""arrival_head_seam — comparing the presented head against the remembered one.

Slice 3 / WP3 of the arrival break (``design:arrival-break-slice3-witness-minimum``).
The design of record is ``docs/scratch/arrival-break/slice3-design-proposal.md`` §D;
:mod:`engine.arrival_head_attestation` is WP1's half — the record, the journal and
the judgment — and this module is the seam that calls it on every open.

**Why the seam sits at the registry and not lower.** ``ArrivalStore.__init__`` runs
``catch_up()`` on every open, and a shrunk log is one of its documented triggers for
a full index REBUILD. A shrunk log whose index still holds rows past the log's new
head is *the* signature of tail truncation — and the rebuild erases the rows that
testify to it. Detection placed downstream of that repair can only report the
agreement the repair just manufactured. The registry's opener performs no recovery
(``ArrivalLog`` construction does no I/O at all), so putting the comparison here
satisfies "the witness observes before the runtime heals" structurally rather than
by discipline. That is F2's "verification never repairs" applied one level out.

**Always on, never a flag.** A configuration switch for a safety property is a
shape the arrival vocabulary ratchet's own denylist rejects: custody is structural
rather than configured, so there is no setting that turns the comparison off and no
second opener that skips it. Slice 4's migration sidecar needs no exemption either —
minting through the wrapper IS how its bootstrap receipt gets written, and there is
no privileged path.

**No refusal is raised after a journal write, and no journal write happens before
every refusal has had its chance.** :meth:`AttestedLedger._observe` is pure with
respect to the journal — it RETURNS what should be written and writes nothing — and
the constructor performs the writes only once observation has returned without
raising. Structural, so a later edit cannot quietly leave a memory behind that
records a head the very same open went on to refuse.

**Backend-neutral, and that is a dissolution rather than a discipline.** §D.3 posits
"a small function beside the adapter" to gather descent evidence. It is not needed:
``verify(Open())``, ``verify(Full(...))`` and ``head_at(Watermark(...))`` are all
contract operations returning contract types, so the entire evidence gather is
spelled in the neutral vocabulary and this module names no adapter, no wire field
and no backend exception. See :meth:`AttestedLedger._present` for the one place
that cost something.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .arrival_contract import (
    ArrivalLedger,
    ArrivalQuery,
    Capabilities,
    Commit,
    ExportedPrefix,
    Full,
    Head,
    Open,
    RecordDraft,
    VerifyScope,
    Watermark,
)
from .arrival_head_attestation import (
    AbsentStoreOutcome,
    AttestationRefusal,
    EstablishedHead,
    HeadAttestation,
    HeadFork,
    HeadLowerBound,
    HeadRollback,
    IndeterminateComparison,
    JournalRead,
    Kind,
    Level,
    LineageReplaced,
    Outcome,
    StoreLost,
    append_entry,
    bindings_path,
    bound_lineage,
    compare,
    compare_absent_store,
    entry_identity,
    last_entry,
    read_journal,
    record_binding,
    refusal_for,
    unaccounted_heads,
)

__all__ = [
    "AttestedLedger",
    "AbandonedHistoryFenced",
    "AuditFoundUnaccountedHeads",
    "Compared",
    "Indeterminate",
    "NotWitnessed",
    "TrustResetNotHonored",
    "OpenReport",
    "PreGenesis",
    "ProjectionAgreement",
    "ProjectionAheadOfLedger",
    "ProjectionReport",
    "audit",
    "bootstrap",
    "aliased_lineage",
    "canonical_location",
    "days_since_audit",
    "match_identity",
    "trust_reset",
]

_SECONDS_PER_DAY = 86400.0


# ---------------------------------------------------------------------------
# What the seam adds to WP1's refusal family
# ---------------------------------------------------------------------------


class ProjectionAheadOfLedger(AttestationRefusal):
    """The projection accounts for a head the ledger will not vouch for.

    A watermark above the presented head is tail-truncation evidence that
    survives INDEPENDENTLY of the journal — it is the one signal available on
    a store this machine has never seen before, where there is nothing
    remembered to compare against. §D.3: only when the ordinals disagree does
    the seam ask ``head_at`` to turn the coordinate into a head the ledger
    vouches for, and on this branch the ledger's refusal *is* the answer.

    §11's response is ``rederive_projections``. Never edit the ledger to match
    the projection: the projection is derived state and the ledger is the
    authority, so an agreement manufactured by moving the authority is the one
    repair that destroys the evidence.
    """


class AbandonedHistoryFenced(AttestationRefusal):
    """The advance descends through history an operator decreed away.

    Sol's silent loop, and what makes it a loop rather than a single mistake:
    reset from an abandoned *N+1* to *N*, restore the authentic *N+1* backup,
    and the open verifies descent honestly — the chain really does reach *N+1*
    from *N* — so it answers ADVANCED, **journals** *N+1* back into the current
    epoch, and every later open reads UNCHANGED. No refusal, no fork, ever, and
    repeatable indefinitely. The acceptance erases its own evidence by
    recording it (``finding:s3-reset-descendant-silent-loop``).

    Verified descent is not the whole question. A chain can be perfectly
    intact and still be the history a ceremony put behind us — machinery must
    never silently reverse an operator's decree.

    The acceptance path is the ceremony, and it is one command: decree the
    recovered head. That is the lift rule, and it is why this refusal names it
    rather than leaving an operator to guess at a way forward.
    """


class AuditFoundUnaccountedHeads(AttestationRefusal):
    """The store can no longer account for heads journaled in this epoch.

    Raised INSTEAD of appending the audit entry, never alongside it: an
    ``audit``/``full`` entry asserts that the walk found everything it was
    asked about, and writing one over an unaccounted head would record a
    verification that did not happen. :attr:`heads` carries the entries.
    """

    def __init__(self, message: str, *, heads: tuple[HeadAttestation, ...]) -> None:
        super().__init__(message)
        self.heads = heads


class TrustResetNotHonored(Exception):
    """The reset was appended and does not open an epoch.

    Deliberately NOT an :class:`~engine.arrival_head_attestation.AttestationRefusal`,
    for the reason :class:`NotWitnessed` is not one: that family means the
    operation did not happen, and this one means it happened without taking
    effect. The entry is in the journal as evidence either way.

    The failure it reports is safe in direction and dishonest only if silent —
    an unhonored reset leaves the higher abandoned head standing, so opens keep
    refusing, and the harm is an operator who believes otherwise.
    """

    def __init__(self, message: str, *, entry: HeadAttestation) -> None:
        super().__init__(message)
        self.entry = entry


class NotWitnessed(Exception):
    """The mutation COMMITTED, and the journal write for it failed.

    §05's ``committed`` versus ``witnessed`` distinction, and §D.4's rule that
    a journal write failure is surfaced rather than swallowed: the append has
    already landed, so the store has advanced past its witness and the caller
    is told which of the two it got instead of having both collapsed into
    "saved".

    **Deliberately NOT an** :class:`~engine.arrival_head_attestation.AttestationRefusal`.
    Every member of that family means the operation did not happen. This one
    means the opposite — the data is committed and durable — so a caller
    catching the refusal root to mean "nothing changed" must not catch this
    too. Propagating past those handlers is the never-silent mechanism, and
    the type name is the whole message.

    :attr:`head` is where the lineage now stands. :attr:`commit` is the full
    transition for the append and replicate paths, and ``None`` for a mint,
    which returns a head rather than a commit.
    """

    def __init__(
        self, message: str, *, head: Head, commit: Commit | None = None
    ) -> None:
        super().__init__(message)
        self.head = head
        self.commit = commit


# ---------------------------------------------------------------------------
# What one open observed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Compared:
    """The journal answered in full, and this is the row it answered with."""

    outcome: Outcome
    presented: Head
    known: HeadAttestation | None


@dataclass(frozen=True)
class Indeterminate:
    """The journal's read was INCOMPLETE, so no row was obtainable.

    Deliberately **no** ``outcome`` attribute — the same discipline WP1 applied
    one level down, where :class:`~engine.arrival_head_attestation.HeadLowerBound`
    has no ``entry`` field. There is no expression that reads an outcome off an
    open report without first naming which case the report is in, so a consumer
    cannot treat a degraded open as an answered one by forgetting to look.

    :attr:`refusal` is the :class:`~engine.arrival_head_attestation.IndeterminateComparison`
    that ``established_head()`` DID raise and this seam declined to propagate.
    It is carried rather than discarded so a caller that wants the strict
    posture can raise it, and so the reason is in the report rather than in a
    log line nobody kept.

    :attr:`at_least` is the bound the readable entries establish, or ``None``
    when the read held content but nothing readable — there is no bound then,
    and every comparison declines rather than merely the proceed-answers.
    """

    presented: Head
    refusal: IndeterminateComparison
    skipped: tuple[str, ...]
    at_least: Head | None


@dataclass(frozen=True)
class PreGenesis:
    """The ledger named no head, and nothing was remembered for this location.

    The ordinary state of a location a moment before the sidecar mints into
    it, and refusing here would make minting impossible. The seam makes NO
    claim on this branch — it did not verify a store, and it did not accept
    one.

    :attr:`ledger_refusal` is why the ledger would not name a head, carried so
    the branch is labeled rather than silent. An absent or empty log is the
    expected reason; a corrupt one lands here too when this location has no
    memory, and its own operations refuse on their own account.
    """

    ledger_refusal: BaseException | None


class ProjectionAgreement(Enum):
    """How far the projection is from the head the ledger presented."""

    ABSENT = "absent"  # the projection reports no watermark at all
    BEHIND = "behind"  # ordinary staleness — catch-up's job, never refused
    LEVEL = "level"  # the projection accounts for exactly the presented head


@dataclass(frozen=True)
class ProjectionReport:
    """What the projection claimed, and how it compares.

    Ahead-of-the-ledger is absent from :class:`ProjectionAgreement` on purpose:
    it refuses, so it is never a value a successful open can hold.
    """

    agreement: ProjectionAgreement
    watermark: Watermark | None


@dataclass(frozen=True)
class _Earned:
    """An entry an observation earned but did not write.

    The carrier that makes "nothing writes until every refusal has had its
    chance" a property of the control flow rather than a rule each branch has
    to remember. Observation is pure with respect to the journal: it RETURNS
    one of these, and :meth:`AttestedLedger.__init__` writes it only once
    observation has returned without raising.

    It exists because the per-branch version of the rule failed. The
    first-contact branch deferred correctly while the advance branch wrote
    inline, so a store that passed the journal comparison and then failed the
    projection one left an ``advance``/``descendant`` entry recording a head
    the very same open refused
    (``finding:s3wp3-gate-advance-journaled-before-projection-refusal``). One
    branch honoring a rule the next branch does not is what a carrier removes
    and a comment does not.

    **It is the same rule the degraded branch already obeys**, which is what
    makes it one rule rather than two. A degraded open writes nothing because
    the evidence behind the head was incomplete; a refused open must write
    nothing because a later step invalidated it. Both hazards are one hazard —
    *a journal entry recording a head this open did not actually establish* —
    and both are closed the same way, by not writing until the judgment is
    finished. ``test_an_incomplete_read_does_not_answer_advanced_above_the_bound``
    and ``test_an_advance_is_not_journaled_when_the_projection_then_refuses``
    are the same assertion about the same guarantee, reached down two different
    branches.
    """

    head: Head
    kind: Kind
    level: Level


@dataclass(frozen=True)
class OpenReport:
    """Everything one compare-on-open established.

    :attr:`projection` is ``None`` when no comparison was made — either no
    query half was supplied, or the ledger named no head for a watermark to be
    compared against. Both are different from
    :attr:`ProjectionAgreement.ABSENT`, where a projection WAS asked and
    reported no position of its own.
    """

    comparison: Compared | Indeterminate | PreGenesis
    projection: ProjectionReport | None
    days_since_audit: float | None


# ---------------------------------------------------------------------------
# TRANSITIONAL — DELETE IN SLICE 5, with the binding it serves.
#
# WP1 named the gap and left it here: `bindings.jsonl` matches `location` as an
# exact string, so the seam must pass ONE canonical form or a symlinked or
# relative path manufactures a first contact through the hole the binding
# exists to close. This is that form, and it is part of the same unit slice 5
# deletes: once every `.vertex` declares its lineage, `descriptor.lineage`
# answers the replacement question from a source an operator can read, and
# neither the binding nor its canonicalization has anything left to do.
# ---------------------------------------------------------------------------


def canonical_location(location: str) -> str:
    """The one string form of a location, for the binding. DELETE IN SLICE 5.

    ``Path.resolve()``: relative paths become absolute against the process cwd,
    ``..`` segments collapse, and symlinks resolve to their target — so two
    vertices reaching one log by different routes present one binding key
    rather than two, which is exactly the first contact the binding exists to
    prevent. Non-strict by default, so a location that does not exist yet
    still canonicalizes; the mint path depends on that.

    **Scope the claim.** This assumes a location is a filesystem path. §02 is
    explicit that a ``location`` may be a DSN or a service URL, and resolving
    one of those against the cwd would mangle it. That is bounded and it dies
    with this function: the value is used ONLY as the binding key and as the
    diagnostic ``location`` field, never as a journal key — journals are keyed
    by lineage — so a mangled location degrades to "no binding found", which
    is first contact, the state the binding improves on rather than
    guarantees. The file adapter is the only registered backend, and slice 5
    removes the binding before a second one can arrive.

    **This is a SPELLING, not an identity**, and the difference is the whole of
    ``finding:s3wp3-canonical-location-alias-first-contact``. ``resolve()``
    normalizes a path; it does not establish which filesystem object a path
    names. A case-variant spelling on a case-insensitive filesystem — the macOS
    default — or a second mount of the same volume reaches the very same store
    through a string this function returns unchanged and different. Bound under
    one spelling and presented under the other, the store has no binding, reads
    as first contact, and a replacement with a fresh lineage walks past
    :class:`~engine.arrival_head_attestation.LineageReplaced`. That hole is
    closed by :func:`aliased_lineage`, which asks the filesystem rather than
    the string.

    Residuals, both stated rather than papered over: a store reached through a
    symlink whose target later changes presents a different canonical form and
    is first contact again; and two aliases that genuinely report DIFFERENT
    ``(st_dev, st_ino)`` — two network mounts of one export are the ordinary
    case — are beyond anything a client can detect from here. Path-keying is
    transitional for exactly these reasons, and the lineage-keyed journal is
    the memory that does not have them.
    """
    return str(Path(location).resolve())


#: A filesystem object's identity on this host: the device and inode a path
#: currently resolves to. Never RECORDED — inodes go stale when a file is
#: recreated and get recycled onto unrelated files, so a stored one is a claim
#: that rots into a false match. Only ever compared live, at the moment both
#: sides are stat'd.
Identity = tuple[int, int]


def _identity_of(location: str) -> Identity | None:
    """What filesystem object this path names right now, or None.

    None for a path that does not stat — it was deleted, the mount is gone, or
    permission was withdrawn. Those bindings are skipped rather than guessed
    at: a path that cannot be stat'd makes no claim about identity either way.
    """
    try:
        stat = Path(location).stat()
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino)


def match_identity(
    presenting: Identity | None,
    recorded: Sequence[tuple[str, str, Identity | None]],
) -> str | None:
    """The lineage bound to another spelling of the SAME filesystem object.

    Pure, and separated from the stat calls on purpose: the alias this closes
    can only be CONSTRUCTED on a case-insensitive filesystem, so a test that
    builds one is skipped on a case-sensitive CI runner. The judgment is the
    part worth pinning everywhere, so it takes identities as arguments and is
    testable on any filesystem, while the construction test carries an honest
    skip.

    ``recorded`` is (location, lineage, identity) in file order, so the newest
    binding for an aliased object wins — the same rule
    :func:`~engine.arrival_head_attestation.bound_lineage` applies to an exact
    location. An unstattable recorded path contributes nothing.
    """
    if presenting is None:
        return None
    found: str | None = None
    for _location, lineage, identity in recorded:
        if identity is not None and identity == presenting:
            found = lineage
    return found


def aliased_lineage(location: str) -> str | None:
    """The lineage bound to this store under a DIFFERENT spelling.

    Consulted only when the presenting location has no binding of its own —
    which is the one moment the hole is open, and which keeps every subsequent
    open free of the sweep. It live-stats each recorded binding; a store bound
    under one spelling and opened under another is then NOT first contact, and
    a replacement at that location refuses.

    The filesystem namespace is ambient authority: two names for one object is
    a property of the namespace rather than of the store, so asking the
    filesystem which object a name currently denotes is a location claim about
    this host and not a verdict about the store. DELETE IN SLICE 5 with the
    rest of the binding.
    """
    try:
        text = bindings_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    recorded: list[tuple[str, str, Identity | None]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            decoded = json.loads(stripped)
        except ValueError:
            continue
        where = decoded.get("location") if isinstance(decoded, dict) else None
        lineage = decoded.get("lineage") if isinstance(decoded, dict) else None
        if isinstance(where, str) and isinstance(lineage, str):
            recorded.append((where, lineage, _identity_of(where)))
    return match_identity(_identity_of(location), recorded)


# ---------------------------------------------------------------------------
# Producers — the entries something other than an ordinary open writes
# ---------------------------------------------------------------------------


def bootstrap(
    head: Head, *, level: Level, location: str, observed_at: float
) -> Path:
    """The first entry for a lineage, plus its binding. Returns the journal.

    ``Level.MINT`` when this process minted the genesis, ``Level.FIRST_CONTACT``
    when an already-existing store was opened for the first time. **Slice 6's
    verification depends on the distinction**: a journal beginning at ``mint``
    was witnessed from genesis forward and every head in it is accounted for;
    one beginning at ``first-contact`` was trusted on sight, and that label is
    permanent. Slice 4's sidecar must produce the former for every migrated
    store by minting through :class:`AttestedLedger`, and slice 6 checks it.

    No other level is admitted. ``COMMIT``, ``DESCENDANT`` and ``FULL`` each
    name evidence a first entry cannot have — there was nothing to descend
    from — so accepting one would let a journal open with a claim stronger than
    anything that happened.

    The binding is recorded here rather than by the caller so that the
    canonical form is applied in exactly one place (see
    :func:`canonical_location`); a caller that wrote its own binding is how the
    two spellings diverge.
    """
    if level not in (Level.MINT, Level.FIRST_CONTACT):
        raise ValueError(
            f"a bootstrap entry may be {Level.MINT.value!r} or "
            f"{Level.FIRST_CONTACT.value!r}, not {level.value!r} — every other "
            "level names evidence a first entry cannot have, because there was "
            "nothing before it to descend from or verify against"
        )
    canonical = canonical_location(location)
    path = append_entry(
        HeadAttestation(
            head=head,
            kind=Kind.BOOTSTRAP,
            level=level,
            observed_at=observed_at,
            location=canonical,
        )
    )
    record_binding(canonical, head.lineage, observed_at)
    return path


def trust_reset(
    *,
    accepted: Head,
    abandoned: Head | None,
    refused: Head | None,
    reason: str,
    location: str,
    observed_at: float,
    level: Level = Level.FIRST_CONTACT,
) -> Path:
    """The operator ceremony's entry, opening a new trust epoch.

    §11's last row asks for exactly this — *"perform explicit trust reset from
    archives or operator ceremony and record the gap"* — against the unsafe
    shortcut of treating the first presented database as historically proven.
    Refusals are terminal for the open and no automatic path may abandon one;
    this is the licensed way down, and it is a function an operator's ceremony
    calls rather than anything the seam can reach.

    The gap goes in ``note`` and it is the point of the entry: the head being
    abandoned, the head that was refused, and why. Entries before the reset
    stay in the journal as **evidence, not as claims** — the read scope moves,
    the history does not.

    ``level`` defaults to the WEAKEST claim available. An operator ceremony may
    have verified the accepted head from genesis, and one that did should pass
    ``Level.FULL``; one that took a head from an archive on an operator's word
    has proven nothing, which is what ``first-contact`` says. Defaulting down
    is deliberate — a default can then only under-claim, and an entry that
    under-claims costs a later audit some work while one that over-claims is a
    lie the journal keeps forever.

    **The reset is bound to the entry it is appended after**, which is what
    makes a replayed copy inexpressible as valid — see
    :attr:`~engine.arrival_head_attestation.HeadAttestation.follows`. Binding
    it here is the FOOTGUN GUARD, not the protection: an operator constructing
    an entry by hand still produces one, and the protection is the read-time
    validation in ``_epoch_of``, which is what every reader performs. A writer
    that raced another appender between this read and its own write produces a
    binding that no longer matches, and that reset is then not honored — the
    refusal-side failure, and the reason the read-time half is the load-bearing
    one.

    **What a reset fences out.** A reset decrees trust in *N*, and verified
    descendants of *N* that pass through history the decree abandoned are
    REFUSED (:class:`AbandonedHistoryFenced`) until a new decree reaches them.
    Genuine recovery of that history therefore costs exactly one ceremony:
    decree the recovered head, and the fence lifts.

    This corrects what this docstring said before amendment #6, which was that
    such descendants were accepted. They were, and that was the silent loop —
    an accepted re-presentation journaled itself back into the current epoch and
    every later open read UNCHANGED (``finding:s3-reset-descendant-silent-loop``).

    The CLI surface for the ceremony is slice 5's cut. This is the producer, so
    slices 4 and 6 have something to call.
    """
    previous = last_entry(accepted.lineage)
    follows = (
        (0, "") if previous is None else (previous[0], entry_identity(previous[1]))
    )
    if not reason.strip():
        raise ValueError(
            "a trust reset records the gap it opens — an empty reason would "
            "leave the journal holding the abandonment without the evidence "
            "for it, which is the whole thing the ceremony exists to write down"
        )
    note = (
        f"trust reset: abandoning {_head_text(abandoned)}, "
        f"refused {_head_text(refused)}, accepting "
        f"{accepted.lineage}/{accepted.ordinal}/{accepted.record_hash}. "
        f"{reason.strip()}"
    )
    entry = HeadAttestation(
        head=accepted,
        kind=Kind.TRUST_RESET,
        level=level,
        observed_at=observed_at,
        location=canonical_location(location),
        note=note,
        follows=follows,
    )
    path = append_entry(entry)
    _confirm_reset_took_effect(entry)
    return path


def _confirm_reset_took_effect(entry: HeadAttestation) -> None:
    """Read the ceremony back, and say so loudly if it did not take.

    The position claim buys its protection with an obligation. Binding a reset
    to the line it follows means reading the tail and then appending, and there
    is NO lock to hold across the two — the journal is append-only precisely so
    that writers need none. So an automated append (an ordinary open, an audit)
    landing in that window leaves a legitimate, freshly written reset carrying a
    position that is already stale, and a later reader will decline to honor it.

    The direction is safe — an unhonored reset leaves *K* at the higher
    abandoned head, which refuses rather than accepts. What is NOT safe is
    silence: an operator who ran the ceremony, saw it return, and believes their
    store will now open is holding a false belief that the next open will
    contradict. So the entry is read back and checked against the same judgment
    every reader applies, and a ceremony that did not take effect raises.

    Emit-then-read-back rather than trust-the-write, which is the store's own
    ethos: the append landing is not the same claim as the append counting.
    """
    try:
        epoch = read_journal(entry.head.lineage).epoch
    except AttestationRefusal as exc:
        raise TrustResetNotHonored(
            "the trust reset was APPENDED, and the journal could not then be "
            f"read back to confirm it took effect: {exc}. The entry is in the "
            "file as evidence; whether it opens an epoch is unconfirmed",
            entry=entry,
        ) from exc
    if not epoch or epoch[0] != entry:
        raise TrustResetNotHonored(
            "the trust reset was APPENDED and is NOT honored as an epoch "
            "boundary — another entry landed between reading the tail and "
            "writing, so the position this reset records is already stale. "
            "Nothing was lost and nothing was wrongly accepted: the previous "
            "head still stands, so opens keep refusing. Run the ceremony again "
            "against the journal as it now is",
            entry=entry,
        )


def audit(
    ledger: ArrivalLedger,
    *,
    presented: Head,
    epoch: Sequence[HeadAttestation],
    projection: str,
    location: str,
    observed_at: float,
) -> Path:
    """The full chain-plus-projection audit (§D.5). Returns the journal.

    Three things, and the third is what makes the cheap per-open check safe:

    1. ``verify(Full(through=presented))`` — grammar, density, lineage and the
       hash chain for the complete prefix.
    2. Every head journaled **in the current trust epoch** is still present at
       its own ordinal with its own hash. An advance accepted on partial
       evidence is re-examined against the complete record of everything
       accepted since the last reset — which a single-value cache could not
       offer at any price, because it would have forgotten those heads.
    3. Only then, an ``audit``/``full`` entry carrying the head the audit
       covered and, in ``note``, the projection-agreement result.

    **The all-journaled-heads lookup is built here and cannot be passed in.**
    :func:`~engine.arrival_head_attestation.unaccounted_heads` takes an injected
    ``at_ordinal`` so the neutral module never reaches for a backend, and an
    injection point is a place a fabricated head can lie: a lookup that
    answered from the journal, from a cache, or from the projection would
    "confirm" every entry without the store having been asked. So this
    function accepts no lookup parameter. It builds one from ``ledger.head_at``,
    which resolves through a verified walk from ordinal 0 — the same evidence
    ``verify`` gathers, obtained through custody rather than around it.

    ``projection`` is the agreement result as a STRING, taken as an input so
    this module never imports the projection auditor — §D.5's own discipline,
    and the reason the audit stays callable from a CLI that has already
    computed it.

    **Writing an entry from a verification path is not what F2 forbids.** F2
    forbids repairing the store under judgment. Recording evidence outside it
    is the entire purpose of a witness.

    Cost: the full walk, plus one verified walk per journaled head in the
    epoch. "Periodic" is operator cadence and this is the operator-cadence
    path, so the honest lookup is worth more than a cheaper one — but the cost
    is real, and a store whose epoch holds many entries is where a
    single-walk-with-a-table form would earn its keep. Named rather than
    pre-paid; its forcing consumer is a store large enough to notice.
    """
    ledger.verify(Full(through=presented))
    unaccounted = unaccounted_heads(epoch, _vouched_at(ledger, presented.lineage))
    if unaccounted:
        raise AuditFoundUnaccountedHeads(
            "the store can no longer account for "
            f"{len(unaccounted)} head(s) journaled in the current trust epoch: "
            + "; ".join(
                f"ordinal {entry.head.ordinal} ({entry.head.record_hash})"
                for entry in unaccounted
            )
            + ". No audit entry was written — one would record a verification "
            "that did not happen. Locate a replica or backup that holds them, "
            "or run the explicit trust-reset ceremony and record the gap",
            heads=tuple(unaccounted),
        )
    return append_entry(
        HeadAttestation(
            head=presented,
            kind=Kind.AUDIT,
            level=Level.FULL,
            observed_at=observed_at,
            location=canonical_location(location),
            note=projection,
        )
    )


def days_since_audit(read: JournalRead, now: float) -> float | None:
    """Days since the last audit entry in the CURRENT epoch, or None.

    Report only. The open path never triggers an audit, because a full walk at
    open is exactly what the adapter refused to pay under an ``Open`` label —
    an operation that quietly upgraded its own verification level would be
    lying about its cost. Wiring a command to append an audit entry is slice
    5's CLI cut.

    Epoch-scoped for the same reason *K* is: an audit that ran before a trust
    reset covered a history the reset abandoned, so counting it would report
    freshness the current epoch has not earned. ``None`` means "no audit has
    covered this epoch", which is different from "the last one was long ago"
    and is why this does not answer with an age of infinity.
    """
    stamps = [
        entry.observed_at for entry in read.epoch if entry.kind is Kind.AUDIT
    ]
    if not stamps:
        return None
    return (now - max(stamps)) / _SECONDS_PER_DAY


def _head_text(head: Head | None) -> str:
    """A head for a human, or an explicit nothing."""
    if head is None:
        return "(none)"
    return f"{head.lineage}/{head.ordinal}/{head.record_hash}"


def _remembered_floor(read: JournalRead) -> int | None:
    """The lowest ordinal the journal already knows the accepted head is at.

    One number for all three states of a read, which is what lets the
    across-time re-observation be decided in one place rather than repeated on
    each comparison branch. An established head knows its own ordinal; a bound
    knows at least its own; an unreadable read and an absent journal know
    nothing and answer ``None``, because a store cannot look like it went
    backward relative to a memory that holds no position.
    """
    known = read.known
    if isinstance(known, EstablishedHead):
        return known.entry.head.ordinal
    if isinstance(known, HeadLowerBound):
        return known.at_least.head.ordinal
    return None


def _vouched_at(
    ledger: ArrivalLedger, lineage: str
) -> Callable[[int], Head | None]:
    """A lookup that answers only what the LEDGER vouches for at an ordinal.

    ``head_at`` resolves through a verified walk, so an answer here means the
    chain from genesis reaches that coordinate and holds that record. A refusal
    means the ledger will not vouch for anything there, and ``None`` is the
    honest spelling of that — the caller then treats the head as unaccounted,
    which is the refusing direction.

    Broad catch, and it is safe in exactly one direction. The contract's
    ``head_at`` says it "answers or it refuses" without naming an exception
    family, and the file adapter's "no record at that ordinal" is its own
    backend error rather than a ``ContractRefusal``, so a neutral caller cannot
    enumerate the refusals without naming a backend
    (``finding:s3wp3-head-at-refusal-family-unnamed``). Catching broadly is
    sound here because every catch lands on "unaccounted", which REFUSES; the
    opposite default — treating an unrecognized failure as agreement — is the
    silent-acceptance hazard, and that is the direction this must never fail in.
    """

    def at_ordinal(ordinal: int) -> Head | None:
        try:
            return ledger.head_at(Watermark(lineage=lineage, ordinal=ordinal))
        except Exception:  # noqa: BLE001 — see the docstring: fails to REFUSE
            return None

    return at_ordinal


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


class AttestedLedger:
    """An :class:`~engine.arrival_contract.ArrivalLedger` that remembers.

    Two things, and no third: it compares at construction, and it journals
    after a successful ``mint``, ``append`` or ``replicate``. Everything else
    is delegation.

    **Delegation is by explicit method, never** ``__getattr__``. A catch-all
    would forward ``import_prefix`` — a mutation the contract Protocol
    deliberately does not declare but which is in ``LEDGER_MUTATIONS``
    regardless, because the custody/reads separation must cover every op that
    can change what a lineage holds. Forwarded silently, it would be a mutation
    reachable through the attested handle that the seam does not journal: a
    hole in the witness, opened by a convenience nobody wrote down. It is
    therefore NOT reachable through this wrapper, and a future op added to the
    adapter is not reachable either until somebody decides how it is witnessed.

    **The IndeterminateComparison posture** — the WP's flagged design point — is
    in :meth:`_degraded`, with the argument.
    """

    def __init__(
        self,
        ledger: ArrivalLedger,
        *,
        location: str,
        query: ArrivalQuery | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Compare, then write what the comparison earned.

        ``clock`` is injected because WP1's module reads no clock — every
        ``observed_at`` there is a caller-supplied argument — and this is the
        caller. It is what keeps staleness reporting testable without freezing
        time inside the journal.

        **This is the ONLY place the open path writes**, and that is the whole
        of "nothing writes until every refusal has had its chance". Observation
        is pure with respect to the journal — it returns an :class:`_Earned`
        and writes nothing — so an open that refuses anywhere leaves no memory
        claiming it accepted the thing it refused.

        Stating it per-branch was not enough: the first-contact branch deferred
        while the advance branch wrote inline, and a store that passed the
        journal comparison and then failed the projection one kept an
        ``advance`` entry for the head it had just been refused
        (``finding:s3wp3-gate-advance-journaled-before-projection-refusal``).
        The rule is now carried by the return type, and
        ``test_only_the_constructor_and_the_producers_write_to_the_journal``
        pins it against the branch somebody adds next.
        """
        self._ledger = ledger
        self._location = location
        self._canonical = canonical_location(location)
        self._query = query
        self._clock = clock

        report, earned = self._observe()
        if earned is not None:
            self._write(earned)
        self.opened: OpenReport = report
        """What the compare-on-open established. See :class:`OpenReport`."""

    def _write(self, earned: _Earned) -> None:
        """Write what an observation earned, once it has earned it.

        A bootstrap goes through :func:`bootstrap` rather than straight to
        ``append_entry`` so that the level validation and the binding stay on
        one path — a seam that appended its own bootstrap would be the second
        place the canonical form is applied, which is how two spellings
        diverge.
        """
        if earned.kind is Kind.BOOTSTRAP:
            bootstrap(
                earned.head,
                level=earned.level,
                location=self._location,
                observed_at=self._clock(),
            )
            return
        append_entry(
            HeadAttestation(
                head=earned.head,
                kind=earned.kind,
                level=earned.level,
                observed_at=self._clock(),
                location=self._canonical,
            )
        )

    # -- the comparison ----------------------------------------------------

    def _observe(self) -> tuple[OpenReport, _Earned | None]:
        """Everything the open judged, and the entry it earned — written by
        the caller.

        Order is load-bearing and every step of it is a refusal that must fire
        before anything is remembered:

        1. Ask the ledger for a head. No head is §D.4's absent-store split.
        2. The location's binding — a DIFFERENT lineage here is replacement,
           and it must be caught before the presented lineage's journal is
           read, or the seam would consult a journal that has never seen this
           location and answer first contact through the very hole the binding
           closes.
        3. The journal comparison — the custody claim, and the stronger one:
           it is the out-of-band memory, and its refusals name the recovery an
           operator actually performs.
        4. The projection comparison, which §D.2 calls a second and separable
           step. Separable is what keeps the seam working when the projection
           is absent, and second is why an ahead-of-the-ledger index cannot be
           reported as a rollback it is not.

        None of these writes. The bootstrap entry a first contact earns is
        RETURNED, so a store that passes the journal comparison and then fails
        the projection one leaves no memory claiming its head was accepted.
        """
        presented, ledger_refusal = self._present()
        if presented is None:
            return self._absent(ledger_refusal), None

        remembered_lineage = bound_lineage(self._canonical)
        if remembered_lineage is None:
            # No binding for THIS spelling. Before calling it first contact,
            # ask the filesystem whether another spelling already names this
            # same object — a case variant, or a second mount. Live-stat, and
            # only here: once a binding exists for the spelling in use, the
            # exact match above answers and this sweep never runs.
            remembered_lineage = aliased_lineage(self._canonical)
        if (
            remembered_lineage is not None
            and remembered_lineage != presented.lineage
        ):
            raise LineageReplaced(
                f"{self._canonical} previously presented lineage "
                f"{remembered_lineage} and now presents {presented.lineage} — "
                "a fresh lineage at a location that already had one is a "
                "replacement wearing the old name, not a new store. If this "
                "replacement is intended, the licensed way to accept it is the "
                "explicit trust-reset ceremony, which records the gap"
            )

        read = read_journal(presented.lineage)
        presented = self._not_older_than_the_journal(read, presented)

        try:
            known = read.established_head()
        except IndeterminateComparison as exc:
            comparison: Compared | Indeterminate = self._degraded(
                read, presented, exc
            )
            earned: _Earned | None = None
        else:
            outcome, earned = self._judge(known, presented, read)
            comparison = Compared(
                outcome=outcome, presented=presented, known=known
            )

        return (
            OpenReport(
                comparison=comparison,
                projection=self._projection(presented),
                days_since_audit=days_since_audit(read, self._clock()),
            ),
            earned,
        )

    def _not_older_than_the_journal(
        self, read: JournalRead, presented: Head
    ) -> Head:
        """Re-observe the store when it looks like it went backward.

        **The comparison is between two files read at two different moments,
        and that gap is a hazard the read rules alone cannot close.** The store
        is observed, then the journal is. A writer that commits and journals
        in between leaves the journal holding a head the store's older
        observation does not have — which is bit-for-bit what a rollback looks
        like. Two processes appending to one lineage while a third opens it is
        not exotic: it is the concurrency this backend advertises, and the
        symptom is an operator told their store was rolled back by an ordinary
        pair of concurrent writes (``finding:s3wp3-open-compares-across-time``).

        This is WP1's write-path lesson at the next layer up. There the rule
        was that a read rule closing a hazard can be reopened by a write path;
        here a COMPARISON rule closed at read time is reopened by somebody
        else's write between the two reads.

        The fix is to make the refusing observation not older than the journal:
        when the presented head sits below what the journal already knows, the
        store is asked once more, and the fresher answer is what gets
        classified. One extra constant-time tail read, on the descending branch
        only — the dominant unchanged case pays nothing, and the branch that
        does pay is the one about to accuse an operator of losing data.

        Terminating, not a retry loop, and the residual window fails SAFE. A
        writer committing after the re-read is invisible to the journal read
        that preceded it, so its effect can only be to make *K* lower than
        reality — which classifies unchanged or advanced and pays a verified
        walk, never a false refusal. A genuine rollback is stable across both
        reads and survives.
        """
        floor = _remembered_floor(read)
        if floor is None or presented.ordinal >= floor:
            return presented
        fresh, _refusal = self._present()
        return presented if fresh is None else fresh

    def _present(self) -> tuple[Head | None, BaseException | None]:
        """The head the ledger names, or nothing and why.

        ``verify(Open())`` and never ``head()``: the Open level is a
        constant-time reverse tail read that validates the genesis and the
        adopted head record, while ``head()`` reaches its answer through a full
        walk — which would make every open pay a Full verification wearing an
        Open label. That single choice is what makes the dominant unchanged
        case O(1).

        **The seam never classifies why the ledger refused**, and that is what
        keeps it neutral. §D.4 needs an absent or empty log to branch rather
        than read as corruption, and the adapter says so with its own
        ``GenesisRefused`` — a backend exception this module would have to
        import to recognize, dragging the codec into the seam and hard-coding
        one adapter into a wrapper that wraps any. It does not need to: WP1's
        :func:`~engine.arrival_head_attestation.compare_absent_store` splits on
        MEMORY, not on the store. "Did the ledger name a head" and "does the
        journal remember one" are two questions, and the four cells they make
        are answerable without ever asking why.

        A corrupt log lands on the no-head branch too, and lands correctly:
        with a memory here it is a loss and refuses, and without one it is
        pre-genesis with the refusal carried on the report — where the store's
        own operations go on refusing on their own account. The refusal is
        never swallowed either way.
        """
        try:
            return self._ledger.verify(Open()), None
        except Exception as exc:  # noqa: BLE001 — see the docstring
            return None, exc

    def _absent(self, ledger_refusal: BaseException | None) -> OpenReport:
        """§D.4's split for a location whose ledger names no head.

        Decided on memory alone. The binding says which lineage this location
        last presented; that lineage's journal says whether anything was ever
        accepted for it.

        The third state is handled here rather than routed through
        :func:`~engine.arrival_head_attestation.compare_absent_store`, which
        takes an entry or ``None``: a journal holding content none of which is
        readable has no entry to pass, and passing ``None`` would answer
        pre-genesis — a store trusted as never-having-existed precisely because
        its memory became unreadable. That is BLOCKING-2's silent
        trust-on-first-use, reached through the absent-store door instead. It
        refuses, and it needs no bound to do so: the question here is whether
        anything was ever accepted, and unreadable content answers yes.
        """
        remembered_lineage = bound_lineage(self._canonical)
        known = None if remembered_lineage is None else read_journal(
            remembered_lineage
        ).known

        if known is None:
            entry: HeadAttestation | None = None
        elif isinstance(known, EstablishedHead):
            entry = known.entry
        elif isinstance(known, HeadLowerBound):
            entry = known.at_least
        else:  # HeadUnreadable — content was claimed and none of it survives
            raise StoreLost(
                f"{self._canonical} holds no readable head, and the journal "
                f"for lineage {remembered_lineage} holds content none of which "
                "this build can read — so heads WERE accepted here and the "
                "store cannot present one. This is not first contact and it is "
                "not a fresh location. Recovery is the explicit trust-reset "
                "ceremony"
            ) from ledger_refusal

        outcome = compare_absent_store(entry)
        if outcome is AbsentStoreOutcome.STORE_LOST:
            refusal = refusal_for(outcome)
            assert refusal is not None  # the table's only refusing row
            raise refusal(
                f"{self._canonical} presents no head, but the journal for "
                f"lineage {remembered_lineage} remembers "
                f"{_head_text(entry.head if entry else None)}. The witness "
                "proves what was lost, not its contents. A fresh genesis here "
                "would be a replacement wearing the old name, so a re-mint is "
                "refused too. Locate a replica or backup at or above the "
                "remembered head, or run the explicit trust-reset ceremony"
            ) from ledger_refusal

        return OpenReport(
            comparison=PreGenesis(ledger_refusal=ledger_refusal),
            projection=None,
            days_since_audit=None,
        )

    def _judge(
        self,
        known: HeadAttestation | None,
        presented: Head,
        read: JournalRead,
    ) -> tuple[Outcome, _Earned | None]:
        """Classify against a head the journal established in full.

        ``at_known`` is gathered ONLY on the ascending branch — same lineage,
        higher ordinal — which is what keeps the dominant unchanged case at the
        single ``verify(Open())`` the head already cost. On every other branch
        there is nothing for it to discriminate.

        Descent is established before the classifier is asked, because the
        classifier's ADVANCED row requires it and the classifier takes only
        ``at_known``. Two verified walks: ``verify(Full(through=presented))``
        establishes the chain through the presented head, and
        ``head_at(K)`` answers whether the record at the remembered ordinal is
        still the remembered one. Both are needed and neither substitutes for
        the other — a walk that checks only that it reached the presented head
        has verified the current chain while answering nothing about continuity
        with what was previously accepted, which is precisely the "never accept
        height as proof of continuity" failure.

        The advance branch is rare BY CONSTRUCTION, because a writer journals
        its own commit under the full-head fence and the next open then sees
        the presented head equal to the remembered one. An advance observed at
        open means an unjournaled writer touched the lineage — a foreign host,
        a restore, a crashed process, or the legacy store path during slices
        3-4 — and paying a verified walk there is correct rather than a
        regression.
        """
        at_known: Head | None = None
        descent_refusal: BaseException | None = None
        if (
            known is not None
            and presented.lineage == known.head.lineage
            and presented.ordinal > known.head.ordinal
        ):
            at_known, descent_refusal = self._descent(known.head, presented)

        outcome = compare(known, presented, at_known)
        refusal = refusal_for(outcome)
        if refusal is not None:
            raise refusal(
                self._refusal_text(outcome, known, presented, descent_refusal)
            ) from descent_refusal

        if outcome is Outcome.FIRST_CONTACT:
            return outcome, _Earned(
                head=presented, kind=Kind.BOOTSTRAP, level=Level.FIRST_CONTACT
            )
        if outcome is Outcome.ADVANCED:
            # The fence sits HERE: after the outcome, before anything is
            # earned. `compare` stays the pure seven-outcome machine — the
            # question the fence asks needs journal state its signature
            # rightly does not carry.
            self._refuse_abandoned_history(read, presented)
            # RETURNED, never written here. `_projection` still runs after this
            # and can refuse, and an advance written from inside the
            # classification would be a memory recording a head the very same
            # open went on to refuse.
            return outcome, _Earned(
                head=presented, kind=Kind.ADVANCE, level=Level.DESCENDANT
            )
        # UNCHANGED earns NOTHING. A read that touched the write path would
        # make every open a writer, and the byte-compare that proves it is the
        # rule keeping reads off that path.
        return outcome, None

    def _refuse_abandoned_history(
        self, read: JournalRead, presented: Head
    ) -> None:
        """Refuse an advance that descends through decreed-away history.

        **Identity-keyed, never ordinal spans.** The anchor set is
        ``(ordinal, record_hash)`` taken from the entries the journal holds in
        abandoned epochs — the same discriminator ``SAME_HEIGHT_FORK`` relies
        on. A span would be either vacuous or catastrophic: an operator who
        resets to 5 and lets the store re-advance mints a NEW 6, 7 and 8 inside
        the abandoned span, and fencing by ordinal would refuse every one of
        them forever. Only the exact records that were abandoned are fenced.

        Those entries are still readable in the file — epoch scoping excludes
        them from *K*, never from the read — which is what makes them available
        to be the anchor set at all.

        **Reach: every coordinate the descent passes, not just its head.** An
        abandoned branch that grew offline presents *N+3* while the journal's
        abandoned entry sits at *N+1*, and head-only checking waves it through.
        Asking ``head_at`` at each fenced anchor's own coordinate is the
        complete form of that check — an anchor can only be touched at its own
        ordinal — and it is spelled in contract ops, so the fence stays
        backend-neutral like the rest of the seam.

        **The lift rule, and the one place it is narrower than its wording.**
        A later decree supersedes an earlier abandonment, so an abandoned entry
        is fenced only while no reset has decreed at or above it — otherwise
        recovering the authentic history would be impossible and the ceremony
        would re-brick the store, which is L-3's shape exactly. The narrowing:
        only the CURRENT boundary decree lifts, not any later reset. Read
        literally, an intermediate decree would lift an entry that a subsequent
        decree then abandoned again — reset to 10, then reset back to 5, and
        the 10 is un-fenced by the decree the second ceremony overrode. The
        boundary is the one decree nothing has superseded, so it is the one
        that speaks. Fences more, never less.

        Cost: one verified walk per fenced anchor ordinal, on the ADVANCED
        branch only — which is rare by construction, because a writer journals
        its own commit.
        """
        abandoned = read.entries[: len(read.entries) - len(read.epoch)]
        if not abandoned:
            return
        decree = read.epoch[0] if read.epoch else None
        if decree is None or decree.kind is not Kind.TRUST_RESET:
            # No boundary decree means nothing was decreed away, so there is
            # nothing to fence — abandoned entries only exist behind a reset.
            return

        fenced: dict[int, set[str]] = {}
        for entry in abandoned:
            head = entry.head
            if head.lineage != presented.lineage:
                continue
            if head.ordinal <= decree.head.ordinal:
                continue  # lifted: the standing decree reaches at or above it
            if head.ordinal > presented.ordinal:
                continue  # cannot be on this history's path at all
            fenced.setdefault(head.ordinal, set()).add(head.record_hash)

        for ordinal in sorted(fenced):
            try:
                vouched = self._ledger.head_at(
                    Watermark(lineage=presented.lineage, ordinal=ordinal)
                )
            except Exception:  # noqa: BLE001 — no answer is no evidence of a touch
                continue
            if vouched.record_hash in fenced[ordinal]:
                raise AbandonedHistoryFenced(
                    f"{self._canonical} presents {_head_text(presented)}, whose "
                    f"verified history holds {vouched.record_hash} at ordinal "
                    f"{ordinal} — a record this machine's operator decreed away "
                    f"when they reset trust to ordinal {decree.head.ordinal}. "
                    "The chain is intact; that is not the question. Accepting it "
                    "would silently reverse the decree, and journaling the "
                    "advance would erase the evidence that it had been reversed. "
                    "If this history is the one to keep, run the trust-reset "
                    "ceremony to decree the recovered head — that is the "
                    "licensed way, and it records the gap"
                )

    def _descent(
        self, known: Head, presented: Head
    ) -> tuple[Head | None, BaseException | None]:
        """Was the presented head reached BY DESCENT from the remembered one?

        Answers with the head the ledger vouches for at the remembered
        coordinate, which is the ADVANCED/REWRITE discriminator, or ``None``
        when it will not vouch for anything there.

        Any failure of either walk answers ``None``, which classifies REWRITE,
        which refuses — the same one-directional argument :func:`_vouched_at`
        makes. A corrupt log therefore surfaces as a refusal with the
        corruption chained as the cause, so the operator is told both things:
        the comparison would not proceed, and here is what the walk hit.
        """
        try:
            self._ledger.verify(Full(through=presented))
            return (
                self._ledger.head_at(
                    Watermark(lineage=known.lineage, ordinal=known.ordinal)
                ),
                None,
            )
        except Exception as exc:  # noqa: BLE001 — see the docstring
            return None, exc

    def _degraded(
        self,
        read: JournalRead,
        presented: Head,
        refusal: IndeterminateComparison,
    ) -> Indeterminate:
        """**The IndeterminateComparison posture, and the argument for it.**

        The choice: does the seam surface an incomplete journal read as a
        refusal demanding an operator decision, or proceed under an explicitly
        labeled degradation? **It proceeds — after firing every refusal the
        incomplete read still soundly supports.** That is not the two-valued
        question it looks like, and the third answer is the whole of it.

        **Why not refuse.** An incomplete read persists until an operator
        acts. The journal is append-only and never rewritten, and the torn-
        tail guard preserves a crashed writer's fragment rather than removing
        it, so a line lost to an ordinary crash sits in ``skipped`` on every
        later read — recorded forever, weighed only until a trust-reset
        ceremony decrees past it, since the epoch-scoped weighting stops
        counting a loss the decree superseded. Until that ceremony, a seam
        that refused on it would make one crashed writer a store that never
        opens again — which is verbatim the argument WP1's amended ruling used
        to REJECT refusing on mid-file damage, one level down: "it made an
        ordinary crash a permanent incident, and it claimed a protection this
        location cannot deliver anyway — anyone able to corrupt the journal can
        delete it instead and be met with trust-on-first-use." Refusing here
        would re-impose at the composition boundary the exact verdict the
        module removed, which is WP1's own write-path lesson generalized: a
        rule relaxed in a module can be re-tightened by its caller, undoing the
        ruling without touching the code it was made about.

        **Why "proceed" alone would be dishonest, and what makes it not that.**
        A bound is not nothing. Two of the four refusals are still SOUND
        against it and both are raised here:

        * A presented head BELOW the bound is a rollback. The accepted head is
          at least the bound, so it is certainly above what is being presented.
        * A presented head at the bound's ordinal with a DIFFERENT hash is a
          same-height fork. The bound is a real entry — a head this machine
          accepted at that ordinal — and the store presents a different record
          there. The lost lines cannot make that agree.

        What remains indeterminate is the region at and above the bound:
        equal is not unchanged (it may be a rollback from the very entry the
        read missed) and higher is not advanced (nothing bounds the accepted
        head from ABOVE, so a lost entry may sit above both). Those two proceed
        answers are the ones that are unobtainable, and the seam does not claim
        either — :class:`Indeterminate` carries no outcome at all.

        **How never-silent is satisfied without a refusal.** Three ways, and
        none of them is a field somebody has to remember to read:

        * The report's degraded case is its own TYPE with no ``outcome``
          attribute, so no expression reads an answer off it without naming the
          case — WP1's unignorable-by-construction discipline, applied at the
          seam's own boundary.
        * The refusal that was not raised is carried on it, so a caller wanting
          the strict posture raises it and nothing has to be reconstructed.
        * **Nothing is written.** A degraded open journals no entry and records
          no binding, so the degradation never launders itself into a memory,
          and the bound never rises on evidence the read did not have. That
          also keeps ``HeadUnreadable`` clear of BLOCKING-2: a journal holding
          content none of which is readable is NOT granted the bootstrap
          entry that first contact gets, so it is never trusted on sight
          precisely because it became unreadable.

        The evidence is durable without being written: ``skipped`` is derived
        from the journal's own bytes, so every future open re-derives the same
        degradation. Nothing is lost by not recording it, and a record would be
        the one thing that could make a lost line look accounted for.

        And it stays honest under the adversarial reading. An attacker who can
        corrupt a line can delete the journal instead and get first contact,
        so a refusal here buys nothing against one — while it costs everything
        against a crash. The refusals that survive are the ones an attacker
        cannot evade by damaging the journal, because damage cannot lower a
        bound below what the surviving entries prove.
        """
        known = read.known
        if not isinstance(known, HeadLowerBound):
            # HeadUnreadable: no bound at all, so every comparison declines —
            # rollback included. There is nothing to compare against.
            return Indeterminate(
                presented=presented,
                refusal=refusal,
                skipped=read.skipped,
                at_least=None,
            )

        bound = known.at_least.head
        missed = "; ".join(known.skipped)
        # No lineage check: the journal is keyed by lineage, so every entry in
        # it is this lineage's. Replacement is the binding's question and it
        # was already asked, before this journal was opened.
        if presented.ordinal < bound.ordinal:
            raise HeadRollback(
                f"{self._canonical} presents ordinal {presented.ordinal}, and "
                f"this machine accepted at least ordinal {bound.ordinal} for "
                f"lineage {presented.lineage}. This read of the journal is "
                f"incomplete — it missed: {missed} — but a head below the "
                "bound is below the accepted head whatever the read missed. "
                "Locate a replica or backup at or above the accepted head; "
                "never move the witness backward to match the store"
            )
        if (
            presented.ordinal == bound.ordinal
            and presented.record_hash != bound.record_hash
        ):
            raise HeadFork(
                f"{self._canonical} presents {presented.record_hash} at "
                f"ordinal {presented.ordinal}, and this machine accepted "
                f"{bound.record_hash} at that same ordinal. Two different "
                "records claim one height. This read of the journal is "
                f"incomplete — it missed: {missed} — but the entry the bound "
                "rests on is one the journal does hold. Freeze both branches "
                "and collect evidence; never pick the taller branch"
            )
        return Indeterminate(
            presented=presented,
            refusal=refusal,
            skipped=read.skipped,
            at_least=bound,
        )

    def _projection(self, presented: Head) -> ProjectionReport | None:
        """Compare what the projection accounts for against the presented head.

        Comparing the watermark's ORDINAL is free and gives the whole
        classification — behind (ordinary staleness, catch-up's job), level, or
        ahead of the ledger, which is tail-truncation evidence that survives
        independently of the journal. Only when they disagree does the seam
        call ``head_at``, which turns the coordinate into a head the ledger
        vouches for; on the ahead branch it refuses rather than answering,
        because the log holds no record at that ordinal — and the refusal IS
        the answer.

        Behind is never a refusal. A projection that lags is the ordinary
        state of a store between a commit and its next catch-up, and refusing
        it would make the seam an availability problem rather than a witness.
        """
        if self._query is None:
            return None
        watermark = self._query.projected_through()
        if watermark is None:
            return ProjectionReport(
                agreement=ProjectionAgreement.ABSENT, watermark=None
            )

        if watermark.lineage != presented.lineage:
            # `head_at` refuses a watermark from another lineage with the
            # contract's own NotAuthority, which is exactly the right answer:
            # this projection is not a projection of this log. Letting it out
            # keeps the refusal the contract names rather than restating it.
            self._ledger.head_at(watermark)
            raise ProjectionAheadOfLedger(
                f"the projection beside {self._canonical} reports lineage "
                f"{watermark.lineage} while the log presents "
                f"{presented.lineage}, and the ledger vouched for the "
                "watermark anyway — the projection and the ledger disagree "
                "about which lineage this store is"
            )

        if watermark.ordinal > presented.ordinal:
            cause: BaseException | None = None
            try:
                self._ledger.head_at(watermark)
            except Exception as exc:  # noqa: BLE001 — the refusal IS the answer
                cause = exc
            raise ProjectionAheadOfLedger(
                f"the projection beside {self._canonical} accounts for "
                f"ordinal {watermark.ordinal} of lineage {watermark.lineage}, "
                f"but the log presents only ordinal {presented.ordinal}. A "
                "projection ahead of its ledger is what a truncated log looks "
                "like from the outside. Re-derive the projection from the "
                "ledger; never edit the ledger to match the projection"
            ) from cause

        return ProjectionReport(
            agreement=(
                ProjectionAgreement.LEVEL
                if watermark.ordinal == presented.ordinal
                else ProjectionAgreement.BEHIND
            ),
            watermark=watermark,
        )

    def _refusal_text(
        self,
        outcome: Outcome,
        known: HeadAttestation | None,
        presented: Head,
        descent_refusal: BaseException | None,
    ) -> str:
        """A refusal that names §11's response, not just the state.

        §11's recovery table maps each state to a named response, and carrying
        it in the message is what makes a refusal actionable at the moment it
        fires rather than an incident somebody has to go and look up.
        """
        responses = {
            Outcome.ROLLBACK: (
                "Locate a replica or backup at or above the accepted head; "
                "never move the witness backward to match the store"
            ),
            Outcome.SAME_HEIGHT_FORK: (
                "Freeze both branches and collect evidence under an explicit "
                "incident procedure; never pick the taller branch"
            ),
            Outcome.REWRITE: (
                "The chain in front of us may verify perfectly and still be a "
                "different history than the one accepted. Collect evidence "
                "before anything writes to this store"
            ),
            Outcome.LINEAGE_REPLACED: (
                "A different lineage is presented where a known one was "
                "expected; the licensed way to accept it is the explicit "
                "trust-reset ceremony, which records the gap"
            ),
        }
        remembered = _head_text(known.head if known is not None else None)
        seen = (
            ""
            if known is None
            else f", accepted {_observed_text(known)}"
        )
        why = (
            ""
            if descent_refusal is None
            else f" The descent walk did not complete: {descent_refusal}."
        )
        return (
            f"{outcome.value}: {self._canonical} presents "
            f"{_head_text(presented)}, and this machine remembers "
            f"{remembered}{seen}.{why} {responses[outcome]}"
        )

    # -- custody, witnessed ------------------------------------------------

    def mint(self, options: Mapping[str, Any]) -> Head:
        """Mint through the wrapper, and the bootstrap receipt is a consequence.

        Slice 4's sidecar gets its receipt by using the ordinary
        registry-opened ledger: there is no privileged path and no special API,
        which mirrors the sink's own rule that migration appends through
        ordinary ``append``. The level is ``mint`` — this process minted the
        genesis, so the journal is witnessed from genesis forward and slice 6's
        exit criterion can tell it apart from a store trusted on sight.
        """
        head = self._ledger.mint(options)
        try:
            bootstrap(
                head,
                level=Level.MINT,
                location=self._location,
                observed_at=self._clock(),
            )
        except (OSError, AttestationRefusal) as exc:
            raise NotWitnessed(
                f"the genesis for lineage {head.lineage} is COMMITTED at "
                f"{self._canonical}, and its bootstrap receipt could not be "
                f"written: {exc}. The store exists and this machine has no "
                "memory of it, so its next open is first contact rather than "
                "the mint-level receipt slice 6 checks for",
                head=head,
            ) from exc
        return head

    def append(
        self, expected: Head | None, drafts: Sequence[RecordDraft]
    ) -> Commit:
        """Append, then journal the commit — §D.3's O(1)-unchanged-open design.

        A successful append returns a ``Commit`` whose ``before`` and ``after``
        are full heads, compared under the full-head fence: the writer already
        holds the strongest descent evidence there is, so recording it at
        ``Level.COMMIT`` means the NEXT open sees the presented head equal to
        the remembered one and takes the O(1) unchanged branch. Without this
        the next open would observe an advance and pay a verified walk for
        evidence this process had already gathered and thrown away.
        """
        commit = self._ledger.append(expected, drafts)
        self._witness(commit)
        return commit

    def replicate(
        self, expected: Head | None, records: Sequence[Mapping[str, Any]]
    ) -> Commit:
        """Replicate, then journal the commit. Same fence, same evidence.

        Replication assigns no coordinates — it inserts an exact
        pre-coordinated suffix — but it goes through the same full-head compare,
        so the commit it returns is the same evidence an append's is and it is
        recorded at the same level.
        """
        commit = self._ledger.replicate(expected, records)
        self._witness(commit)
        return commit

    def _witness(self, commit: Commit) -> None:
        """Journal a commit, or say loudly that it went unwitnessed.

        The append has already landed when this runs, so a failure here cannot
        be reported as a failed append — the store has advanced past its
        witness, and §05's ``committed`` versus ``witnessed`` distinction is
        exactly the thing that must not be collapsed into "saved". Raising
        :class:`NotWitnessed` is the never-silent mechanism, and its type says
        the data is safe.
        """
        try:
            append_entry(
                HeadAttestation(
                    head=commit.after,
                    kind=Kind.ADVANCE,
                    level=Level.COMMIT,
                    observed_at=self._clock(),
                    location=self._canonical,
                )
            )
        except (OSError, AttestationRefusal) as exc:
            raise NotWitnessed(
                f"{len(commit.records)} record(s) are COMMITTED at "
                f"{self._canonical} through {_head_text(commit.after)}, and "
                f"the journal entry for them could not be written: {exc}. The "
                "store has advanced past its witness, so the next open will "
                "observe an advance and pay a verified walk for it",
                head=commit.after,
                commit=commit,
            ) from exc

    # -- reads, delegated unchanged ----------------------------------------

    def head(self, lineage: str | None = None) -> Head:
        """The currently complete head."""
        return self._ledger.head(lineage)

    def head_at(self, watermark: Watermark) -> Head:
        """Resolve a projection's watermark into the verified head it names."""
        return self._ledger.head_at(watermark)

    def read(self, coordinate: int) -> Mapping[str, Any]:
        """The exact record, after establishing its membership in the lineage."""
        return self._ledger.read(coordinate)

    def scan(
        self, *, after: int | None = None, through: Head | None = None
    ) -> Any:
        """An ordered, consistent prefix range and no later record."""
        return self._ledger.scan(after=after, through=through)

    def verify(self, scope: VerifyScope) -> Head:
        """Verify through a named head; return the head the claim covers."""
        return self._ledger.verify(scope)

    def export(self, *, through: Head, codec: str) -> ExportedPrefix:
        """Deterministic portable records plus a manifest, for a prefix."""
        return self._ledger.export(through=through, codec=codec)

    def capabilities(self) -> Capabilities:
        """The wrapped backend's self-report, unchanged.

        Not this wrapper's. Everything ``Capabilities`` describes — profiles,
        durability, verification levels, concurrency, codecs — is a property of
        the backend holding the bytes, and the seam changes none of them.
        Amending the report to mention the witness would be advertising a
        guarantee at the layer that does not provide it.
        """
        return self._ledger.capabilities()


def _observed_text(entry: HeadAttestation) -> str:
    """When and on what evidence a remembered head was accepted."""
    return f"{entry.kind.value}/{entry.level.value} at {entry.observed_at}"
