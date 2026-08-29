"""arrival_contract — the storage-neutral authority protocol.

Slice 2 of the arrival break (``design:arrival-break-slice2-backend-contract``).
The contract of record is ``docs/architecture/arrival/backend-contract.html``
(Draft v1); this module states its §03 core types and interfaces in Python so
adapters can be written against them. It designs nothing — where the two
disagree, the HTML is right and this file is a bug.

**stdlib and typing only.** Nothing here imports sqlite3, and nothing here
imports :mod:`engine.arrival` at runtime. That is the whole reason this is a
separate module from the adapter: ``import engine.arrival_contract`` is what
:mod:`store`, :mod:`sdk` and the next arc's DuckDB adapter all reach for, and a
caller that only wants to name a :class:`Head` must not drag a file codec and a
database driver along behind it. It also removes a cycle by construction — the
adapter imports the contract, the registry imports both, and nothing imports
the registry from below.

**Protocols, not abstract base classes.** The file adapter wraps concrete
classes that already exist rather than inheriting new engine machinery, and the
DuckDB adapter will live outside this package entirely. ``store.transport``'s
``Transport`` states a pluggable seam the same way.

**The refusals are rooted here, not in one backend's exception family.**
:class:`ContractRefusal` deliberately does not descend from
``engine.arrival.ArrivalError``. A caller written against the contract must be
able to catch a head mismatch from a DuckDB or PostgreSQL authority, and a
hierarchy rooted in the file backend's module cannot offer that. Each adapter
translates its own family into these, one-for-one — a translation that lumps
several backend faults into one contract refusal is a verdict claim, and the
contract only licenses location claims.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "Profile",
    "DurabilityProfile",
    "VerificationLevel",
    "Head",
    "Watermark",
    "RecordDraft",
    "DurabilityReceipt",
    "Commit",
    "ExportedPrefix",
    "Capabilities",
    "Open",
    "Incremental",
    "Full",
    "VerifyScope",
    "StoreDescriptor",
    "ArrivalLedger",
    "ArrivalQuery",
    "LEDGER_MUTATIONS",
    "ContractRefusal",
    "HeadMismatch",
    "SameHeightFork",
    "NotAuthority",
    "UnknownBackend",
    "AtomicLimitExceeded",
]


# ---------------------------------------------------------------------------
# Named vocabularies — the contract's own tables, typed
# ---------------------------------------------------------------------------


class Profile(Enum):
    """What a store is licensed to do (§03's Profile column).

    Not a description of the software: a Replica running the same adapter as
    an Authority differs in what it may be *asked* to do, which is why §08
    ends "Replica is not authority" — a byte-identical copy that accepts
    independent writes has forked.
    """

    AUTHORITY = "authority"
    REPLICA = "replica"
    ARCHIVE = "archive"


class DurabilityProfile(Enum):
    """What a successful append survives (§05's table).

    Named rather than assumed because "durable" is meaningless without a
    failure boundary, and a caller may require a stronger profile than a
    backend offers.
    """

    PROCESS = "process"
    HOST = "host"
    REPLICATED = "replicated"
    ARCHIVE = "archive"


class VerificationLevel(Enum):
    """How much of the prefix a verification actually established (§06).

    Open-level checks are operational fast paths, not substitutes for a full
    audit; a backend must describe exactly which level each API invokes,
    which is what makes this an enum and not a boolean.
    """

    OPEN = "open"
    INCREMENTAL = "incremental"
    FULL = "full"


# ---------------------------------------------------------------------------
# Core types (§03)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Head:
    """The complete coordinate of a lineage's newest record.

    All three fields, always. The ordinal alone is what the pre-slice-2 CAS
    compared, and an ordinal-only pin cannot tell "nothing has changed" from
    "the record at this ordinal was replaced" — the rollback and same-height
    fork §11 asks backends to detect. A head that omits the hash is not a
    weaker head, it is a different and much smaller claim.
    """

    lineage: str
    ordinal: int
    record_hash: str


@dataclass(frozen=True)
class Watermark:
    """How much of a lineage a projection accounts for (§07).

    Deliberately NOT a :class:`Head`. §07 asks a projection to store a
    verified ``projected_through`` head, and a projection that stores one can
    answer with a full head; the arrival file projection stores a coordinate
    and a seek hint, so this is the honest shape of what it knows. Turning a
    watermark into a verified head means reading the record that sits at that
    ordinal, and only the ledger half can attest to that — which is the
    custody/reads separation stated in a return type rather than in prose.
    """

    lineage: str
    ordinal: int


@dataclass(frozen=True)
class RecordDraft:
    """One record a caller wants appended, minus its coordinate.

    The coordinate — lineage, ordinal, predecessor link, record hash — is the
    ledger's to assign inside the fence (§04 step 5), so a draft names only
    what its author owns. ``signature``, when present, is over the authored
    content and not over the coordinate, which is what makes it something a
    caller can produce before knowing where the record will land.
    """

    kind: str
    authored_at: float
    observer: str
    origin: str = ""
    body: Mapping[str, Any] = field(default_factory=dict)
    signature: str | None = None


@dataclass(frozen=True)
class DurabilityReceipt:
    """What was actually established before an append reported success (§05).

    ``mechanism`` is free text naming the concrete step, because the profile
    alone does not tell an operator what to check when it fails.
    """

    profile: DurabilityProfile
    mechanism: str


@dataclass(frozen=True)
class Commit:
    """One accepted append transition: where it started, what landed, where it ended.

    ``before`` and ``after`` are both full heads, so a caller can chain
    commits without re-reading the ledger — the shape §10's migration sidecar
    loop depends on (``head = commit.after``).
    """

    before: Head
    records: tuple[Mapping[str, Any], ...]
    after: Head
    durability: DurabilityReceipt


@dataclass(frozen=True)
class ExportedPrefix:
    """A captured prefix, re-encoded, and the manifest describing it (§08).

    ``records`` is an iterator: an export streams by construction, because a
    canonical export of a large lineage that had to be materialised whole
    would be an export the biggest stores cannot run.
    """

    head: Head
    codec: str
    records: Iterator[bytes]
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class Capabilities:
    """A backend's machine-readable self-report (§12).

    Deployment tooling refuses an Authority assignment whose required
    guarantees are absent, so every field here is a claim the backend can be
    held to — an adapter that advertises an operation it does not implement
    has told a lie the conformance suite exists to catch.

    ``max_atomic_records`` is ``None`` for "no configured limit", which is
    different from a limit of one: §04 requires every backend to support one
    record and lets it advertise more.
    """

    protocol_version: int
    profiles: frozenset[Profile]
    durability: DurabilityProfile
    verification_levels: frozenset[VerificationLevel]
    writer_concurrency: str
    snapshot: str
    watermark: str
    max_atomic_records: int | None = None
    idempotency_keys: bool = False
    export_codecs: tuple[str, ...] = ()
    limits: tuple[tuple[str, int], ...] = ()


# ---------------------------------------------------------------------------
# Verification scopes (§06)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Open:
    """Genesis, stored head metadata, and the adopted head record.

    Claim: the backend can identify a self-consistent current tip. Nothing
    about the prefix behind it.
    """

    level: VerificationLevel = VerificationLevel.OPEN


@dataclass(frozen=True)
class Incremental:
    """A verified checkpoint through to the captured head.

    Claim: the suffix follows a previously fully verified prefix — so the
    claim is only as good as the checkpoint it starts from, which is why the
    checkpoint is named rather than remembered.
    """

    through: Head
    checkpoint: Head
    level: VerificationLevel = VerificationLevel.INCREMENTAL


@dataclass(frozen=True)
class Full:
    """Genesis through the captured head.

    Claim: grammar, density, lineage, and hash chain are intact for the
    complete prefix.
    """

    through: Head
    level: VerificationLevel = VerificationLevel.FULL


VerifyScope = Open | Incremental | Full


# ---------------------------------------------------------------------------
# Descriptors (§02)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoreDescriptor:
    """Which adapter opens which artifact, stated rather than sniffed.

    Backend selection MUST be explicit: nothing infers authority, canonical
    format, or migration behaviour from a ``.arrival``, ``.duckdb`` or ``.db``
    suffix. ``location`` is a ``str`` and not a ``Path`` on purpose — it is
    interpreted only by the named adapter and may be a filesystem path, a DSN
    reference, or a service URL.

    ``lineage``, when already known, is checked against genesis rather than
    trusted as a replacement for it. ``role`` expresses operator intent; the
    backend still verifies it can safely perform what is asked. Secrets are
    referenced through ``witness``/a secret provider, never embedded.

    Locally this descriptor dissolves into the ``.vertex`` store clause
    (backend-contract.html:140-149) — WP4 builds that resolution.
    """

    backend: str
    location: str
    lineage: str | None = None
    role: Profile | None = None
    query: str | None = None
    witness: str | None = None


# ---------------------------------------------------------------------------
# Interfaces (§03)
# ---------------------------------------------------------------------------

# The ledger operations that can change what a lineage holds. Stated here,
# beside the Protocol that declares them, so the custody/reads separation test
# reads this list instead of re-typing it — a hand-copied list in a test is a
# ratchet that silently stops covering the op added after it was written.
#
# `import_prefix` is a mutation and is therefore HERE, but it is deliberately
# not declared on the Protocol below: §08 describes portable import in prose
# and the ratified op table gives it no row, so an adapter that offers one is
# offering more than the contract asks for. Growing the Protocol is a contract
# decision; this set is the safety ratchet, and a mutating op that is not in it
# is a hole in the custody/reads separation whether the contract names the op
# or not.
LEDGER_MUTATIONS = frozenset({"mint", "append", "replicate", "import_prefix"})


@runtime_checkable
class ArrivalLedger(Protocol):
    """Custody: everything that can change what the lineage holds.

    ``runtime_checkable`` so a conformance test can ask whether an adapter
    satisfies the surface. That check is by method NAME only — Python's
    protocol runtime check cannot judge signatures — so it is a location
    claim ("this adapter offers these ops"), never a conformance verdict.
    The vectors are what judge behaviour.
    """

    def mint(self, options: Mapping[str, Any]) -> Head:
        """Exclusively create one signed genesis and return head 0."""
        ...

    def head(self, lineage: str | None = None) -> Head:
        """The currently complete head, or a typed absence/corruption refusal."""
        ...

    def head_at(self, watermark: Watermark) -> Head:
        """Resolve a projection's watermark into the verified head it names.

        §07 asks a projection to store a verified ``projected_through`` head,
        and a projection that holds a coordinate cannot produce one: only
        custody holds the record whose hash completes it. So the resolution
        is a ledger op, and the return type is what states the custody/reads
        separation rather than prose. It answers or it refuses — a watermark
        the ledger will not vouch for IS the projection/ledger disagreement,
        and a manufactured head would hide exactly the thing being asked
        about.

        A read, not a mutation: deliberately absent from
        :data:`LEDGER_MUTATIONS`.
        """
        ...

    def append(self, expected: Head | None, drafts: Sequence[RecordDraft]) -> Commit:
        """Compare the full head, then assign and commit, indivisibly (§04)."""
        ...

    def replicate(
        self, expected: Head | None, records: Sequence[Mapping[str, Any]]
    ) -> Commit:
        """Append exact pre-coordinated records; never rehash, never re-sign."""
        ...

    def read(self, coordinate: int) -> Mapping[str, Any]:
        """The exact record, after establishing its membership in the lineage."""
        ...

    def scan(
        self, *, after: int | None = None, through: Head | None = None
    ) -> Iterator[Mapping[str, Any]]:
        """An ordered, consistent prefix range and no later record (§06)."""
        ...

    def verify(self, scope: VerifyScope) -> Head:
        """Verify through a named head; return the head the claim covers.

        Verification reports; it does not repair. Whether that is a MUST is
        the F2 addendum Kyle rules on at the slice-2 gate — until then the
        obligation lives in the adapters that already hold it.
        """
        ...

    def export(self, *, through: Head, codec: str) -> ExportedPrefix:
        """Deterministic portable records plus a manifest, for a captured prefix."""
        ...

    def capabilities(self) -> Capabilities:
        """Profiles, limits, concurrency scope, durability, codecs, query behaviour."""
        ...


@runtime_checkable
class ArrivalQuery(Protocol):
    """Reads: what a projection can answer, and how far it can answer it for.

    §03 gives this half "facts, ticks, folds, search, and SQL-oriented reads",
    and a query handle MUST NOT expose a generic mutation escape hatch into
    the ledger. The row-shaped read surface stays each backend's own for now
    and is deliberately not declared here — one adapter is not yet a pattern,
    and the second backend is where a neutral spelling of "give me the facts"
    earns its keep. What IS declared is §07's projection obligation, which
    every backend owes regardless of how its rows are shaped: say which
    lineage you are answering about, and how much of it you actually have.
    """

    def lineage(self) -> str | None:
        """The lineage this projection represents, or None when it holds none."""
        ...

    def projected_through(self) -> Watermark | None:
        """How much of the lineage this projection accounts for."""
        ...


# ---------------------------------------------------------------------------
# Typed refusals
# ---------------------------------------------------------------------------


class ContractRefusal(Exception):
    """Root of the backend-neutral refusals.

    Rooted here rather than in any backend's family so a caller can catch a
    refusal without knowing which adapter produced it.
    """


class HeadMismatch(ContractRefusal):
    """The actual head is not the expected head; nothing was mutated.

    §04: an append succeeds if and only if the actual head equals the expected
    head and every assigned record is durable. This is the first half failing,
    and it is raised BEFORE any mutation — a caller that sees it re-reads and
    retries.
    """


class SameHeightFork(ContractRefusal):
    """A conflicting record already occupies this coordinate (§08).

    Not a stale head: replication found a *different* record at the height it
    was about to fill. Replication stops rather than choosing, because
    choosing is admission into another lineage and admission is a different
    operation.
    """


class NotAuthority(ContractRefusal):
    """This store may not perform the operation asked of it.

    §02: opening an exported log does not grant it authority merely because
    the codec can append to such files. Authority comes from the active
    descriptor plus the backend's fencing checks.
    """


class UnknownBackend(ContractRefusal):
    """No adapter is registered under the descriptor's backend name.

    Refusing is the point: §02 forbids inferring a backend from a suffix, so
    an unregistered name has no fallback to degrade into.
    """


class AtomicLimitExceeded(ContractRefusal):
    """The request holds more records than this backend commits atomically.

    §04: refuse BEFORE mutation. A backend that accepted the request and split
    it across transactions would have turned one logical group into several,
    which is the outcome the atomic limit exists to make impossible.
    """
