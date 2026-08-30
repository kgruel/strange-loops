"""arrival_head_attestation — remembering a lineage's head across opens.

Slice 3 of the arrival break (``design:arrival-break-slice3-witness-minimum``).
The design of record is ``docs/scratch/arrival-break/slice3-design-proposal.md``
§§A-C; the protocol it implements a minimum of is
``docs/architecture/arrival/witness-protocol.html``.

**What this module is for.** A backend can prove a log is internally consistent
— genesis validates, every record links to its predecessor, the head is the
last one. It cannot prove that the log in front of it is the *same* log this
machine accepted yesterday, because every fact it could consult lives inside
the boundary an attacker or a restore would move. So the memory of what was
accepted has to live somewhere a single restore of the store cannot also
revert, and comparing the two is what turns "this log is well-formed" into
"this log is the one we know".

**stdlib and** :mod:`engine.arrival_contract` **only.** Not a taste rule: this
journal exists to stay readable when the store it witnesses cannot be opened at
all, and a module that dragged the file codec and sqlite3 behind it would tie
its own readability to the health of the thing it is judging. The classifier is
pure, the journal is ``pathlib``/``json``/``os``, and
``test_reading_a_head_journal_does_not_drag_the_adapter_in`` pins it.

**The name is the Rule 18 join.** ``arrival*.py`` under ``engine/`` is globbed
by ``test_every_arrival_named_engine_module_is_scanned``, so naming the module
this way enrolls it in the arrival vocabulary ratchet by birth rather than by a
``_SCAN_TARGETS`` edit somebody has to remember.

**Vocabulary hazard.** "Attestation" already means something else here:
``FactAttestation``/``TickAttestation`` are the *signed* receipt on a committed
row. What this module writes is unsigned and local, so its serialized ``type``
is ``arrival-head-observation`` — distinct types, distinct serialization names
— which also leaves the future signed corpus unencumbered. Nothing here is
signed: no ``sig``, ``issuer``, ``key_id`` or chaining field, and their absence
is the point rather than an omission. An empty ``sig`` field would advertise a
claim this slice does not make.

**What is deliberately not here.** The seam that calls this on every open, the
evidence gatherer that walks a backend for descent, the audit and trust-reset
producers, and staleness reporting are WP3's. The conformance vectors are
WP2's. This module holds the record, the journal, and the judgment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .arrival_contract import Head

__all__ = [
    "ABSENT_STORE_REFUSALS",
    "AbsentStoreOutcome",
    "AttestationRefusal",
    "BindingProbeUnanswered",
    "BindingsUnreadable",
    "EstablishedHead",
    "HeadAttestation",
    "HeadFork",
    "HeadLowerBound",
    "HeadUnreadable",
    "HeadRewrite",
    "HeadRollback",
    "IndeterminateComparison",
    "JournalEquivocation",
    "JournalRead",
    "JournalUnreadable",
    "Kind",
    "Level",
    "LineageReplaced",
    "Outcome",
    "ProbeUnanswered",
    "REFUSALS",
    "StoreLost",
    "UnsafeLineageName",
    "append_entry",
    "bindings_path",
    "bound_lineage",
    "compare",
    "compare_absent_store",
    "heads_dir",
    "journal_path",
    "last_entry",
    "parse_journal_lines",
    "entry_identity",
    "read_journal",
    "record_binding",
    "refusal_for",
    "state_root",
    "storage_advice",
    "unaccounted_heads",
]


# ---------------------------------------------------------------------------
# Typed refusals — rooted HERE, not under ContractRefusal
# ---------------------------------------------------------------------------


class AttestationRefusal(Exception):
    """Root of the head-comparison refusals.

    Deliberately NOT a subclass of
    :class:`~engine.arrival_contract.ContractRefusal`, which is the arbiter's
    ruling 1 on the slice-3 design and applies the slice-2 narrow-form ruling
    in its own words: the contract root "covers what the contract asserts, no
    more". Rollback, fork, rewrite and replacement are conditions
    ``witness-protocol.html`` names, about a layer that sits *above* the
    backend contract and compares two heads it obtained through it —
    ``backend-contract.html`` does not name one of them. Joining the contract
    root would assert that every conforming backend owes these refusals, and
    only a contract-text line can make that claim.
    """


class HeadRollback(AttestationRefusal):
    """The presented head sits below the head this machine last accepted.

    §11's response is to locate a replica or backup at or above the witnessed
    head. Never move the witness backward to match the store: that is the
    silent re-acceptance the journal exists to prevent, and the only licensed
    way down is the explicit trust-reset ceremony (:attr:`Kind.TRUST_RESET`).
    """


class HeadFork(AttestationRefusal):
    """Two different records claim the same ordinal in the same lineage.

    Named ``HeadFork`` rather than ``SameHeightFork`` because
    ``arrival_contract.SameHeightFork`` already exists and means something
    adjacent but different — replication found a conflicting record at the
    height it was about to fill. This is a comparison of two heads. Same
    ratified *state* name (the outcome string stays ``same-height-fork``),
    different operation, different type: the state machine's vocabulary is
    preserved where it is normative and the Python names stay unambiguous
    where a collision would bite.

    §11's response is to freeze both branches and collect evidence. Never pick
    the taller branch — height is not evidence of continuity.
    """


class HeadRewrite(AttestationRefusal):
    """The head advanced, but the record at the known ordinal is not the known one.

    The chain in front of us may verify perfectly and still be a different
    history than the one we accepted. Checking only that a walk reached the
    presented head answers nothing about continuity with what came before,
    which is precisely the "never accept height as proof of continuity"
    failure.
    """


class LineageReplaced(AttestationRefusal):
    """A different lineage is presented where a known one was expected.

    Where the expected lineage is declared, the backend's own
    ``NotAuthority`` fires first and is already correct. This exists because
    the classifier owns the row the vectors exercise, and because a caller
    that reached the comparison without a declared lineage still needs it.
    """


class StoreLost(AttestationRefusal):
    """The log is gone, but the journal remembers a head for it.

    The attack matrix's "delete the store and every backup" row, where the
    witness proves what was *lost* rather than its contents. It must refuse,
    and in particular it must never permit a silent re-mint under a remembered
    lineage: a fresh genesis at a location whose journal remembers ordinal
    4217 is a replacement wearing the old name. Recovery is the explicit
    trust-reset ceremony.
    """


class JournalEquivocation(AttestationRefusal):
    """The journal itself holds two incompatible histories.

    Two entries at the maximum ordinal of the current trust epoch with
    different record hashes. The journal has recorded both and it is not the
    journal's place to choose between them.
    """


class JournalUnreadable(AttestationRefusal):
    """There is nothing to parse: the journal cannot be read as text at all.

    A directory where the journal should be, a permission wall, bytes that
    are not text. Distinct from an *absent* journal, which is first contact,
    and from a journal whose *content* cannot be read, which is
    :class:`HeadUnreadable`. Raised rather than let out as the underlying
    ``OSError`` so that a caller catching :class:`AttestationRefusal` does not
    have a builtin escape past it.

    **This is the only thing that raises it, and the scope has narrowed
    twice.** It once covered damage above the last line, then entries with no
    header. Both are now tolerated: an unreadable line is skipped and
    reported, a missing header is reported as an absence, and in each case the
    loss is carried in the result type (:class:`HeadLowerBound`) instead of
    converted into a verdict. Refusing made an ordinary crash a permanent
    incident, and it claimed a protection this location cannot deliver anyway
    — anyone able to corrupt the journal can delete it instead and be met with
    trust-on-first-use. Where a weakened claim is available, a refusal is a
    verdict the evidence does not support.
    """


class IndeterminateComparison(AttestationRefusal):
    """A full comparison was asked of a journal whose read was incomplete.

    See :class:`HeadLowerBound` for what "incomplete" means and why the term
    is not "unreadable".

    Not a claim about the store. The journal's own record of what this machine
    accepted has a hole in it, so "unchanged" is a question this journal can no
    longer answer — while "rollback" is one it still can, for anything below
    the bound. Raised by :meth:`JournalRead.established_head` so the cheap
    unchanged shortcut cannot be taken by a caller who simply forgot to look.
    """


class ProbeUnanswered(AttestationRefusal):
    """Storage would not answer, so a check a caller depends on did not happen.

    The general form, named because the defect it guards against is a SHAPE
    rather than a site: a probe whose own failure gets read as the absence of
    what it was probing for. Evidence absent is not absence of evidence, and a
    probe that conflates the two answers its whole question wrongly, in the
    acceptance direction (``finding:s3-fence-probe-fails-open``,
    ``finding:s3wp3-binding-probes-fail-acceptance-side``).

    **The line is CONTENT versus STORAGE, and that is the whole of it.** This
    family means the bytes never arrived: the read could not get an answer out
    of storage at all. Its sibling :class:`BindingsUnreadable` means the bytes
    DID arrive and could not be interpreted. That split is decidable from where
    the failure happened, which is why it can be a type.

    **It used to promise that retrying is the remedy, and that promise was not
    the type's to make.** Transient-versus-permanent is not decidable from an
    exception class: ``IsADirectoryError`` arrives through the same ``OSError``
    door as a passing I/O fault, and retrying a directory resolves nothing. A
    remedy taxonomy is a verdict claim, and it falls to the next errno
    (``finding:s3-refusal-family-remedy-promise-undecidable``).

    So the remedy is **advisory prose in the message**, chosen per cause, and
    the type asserts only what the read lacks. Both families refuse, so a
    misfiled hint costs an operator some convenience and never costs an
    acceptance — which is exactly why advice can be offered here where a
    promise could not.

    An ABSENT input is never one of these. "There is no bindings file" and "the
    log does not exist yet" are answers, and correct ones; only an input that
    exists and will not yield leaves the question open.

    It lives here rather than in the seam because the binding unit does, and
    because a subclass of it has to be raisable from this module.
    """


def storage_advice(exc: BaseException) -> str:
    """What an operator might try, given how storage refused.

    Advisory, never a claim the type makes. Each arm is a guess that costs
    convenience if it is wrong, which is the standard prose can meet and a type
    could not.
    """
    if isinstance(exc, IsADirectoryError):
        return (
            "a directory sits where this file should be — remove it; retrying "
            "will not resolve that"
        )
    if isinstance(exc, PermissionError):
        return "check the permissions on the path, then retry the open"
    return "the failure may be transient — retry the open"


class BindingsUnreadable(AttestationRefusal):
    """The bytes arrived and could not be interpreted as bindings.

    The CONTENT half of the split :class:`ProbeUnanswered` describes: bytes
    that are not UTF-8, a line that is not JSON, and a line that is JSON but
    carries nothing a binding could be read out of. All three were read
    successfully and none of them says anything about which lineage a location
    presented.

    Decidable from where the failure happened rather than from a guess about
    whether it will recur, which is what makes it a type at all — the earlier
    split by remedy was not
    (``finding:s3-refusal-family-remedy-promise-undecidable``).

    The parallel one file over is :class:`JournalUnreadable`, and it is the
    same claim about the same kind of loss. Raised rather than let out as the
    underlying ``UnicodeDecodeError`` or ``ValueError`` so a caller catching
    :class:`AttestationRefusal` has no builtin escape past it
    (``finding:s3-bindings-decode-escapes-untyped``).

    DELETE IN SLICE 5 with the binding unit it serves.
    """


class BindingProbeUnanswered(ProbeUnanswered):
    """The location binding could not be read, so replacement cannot be ruled out.

    DELETE IN SLICE 5 with the binding unit it serves. :class:`ProbeUnanswered`
    survives — it names a shape that outlives any one probe — so the sweep
    removes a leaf, not the concept.
    """


class UnsafeLineageName(AttestationRefusal):
    """This lineage cannot be used as a journal filename.

    ``lin`` is validated only as a non-empty string on the wire, and while
    ``mint_lineage()`` produces a ULID, a foreign or hostile genesis need not.
    Scope-the-claim: this is a location claim ("this cache cannot key on that
    string"), NOT a verdict about the store — refusing to resolve a path says
    nothing about whether the store is trustworthy.
    """


# ---------------------------------------------------------------------------
# The observation record (§B.2)
# ---------------------------------------------------------------------------


class Kind(Enum):
    """Why this entry exists."""

    BOOTSTRAP = "bootstrap"  # the first entry for a lineage
    ADVANCE = "advance"  # the head moved
    AUDIT = "audit"  # a full chain-plus-projection audit ran
    TRUST_RESET = "trust-reset"  # an operator ceremony re-established trust


class Level(Enum):
    """What evidence backed this entry's head.

    The one addition to §04's field table, and it is the scope-the-claim
    field: it states how much was actually established, so an entry can never
    be read as a stronger claim than the evidence behind it.
    """

    MINT = "mint"  # this process minted the genesis
    FIRST_CONTACT = "first-contact"  # trust on first use; nothing was proven
    COMMIT = "commit"  # appended by this process under the full-head fence
    DESCENDANT = "descendant"  # a verified suffix walk from the previous head
    FULL = "full"  # verified from genesis


@dataclass(frozen=True)
class HeadAttestation:
    """One observation of a lineage's head, at a moment, with its evidence.

    Field choices, against §04's table:

    * **The whole** :class:`~engine.arrival_contract.Head`, **always.** §04's
      lineage/ordinal/record_hash are exactly that type, and reusing it rather
      than restating three fields means this comparison cannot drift from the
      backend's own notion of a head.
    * **Counts omitted** — projection corroboration smuggled into a custody
      claim. Absent from the type, not optional-and-unset.
    * **Signed fields absent**, per the module docstring.
    * **protocol/wire omitted from the record**, carried by the file header:
      they are properties of the journal, not of each entry, and a field
      nothing reads is how speculative grammar ossifies.
    * **observed_at kept.** It is what makes a refusal actionable ("your
      remembered head is from three weeks ago") and what answers audit
      staleness. Witness metadata, never ledger order.

    ``location`` is diagnosis only and is **never** a key: journals are keyed
    by lineage so that a worktree, a move, or a copy still finds the lineage's
    memory. ``note`` carries the trust-reset gap description and the audit
    result.
    """

    head: Head
    kind: Kind
    level: Level
    observed_at: float
    location: str = ""
    note: str = ""
    follows: tuple[int, str] | None = None
    """The PHYSICAL LINE and identity of the entry this one was appended after
    — REQUIRED on a trust reset, ``None`` on every other kind.

    ``(0, "")`` is the honest claim for a reset that opens an empty journal:
    line numbers start at 1, so zero says "there was no predecessor" rather
    than "no claim was made", which is what ``None`` says and what makes an
    unbound reset invalid.

    **Not the deferred** ``previous``. That one is the signed grammar's
    per-entry chain link over the whole journal, and it stays absent: this is
    unsigned, it is carried by exactly one kind, and it makes exactly one
    claim — where this reset sat, and what sat in front of it.

    It exists because a trust reset was REPLAYABLE, and it took two rounds to
    get right. An entry is just bytes in an append-only file, so re-appending
    an old reset re-opened the epoch it had closed
    (``finding:s3wp3-trust-reset-replay``). Binding the reset to its
    predecessor's IDENTITY closed the one-line replay — and sol r2 defeated
    that too, by replaying the historical predecessor AND the reset as an
    ordered suffix, which reproduces the recorded identity exactly.

    **The position is what closes the class rather than the instance.** Copied
    bytes appended later always land at a later line, so a stale position
    claim is unavoidable no matter how much surrounding context is replayed
    with them: the two-line replay, a full-suffix replay and a wholesale
    journal concatenation all fail the same check for the same reason. Identity
    stays in the pair because position alone would accept a truncation that
    happens to realign a different entry onto the recorded line.

    Physical LINE, never an index among parsed entries: an index is a judgment,
    and a future build that classifies one line differently renumbers every
    entry after it and silently voids every reset bound below.

    The residual, stated rather than implied: truncating the journal and then
    replaying realigns positions, and this cannot detect it. That is
    journal-rollback territory — the known bound of unsigned local state, the
    same class as deleting the journal outright and being met with
    trust-on-first-use. The named upgrade is the deferred signed grammar, whose
    chained entries make a truncation detectable rather than merely
    disbelieved.
    """



# ---------------------------------------------------------------------------
# The comparison state machine (§C)
# ---------------------------------------------------------------------------


class Outcome(Enum):
    """The seven rows of the comparison.

    Seven for six states because §07 lists first contact separately from the
    five comparisons. The outcome *values* are what the conformance vectors
    pin — never a Python exception type, for the reason the replicate family
    gives: naming one implementation's exception family in a language-neutral
    vector pins that family on every other implementation.
    """

    FIRST_CONTACT = "first-contact"  # proceed, trust on first use, labeled
    UNCHANGED = "unchanged"  # proceed
    ADVANCED = "advanced"  # proceed
    ROLLBACK = "rollback"  # refuse
    SAME_HEIGHT_FORK = "same-height-fork"  # refuse
    REWRITE = "rewrite"  # refuse
    LINEAGE_REPLACED = "lineage-replaced"  # refuse


class AbsentStoreOutcome(Enum):
    """The §D.4 split for a location whose log is not there at all.

    Deliberately a separate enum rather than two more :class:`Outcome` rows.
    :func:`compare` has exactly seven rows and the vectors pin those; an
    absent store is a different question, asked before there is a head to
    present, and folding it in would make "the seven rows" mean nine.
    """

    PRE_GENESIS = "pre-genesis"  # proceed — this is the sidecar about to mint
    STORE_LOST = "store-lost"  # refuse — the journal remembers what is gone


def compare(
    known: HeadAttestation | None,
    presented: Head,
    at_known: Head | None,
) -> Outcome:
    """Judge a presented head against the one this machine remembers.

    Pure, stdlib-only, no I/O — which is what makes it directly
    vector-testable and what keeps the vectors free of any implementation's
    exception family. This function only judges; the caller gathers.

    ``at_known`` is the head the ledger vouches for at *K*'s coordinate, or
    ``None`` when it will not vouch for anything there. It is the
    advanced-versus-rewrite discriminator and it is the whole reason a walk
    that merely reaches the presented head is not enough.

    Guard order is load-bearing. Lineage is checked before any ordinal
    arithmetic, because comparing heights across two different lineages is
    comparing two unrelated number lines. ``at_known`` is consulted only on
    the ascending branch: on the unchanged branch there is nothing to
    discriminate, and asking would make the dominant case pay for evidence it
    does not need.
    """
    if known is None:
        return Outcome.FIRST_CONTACT

    remembered = known.head
    if presented.lineage != remembered.lineage:
        return Outcome.LINEAGE_REPLACED
    if presented == remembered:
        return Outcome.UNCHANGED
    if presented.ordinal < remembered.ordinal:
        return Outcome.ROLLBACK
    if presented.ordinal == remembered.ordinal:
        # Equal ordinal, and not equal heads, so the hashes differ.
        return Outcome.SAME_HEIGHT_FORK
    if at_known != remembered:
        return Outcome.REWRITE
    return Outcome.ADVANCED


def compare_absent_store(known: HeadAttestation | None) -> AbsentStoreOutcome:
    """Judge a location whose log is absent or empty (§D.4).

    ``verify(Open())`` on a missing or empty log refuses with
    ``GenesisRefused``, so the seam must branch on that rather than treat it
    as corruption — an absent store is the ordinary state of a location a
    moment before it is minted into.

    The split is on memory, not on the store: with nothing remembered this is
    pre-genesis and refusing would make minting impossible; with a head
    remembered it is a loss, and proceeding would license a silent re-mint
    under a remembered lineage.
    """
    return (
        AbsentStoreOutcome.PRE_GENESIS
        if known is None
        else AbsentStoreOutcome.STORE_LOST
    )


#: Which refusal each refusing outcome raises. The mapping lives here so the
#: seam does not re-implement the posture table, and so "which outcomes
#: refuse" is one enumerable fact rather than a chain of ``if`` statements in
#: whatever calls the classifier.
REFUSALS: dict[Outcome, type[AttestationRefusal]] = {
    Outcome.ROLLBACK: HeadRollback,
    Outcome.SAME_HEIGHT_FORK: HeadFork,
    Outcome.REWRITE: HeadRewrite,
    Outcome.LINEAGE_REPLACED: LineageReplaced,
}

#: The same table for the absent-store split.
ABSENT_STORE_REFUSALS: dict[AbsentStoreOutcome, type[AttestationRefusal]] = {
    AbsentStoreOutcome.STORE_LOST: StoreLost,
}


def refusal_for(
    outcome: Outcome | AbsentStoreOutcome,
) -> type[AttestationRefusal] | None:
    """The refusal this outcome raises, or None if it proceeds."""
    if isinstance(outcome, AbsentStoreOutcome):
        return ABSENT_STORE_REFUSALS.get(outcome)
    return REFUSALS.get(outcome)


# ---------------------------------------------------------------------------
# Where the journal lives (§A.3)
# ---------------------------------------------------------------------------

#: Conservative: a leading alphanumeric, then alphanumerics, dot, dash,
#: underscore. A ULID passes; a path separator, a leading dot, an empty
#: string, a traversal segment and a name long enough to trouble a filesystem
#: all fail. Narrow by intent — widening it later is additive, and every
#: character admitted is a character some filesystem treats specially.
_SAFE_LINEAGE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

#: Names the heads directory already spends on something else. ``bindings``
#: is the transitional binding file below, and a lineage literally named
#: "bindings" would otherwise write its observations into it. Compared
#: case-folded because the filesystems this runs on are commonly
#: case-insensitive, so ``BINDINGS`` collides just as hard.
_RESERVED_LINEAGE_NAMES = frozenset({"bindings"})

#: The journal grammar version. A literal rather than an import of
#: ``engine.arrival.GRAMMAR_VERSION``: reaching for it would drag the whole
#: file codec into a module whose readability must not depend on it, and the
#: two version each other independently anyway — this is the journal's
#: grammar, not the record grammar.
_JOURNAL_VERSION = 1

#: Written into the header so a journal's hash derivation is RECORDED. §B.3
#: asks for more than that — that a v1 journal never be silently compared
#: against a v2 head whose hashes derive differently — and nothing reads these
#: back yet, so the promise is only half kept. Stated rather than implied,
#: because a comment claiming the enforcement would be the same stale-prose
#: defect this file has already paid for three times. The forcing consumer is
#: wire v2; sol r1 made it concrete, since a v2-shaped header is now
#: recognized as a header and its version ignored.
_PROTOCOL_VERSION = 1
_WIRE_VERSION = 1

#: The serialized ``type``. Never bare "attestation" — see the module
#: docstring's vocabulary note.
_OBSERVATION_TYPE = "arrival-head-observation"


def state_root() -> Path:
    """The per-user state root for loops, honoring ``XDG_STATE_HOME``.

    A *state* root, not a config root, and that separation is the whole
    threat-model argument: the live config-level stores are themselves under
    ``$XDG_CONFIG_HOME/loops``, so a memory kept there would share a restore
    boundary with the very stores it witnesses. Same for a sibling file beside
    the store, for ``.loops/state/``, and for git tracking as a sole home. A
    state root is outside all of them.

    Follows ``vertex_reader._loops_home()``'s idiom for the config root, with
    the standard ``~/.local/state`` fallback, so tests can point it at a
    temporary directory the way the CLI tests already do for config.
    """
    xdg = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(xdg) / "loops"


def heads_dir() -> Path:
    """Where head journals live: one file per lineage."""
    return state_root() / "heads"


def journal_path(lineage: str) -> Path:
    """The journal for this lineage, refusing a name it cannot safely key on.

    **Keyed by lineage, not by path**, and that is the load-bearing half of
    the design. A worktree gets no project store of its own, so a path-keyed
    cache would manufacture a fresh first contact per worktree — silent
    re-acceptance through the back door, on the most ordinary operation there
    is. A restored old copy opened at a *new* path still presents its lineage,
    still finds this journal, and is still classified a rollback.
    """
    if not _SAFE_LINEAGE.match(lineage) or lineage.casefold() in _RESERVED_LINEAGE_NAMES:
        raise UnsafeLineageName(
            f"lineage {lineage!r} cannot be used as a head-journal filename; "
            "this says nothing about the store, only that the cache cannot "
            "key on that string"
        )
    return heads_dir() / f"{lineage}.jsonl"


# ---------------------------------------------------------------------------
# Serialization (§B.3)
# ---------------------------------------------------------------------------


def _header_line() -> str:
    """The first line of a new journal: what this file is."""
    return (
        json.dumps(
            {
                "v": _JOURNAL_VERSION,
                "type": _OBSERVATION_TYPE,
                "protocol": _PROTOCOL_VERSION,
                "wire": _WIRE_VERSION,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _entry_line(entry: HeadAttestation) -> str:
    """One entry as one line.

    ``location`` and ``note`` are omitted when empty. They are diagnosis, so
    absent and empty carry the same (absence of a) claim, and leaving them out
    keeps a line that is appended on every commit small.
    """
    record: dict[str, object] = {
        "v": _JOURNAL_VERSION,
        "kind": entry.kind.value,
        "level": entry.level.value,
        "lineage": entry.head.lineage,
        "ordinal": entry.head.ordinal,
        "record_hash": entry.head.record_hash,
        "observed_at": entry.observed_at,
    }
    if entry.location:
        record["location"] = entry.location
    if entry.note:
        record["note"] = entry.note
    if entry.follows is not None:
        record["follows"] = [entry.follows[0], entry.follows[1]]
    return json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"


def _follows_of(raw: object) -> tuple[int, str] | None:
    """A predecessor claim off the wire, or None if there is not a valid one.

    A malformed claim reads as ABSENT rather than as a claim that fails to
    match. Both end at the same place — the reset is not honored — and absent
    is the honest description of bytes this build cannot read as a pair.
    """
    if (
        isinstance(raw, list)
        and len(raw) == 2
        and isinstance(raw[0], int)
        and not isinstance(raw[0], bool)
        and isinstance(raw[1], str)
    ):
        return (raw[0], raw[1])
    return None


def _parse_entry(raw: object) -> HeadAttestation | None:
    """One decoded JSON line as an entry, or None if this build cannot read it.

    None means "a later build wrote something this one does not understand",
    and the caller skips and reports it. It does **not** mean malformed —
    malformed JSON never reaches here.

    §B.3's forward-compatibility promise, **as re-scoped by the gate**: an
    entry from a later build is skipped and reported, never refused *on its
    own account*. That much survives verbatim, and it is what keeps a shared
    journal from bricking an older build. What it never licensed is the
    stronger reading — that a comparison holding **zero** readable evidence
    should proceed. Declining there refuses no entry; it declines a question
    nothing left in the journal can answer, and the alternative is
    trust-on-first-use granted precisely because the journal became
    unreadable (:class:`HeadUnreadable`).

    The version-skew consequence, stated rather than hidden: an older build
    reading a purely newer journal declines its comparisons. Resolution is
    operator work — run the newer build, or the trust-reset ceremony.

    Unknown *fields* need no handling at all: the journal is append-only and
    never rewritten, so fields this build does not name are preserved on disk
    by construction and ignored here.
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("v") != _JOURNAL_VERSION:
        return None
    if "kind" not in raw:
        # NOT a header — :func:`_classify` has already taken those, and this
        # function is only reached by lines it judged entry-shaped. A kindless
        # object arriving here is one this build cannot name, and the caller
        # reports it as a skipped line rather than absorbing it silently,
        # which is the whole of BLOCKING-1.
        return None
    try:
        kind = Kind(raw["kind"])
        level = Level(raw["level"])
    except (KeyError, ValueError):
        return None
    lineage = raw.get("lineage")
    ordinal = raw.get("ordinal")
    record_hash = raw.get("record_hash")
    observed_at = raw.get("observed_at")
    if (
        not isinstance(lineage, str)
        or not isinstance(ordinal, int)
        or isinstance(ordinal, bool)
        or not isinstance(record_hash, str)
        or not isinstance(observed_at, (int, float))
        or isinstance(observed_at, bool)
    ):
        return None
    return HeadAttestation(
        head=Head(lineage=lineage, ordinal=ordinal, record_hash=record_hash),
        kind=kind,
        level=level,
        observed_at=float(observed_at),
        location=raw["location"] if isinstance(raw.get("location"), str) else "",
        note=raw["note"] if isinstance(raw.get("note"), str) else "",
        follows=_follows_of(raw.get("follows")),
    )


# ---------------------------------------------------------------------------
# Reading the journal (§B.3's three read rules)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstablishedHead:
    """*K*, from an epoch every line of which was readable.

    The head, full stop: a presented head equal to this one IS unchanged, and
    all seven comparison rows are sound against it.
    """

    entry: HeadAttestation


@dataclass(frozen=True)
class HeadLowerBound:
    """*K* is **at least** this, because the read was INCOMPLETE.

    **"Incomplete read" is this module's one term for the weakening
    condition, and this is its definition:** the read needed something it did
    not get — a line it could not parse, a line it could not classify, an
    entry written by a later build, or the header itself. :attr:`JournalRead.skipped`
    :attr:`skipped` records every skip, and the WEAKENING ones — every cause
    except a literal re-assertion — are what produce this type.
    Prose here has drifted four times by naming one cause as though it were
    the definition (unreadable lines, then damage past the last line, then a
    missing header); the term is deliberately about what the read LACKS
    rather than about why, so that a new cause joins it without new
    vocabulary.

    Not "unreadable" — that word belongs to text this build cannot read at
    all (:class:`JournalUnreadable`, :class:`HeadUnreadable`), and a journal
    with a missing header and every entry readable is incomplete without
    being unreadable in any part. Not "unaccounted" either: :func:`unaccounted_heads`
    already means heads the STORE can no longer account for, a different
    question about a different party.

    Whatever the read missed carries no information about the ordinal it
    held, so the readable entries bound the accepted head from below and
    nothing bounds it from above. Deliberately **no** ``entry`` attribute: the
    field is named ``at_least`` so that no expression reaches a head from this
    type without naming the weaker claim, and so a caller cannot reach one
    uniformly across both cases.

    What a bound can and cannot answer:

    * **Sound.** A presented head *below* the bound is a rollback — the
      accepted head is at least the bound, so it is certainly above what is
      being presented.
    * **Unsound, and this is the trap.** A presented head *equal to* the bound
      is not unchanged; it may be a rollback from the very entry the read
      missed.
    * **Unsound for the same reason, one step further.** A presented head
      *above* the bound is not an advance either. Nothing bounds the accepted
      head from above, so a head at ordinal 95 may still sit below a lost
      entry at 200 — and descent verified from the bound says nothing about
      an entry that was never on the walk. Both proceed answers are
      unobtainable; only the refusal below the bound survives.

    **Gathering evidence from the store does not resolve any of this** — a
    walk verifies the store's own chain, and the missing fact is about what
    this machine previously ACCEPTED, which the store never knew. Recovering
    it means repairing the journal or running the trust-reset ceremony, both
    of which are operator work.
    """

    at_least: HeadAttestation
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class HeadUnreadable:
    """The journal claimed content and **none of it** could be read.

    The third state, and it is not the absence of one. An empty journal says
    "nothing was ever accepted here" and first-contact TOFU is the honest
    answer to it. A journal holding lines this build cannot read says
    something else entirely: heads WERE accepted, and their ordinals are
    exactly what has been lost. Collapsing the two would let a journal be
    trusted on first use precisely because it became unreadable, which is the
    silent re-acceptance every rule in this module exists to prevent
    (``finding:s3wp1-gate-all-entries-unreadable-silent-tofu``).

    Carries no ordinal, deliberately and by construction. :class:`HeadLowerBound`
    can at least refuse anything below its bound; here there is no bound, so
    **every** comparison declines — rollback included. There is nothing to
    compare against.
    """

    skipped: tuple[str, ...]


@dataclass(frozen=True)
class JournalRead:
    """Everything a caller needs from one pass over a journal.

    One structure because the ratified scope's three artifacts — a cached
    head, a bootstrap receipt at migration, and a periodic full-audit entry —
    dissolve into one append-only journal: the remembered head is the
    highest-ordinal entry, the bootstrap receipt is the first entry, an audit
    entry is an entry.
    """

    entries: tuple[HeadAttestation, ...]
    """Every readable entry, in the order the file holds them."""

    epoch: tuple[HeadAttestation, ...]
    """The current trust epoch: the last trust-reset entry and everything after
    it, or all entries when there has never been a reset."""

    known: EstablishedHead | HeadLowerBound | HeadUnreadable | None
    """*K*, and how much of a claim it is. See the two types.

    Two types rather than a head plus a flag, deliberately: the weakened case
    has no ``entry`` attribute at all, so there is no expression that reaches
    a comparable head without first saying which case it is in."""

    bootstrap: HeadAttestation | None
    """The journal's first entry, whatever epoch it belongs to. A journal
    beginning at :attr:`Level.MINT` was witnessed from genesis forward; one
    beginning at :attr:`Level.FIRST_CONTACT` was trusted on sight, and that
    label is permanent."""

    skipped: tuple[str, ...]
    """What this build could not use, each with why. Mostly lines; a missing
    header is reported here too, without a line number, because an absence
    does not have one. Reported rather than swallowed: a tolerated loss that
    nobody is told about is just a loss.

    **Non-empty no longer implies a weakened claim**, and that is the one thing
    to carry away from this field. Skips are weighted per cause: a line that is
    byte-identical to an earlier one is a re-assertion, recorded here and
    carrying NO weight, because its content is a line this read already
    counted. Every other cause weakens. A crash-retry duplicate is
    byte-identical by construction, and the journal is append-only, so
    weighting it would have bounded every subsequent read for the life of the
    file (``finding:s3-dedup-skip-weakens-read-permanently``).
    :class:`HeadLowerBound` carries only the weakening subset, so the causes of
    a bound are readable off the bound itself."""

    def established_head(self) -> HeadAttestation | None:
        """*K* for a full comparison, or a refusal if the read was incomplete.

        This is the only way to obtain an argument for :func:`compare`, and it
        refuses rather than answering whenever the read was incomplete — see
        :class:`HeadLowerBound` for the definition of that term, which covers
        a missing header as squarely as a torn line. That refusal is the
        point: against an incomplete
        journal the cheap "presented equals *K*, therefore unchanged" shortcut
        is not merely discouraged, it is unobtainable.
        """
        if isinstance(self.known, HeadLowerBound):
            raise IndeterminateComparison(
                "this read of the journal is incomplete, so its head is "
                "only known to be at or above ordinal "
                f"{self.known.at_least.head.ordinal}; a presented head cannot "
                "be called unchanged or advanced against a bound. The read "
                "missed: " + "; ".join(self.known.skipped)
            )
        if isinstance(self.known, HeadUnreadable):
            raise IndeterminateComparison(
                "this journal holds content but none of it is readable by "
                "this build, so nothing is known about the head it accepted "
                "— not even a lower bound. This is NOT first contact: heads "
                "were accepted here. The read missed: "
                + "; ".join(self.known.skipped)
            )
        return self.known.entry if self.known is not None else None


def _epoch_of(
    entries: tuple[HeadAttestation, ...],
    positions: tuple[int, ...],
) -> tuple[tuple[HeadAttestation, ...], int | None, tuple[tuple[int, str], ...]]:
    """The entries in the current trust epoch, reset-INCLUSIVE.

    Epoch scoping is what keeps the ceremony and the max-ordinal rule from
    deadlocking each other. After an operator accepts a restore from ordinal
    100 back to 90, the abandoned entries at 91-100 still hold the maximum
    ordinal; unscoped, *K* would read as the head that was deliberately
    abandoned and every subsequent open would refuse a rollback forever. Those
    entries are retained as **evidence, not as claims** — which is the whole
    point of recording the gap.

    **Inclusive of the reset entry**, not merely the entries after it. The
    reset entry carries the head the operator accepted; scoping it out would
    leave a just-reset journal with an empty epoch, *K* of None, and a next
    open classifying first contact — the deadlock's mirror image, and silent
    re-acceptance by a different route.

    **A reset is honored only if its recorded predecessor — LINE and identity
    both — is the entry actually preceding it**, which is what makes a replayed
    reset inexpressible as valid rather than merely detectable. Identity alone
    was not enough: replaying the historical predecessor together with the
    reset reproduces it exactly. The line cannot be reproduced, because copied
    bytes appended later land later. See :attr:`HeadAttestation.follows`.

    A reset whose binding does not match is **not an epoch boundary**, and the
    scan keeps walking back for an earlier valid one. It is reported through
    the ordinary skipped channel rather than refused, for the reason every
    other tolerated loss here is: refusing would brick opens on a benign
    crash-retry duplicate, where the same reset is appended twice and the
    second copy's predecessor is the first. The direction of the lie is the
    safe one either way — misjudging a legitimate reset leaves *K* at the
    HIGHER abandoned head, so the failure is a refusal rather than an
    acceptance.

    Note the consequence, which is deliberate and not a side effect: a
    rejected reset puts a WEAKENING note in ``skipped`` — resets keep their
    weight, ruled narrowly, because a voided reset leaves the operator's intent
    uncertain even where the line's content is known. So a journal holding a
    replayed reset still refuses anything below the bound, which is the attack
    it was closing.
    """
    notes: list[tuple[int, str]] = []
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if entry.kind is not Kind.TRUST_RESET:
            continue
        expected: tuple[int, str] = (
            (0, "")
            if index == 0
            else (positions[index - 1], entry_identity(entries[index - 1]))
        )
        if entry.follows == expected:
            return entries[index:], positions[index], tuple(notes)
        notes.append((
            positions[index],
            f"trust-reset at ordinal {entry.head.ordinal}: recorded "
            f"predecessor {_claim_text(entry.follows)} is not the entry that "
            f"precedes it ({_claim_text(expected)}), so it does not open an "
            "epoch — a reset is bound to the line it was appended after and to "
            "what sat there, and bytes copied to any other position cannot "
            "satisfy both",
        ))
    return entries, None, tuple(notes)


def _claim_text(claim: tuple[int, str] | None) -> str:
    """A predecessor claim for an operator reading a skip record."""
    if claim is None:
        return "(none)"
    if claim == (0, ""):
        return "(start of journal)"
    return f"line {claim[0]}/{claim[1][:12]}"


def entry_identity(entry: HeadAttestation) -> str:
    """What a trust reset names when it binds itself to its predecessor.

    A digest over the entry's own serialized line, which is deterministic —
    :func:`_entry_line` sorts keys and omits empty optionals — so an appender
    and a reader compute the same value from the same entry without the raw
    bytes having to be carried around.

    Derived from the PARSED entry rather than the file's bytes, and the
    residual is stated: an entry written by a later build carries fields this
    one drops, so its digest here differs from the digest its own build would
    compute. A reset bound to such an entry is therefore not honored, *K*
    stays at the higher head, and the note says so — the refusal-side failure
    again, which is the side this must fail on.
    """
    return hashlib.sha256(_entry_line(entry).rstrip("\n").encode("utf-8")).hexdigest()


def _known_of(epoch: tuple[HeadAttestation, ...]) -> HeadAttestation | None:
    """*K*: the maximum-ordinal entry of the epoch, not the last line.

    Two writers append concurrently — the arrival lock serializes their
    *appends*, not their journal writes — so lines can land out of order: A
    commits ordinal 5, B commits 6 and journals it, A journals 5 last.
    Last-line semantics would then read K=5 and classify a genuine restore to
    5 as unchanged. Maximum-ordinal closes it, and duplicate entries at one
    ordinal are harmless.
    """
    if not epoch:
        return None
    best = max(epoch, key=lambda entry: entry.head.ordinal)
    tied = {
        entry.head.record_hash
        for entry in epoch
        if entry.head.ordinal == best.head.ordinal
    }
    if len(tied) > 1:
        raise JournalEquivocation(
            f"journal holds {len(tied)} different records at ordinal "
            f"{best.head.ordinal} in the current trust epoch: "
            f"{', '.join(sorted(tied))}"
        )
    return best


#: The three outcomes of looking at one decoded line. Named, because "how a
#: line is classified" is the contract sentence this module got wrong twice.
_HEADER = "header"
_AMBIGUOUS = "ambiguous"
_ENTRY_SHAPED = "entry-shaped"


def _classify(decoded: object) -> str:
    """Header, ambiguous, or entry-shaped — by SHAPE, never by position.

    **The rule never absorbs a line and never refuses the file.** Both halves
    are scar tissue from a fix that went wrong in each direction:

    * Treating any *kindless* dict as a header absorbed ``{}`` silently, with
      no skip recorded, and so lost the line holding the epoch maximum
      (``finding:s3wp1-gate-kindless-dict-absorbed-as-header``).
    * Keying on the type string *alone* would let a future ENTRY that happens
      to carry the type marker be absorbed as a header — the same class of
      failure from the other side.
    * Requiring the type string *and* the absence of ``kind`` refused the
      whole file when a later build's header carried a ``kind`` of its own,
      an uncontracted version-skew refusal
      (``finding:s3wp1-sol-l1-header-classification-three-way``).

    So an object carrying **both** markers is not classified at all. It is
    reported as ambiguous and skipped, which is a location claim about this
    build's ability to read the line — not a verdict about what the line is,
    which is precisely what this build cannot know.
    """
    if isinstance(decoded, dict) and decoded.get("type") == _OBSERVATION_TYPE:
        return _AMBIGUOUS if "kind" in decoded else _HEADER
    return _ENTRY_SHAPED


class _Skips:
    """Skip records, and which of them actually represent IGNORANCE.

    A plain class rather than a dataclass, deliberately. Rule 5 asks lib
    dataclasses to be frozen because they are value objects; this is an
    ACCUMULATOR, and it lives only inside one parse. Declaring it frozen with
    mutable lists inside would satisfy the rule's letter while holding exactly
    the mutable state the rule is about — the shape of gaming a ratchet rather
    than answering it.

    **Per-cause, deliberately not per-read.** The tempting shape is "a read
    whose only skips are re-assertions is established", and it does not
    compose: a journal holding a duplicate AND an unreadable line must still
    bound, and it does so here because the unreadable line carries its own
    weight regardless of what else is in the file. Each call site names its
    cause by which method it calls, so a new cause has to choose.

    The bound machinery exists to represent ignorance. A re-assertion is the
    one cause that carries none — the skipped line's content is a line this
    read already counted, so nothing about the accepted head is unknown because
    of it (``finding:s3-dedup-skip-weakens-read-permanently``). Everything else
    is something the read needed and did not get.
    """

    def __init__(self) -> None:
        self.all: list[str] = []
        self._weighted: list[tuple[int | None, str]] = []

    def missed(self, note: str, *, line: int | None = None) -> None:
        """The read needed something and did not get it. Recorded, and it counts.

        ``line`` is the physical line the loss sits at, or ``None`` for a
        STRUCTURAL absence — something missing from the file as a whole rather
        than at a position in it. Structural losses are exempt from the
        position scoping below, because there is no position for a decree to
        be "after".
        """
        self.all.append(note)
        self._weighted.append((line, note))

    def weakening(self, boundary: int | None) -> tuple[str, ...]:
        """The skips that actually weaken the read, given the epoch boundary.

        **Weight is cause times position.** A re-assertion never reaches here
        at all — that is the cause half, and it is why
        :meth:`re_asserted` records without weighing. This is the position
        half: a line-positioned loss sitting BEFORE the boundary reset's line
        carries zero weight, because the ceremony decreed trust in a head and
        everything positionally behind that decree is what it decreed past.
        Appends are tail-only, so a line's position in the file IS its place in
        time — the non-ascending order this journal documents is about
        ORDINALS, which two writers can interleave, never about positions,
        which the filesystem serializes.

        Without it the ceremony cannot heal: an operator resets past a damaged
        line and still gets a bounded read forever, from damage the reset was
        run to put behind them (``design amendment #5``).

        Structural absences (``line is None``) keep their weight regardless.
        The header is line 1 and would sit below every boundary, but its
        absence is a claim about the FILE rather than a line anyone decreed
        past.

        **No valid reset means no boundary, and then every weakening cause
        keeps full weight** — stated here rather than left to fall out of a
        comparison, because "there is nothing to be after" is a different
        situation from "this is after it".
        """
        if boundary is None:
            return tuple(note for _line, note in self._weighted)
        return tuple(
            note
            for line, note in self._weighted
            if line is None or line >= boundary
        )

    def re_asserted(self, note: str) -> None:
        """The read got something it already had. Recorded, and it does NOT count.

        Never weighed at any position — the cause half of the weighting.
        Still reported: a tolerated loss nobody is told about is just a loss,
        and an operator seeing replayed lines in their journal wants to know.
        What it must not do is weaken the claim, because a crash-retry
        duplicate is byte-identical by construction and the journal is
        append-only: one benign retry would otherwise bound every subsequent
        read for the life of the file, and ``established_head()`` would raise
        forever.
        """
        self.all.append(note)


def _scan(
    lines: Iterable[str],
) -> tuple[list[tuple[int, HeadAttestation]], _Skips, bool]:
    """Every readable entry with its PHYSICAL LINE ORDINAL, what was skipped,
    and whether a header was seen.

    The line number is the file's own, counted from 1 over every line including
    ones this build skipped — never an index among the entries that happened to
    parse. That distinction is the whole of the position claim: an index among
    valid entries is a judgment, and a future build that classifies one line
    differently renumbers every entry after it, silently voiding every reset
    bound below. Physical line N is line N forever in a file that is only ever
    appended to.

    Split out of :func:`parse_journal_lines` so a caller can reach the entries
    WITHOUT the judgment built on top of them. That judgment can refuse —
    :func:`_known_of` raises on equivocation — and the trust-reset ceremony
    needs the last entry precisely when the journal is in a state a full read
    will not answer for. A recovery path that depended on the read it recovers
    from would be unusable exactly when it is needed.
    """
    entries: list[tuple[int, HeadAttestation]] = []
    skips = _Skips()
    seen: dict[str, int] = {}
    header_seen = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            decoded = json.loads(stripped)
        except ValueError as exc:
            skips.missed(
                f"line {index + 1}: does not parse ({exc})", line=index + 1
            )
            continue
        verdict = _classify(decoded)
        if verdict is _HEADER:
            # Not tracked by position: two writers racing to create the same
            # journal can each write one, so "the header is line 1" is not a
            # property this reader may assume.
            header_seen = True
            continue
        if verdict is _AMBIGUOUS:
            skips.missed(
                f"line {index + 1}: carries both the journal type marker and "
                "an entry kind, so this build cannot say which it is",
                line=index + 1,
            )
            continue
        entry = _parse_entry(decoded)
        if entry is None:
            skips.missed(
                f"line {index + 1}: not readable by this build", line=index + 1
            )
            continue
        if stripped in seen:
            # A LITERAL RE-ASSERTION: recorded, and WEIGHTLESS. The line's
            # content is one this read already counted, so nothing about the
            # accepted head is unknown because of it.
            skips.re_asserted(
                f"line {index + 1}: byte-identical to line {seen[stripped]}, "
                "so it re-asserts an observation this journal already holds "
                "rather than recording a new one — a replayed line cannot "
                "count twice"
            )
            continue
        seen[stripped] = index + 1
        entries.append((index + 1, entry))

    return entries, skips, header_seen


def last_entry(lineage: str) -> tuple[int, HeadAttestation] | None:
    """The last readable entry and its PHYSICAL LINE, or None if there is none.

    Both halves, because a trust reset binds to both — see
    :attr:`HeadAttestation.follows`. File order, not maximum ordinal: a reset
    binds to the entry it is physically appended after, which is what a later
    reader finds sitting in front of it.

    Deliberately performs no epoch scoping, no equivocation check and no *K*
    computation. That is not an optimization — see :func:`_scan`.
    """
    try:
        text = journal_path(lineage).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise JournalUnreadable(
            f"the journal for lineage {lineage!r} exists but cannot be read "
            f"as text at all: {exc}"
        ) from exc
    scanned, _skips, _header = _scan(text.splitlines(keepends=True))
    return scanned[-1] if scanned else None


def parse_journal_lines(lines: Iterable[str]) -> JournalRead:
    """Read a journal from its raw lines. Pure — no filesystem.

    The pure half is separate so the conformance vectors can hand it raw log
    lines and so every read rule is testable without a temporary directory.

    **Every line this build cannot use is skipped and reported, wherever it
    sits** — which is half of what makes a read incomplete
    (:class:`HeadLowerBound`); a missing header is the other half. The
    earlier design distinguished a torn final line from damage further up and
    refused the latter, on the reasoning that skipping could silently lower
    *K*. Skipping CAN lower *K* — concurrent writers journal out of order, so
    the epoch maximum is not the last line and damage anywhere can take it
    (``finding:s3wp1-epoch-ordinals-do-not-ascend-in-file-order``). But
    refusing was the wrong answer to it. It made an ordinary crash a permanent
    incident, and it claimed a protection this location cannot deliver: anyone
    who can corrupt a line here can delete the whole journal instead and be
    met with trust-on-first-use. So the loss is **carried in the result type**
    — :class:`HeadLowerBound` — rather than converted into a verdict, and the
    positional rule dissolves along with the distinction it enforced.

    **This function never refuses on structure.** Entries with no recognized
    header are tolerated too: the entries are self-describing evidence that
    heads were accepted, so what is lost — the protocol and wire versions the
    hashes derive under — weakens the claim to :class:`HeadLowerBound` rather
    than voiding the file. The absence is reported without a line number,
    because an absence does not have one. Only
    :class:`JournalEquivocation` is raised from here, and it is a statement
    about the journal's content rather than its readability.
    :class:`JournalUnreadable` belongs to :func:`read_journal`, where there
    may be no text to hand this function at all.
    """
    scanned, skips, header_seen = _scan(lines)
    positions = tuple(line for line, _entry in scanned)
    frozen = tuple(entry for _line, entry in scanned)
    if frozen and not header_seen:
        # TOLERATED, not refused. The entries are self-describing evidence
        # that heads were accepted, and a weakened claim is available — so
        # refusing the file would be a verdict where a bound would do, which
        # is the error `HeadUnreadable` was added to correct. What is lost is
        # the protocol and wire versions the hashes derive under, and losing
        # that is exactly what a lower bound is for. Reported without a line
        # number because an absence does not have one.
        # STRUCTURAL, so no line and no exemption from weight: the header
        # would be line 1 and would sit below every boundary, but its absence
        # is a claim about the FILE rather than a line an operator decreed
        # past. Reported without a line number because an absence does not
        # have one — which is exactly what marks it structural here.
        skips.missed(
            "header: absent, so the protocol and wire versions these record "
            "hashes derive under are unknown"
        )
    epoch, boundary, epoch_notes = _epoch_of(frozen, positions)
    for line, note in epoch_notes:
        # A voided reset KEEPS its cause-weight, ruled narrowly: the content of
        # the line is known, but what the operator INTENDED by it is not, and
        # that uncertainty is exactly what a bound represents.
        #
        # Its position is carried for uniformity, and it never exempts anything:
        # `_epoch_of` walks BACKWARD and returns at the first valid reset, so
        # every note it produces comes from a reset ABOVE the boundary by
        # construction. A failed attempt followed by a successful re-run still
        # heals — but through the walk short-circuiting past it, not through
        # this weighting. Stated because a comment claiming the weighting does
        # that work would describe a path nothing can reach.
        skips.missed(note, line=line)
    weakening = skips.weakening(boundary)
    best = _known_of(epoch)
    known: EstablishedHead | HeadLowerBound | HeadUnreadable | None
    if best is not None:
        known = (
            HeadLowerBound(at_least=best, skipped=weakening)
            if weakening
            else EstablishedHead(entry=best)
        )
    elif weakening:
        # Content was claimed and none of it could be read. NOT first contact.
        known = HeadUnreadable(skipped=weakening)
    else:
        known = None
    return JournalRead(
        entries=frozen,
        epoch=epoch,
        known=known,
        bootstrap=frozen[0] if frozen else None,
        skipped=tuple(skips.all),
    )


def read_journal(lineage: str) -> JournalRead:
    """This lineage's journal, or an empty read if it has none.

    An absent journal is not a fault — it is first contact, and answering
    with an empty read rather than raising is what lets the classifier say so.
    """
    path = journal_path(lineage)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Absent is not a fault — it is first contact, and answering with an
        # empty read is what lets the classifier say so.
        return JournalRead(
            entries=(), epoch=(), known=None, bootstrap=None, skipped=()
        )
    except (OSError, UnicodeDecodeError) as exc:
        # The journal is THERE and cannot be read at all — a directory, a
        # permission wall, bytes that are not text. Distinct from every case
        # the parser handles, because there is nothing to parse. Raised as a
        # refusal rather than let out as a builtin: a caller catching
        # AttestationRefusal must not have an OSError escape past it.
        raise JournalUnreadable(
            f"the journal for lineage {lineage!r} exists but cannot be read "
            f"as text at all: {exc}"
        ) from exc
    return parse_journal_lines(text.splitlines(keepends=True))


# ---------------------------------------------------------------------------
# Writing the journal
# ---------------------------------------------------------------------------


def _torn_tail_guard(path: Path) -> str:
    """A newline when the file does not end in one, so an append cannot glue.

    A crash mid-append leaves a fragment with no trailing newline. Appending
    straight onto it would concatenate the next entry into that fragment,
    producing ONE unreadable line — and the new entry's bytes would be lost
    inside it. The design's promise is that a torn tail costs at most the
    newest observation; without this guard an ordinary crash plus one commit
    would cost the next observation too.

    Conservative when it cannot tell: an unreadable file gets the newline. A
    spurious blank line is skipped for free on read, while gluing is not
    recoverable at all.
    """
    try:
        with path.open("rb") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                return ""
            handle.seek(-1, os.SEEK_END)
            return "" if handle.read(1) == b"\n" else "\n"
    except OSError:
        return "\n"


def _write_all(handle: int, payload: bytes) -> None:
    """Write every byte, or raise. A short write is a self-inflicted torn line."""
    written = 0
    while written < len(payload):
        count = os.write(handle, payload[written:])
        if count <= 0:
            raise OSError(
                f"journal write stalled after {written} of {len(payload)} bytes"
            )
        written += count


def append_entry(entry: HeadAttestation) -> Path:
    """Append one observation. Returns the journal it landed in.

    Append-only, so there is no read-modify-write, no torn partial update and
    no lock. Retaining every previously accepted head is also what makes an
    under-evidenced advance *recoverable* rather than a loss: *K* stays in the
    journal forever, so the periodic audit can re-examine everything accepted
    since the last reset. A single overwritten value could not offer that at
    any price, because it would have forgotten *K* — and it could not hold the
    bootstrap receipt either, since the first advance would erase it.

    A brand-new journal gets its header and its first entry in one write. The
    exclusive create keeps two racing writers from each emitting a header; the
    reader tolerates a second one anyway, because a create race is cheaper to
    survive than to prevent.

    **Every open carries O_APPEND, including the exclusive create.** Without it
    the creating writer's descriptor sits at offset zero, and a second writer
    that lost the create race can land a complete entry there first — which the
    creator then overwrites. The journal would have silently forgotten a head,
    and a later restore to the surviving ordinal would classify UNCHANGED: the
    exact failure the maximum-ordinal read rule exists to close, arriving
    through the write path instead.
    """
    path = journal_path(entry.head.lineage)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _entry_line(entry)
    try:
        handle = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600
        )
    except FileExistsError:
        # An empty existing file is a creator that crashed between the
        # exclusive create and its write. Supplying the header here keeps that
        # crash from leaving a journal with no header at all. The reader
        # tolerates one and says so, but the header carries the protocol and
        # wire versions, so a journal that HAS one keeps a claim it would
        # otherwise have to weaken.
        payload = _torn_tail_guard(path) + line
        if path.exists() and path.stat().st_size == 0:
            payload = _header_line() + line
        handle = os.open(path, os.O_WRONLY | os.O_APPEND)
    else:
        payload = _header_line() + line
    try:
        _write_all(handle, payload.encode("utf-8"))
    finally:
        os.close(handle)
    return path


# ---------------------------------------------------------------------------
# The audit's all-journaled-heads check (§C.4)
# ---------------------------------------------------------------------------


def unaccounted_heads(
    epoch: Iterable[HeadAttestation],
    at_ordinal: Callable[[int], Head | None],
) -> tuple[HeadAttestation, ...]:
    """Journaled heads the store can no longer account for.

    The periodic audit does not merely re-verify the current chain — it checks
    that every head journaled **in the current trust epoch** is still present
    at its own ordinal with its own hash. That single walk is what makes the
    cheap per-open check safe: an advance accepted today on partial evidence
    is re-examined against the complete record of everything accepted since
    the last reset.

    The epoch scope is not a convenience. A legitimately accepted restore
    leaves heads in the journal that the restored store does not and cannot
    contain; auditing against those would fail permanently and train an
    operator to ignore the audit, which is worse than not running one.

    ``at_ordinal`` is injected rather than imported so this module never
    reaches for a backend or a projection auditor. The audit producer that
    supplies it is WP3's.
    """
    return tuple(
        entry for entry in epoch if at_ordinal(entry.head.ordinal) != entry.head
    )


# ---------------------------------------------------------------------------
# TRANSITIONAL — DELETE IN SLICE 5.
#
# Lineage-keying leaves exactly one hole: wholesale replacement. A store
# rewritten with a NEW lineage finds no journal, is classified first contact,
# and is trusted on sight — §07's "replacement or explicit re-custody" row
# passing silently. Detecting it requires knowing which lineage a location
# SHOULD present, and architecturally that is `StoreDescriptor.lineage`
# ("when already known, is checked against genesis rather than trusted as a
# replacement for it"). Slice 2 deliberately left that field unparsed with its
# forcing consumer named as slice 5's adopt ceremony, and growing the `.vertex`
# grammar out of sequence here would take a decision slice 3 was not given.
#
# So the binding lives here until the declared lineage supersedes it. Its
# deletion is a residue sweep, not a behavior change: once every store's
# vertex declares its lineage, `descriptor.lineage` answers every question
# this file answers, from a source the operator can read and review. Slice 5
# deletes this section, `bindings.jsonl`, and its tests together — the same
# obligation `arrival_registry`'s transitional inference arm carries.
# ---------------------------------------------------------------------------


def bindings_path() -> Path:
    """The transitional location-to-lineage bindings file. DELETE IN SLICE 5."""
    return heads_dir() / "bindings.jsonl"


def record_binding(location: str, lineage: str, observed_at: float) -> None:
    """Remember which lineage this location presented. DELETE IN SLICE 5.

    Append-only and keyed on nothing: the newest binding for a location wins
    on read, and older ones stay as evidence of what it used to be.
    """
    path = bindings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(
            {
                "v": _JOURNAL_VERSION,
                "location": location,
                "lineage": lineage,
                "observed_at": observed_at,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    payload = _torn_tail_guard(path) + line
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        _write_all(handle, payload.encode("utf-8"))
    finally:
        os.close(handle)


def bound_lineage(location: str) -> str | None:
    """The lineage this location most recently presented, if any.

    DELETE IN SLICE 5.

    **An ABSENT file answers None**, and that is the one degradation this makes:
    nothing has ever been bound, so first contact is the honest state.

    Everything else REFUSES, which is the correction to what this docstring
    used to claim. It said a malformed line is skipped because "this file makes
    no claim a skipped line could weaken" — and that was wrong in the way that
    mattered: the skipped line may be the very binding that names this
    location, so skipping answers "nothing is bound here" on evidence that says
    nothing of the kind, and a replaced store then opens as first contact
    (``finding:s3wp3-binding-probes-fail-acceptance-side``). Unreadable content
    raises :class:`BindingsUnreadable` and asks for repair; a transient read
    failure raises :class:`BindingProbeUnanswered` and asks for a retry.
    """
    try:
        text = bindings_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        # ABSENT is an answer: nothing has ever been bound.
        return None
    except UnicodeDecodeError as exc:
        # PERMANENT, so not a probe failure: these bytes will decode the same
        # way on every retry, and the honest advice is repair.
        raise BindingsUnreadable(
            f"the bindings file at {bindings_path()} is not valid UTF-8 "
            f"({exc}), so no location's recorded lineage can be read. Nothing "
            "has been accepted or written — repair or remove the file"
        ) from exc
    except OSError as exc:
        # Was a RAW OSError escaping past every `except AttestationRefusal`,
        # which is the builtin-escape gap `JournalUnreadable` exists to close
        # one file over. Refusing is the right direction; being typed is what
        # lets a caller catch it with the rest. TRANSIENT-flavoured, so it
        # stays a probe failure: a permission wall can be lifted and an I/O
        # error can pass.
        raise BindingProbeUnanswered(
            f"the bindings file at {bindings_path()} exists and storage "
            f"would not yield it ({exc}), so this location's recorded lineage "
            f"is unknown. Nothing has been accepted or written — "
            f"{storage_advice(exc)}"
        ) from exc
    found: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            decoded = json.loads(stripped)
        except ValueError as exc:
            raise BindingsUnreadable(
                f"a line of {bindings_path()} does not parse ({exc}), and a "
                "line that cannot be read may be the binding that names this "
                "location. Nothing has been accepted or written — repair or "
                "remove the line, then retry the open"
            ) from exc
        if not (
            isinstance(decoded, dict)
            and isinstance(decoded.get("location"), str)
            and isinstance(decoded.get("lineage"), str)
        ):
            # READ, and not interpretable as a binding — a CONTENT failure,
            # exactly like a line that is not JSON. Filtering it to None used
            # to answer "nothing is bound here" on a line that says nothing of
            # the kind (``finding:s3-binding-shape-filter-silently-drops``).
            raise BindingsUnreadable(
                f"a line of {bindings_path()} is valid JSON but carries no "
                "location and lineage, so it cannot be read as a binding and "
                "cannot be ruled out as this location's. Nothing has been "
                "accepted or written — repair or remove the line"
            )
        if decoded["location"] == location:
            # The one thing that survives as a legitimate skip: a well-formed
            # binding for a DIFFERENT store genuinely says nothing about this
            # one.
            found = decoded["lineage"]
    return found
