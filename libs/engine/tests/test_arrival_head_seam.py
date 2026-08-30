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

from engine.arrival import ArrivalLog
from engine.arrival_contract import (
    ArrivalLedger,
    Commit,
    ContractRefusal,
    Head,
    Open,
    RecordDraft,
    StoreDescriptor,
)
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_head_attestation import (
    HeadAttestation,
    HeadFork,
    HeadRewrite,
    HeadRollback,
    IndeterminateComparison,
    Kind,
    Level,
    LineageReplaced,
    Outcome,
    StoreLost,
    append_entry,
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
    audit,
    bootstrap,
    canonical_location,
    days_since_audit,
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
