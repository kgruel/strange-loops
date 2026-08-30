"""The compare-on-open seam — against real stores, not mocks.

Slice 3 / WP3 (``design:arrival-break-slice3-witness-minimum`` §D, §E-WP3, §0.4).

Every store here is a real minted ``.arrival`` log with a real sqlite projection
beside it, because the property the seam exists for is about what a restore, a
truncation or a rewrite does to bytes on disk — and a mock cannot be truncated.

Every test runs against a temporary state root. The journal resolves its home from
``$XDG_STATE_HOME`` at call time and the autouse fixture below redirects it, so no
test can reach the developer's real journals: a suite that wrote head observations
into ``~/.local/state/loops`` would be corrupting the very memory the design exists
to protect.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from atoms import Fact

import engine.arrival_head_seam
from engine.arrival import ArrivalLog
from engine.arrival_contract import (
    ArrivalLedger,
    Commit,
    ContractRefusal,
    Head,
    Open,
    RecordDraft,
    StoreDescriptor,
    Watermark,
)
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_head_attestation import (
    HeadAttestation,
    HeadFork,
    HeadRewrite,
    HeadRollback,
    IndeterminateComparison,
    JournalEquivocation,
    Kind,
    Level,
    LineageReplaced,
    Outcome,
    StoreLost,
    append_entry,
    bindings_path,
    bound_lineage,
    heads_dir,
    journal_path,
    read_journal,
    state_root,
)
from engine.arrival_head_seam import (
    AttestedLedger,
    AuditFoundUnaccountedHeads,
    Compared,
    Indeterminate,
    NotWitnessed,
    PreGenesis,
    ProjectionAgreement,
    ProjectionAheadOfLedger,
    TrustResetNotHonored,
    audit,
    bootstrap,
    canonical_location,
    days_since_audit,
    match_identity,
    trust_reset,
)
from engine.arrival_registry import BackendRegistry
from engine.arrival_store import ArrivalStore
from engine.residence import index_path_for
from tests.conftest import STUB_KEY as _KEY
from tests.conftest import stub_sign as _sign


@pytest.fixture(autouse=True)
def _isolated_state_root(tmp_path, monkeypatch):
    """Point the state root at a temporary directory, for every test here."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


def test_the_state_root_is_redirected_for_this_suite(tmp_path):
    """The isolation itself, asserted rather than assumed.

    The fixture above is the only thing standing between this suite and the
    developer's real head journals, and a fixture that silently stopped
    applying would leave every other test in the file writing to
    ``~/.local/state/loops`` while still passing.
    """
    assert state_root() == tmp_path / "state" / "loops"
    assert Path.home() not in state_root().parents


# ---------------------------------------------------------------------------
# Real stores
# ---------------------------------------------------------------------------


def minted(path: Path) -> Path:
    """A real minted arrival log at ``path``."""
    ArrivalLog.mint(path, observer="kyle", signer=_sign, key=_KEY)
    return path


def append_legacy(log_path: Path, *messages: str) -> None:
    """Append through the LEGACY store path — which journals nothing.

    This is how an unjournaled advance is manufactured, and during slices 3-4
    it is also the ordinary write path, so the branch it exercises is the real
    one rather than a contrived one. It builds the sqlite projection beside the
    log as a side effect, which is what gives these tests a watermark.
    """
    store = ArrivalStore(
        path=index_path_for(log_path),
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=_sign,
    )
    try:
        for message in messages:
            store.append(Fact.of("note", "kyle", message=message))
    finally:
        store.close()


def opened(log_path: Path, **kwargs: Any) -> AttestedLedger:
    """The seam over a real file backend, without the registry."""
    return AttestedLedger(
        FileLedger(ArrivalLog(log_path)), location=str(log_path), **kwargs
    )


def through_registry(log_path: Path | str):
    """Exactly what a consumer gets: the registry's own wrapped pair."""
    return BackendRegistry.with_builtin_backends().open(
        StoreDescriptor(backend="file", location=str(log_path))
    )


def digest(path: Path) -> str:
    """A file's bytes, as one comparable string."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def journal_bytes(lineage: str) -> bytes:
    """The lineage's journal exactly as it sits on disk, or empty."""
    path = journal_path(lineage)
    return path.read_bytes() if path.exists() else b""


def lineage_of(log_path: Path) -> str:
    return ArrivalLog(log_path).lineage()


def truncate_records(log_path: Path, keep: int) -> None:
    """Drop every record past ``keep``, cleanly at a line boundary.

    Cleanly on purpose: a torn tail is a different failure with its own
    refusal, and this suite is about a log that is internally well-formed and
    SHORTER than the one this machine accepted. That is what a restore, a
    rollback or a deliberate truncation actually leaves behind.
    """
    lines = log_path.read_bytes().splitlines(keepends=True)
    log_path.write_bytes(b"".join(lines[: keep + 1]))


class Recorder:
    """A ledger that records which operations the seam actually called.

    The O(1) claim is about EVIDENCE GATHERED, not about wall clock: a timing
    assertion on a small store measures the machine, while the op list measures
    the design. ``verify(Open())`` is the constant-time tail read; ``head()``,
    ``scan()``, ``read()`` and ``verify(Full(...))`` all walk, so their absence
    from the list IS the claim that no full walk happened.
    """

    def __init__(self, inner: ArrivalLedger) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def mint(self, options):
        self.calls.append("mint")
        return self._inner.mint(options)

    def head(self, lineage=None):
        self.calls.append("head")
        return self._inner.head(lineage)

    def head_at(self, watermark):
        self.calls.append("head_at")
        return self._inner.head_at(watermark)

    def append(self, expected, drafts):
        self.calls.append("append")
        return self._inner.append(expected, drafts)

    def replicate(self, expected, records):
        self.calls.append("replicate")
        return self._inner.replicate(expected, records)

    def read(self, coordinate):
        self.calls.append("read")
        return self._inner.read(coordinate)

    def scan(self, *, after=None, through=None):
        self.calls.append("scan")
        return self._inner.scan(after=after, through=through)

    def verify(self, scope):
        self.calls.append(f"verify:{scope.level.value}")
        return self._inner.verify(scope)

    def export(self, *, through, codec):
        self.calls.append("export")
        return self._inner.export(through=through, codec=codec)

    def capabilities(self):
        return self._inner.capabilities()


# ---------------------------------------------------------------------------
# THE ITEM THAT MATTERS (§E.1) — detection precedes repair
# ---------------------------------------------------------------------------


def test_a_truncated_log_with_an_index_ahead_refuses_and_leaves_the_index_alone(
    tmp_path,
):
    """§D.2's whole argument, as an assertion about bytes.

    ``catch_up()`` runs on every ``ArrivalStore`` open and a shrunk log is one
    of its documented triggers for a full index REBUILD — which erases exactly
    the rows that testify to the truncation. So the comparison must happen
    somewhere that does no recovery, and the registry's opener is that place.

    Two assertions, and the second is the one that proves the placement rather
    than merely the detection: the open refuses with a typed refusal, **and the
    index file is byte-for-byte what it was before**. A detector downstream of
    the repair could still have refused — on the agreement the repair
    manufactured — so the refusal alone proves nothing.

    No journal exists for this store, deliberately. The projection being ahead
    of the ledger is evidence that stands entirely on its own, and it is the
    only signal available on a store this machine has never seen before.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one", "two", "three")
    index = index_path_for(log_path)

    truncate_records(log_path, keep=1)
    before = digest(index)
    assert not journal_path(lineage_of(log_path)).exists()

    with pytest.raises(ProjectionAheadOfLedger) as excinfo:
        through_registry(log_path)

    assert digest(index) == before, "the index was touched before it was judged"
    message = str(excinfo.value)
    assert "truncated log" in message
    assert "never edit the ledger to match the projection" in message


def test_the_refused_truncation_left_no_memory_claiming_it_was_accepted(tmp_path):
    """A refused open writes nothing — the ordering that makes the seam safe.

    The store above is first contact as far as the journal is concerned, and
    first contact WRITES a bootstrap receipt. If the projection comparison ran
    after that write, the journal would hold a permanent entry recording that
    this machine accepted the truncated head, at the very open that refused it
    — and the next open would then compare against the truncation as though it
    were the accepted history.

    That ordering is structural rather than remembered: the observation returns
    what should be written and writes nothing, and the constructor performs the
    write only once observation has returned without raising.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one", "two", "three")
    lineage = lineage_of(log_path)
    truncate_records(log_path, keep=1)

    with pytest.raises(ProjectionAheadOfLedger):
        through_registry(log_path)

    assert not journal_path(lineage).exists()
    assert not heads_dir().exists() or list(heads_dir().glob("*.jsonl")) == []


def test_an_advance_is_not_journaled_when_the_projection_then_refuses(tmp_path):
    """The gate's BLOCKING repro. A refused open must not move the witness.

    The headline cell above, in REMEMBERED form: the journal knows ordinal 1,
    an unjournaled writer took the store to 3, and the tail is then truncated
    back to 2. The journal comparison answers ADVANCED — legitimately, the
    descent from 1 to 2 verifies — and only then does the projection, still
    accounting for 3, refuse.

    Written from inside the classification, that advance entry survived the
    refusal: the journal permanently recorded that this machine accepted
    ordinal 2, at the very open that refused it, and the next open would
    compare against the truncation as though it were the accepted history.

    The claim "nothing writes until every refusal has had its chance" was true
    of the first-contact branch, which deferred, and false of this one, which
    did not — which is exactly why the rule now lives in a return type and a
    ratchet rather than in each branch's good intentions
    (``finding:s3wp3-gate-advance-journaled-before-projection-refusal``).
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)  # first contact at ordinal 1
    append_legacy(log_path, "two", "three")  # unjournaled, to ordinal 3
    truncate_records(log_path, keep=2)

    lineage = lineage_of(log_path)
    before = journal_bytes(lineage)
    index_before = digest(index_path_for(log_path))

    with pytest.raises(ProjectionAheadOfLedger):
        through_registry(log_path)

    assert journal_bytes(lineage) == before, (
        "a refused open advanced the witness"
    )
    assert digest(index_path_for(log_path)) == index_before


class ForeignWatermarkQuery:
    """A projection reporting a lineage that is not the log's.

    A double for the query half only — the ledger stays real, so the
    ``NotAuthority`` this provokes is the adapter's own refusal rather than a
    manufactured one. Building this state from real artifacts would mean
    swapping a log out from under a consumed index, which tests the swap rather
    than the branch.
    """

    def __init__(self, watermark: Watermark) -> None:
        self._watermark = watermark

    def lineage(self) -> str | None:
        return self._watermark.lineage

    def projected_through(self) -> Watermark | None:
        return self._watermark

    def close(self) -> None:
        return None


def test_an_advance_is_not_journaled_when_the_projection_disowns_the_log(
    tmp_path,
):
    """The second refusal sitting behind the same write.

    ``_projection``'s lineage-mismatch arm lets the adapter's ``NotAuthority``
    out — the projection is not a projection of this log — and it runs after
    the journal comparison just as the ahead-of-ledger arm does. Enumerated
    with it rather than left to be found later, because "the refusal I happened
    to test" is not the property; "every refusal that can follow a write" is.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    append_legacy(log_path, "two")  # unjournaled: the open will earn an ADVANCE

    lineage = lineage_of(log_path)
    before = journal_bytes(lineage)
    foreign = ForeignWatermarkQuery(
        Watermark(lineage="01BX5ZZKBKACTAV9WEVGEMMVRZ", ordinal=2)
    )

    with pytest.raises(ContractRefusal):  # NotAuthority, the adapter's own
        AttestedLedger(
            FileLedger(ArrivalLog(log_path)),
            location=str(log_path),
            query=foreign,
        )

    assert journal_bytes(lineage) == before


def test_only_the_constructor_and_the_producers_write_to_the_journal(tmp_path):
    """The rule as an enumerable property, not as review vigilance.

    The gate's finding was not that one branch was wrong — it was that "nothing
    writes until every refusal has had its chance" lived in prose, so the
    branch added second simply did not honor it. A per-branch rule fails
    whenever somebody adds a branch.

    So every call to a journal-writing name in this module must sit inside one
    of the functions allowed to write. The allowlist is SHRINK-ONLY: a new
    branch that writes inline fails here by name, and the fix is to return an
    ``_Earned`` rather than to widen the list.

    **Scope of the claim, stated because the matcher has a precondition.** This
    detects DIRECT-NAME calls — ``ast.Call`` whose ``func`` is an ``ast.Name``.
    It does not see a write reached through an attribute
    (``arrival_head_attestation.append_entry(...)``), through an alias, or
    through ``getattr``. That is deliberately not fixed by growing the matcher:
    a detector that chased every spelling would still miss one, and it would be
    claiming "no write escapes" — a verdict it cannot support — where the
    honest claim is "no direct-name write escapes".

    What IS closed is the innocent evasion, and it is closed by pinning the
    precondition rather than widening the detection. Switching this module to
    attribute-style imports would leave the scan green with zero offenders
    while every write site went invisible — a silent blinding, which is the
    worst failure a ratchet can have. So the precondition is asserted first: if
    a writing name stops being a module-level binding, this test fails LOUDLY
    and names the import, instead of quietly detecting nothing.

    The other spellings are caught today by the byte-compare behavior tests
    (`test_an_advance_is_not_journaled_when_the_projection_then_refuses` and
    its sibling). The residual this ratchet exists for is a later branch that
    has no behavior test yet, and for that branch the direct-name form is the
    one somebody actually writes.
    """
    import ast

    source = (
        Path(engine.arrival_head_seam.__file__).read_text(encoding="utf-8")
    )
    tree = ast.parse(source)

    writing = {"append_entry", "record_binding", "bootstrap", "trust_reset", "audit"}

    # THE PRECONDITION, asserted before the scan that depends on it. Every
    # writing name must be a module-level binding — imported by name, or
    # defined here — because that is what makes a call to it parse as
    # `ast.Call(func=ast.Name)`. If one stops being bound this way, the scan
    # below silently stops seeing its call sites, so the failure has to happen
    # HERE and name the import rather than there and name nothing.
    bound = {
        alias.asname or alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    unbound = writing - bound
    assert not unbound, (
        f"{sorted(unbound)} are no longer module-level bindings in "
        "arrival_head_seam.py, so this ratchet can no longer see calls to "
        "them and would pass by detecting nothing. If the module moved to "
        "attribute-style imports, that is the change to reconsider — the "
        "scan matches direct-name calls only, by design (see the docstring)."
    )

    # The producers write BY DEFINITION — each is the one place its entry kind
    # is created. `_write` is the open path's single write site, `mint` and
    # `_witness` are the mutation paths, and each has nothing that can refuse
    # after it (mint's bootstrap is last; `_witness` runs after the append has
    # already committed, which is what `NotWitnessed` exists to report).
    may_write = {
        "bootstrap",
        "trust_reset",
        "audit",
        "AttestedLedger._write",
        "AttestedLedger.mint",
        "AttestedLedger._witness",
    }

    offenders: list[str] = []

    def walk(node, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                walk(child, f"{scope}.{child.name}" if scope else child.name)
            else:
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id in writing
                    and scope not in may_write
                ):
                    offenders.append(f"{child.func.id}() called from {scope}")
                walk(child, scope)

    walk(tree, "")
    assert not offenders, (
        "journal writes outside the constructor's write site and the "
        "producers:\n  " + "\n  ".join(offenders) + "\nReturn an _Earned "
        "instead — see finding:s3wp3-gate-advance-journaled-before-projection-refusal"
    )
    # The allowlist must not rot into a list of things that no longer exist:
    # an entry naming a function somebody renamed would silently stop
    # permitting anything, and the next inline write would be caught for the
    # wrong reason or not at all.
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    stale = {name.split(".")[-1] for name in may_write} - defined
    assert not stale, f"allowlist names functions that no longer exist: {stale}"


def test_a_truncation_below_a_remembered_head_refuses_as_a_rollback(tmp_path):
    """The same truncation, on a store the journal DOES remember.

    Here the custody claim answers first: the presented head sits below the one
    this machine accepted, which is a rollback and refuses before the
    projection is ever consulted. The index is still untouched, because the
    refusal still precedes every repair.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one", "two", "three")
    ledger, query = through_registry(log_path)
    query.close()
    assert isinstance(ledger.opened.comparison, Compared)
    assert ledger.opened.comparison.outcome is Outcome.FIRST_CONTACT

    index = index_path_for(log_path)
    truncate_records(log_path, keep=1)
    before = digest(index)
    journal_before = journal_bytes(lineage_of(log_path))

    with pytest.raises(HeadRollback) as excinfo:
        through_registry(log_path)

    assert digest(index) == before
    assert journal_bytes(lineage_of(log_path)) == journal_before, (
        "a refused open advanced the journal"
    )
    assert "never move the witness backward" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Compare-on-open classifies correctly (§E.2)
# ---------------------------------------------------------------------------


def test_first_contact_is_labeled_and_the_label_is_permanent(tmp_path):
    """Trust on first use, recorded as exactly that and never as proof.

    A store that predates the journal has to be trusted on sight — refusing
    would make a fresh clone unable to read anything. The design's answer is
    not to pretend otherwise: the bootstrap entry records ``first-contact``,
    and slice 6's verification depends on telling that apart from a journal
    that begins at ``mint``.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")

    ledger, query = through_registry(log_path)
    query.close()

    comparison = ledger.opened.comparison
    assert isinstance(comparison, Compared)
    assert comparison.outcome is Outcome.FIRST_CONTACT
    assert comparison.known is None

    read = read_journal(lineage_of(log_path))
    assert read.bootstrap is not None
    assert read.bootstrap.kind is Kind.BOOTSTRAP
    assert read.bootstrap.level is Level.FIRST_CONTACT
    assert read.bootstrap.head == comparison.presented


def test_a_second_open_of_an_unchanged_store_is_unchanged(tmp_path):
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    through_registry(log_path)[1].close()

    ledger, query = through_registry(log_path)
    query.close()
    comparison = ledger.opened.comparison
    assert isinstance(comparison, Compared)
    assert comparison.outcome is Outcome.UNCHANGED
    assert comparison.known is not None
    assert comparison.known.head == comparison.presented


def test_an_unchanged_open_writes_zero_journal_bytes(tmp_path):
    """The rule that keeps reads off the write path.

    Byte-compare rather than an entry count: a rewritten file with the same
    number of entries would pass a count and still mean every read had become
    a writer.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    through_registry(log_path)[1].close()
    lineage = lineage_of(log_path)

    before = journal_bytes(lineage)
    assert before, "the first open should have written a bootstrap receipt"
    for _ in range(5):
        through_registry(log_path)[1].close()
    assert journal_bytes(lineage) == before


def test_an_unchanged_open_gathers_only_the_open_verification(tmp_path):
    """O(1), asserted by evidence gathered rather than by wall clock.

    ``verify(Open())`` is a constant-time reverse tail read. ``head()``,
    ``read()``, ``scan()`` and ``verify(Full(...))`` all walk the log from
    ordinal 0, so their absence from the recorded call list is the claim that
    the dominant case pays for no walk at all. The projection comparison adds
    nothing: comparing the watermark's ordinal against the presented head is
    arithmetic, and ``head_at`` is reached only when they disagree.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    through_registry(log_path)[1].close()

    recorder = Recorder(FileLedger(ArrivalLog(log_path)))
    query = FileQuery(index_path_for(log_path))
    try:
        ledger = AttestedLedger(
            recorder, location=str(log_path), query=query
        )
    finally:
        query.close()

    assert isinstance(ledger.opened.comparison, Compared)
    assert ledger.opened.comparison.outcome is Outcome.UNCHANGED
    assert recorder.calls == ["verify:open"], recorder.calls


def test_an_unjournaled_advance_is_verified_before_it_is_accepted(tmp_path):
    """An advance observed AT OPEN means an unjournaled writer touched it.

    A foreign host, a restore, a crashed process — or, during slices 3-4, the
    legacy store path, which is what this test uses. Paying a verified walk
    there is correct rather than a regression, and the walk is not merely "did
    we reach the presented head": it also asks what the record at the
    remembered ordinal is now, because a walk that only reached the top has
    verified the current chain while answering nothing about continuity with
    what was previously accepted.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    through_registry(log_path)[1].close()
    append_legacy(log_path, "two", "three")

    recorder = Recorder(FileLedger(ArrivalLog(log_path)))
    ledger = AttestedLedger(recorder, location=str(log_path))

    comparison = ledger.opened.comparison
    assert isinstance(comparison, Compared)
    assert comparison.outcome is Outcome.ADVANCED
    assert "verify:full" in recorder.calls, recorder.calls
    assert "head_at" in recorder.calls, recorder.calls

    read = read_journal(lineage_of(log_path))
    assert read.known is not None
    latest = read.entries[-1]
    assert latest.kind is Kind.ADVANCE
    assert latest.level is Level.DESCENDANT
    assert latest.head == comparison.presented


def test_a_restored_older_copy_refuses_as_a_rollback(tmp_path):
    """The store moved backward; the witness does not follow it."""
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    backup = log_path.read_bytes()
    append_legacy(log_path, "two", "three")
    through_registry(log_path)[1].close()

    lineage = lineage_of(log_path)
    journal_before = journal_bytes(lineage)
    log_path.write_bytes(backup)

    with pytest.raises(HeadRollback) as excinfo:
        opened(log_path)

    assert journal_bytes(lineage) == journal_before
    assert "Locate a replica or backup" in str(excinfo.value)


def test_two_records_at_one_height_refuse_as_a_fork(tmp_path):
    """Same lineage, same ordinal, different record. Never pick a branch."""
    log_path = minted(tmp_path / "s.arrival")
    genesis_only = log_path.read_bytes()
    append_legacy(log_path, "one")
    opened(log_path)  # remembers this branch's ordinal 1

    other = tmp_path / "other.arrival"
    other.write_bytes(genesis_only)
    append_legacy(other, "a different one")
    log_path.write_bytes(other.read_bytes())

    with pytest.raises(HeadFork) as excinfo:
        opened(log_path)
    assert "never pick the taller branch" in str(excinfo.value)


def test_a_rewritten_interior_record_refuses_as_a_rewrite(tmp_path):
    """A taller chain that verifies perfectly, and is a different history.

    The rewritten store is internally flawless: genesis validates, every record
    links, the head is the last one. What it is not is a continuation of what
    this machine accepted — the record at the remembered ordinal has been
    replaced — and height is not evidence of continuity.
    """
    log_path = minted(tmp_path / "s.arrival")
    genesis_only = log_path.read_bytes()
    append_legacy(log_path, "one")
    opened(log_path)  # remembers ordinal 1 of the original branch

    other = tmp_path / "other.arrival"
    other.write_bytes(genesis_only)
    append_legacy(other, "a different one", "and another")
    log_path.write_bytes(other.read_bytes())
    index_path_for(log_path).unlink(missing_ok=True)

    with pytest.raises(HeadRewrite) as excinfo:
        opened(log_path)
    # It verifies as a chain — the refusal is about continuity, not integrity.
    assert FileLedger(ArrivalLog(log_path)).verify(Open()).ordinal == 2
    assert "different history" in str(excinfo.value)


def test_a_fresh_lineage_at_a_known_location_refuses_as_a_replacement(tmp_path):
    """Lineage-keying's one hole, closed by the transitional binding.

    A store rewritten with a NEW lineage finds no journal of its own and would
    be first contact — §07's "replacement or explicit re-custody" row passing
    silently. The binding is what knows this location already presented a
    different lineage.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    first = lineage_of(log_path)

    log_path.unlink()
    index_path_for(log_path).unlink(missing_ok=True)
    minted(log_path)
    assert lineage_of(log_path) != first

    with pytest.raises(LineageReplaced) as excinfo:
        opened(log_path)
    assert first in str(excinfo.value)
    assert "wearing the old name" in str(excinfo.value)


def test_the_binding_matches_through_a_non_canonical_path(tmp_path):
    """The seam passes ONE canonical form, or the binding closes nothing.

    ``bindings.jsonl`` matches ``location`` as an exact string, so a store
    reached by a relative route, through a ``..`` segment, or through a symlink
    would present a second key and manufacture a first contact through exactly
    the hole the binding exists to close. This is the same replacement as
    above, reached by a different spelling of the same path.
    """
    nested = tmp_path / "d"
    nested.mkdir()
    log_path = minted(nested / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    first = lineage_of(log_path)

    log_path.unlink()
    index_path_for(log_path).unlink(missing_ok=True)
    minted(log_path)

    detour = tmp_path / "d" / ".." / "d" / "s.arrival"
    assert str(detour) != str(log_path)
    with pytest.raises(LineageReplaced):
        opened(detour)

    assert bound_lineage(canonical_location(str(detour))) == first


def test_a_projection_behind_the_ledger_is_ordinary_staleness(tmp_path):
    """A lagging projection is catch-up's job and is never a refusal.

    Refusing a projection that lags would make the seam an availability
    problem rather than a witness: a store between a commit and its next
    catch-up is in this state by construction.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    append_through_seam(log_path, "two")

    ledger, query = through_registry(log_path)
    try:
        assert ledger.opened.projection is not None
        assert ledger.opened.projection.agreement is ProjectionAgreement.BEHIND
    finally:
        query.close()


def test_a_store_with_no_projection_reports_absent_rather_than_guessing(tmp_path):
    log_path = minted(tmp_path / "s.arrival")
    ledger, query = through_registry(log_path)
    try:
        assert ledger.opened.projection is not None
        assert ledger.opened.projection.agreement is ProjectionAgreement.ABSENT
        assert ledger.opened.projection.watermark is None
    finally:
        query.close()


# ---------------------------------------------------------------------------
# Journaling on commit (§E.3)
# ---------------------------------------------------------------------------


def append_through_seam(log_path: Path, *messages: str) -> Commit:
    """Append through the wrapper, the way slice 5's writers will."""
    ledger = opened(log_path)
    commit = ledger.append(
        ledger.head(),
        [
            RecordDraft(kind="note", authored_at=0.0, observer="kyle", body={"m": m})
            for m in messages
        ],
    )
    return commit


def test_an_append_through_the_wrapper_journals_its_commit(tmp_path):
    """The commit IS the descent evidence, and it is recorded as such.

    A successful append compared the full head under the fence, so the writer
    holds the strongest evidence there is. Recording it at ``commit`` level is
    what makes the next open cheap rather than making it re-derive what this
    process already knew.
    """
    log_path = minted(tmp_path / "s.arrival")
    commit = append_through_seam(log_path, "one")

    read = read_journal(lineage_of(log_path))
    latest = read.entries[-1]
    assert latest.kind is Kind.ADVANCE
    assert latest.level is Level.COMMIT
    assert latest.head == commit.after


def test_commit_then_open_takes_the_o1_path_not_the_advance_path(tmp_path):
    """§E.6: the second open is unchanged, not advanced.

    This is the whole point of journaling on commit. Without it the next open
    observes an advance and pays two verified walks for evidence the writing
    process had already gathered and thrown away.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_through_seam(log_path, "one")

    recorder = Recorder(FileLedger(ArrivalLog(log_path)))
    ledger = AttestedLedger(recorder, location=str(log_path))

    assert isinstance(ledger.opened.comparison, Compared)
    assert ledger.opened.comparison.outcome is Outcome.UNCHANGED
    assert recorder.calls == ["verify:open"], recorder.calls


def test_a_mint_through_the_wrapper_writes_a_mint_level_receipt(tmp_path):
    """§E.7, and slice 6's exit criterion depends on the level.

    A journal beginning at ``mint`` was witnessed from genesis forward; one
    beginning at ``first-contact`` was trusted on sight. Slice 4's sidecar must
    produce the former for every migrated store, and it gets it with no
    privileged path — by minting through the ordinary registry-opened ledger.
    """
    log_path = tmp_path / "s.arrival"
    ledger, query = through_registry(log_path)
    try:
        assert isinstance(ledger.opened.comparison, PreGenesis)
        head = ledger.mint({"observer": "kyle", "signer": _sign, "key": _KEY})
    finally:
        query.close()

    read = read_journal(head.lineage)
    assert read.bootstrap is not None
    assert read.bootstrap.kind is Kind.BOOTSTRAP
    assert read.bootstrap.level is Level.MINT
    assert read.bootstrap.head == head
    assert bound_lineage(canonical_location(str(log_path))) == head.lineage


def test_a_journal_write_failure_after_a_commit_says_the_records_are_committed(
    tmp_path, monkeypatch
):
    """§05's committed-versus-witnessed distinction, never collapsed.

    The append has already landed when the journal write fails, so reporting a
    failed append would be a lie in the direction that loses data. The type
    raised is deliberately NOT a refusal — every member of that family means
    the operation did not happen — so a caller catching the refusal root to
    mean "nothing changed" does not catch this and it propagates.
    """
    log_path = minted(tmp_path / "s.arrival")
    ledger = opened(log_path)

    def refuse_to_write(_entry):
        raise OSError("no space left on device")

    monkeypatch.setattr(
        "engine.arrival_head_seam.append_entry", refuse_to_write
    )
    with pytest.raises(NotWitnessed) as excinfo:
        ledger.append(
            ledger.head(),
            [RecordDraft(kind="note", authored_at=0.0, observer="kyle")],
        )

    assert not isinstance(excinfo.value, ContractRefusal)
    assert excinfo.value.commit is not None
    assert excinfo.value.head == excinfo.value.commit.after
    assert "COMMITTED" in str(excinfo.value)
    # And the records really are there — the claim the type makes.
    assert FileLedger(ArrivalLog(log_path)).head().ordinal == 1


_CONCURRENT_WRITER = """
import os, sys
from pathlib import Path
from engine.arrival import ArrivalLog
from engine.arrival_contract import HeadMismatch, RecordDraft
from engine.arrival_file_backend import FileLedger
from engine.arrival_head_seam import AttestedLedger

log_path = Path(sys.argv[1])
rounds = int(sys.argv[2])
tag = sys.argv[3]
ledger = AttestedLedger(FileLedger(ArrivalLog(log_path)), location=str(log_path))
landed = 0
for i in range(rounds):
    for _attempt in range(60):
        try:
            ledger.append(
                ledger.head(),
                [RecordDraft(kind="note", authored_at=0.0, observer=tag,
                             body={"i": i})],
            )
        except HeadMismatch:
            continue
        landed += 1
        break
print(landed)
"""

_CONCURRENT_OPENER = """
import sys
from pathlib import Path
from engine.arrival import ArrivalLog
from engine.arrival_file_backend import FileLedger
from engine.arrival_head_seam import AttestedLedger

log_path = Path(sys.argv[1])
for _ in range(int(sys.argv[2])):
    AttestedLedger(FileLedger(ArrivalLog(log_path)), location=str(log_path))
print("ok")
"""


def test_two_writers_and_an_opener_leave_a_parseable_journal(tmp_path):
    """WP1's own suggestion, carried up to the seam that writes.

    WP1's lesson from its write-path findings generalizes: *a read rule that
    closes a hazard can be reopened by the write path*, because the reader only
    ever judges bytes that survived the write. WP1 proved its journal survives
    concurrent appends; this proves the SEAM's journaling-on-commit does, with
    a third process comparing on open at the same time.

    Three assertions, and the third is the one that matters: every line parses
    independently, the journal's remembered head is the store's actual head
    (so no observation was lost or glued to another), and the read is complete
    — because an incomplete read is exactly what a torn or overwritten line
    would produce.
    """
    log_path = minted(tmp_path / "s.arrival")
    lineage = lineage_of(log_path)
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
    rounds = 20

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CONCURRENT_WRITER, str(log_path), str(rounds), tag],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for tag in ("a", "b")
    ]
    procs.append(
        subprocess.Popen(
            [sys.executable, "-c", _CONCURRENT_OPENER, str(log_path), str(rounds)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    )
    outs = [proc.communicate() for proc in procs]
    for proc, (_out, err) in zip(procs, outs, strict=True):
        assert proc.returncode == 0, err

    # Contention actually happened, rather than the processes politely queueing
    # up: both writers landed records, and every record they landed is in the
    # log. A concurrency test where only one writer ever wrote proves nothing.
    landed = [int(out.strip()) for out, _err in outs[:2]]
    assert all(count == rounds for count in landed), landed
    head = FileLedger(ArrivalLog(log_path)).verify(Open())
    assert head.ordinal == sum(landed)

    raw = journal_path(lineage).read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(raw):
        assert json.loads(line), f"line {index + 1} did not parse: {line!r}"

    read = read_journal(lineage)
    assert read.skipped == (), read.skipped
    established = read.established_head()
    assert established is not None
    assert established.head == head


class StaleThenFresh:
    """A ledger whose first head observation is one commit out of date.

    Exactly the interleaving the concurrent run above produces by luck, made
    deterministic: the seam reads the store, another process commits and
    journals, and only then does the seam read the journal. Nothing here is
    fabricated — both heads are real heads of the same real log, taken a commit
    apart.
    """

    def __init__(self, inner: ArrivalLedger, stale: Head) -> None:
        self._inner = inner
        self._stale = stale
        self.observations = 0

    def verify(self, scope):
        if isinstance(scope, Open):
            self.observations += 1
            if self.observations == 1:
                return self._stale
        return self._inner.verify(scope)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_a_commit_racing_the_open_is_not_reported_as_a_rollback(tmp_path):
    """The across-time hazard, pinned deterministically.

    The seam compares two files read at two different moments. A writer that
    commits and journals between them leaves the journal holding a head the
    store's older observation does not have — which is bit-for-bit what a
    rollback looks like, and would tell an operator their store lost data
    because two ordinary writes overlapped.

    The fix is to make the refusing observation not older than the journal:
    a presented head below what the journal already knows earns one more
    constant-time tail read, and the fresher answer is what gets classified.
    Found by the concurrent run above before it was pinned here
    (``finding:s3wp3-open-compares-across-time``).
    """
    log_path = minted(tmp_path / "s.arrival")
    append_through_seam(log_path, "one")
    stale = FileLedger(ArrivalLog(log_path)).verify(Open())
    append_through_seam(log_path, "two")  # commits AND journals, as a peer would

    racing = StaleThenFresh(FileLedger(ArrivalLog(log_path)), stale)
    ledger = AttestedLedger(racing, location=str(log_path))

    assert racing.observations == 2, "the descending branch re-observed once"
    comparison = ledger.opened.comparison
    assert isinstance(comparison, Compared)
    assert comparison.outcome is Outcome.UNCHANGED
    assert comparison.presented.ordinal == 2


def test_a_genuine_rollback_survives_the_re_observation(tmp_path):
    """The other direction: re-reading must not soften a real refusal.

    A rollback is stable across both reads — the store keeps presenting the
    lower head — so the extra observation changes nothing about it. Without
    this the fix above could have been "stop refusing rollbacks", which would
    pass the race test and defeat the whole module.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    backup = log_path.read_bytes()
    append_legacy(log_path, "two")
    opened(log_path)

    log_path.write_bytes(backup)
    recorder = Recorder(FileLedger(ArrivalLog(log_path)))
    with pytest.raises(HeadRollback):
        AttestedLedger(recorder, location=str(log_path))
    assert recorder.calls == ["verify:open", "verify:open"], recorder.calls


# ---------------------------------------------------------------------------
# The store-absent branches (§E.8, §D.4)
# ---------------------------------------------------------------------------


def test_a_fresh_location_is_pre_genesis_and_makes_no_claim(tmp_path):
    """Refusing here would make minting impossible.

    The seam did not verify a store and it did not accept one, and the report
    says exactly that. The ledger's own refusal is carried rather than
    swallowed, so the branch is labeled rather than silent.
    """
    ledger = opened(tmp_path / "nothing.arrival")
    comparison = ledger.opened.comparison
    assert isinstance(comparison, PreGenesis)
    assert comparison.ledger_refusal is not None
    assert not heads_dir().exists()


def test_a_deleted_store_whose_journal_remembers_a_head_refuses(tmp_path):
    """The attack matrix's "delete the store and every backup" row.

    The witness proves what was LOST, not its contents. Proceeding would mean
    a location whose journal remembers a head opening as though nothing had
    ever been there.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    log_path.unlink()

    with pytest.raises(StoreLost) as excinfo:
        opened(log_path)
    assert "proves what was lost" in str(excinfo.value)


def test_a_re_mint_under_a_remembered_location_refuses_too(tmp_path):
    """A fresh genesis where a head is remembered is a replacement.

    The refusal must fire before the mint, not after: an open that proceeded
    would hand back a ledger whose ``mint`` is reachable, and a fresh genesis
    at a location whose journal remembers ordinal N is a replacement wearing
    the old name.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    log_path.unlink()

    with pytest.raises(StoreLost):
        opened(log_path)
    # And the ledger was never handed back, so nothing can mint through it.
    assert not log_path.exists()


def test_an_unreadable_journal_with_the_log_gone_refuses_rather_than_proceeding(
    tmp_path,
):
    """BLOCKING-2, reached through the absent-store door.

    A journal holding content none of which is readable has no entry to pass
    to the absent-store split, and passing ``None`` would answer pre-genesis —
    a store trusted as never-having-existed precisely because its memory became
    unreadable. Content present says heads WERE accepted, and that answers the
    question the split actually asks.
    """
    log_path = minted(tmp_path / "s.arrival")
    lineage = lineage_of(log_path)
    opened(log_path)
    log_path.unlink()

    # A journal of nothing but entries from a later build: content present,
    # none of it readable by this one.
    journal_path(lineage).write_text(
        json.dumps({"v": 1, "type": "arrival-head-observation"})
        + "\n"
        + json.dumps({"v": 99, "kind": "future", "lineage": lineage})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(StoreLost) as excinfo:
        opened(log_path)
    assert "not first contact" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The IndeterminateComparison posture (§E.5) — WP3's design point
# ---------------------------------------------------------------------------


def damage_a_line(lineage: str, needle: str) -> None:
    """Replace the first journal line containing ``needle`` with garbage.

    Exactly what a crashed writer or a bad block leaves: a line this build
    cannot read, sitting in a file it can otherwise read fine.
    """
    path = journal_path(lineage)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if needle in line:
            lines[index] = "{ this is not json\n"
            break
    else:  # pragma: no cover - a test that damaged nothing proves nothing
        raise AssertionError(f"no journal line held {needle!r}")
    path.write_text("".join(lines), encoding="utf-8")


def test_an_incomplete_read_still_refuses_a_head_below_the_bound(tmp_path):
    """The posture's first half: every SOUND refusal still fires.

    A presented head below the bound is below the accepted head whatever the
    read missed — the readable entries bound it from below, and damage cannot
    lower a bound beneath what the surviving entries prove. Proceeding here
    would be the silent re-acceptance the journal exists to prevent, and it
    would be reachable by damaging one line.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    backup = log_path.read_bytes()
    append_legacy(log_path, "two", "three")
    opened(log_path)
    lineage = lineage_of(log_path)

    append_entry_for_damage(lineage)
    damage_a_line(lineage, "damage-me")

    log_path.write_bytes(backup)
    with pytest.raises(HeadRollback) as excinfo:
        opened(log_path)
    assert "incomplete" in str(excinfo.value)


def append_entry_for_damage(lineage: str) -> None:
    """A recognizable extra entry, so a specific line can be damaged.

    Written at a LOWER ordinal than the remembered head, so damaging it leaves
    the bound exactly where it was: the point is to make the read incomplete
    without changing what the surviving entries prove. That is also the honest
    shape of the real failure — a crash costs a line, not a claim.
    """
    append_entry(
        HeadAttestation(
            head=Head(
                lineage=lineage, ordinal=0, record_hash="damage-me" + "0" * 55
            ),
            kind=Kind.AUDIT,
            level=Level.FULL,
            observed_at=1.0,
            note="damage-me",
        )
    )


def test_an_incomplete_read_still_refuses_a_fork_at_the_bound(tmp_path):
    """The posture's second half: the bound is a real accepted entry.

    A presented head at the bound's ordinal with a different hash means two
    records claim one height, and the lost lines cannot make that agree.
    """
    log_path = minted(tmp_path / "s.arrival")
    genesis_only = log_path.read_bytes()
    append_legacy(log_path, "one")
    opened(log_path)
    lineage = lineage_of(log_path)

    append_entry_for_damage(lineage)
    damage_a_line(lineage, "damage-me")

    other = tmp_path / "other.arrival"
    other.write_bytes(genesis_only)
    append_legacy(other, "a different one")
    log_path.write_bytes(other.read_bytes())

    with pytest.raises(HeadFork) as excinfo:
        opened(log_path)
    assert "incomplete" in str(excinfo.value)


def test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound(tmp_path):
    """The posture's choice, pinned.

    At and above the bound is the genuinely indeterminate region: equal is not
    unchanged (it may be a rollback from the entry the read missed) and higher
    is not advanced (nothing bounds the accepted head from above). The seam
    proceeds and claims NEITHER — the report carries no outcome at all — and
    the refusal that was not raised is carried on it.

    Refusing instead would make one crashed writer a store that never opens
    again: the journal is append-only and the torn-tail guard preserves the
    fragment, so an incomplete read is permanent. That is verbatim the argument
    WP1's amended ruling used to reject refusing one level down.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    lineage = lineage_of(log_path)

    append_entry_for_damage(lineage)
    damage_a_line(lineage, "damage-me")

    ledger = opened(log_path)
    comparison = ledger.opened.comparison
    assert isinstance(comparison, Indeterminate)
    assert comparison.at_least is not None
    assert comparison.skipped
    assert isinstance(comparison.refusal, IndeterminateComparison)
    # Unignorable by construction: there is no outcome to read off it.
    assert not hasattr(comparison, "outcome")
    # The ledger still works — reads are what a crash must not brick.
    assert ledger.head().ordinal == 1


def test_an_incomplete_read_does_not_answer_advanced_above_the_bound(tmp_path):
    """The second unsound proceed-answer, and the one a reader talks themselves
    into.

    "Below the bound is a rollback" is easy to believe and easy to get right.
    "Above the bound is an advance" *feels* equally safe and is not: nothing
    bounds the accepted head from ABOVE, so a presented head at ordinal 3 may
    still sit below an entry at 200 that the read missed, and descent verified
    from the bound says nothing about an entry that was never on the walk.

    **This seam is where that rule becomes enforced behavior.** Nothing
    upstream pins it — ``established_head()`` refuses rather than answering,
    ``HeadLowerBound`` has no public methods at all, and the comparison vectors
    recompute the arithmetic in their own runner rather than driving the
    module. So a caller that reached for ``at_least`` and compared it like a
    head would meet nothing that objected, which is exactly why the assertion
    lives here.

    The write assertion is the other half: journaling a ``DESCENDANT`` entry at
    the presented head would raise the bound on evidence the read did not have,
    which is how a degraded open launders itself into a memory.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    lineage = lineage_of(log_path)
    append_entry_for_damage(lineage)
    damage_a_line(lineage, "damage-me")
    before = journal_bytes(lineage)

    append_legacy(log_path, "two", "three")
    ledger = opened(log_path)

    comparison = ledger.opened.comparison
    assert isinstance(comparison, Indeterminate), "an advance was claimed"
    assert comparison.presented.ordinal == 3
    assert comparison.at_least is not None
    assert comparison.at_least.ordinal == 1
    assert journal_bytes(lineage) == before, "the bound was raised on nothing"


def test_a_degraded_open_writes_nothing(tmp_path):
    """The degradation never launders itself into a memory.

    A written entry would raise the bound on evidence the read did not have,
    and would make a lost line look accounted for. Nothing is lost by not
    writing: ``skipped`` is derived from the journal's own bytes, so every
    later open re-derives the same degradation.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    lineage = lineage_of(log_path)
    append_entry_for_damage(lineage)
    damage_a_line(lineage, "damage-me")

    before = journal_bytes(lineage)
    for _ in range(3):
        opened(log_path)
    assert journal_bytes(lineage) == before


def test_a_journal_with_no_readable_content_is_not_granted_a_receipt(tmp_path):
    """BLOCKING-2 at the seam: unreadable is not first contact.

    An empty journal says nothing was ever accepted here and trust on first use
    is the honest answer. A journal holding content this build cannot read says
    heads WERE accepted and their ordinals are what was lost — so it gets no
    bootstrap receipt, because writing one would record a trust decision made
    precisely because the memory became unreadable.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    lineage = lineage_of(log_path)
    journal_path(lineage).parent.mkdir(parents=True, exist_ok=True)
    journal_path(lineage).write_text(
        json.dumps({"v": 1, "type": "arrival-head-observation"})
        + "\n"
        + json.dumps({"v": 99, "kind": "future"})
        + "\n",
        encoding="utf-8",
    )
    before = journal_bytes(lineage)

    ledger = opened(log_path)
    comparison = ledger.opened.comparison
    assert isinstance(comparison, Indeterminate)
    assert comparison.at_least is None, "there is no bound to be had"
    assert journal_bytes(lineage) == before, "a receipt was written anyway"


def test_the_carried_refusal_is_the_one_the_journal_itself_raises(tmp_path):
    """The seam consulted the unignorable path rather than routing around it.

    ``established_head()`` is the only way to obtain a ``compare`` argument and
    it refuses on an incomplete read. Carrying the instance it raised — rather
    than constructing a lookalike — is what proves the seam went through that
    door, and a caller wanting the strict posture can raise it unchanged.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    lineage = lineage_of(log_path)
    append_entry_for_damage(lineage)
    damage_a_line(lineage, "damage-me")

    comparison = opened(log_path).opened.comparison
    assert isinstance(comparison, Indeterminate)
    with pytest.raises(IndeterminateComparison) as excinfo:
        read_journal(lineage).established_head()
    assert str(comparison.refusal) == str(excinfo.value)


# ---------------------------------------------------------------------------
# The producers
# ---------------------------------------------------------------------------


def test_the_audit_writes_a_full_entry_after_a_full_verification(tmp_path):
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one", "two")
    ledger = opened(log_path)
    lineage = lineage_of(log_path)
    read = read_journal(lineage)

    audit(
        FileLedger(ArrivalLog(log_path)),
        presented=ledger.head(),
        epoch=read.epoch,
        projection="projection agrees through ordinal 2",
        location=str(log_path),
        observed_at=1000.0,
    )

    latest = read_journal(lineage).entries[-1]
    assert latest.kind is Kind.AUDIT
    assert latest.level is Level.FULL
    assert latest.note == "projection agrees through ordinal 2"


def test_the_audit_refuses_and_writes_nothing_when_a_head_is_unaccounted(tmp_path):
    """An audit entry asserts the walk found everything it was asked about.

    Writing one over a head the store can no longer account for would record a
    verification that did not happen, so the refusal replaces the entry rather
    than accompanying it.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one", "two")
    ledger = opened(log_path)
    lineage = lineage_of(log_path)
    epoch = list(read_journal(lineage).epoch)
    epoch.append(
        HeadAttestation(
            head=Head(lineage=lineage, ordinal=1, record_hash="f" * 64),
            kind=Kind.ADVANCE,
            level=Level.COMMIT,
            observed_at=1.0,
        )
    )
    before = journal_bytes(lineage)

    with pytest.raises(AuditFoundUnaccountedHeads) as excinfo:
        audit(
            FileLedger(ArrivalLog(log_path)),
            presented=ledger.head(),
            epoch=epoch,
            projection="agrees",
            location=str(log_path),
            observed_at=1000.0,
        )
    assert len(excinfo.value.heads) == 1
    assert journal_bytes(lineage) == before


def test_the_audits_lookup_cannot_be_supplied_by_a_caller(tmp_path):
    """Composition-boundary hardening, mechanized rather than asserted in prose.

    ``unaccounted_heads`` takes an injected ``at_ordinal`` so the neutral
    module never reaches for a backend — and an injection point is where a
    fabricated head can lie: a lookup answering from the journal, from a cache,
    or from the projection would "confirm" every entry without the store having
    been asked anything. So the audit accepts no lookup parameter and builds one
    from ``head_at``, a verified walk obtained through custody.
    """
    import inspect

    params = set(inspect.signature(audit).parameters)
    assert params == {
        "ledger",
        "presented",
        "epoch",
        "projection",
        "location",
        "observed_at",
    }, params


def test_staleness_is_reported_and_never_triggered(tmp_path):
    """The open path reports days since the last audit; it never runs one.

    A full walk at open is exactly what the adapter refused to pay under an
    ``Open`` label. An open that quietly upgraded its own verification level
    would be lying about its cost, so the report is the whole of it.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    lineage = lineage_of(log_path)
    ledger_for_head = FileLedger(ArrivalLog(log_path))
    audit(
        ledger_for_head,
        presented=ledger_for_head.verify(Open()),
        epoch=read_journal(lineage).epoch,
        projection="agrees",
        location=str(log_path),
        observed_at=1000.0,
    )

    recorder = Recorder(FileLedger(ArrivalLog(log_path)))
    ledger = AttestedLedger(
        recorder, location=str(log_path), clock=lambda: 1000.0 + 3 * 86400.0
    )
    assert ledger.opened.days_since_audit == pytest.approx(3.0)
    assert "verify:full" not in recorder.calls, recorder.calls


def test_staleness_is_none_when_no_audit_has_covered_this_epoch(tmp_path):
    """None means "no audit has covered this epoch", not "it was long ago"."""
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    assert opened(log_path).opened.days_since_audit is None


def test_staleness_is_epoch_scoped(tmp_path):
    """An audit before a trust reset covered a history the reset abandoned."""
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    ledger = opened(log_path)
    lineage = lineage_of(log_path)
    head = ledger.head()
    audit(
        FileLedger(ArrivalLog(log_path)),
        presented=head,
        epoch=read_journal(lineage).epoch,
        projection="agrees",
        location=str(log_path),
        observed_at=1000.0,
    )
    assert days_since_audit(read_journal(lineage), 1000.0) == 0.0

    trust_reset(
        accepted=head,
        abandoned=head,
        refused=None,
        reason="operator restored from the archive",
        location=str(log_path),
        observed_at=2000.0,
    )
    assert days_since_audit(read_journal(lineage), 2000.0) is None


def test_the_trust_reset_records_the_gap_and_opens_an_epoch(tmp_path):
    """§11's last row: record the gap, and never treat a presented store as proven.

    The entry is what lets a legitimately accepted restore stop refusing
    forever: the read scope moves to the reset entry and everything after it,
    while the abandoned entries stay in the file as evidence rather than as
    claims.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    backup = log_path.read_bytes()
    append_legacy(log_path, "two", "three")
    opened(log_path)
    lineage = lineage_of(log_path)
    abandoned = FileLedger(ArrivalLog(log_path)).verify(Open())

    log_path.write_bytes(backup)
    with pytest.raises(HeadRollback):
        opened(log_path)

    restored = FileLedger(ArrivalLog(log_path)).verify(Open())
    trust_reset(
        accepted=restored,
        abandoned=abandoned,
        refused=restored,
        reason="restored from the 2026-08-01 archive after disk loss",
        location=str(log_path),
        observed_at=5000.0,
    )

    entry = read_journal(lineage).entries[-1]
    assert entry.kind is Kind.TRUST_RESET
    assert entry.level is Level.FIRST_CONTACT, "the weakest claim, by default"
    assert "disk loss" in entry.note
    assert abandoned.record_hash in entry.note

    comparison = opened(log_path).opened.comparison
    assert isinstance(comparison, Compared)
    assert comparison.outcome is Outcome.UNCHANGED
    # The abandoned entries are still there — evidence, not claims.
    assert len(read_journal(lineage).entries) > len(read_journal(lineage).epoch)


def test_a_trust_reset_refuses_to_record_an_empty_reason(tmp_path):
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    head = opened(log_path).head()
    with pytest.raises(ValueError, match="records the gap"):
        trust_reset(
            accepted=head,
            abandoned=None,
            refused=None,
            reason="   ",
            location=str(log_path),
            observed_at=1.0,
        )


def test_a_bootstrap_refuses_a_level_a_first_entry_cannot_have(tmp_path):
    """Every other level names evidence there was nothing to gather.

    ``commit``, ``descendant`` and ``full`` each describe something established
    against a predecessor, and a first entry has none — so accepting one would
    let a journal open with a claim stronger than anything that happened.
    """
    with pytest.raises(ValueError, match="bootstrap entry"):
        bootstrap(
            Head(lineage="01ARZ3NDEKTSV4RRFFQ69G5FAV", ordinal=0, record_hash="a" * 64),
            level=Level.DESCENDANT,
            location=str(tmp_path / "s.arrival"),
            observed_at=1.0,
        )


# ---------------------------------------------------------------------------
# The wrapper's surface
# ---------------------------------------------------------------------------


def test_the_wrapper_satisfies_the_ledger_surface(tmp_path):
    log_path = minted(tmp_path / "s.arrival")
    ledger = opened(log_path)
    assert isinstance(ledger, ArrivalLedger)


def test_import_prefix_is_not_reachable_through_the_wrapper(tmp_path):
    """Delegation is by explicit method, never ``__getattr__``.

    ``import_prefix`` is a mutation the contract Protocol deliberately does not
    declare but which is in ``LEDGER_MUTATIONS`` regardless, because the
    custody/reads separation must cover every op that can change what a lineage
    holds. A catch-all would forward it silently — a mutation reachable through
    the attested handle that the seam does not journal, which is a hole in the
    witness opened by a convenience nobody wrote down.

    The same construction covers ops that do not exist yet: a future mutation
    added to an adapter is unreachable through this wrapper until somebody
    decides how it is witnessed.
    """
    log_path = minted(tmp_path / "s.arrival")
    ledger = opened(log_path)
    assert hasattr(FileLedger(ArrivalLog(log_path)), "import_prefix")
    assert not hasattr(ledger, "import_prefix")
    assert not hasattr(ledger, "an_op_invented_by_a_later_adapter")


def test_the_wrapper_reports_the_backends_capabilities_unchanged(tmp_path):
    """Everything ``Capabilities`` describes belongs to the backend.

    Amending the report to mention the witness would advertise a guarantee at
    the layer that does not provide it, and an over-claim there turns a
    deployment refusal into a runtime failure.
    """
    log_path = minted(tmp_path / "s.arrival")
    inner = FileLedger(ArrivalLog(log_path))
    assert opened(log_path).capabilities() == inner.capabilities()


def test_every_mutating_op_on_the_wrapper_journals_or_is_absent(tmp_path):
    """The ratchet: a mutation reachable here is a mutation that is witnessed.

    Enumerated from ``LEDGER_MUTATIONS`` rather than hand-copied, so an op
    added to that set joins this check instead of quietly escaping it.
    """
    from engine.arrival_contract import LEDGER_MUTATIONS

    log_path = minted(tmp_path / "s.arrival")
    ledger = opened(log_path)
    reachable = {op for op in LEDGER_MUTATIONS if hasattr(ledger, op)}
    assert reachable == {"mint", "append", "replicate"}
    for op in reachable:
        source = getattr(type(ledger), op).__doc__ or ""
        assert source, f"{op} is undocumented"


# ---------------------------------------------------------------------------
# Alias spellings of one store (finding:s3wp3-canonical-location-alias-first-contact)
# ---------------------------------------------------------------------------


def test_match_identity_finds_another_spelling_of_the_same_object():
    """The judgment, unit-tested portably.

    The alias this closes can only be CONSTRUCTED on a case-insensitive
    filesystem, so the end-to-end test below has to skip on a case-sensitive
    runner. The judgment is the part worth pinning everywhere, so it takes
    identities as arguments and is exercised on every platform — a green Linux
    run must not mean the logic was never checked.
    """
    presenting = (2049, 8675309)
    recorded = [
        ("/other/store.arrival", "LIN-OTHER", (2049, 111)),
        ("/Data/Store.arrival", "LIN-BOUND", presenting),
    ]
    assert match_identity(presenting, recorded) == "LIN-BOUND"


def test_match_identity_takes_the_newest_binding_for_one_object():
    """Same rule the exact-location lookup applies: last write wins."""
    presenting = (2049, 8675309)
    recorded = [
        ("/a.arrival", "LIN-OLD", presenting),
        ("/A.arrival", "LIN-NEW", presenting),
    ]
    assert match_identity(presenting, recorded) == "LIN-NEW"


def test_match_identity_skips_bindings_that_no_longer_stat():
    """A path that cannot be stat'd makes no claim about identity either way.

    Never RECORD an inode to avoid this: a recorded one goes stale when the
    file is recreated and gets recycled onto an unrelated file, so it becomes a
    claim that rots into a false match. Absent is the honest answer.
    """
    presenting = (2049, 8675309)
    recorded = [("/gone.arrival", "LIN-GONE", None)]
    assert match_identity(presenting, recorded) is None


def test_match_identity_answers_nothing_when_the_presenting_path_is_gone():
    assert match_identity(None, [("/a", "LIN", (1, 2))]) is None


def _filesystem_is_case_insensitive(tmp_path: Path) -> bool:
    """Probe rather than assume — the answer is a property of the mount."""
    probe = tmp_path / "CaseProbe"
    probe.write_text("x")
    try:
        return (tmp_path / "caseprobe").exists()
    finally:
        probe.unlink()


def test_a_case_variant_spelling_of_a_bound_store_is_not_first_contact(tmp_path):
    """The alias, end to end: a replacement must not walk past the binding.

    ``canonical_location`` returns a normalized STRING, and a case-variant
    spelling on a case-insensitive filesystem reaches the very same store
    through a different one. Bound under one spelling and presented under the
    other, the store had no binding, read as first contact, and a replacement
    with a fresh lineage sailed past ``LineageReplaced``.

    Skipped honestly where the alias cannot be built — a green run on a
    case-sensitive runner must not be read as this vector having passed. The
    judgment itself is pinned portably by the ``match_identity`` tests above.
    """
    if not _filesystem_is_case_insensitive(tmp_path):
        pytest.skip(
            "case-insensitive filesystem required to construct a case-variant "
            "alias; the identity judgment is covered portably by "
            "test_match_identity_finds_another_spelling_of_the_same_object"
        )

    log_path = minted(tmp_path / "store.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    first = lineage_of(log_path)

    log_path.unlink()
    index_path_for(log_path).unlink(missing_ok=True)
    minted(log_path)
    assert lineage_of(log_path) != first

    variant = tmp_path / "STORE.arrival"
    assert canonical_location(str(variant)) != canonical_location(str(log_path))
    with pytest.raises(LineageReplaced):
        opened(variant)


def test_the_alias_sweep_runs_only_when_the_spelling_has_no_binding(tmp_path):
    """Cost, and the reason it is not paid on the dominant path.

    Once a binding exists for the spelling in use, the exact-location lookup
    answers and the live-stat sweep never runs. So the sweep is a first-open
    cost per spelling rather than a per-open cost, and the unchanged path still
    gathers only its single Open verification.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)  # records the binding for this spelling

    recorder = Recorder(FileLedger(ArrivalLog(log_path)))
    ledger = AttestedLedger(recorder, location=str(log_path))
    assert isinstance(ledger.opened.comparison, Compared)
    assert ledger.opened.comparison.outcome is Outcome.UNCHANGED
    assert recorder.calls == ["verify:open"], recorder.calls


def test_the_alias_refusal_leaves_the_journal_untouched(tmp_path):
    """The check fires before anything is earned, and adds only refusals.

    It sits in the binding arm, ahead of the journal read and well ahead of
    ``_judge``, so it cannot introduce a write site — it can only refuse
    earlier. Asserted on bytes because the AST ratchet cannot see an ordering
    regression here.
    """
    nested = tmp_path / "d"
    nested.mkdir()
    log_path = minted(nested / "s.arrival")
    append_legacy(log_path, "one")
    opened(log_path)
    first = lineage_of(log_path)

    log_path.unlink()
    index_path_for(log_path).unlink(missing_ok=True)
    minted(log_path)
    before = journal_bytes(first)
    bindings_before = bindings_path().read_bytes()

    with pytest.raises(LineageReplaced):
        opened(tmp_path / "d" / ".." / "d" / "s.arrival")

    assert journal_bytes(first) == before
    assert bindings_path().read_bytes() == bindings_before
    assert not journal_path(lineage_of(log_path)).exists()


# ---------------------------------------------------------------------------
# The ceremony itself (finding:s3wp3-trust-reset-ceremony-bricked-on-equivocation)
# ---------------------------------------------------------------------------


def _equivocating_journal(lineage: str) -> None:
    """Two different records at one ordinal, in the CURRENT epoch.

    The state an operator runs the ceremony to resolve, and the one a full read
    refuses outright. Current-epoch on purpose: an equivocation before a reset
    is scoped out and tolerated, so a fixture built that way would pass against
    a ceremony that is still bricked — which is exactly how the first fix here
    passed while the caller was never wired.
    """
    for digest in ("a", "b"):
        append_entry(
            HeadAttestation(
                head=Head(lineage=lineage, ordinal=6, record_hash=digest * 64),
                kind=Kind.ADVANCE,
                level=Level.COMMIT,
                observed_at=1.0,
            )
        )


def test_the_ceremony_succeeds_on_an_equivocating_journal(tmp_path):
    """The producer must work on the journals it exists to recover from.

    ``read_journal`` REFUSES an equivocating journal, and equivocation is one
    of the states §11 sends an operator to this ceremony to resolve. A producer
    that read the journal that way would be unusable exactly when it is needed
    — a recovery path gated on the condition it recovers from.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    lineage = lineage_of(log_path)
    _equivocating_journal(lineage)
    with pytest.raises(JournalEquivocation):
        read_journal(lineage)

    accepted = FileLedger(ArrivalLog(log_path)).verify(Open())
    trust_reset(  # must not raise
        accepted=accepted,
        abandoned=Head(lineage=lineage, ordinal=6, record_hash="a" * 64),
        refused=None,
        reason="operator adjudicated the fork and accepted the archive copy",
        location=str(log_path),
        observed_at=9000.0,
    )

    # And the ceremony took effect: the journal reads again, scoped to it.
    read = read_journal(lineage)
    assert read.epoch[0].kind is Kind.TRUST_RESET
    assert read.established_head() is not None
    assert read.established_head().head == accepted


def test_the_ceremony_reports_a_reset_that_did_not_take_effect(tmp_path):
    """The obligation the position claim buys its protection with.

    Binding to a line means reading the tail and then appending, with no lock
    to hold across the two — the journal is append-only precisely so writers
    need none. An automated append landing in that window leaves a legitimate,
    freshly written reset carrying a stale position, which a later reader
    declines to honor.

    The direction is safe: the higher abandoned head still stands, so opens
    keep refusing. What would not be safe is silence — an operator who saw the
    ceremony return believes their store will now open. So the entry is read
    back against the same judgment every reader applies, and a ceremony that
    did not take raises.
    """
    log_path = minted(tmp_path / "s.arrival")
    append_legacy(log_path, "one")
    lineage = lineage_of(log_path)
    accepted = FileLedger(ArrivalLog(log_path)).verify(Open())
    append_entry(
        HeadAttestation(
            head=Head(lineage=lineage, ordinal=9, record_hash="a" * 64),
            kind=Kind.ADVANCE,
            level=Level.COMMIT,
            observed_at=1.0,
        )
    )

    # A peer appends between the tail read and the write.
    real_last_entry = engine.arrival_head_seam.last_entry

    def racing_last_entry(name: str):
        answer = real_last_entry(name)
        append_entry(
            HeadAttestation(
                head=Head(lineage=name, ordinal=10, record_hash="b" * 64),
                kind=Kind.ADVANCE,
                level=Level.COMMIT,
                observed_at=2.0,
            )
        )
        return answer

    engine.arrival_head_seam.last_entry = racing_last_entry
    try:
        with pytest.raises(TrustResetNotHonored) as excinfo:
            trust_reset(
                accepted=accepted,
                abandoned=None,
                refused=None,
                reason="restored from archive",
                location=str(log_path),
                observed_at=9000.0,
            )
    finally:
        engine.arrival_head_seam.last_entry = real_last_entry

    assert excinfo.value.entry.kind is Kind.TRUST_RESET
    assert "APPENDED and is NOT honored" in str(excinfo.value)
    # Safe direction: the higher head still stands, so opens keep refusing.
    assert read_journal(lineage).known is not None
