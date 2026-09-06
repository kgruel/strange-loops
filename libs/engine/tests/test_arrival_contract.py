"""The contract surface, and the file adapter that first satisfies it.

``design:arrival-break-slice2-backend-contract`` §A. Two subjects here:

1. :mod:`engine.arrival_contract` states backend-contract.html §03 in Python,
   and it must keep the properties that make it importable from anywhere —
   stdlib only, no sqlite3, no runtime dependency on the file backend.
2. :mod:`engine.arrival_file_backend` wraps ``ArrivalLog`` and the projection,
   including the custody/reads separation §A.2 pins with a unit test rather
   than a numbered architecture rule (one adapter is not yet a pattern).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from atoms import Fact

from engine.arrival import ArrivalLog
from engine.arrival_contract import (
    LEDGER_MUTATIONS,
    ArrivalLedger,
    ArrivalQuery,
    AtomicLimitExceeded,
    Capabilities,
    Commit,
    ContractRefusal,
    DurabilityProfile,
    Full,
    Head,
    HeadMismatch,
    Incremental,
    NotAuthority,
    NotSupported,
    Open,
    Profile,
    RecordDraft,
    StoreDescriptor,
    VerificationLevel,
    Watermark,
)
from engine.arrival_file_backend import EXPORT_CODEC, FileLedger, FileQuery
from engine.arrival_store import ArrivalStore
from tests.conftest import STUB_KEY as _KEY
from tests.conftest import stub_sign as _sign

CONTRACT = Path(__file__).resolve().parents[1] / "src/engine/arrival_contract.py"


# --- the contract module's own properties ----------------------------------


def test_the_contract_module_imports_no_sqlite_and_no_backend():
    """Static: nothing here reaches for a driver or for the file codec.

    The property is what makes ``import engine.arrival_contract`` cheap
    enough for libs/store, libs/sdk and an out-of-tree adapter to all depend
    on it. Read from the AST rather than from ``sys.modules`` so a
    conditional or function-local import cannot pass by not executing.
    """
    tree = ast.parse(CONTRACT.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level:
            imported.add(f"<relative level {node.level}>")

    assert "sqlite3" not in imported
    assert not any(name.startswith("<relative") for name in imported), (
        "a relative import is an import of this package's backend layer"
    )
    assert not {"arrival", "engine", "store", "lang", "atoms"} & imported


def test_importing_the_contract_pulls_in_no_backend_module():
    """Dynamic: the same claim, observed rather than parsed.

    A fresh interpreter, because this one has long since imported the world.
    """
    prog = (
        "import sys; import engine.arrival_contract as c; "
        "print(int(any(m.startswith('engine.arrival.') or "
        "m == 'engine.arrival' or m == 'sqlite3' for m in sys.modules)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", prog], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0", (
        "importing the contract dragged the file backend or sqlite3 along"
    )


def test_every_contract_refusal_is_catchable_as_one():
    """A caller must be able to catch a refusal without naming the backend.

    Rooted in ContractRefusal and NOT in engine.arrival.ArrivalError — a
    hierarchy rooted in the file backend's module could not serve a caller
    talking to DuckDB.
    """
    from engine.arrival import ArrivalError

    for refusal in (HeadMismatch, NotAuthority, AtomicLimitExceeded):
        assert issubclass(refusal, ContractRefusal)
        assert not issubclass(refusal, ArrivalError)


def test_a_head_is_all_three_fields_and_compares_on_all_three():
    """The type is the argument: there is no two-field head to construct."""
    head = Head(lineage="L", ordinal=3, record_hash="a" * 64)
    assert head == Head(lineage="L", ordinal=3, record_hash="a" * 64)
    assert head != Head(lineage="L", ordinal=3, record_hash="b" * 64)
    assert head != Head(lineage="OTHER", ordinal=3, record_hash="a" * 64)
    with pytest.raises(TypeError):
        Head(lineage="L", ordinal=3)  # type: ignore[call-arg]


def test_a_descriptor_names_a_backend_and_never_infers_one():
    """§02: backend selection is explicit, and location is adapter-read.

    ``location`` is a str rather than a Path because §02 lets it be a DSN
    reference or a service URL — typing it as a filesystem path would decide,
    in the neutral module, that every backend is a file.
    """
    descriptor = StoreDescriptor(backend="file", location="./s.arrival")
    assert isinstance(descriptor.location, str)
    assert descriptor.role is None and descriptor.lineage is None
    with pytest.raises(TypeError):
        StoreDescriptor(location="./s.arrival")  # type: ignore[call-arg]


# --- the custody / reads separation (§A.2) ---------------------------------


def _reachable(root: object, depth: int = 3) -> list[tuple[str, object]]:
    """Every attribute reachable from ``root`` within ``depth`` hops.

    Instance state, not the class dictionary: the claim is about what a
    query HANDLE gives you, and a handle gives you what it holds.
    """
    seen: set[int] = set()
    found: list[tuple[str, object]] = []

    def walk(obj: object, path: str, left: int) -> None:
        if left < 0 or id(obj) in seen:
            return
        seen.add(id(obj))
        for name, value in vars(obj).items():
            found.append((f"{path}.{name}", value))
            if hasattr(value, "__dict__"):
                walk(value, f"{path}.{name}", left - 1)

    walk(root, "query", depth)
    return found


def test_no_ledger_mutating_op_is_reachable_from_a_query_handle(
    tmp_path, keys_and_store
):
    """§A.2, and backend-contract.html:211-217.

    "A query handle MUST NOT expose a generic mutation escape hatch into the
    ledger." Asserted over everything the handle actually holds, transitively
    — not just its own methods, because a handle that stored an ArrivalLog or
    an ArrivalStore would satisfy a surface-only check while offering
    ``append`` one attribute away. ``ArrivalStore`` is the specific hazard:
    it is the projection's writer AND appends to the log, so a query built
    from one would be a mutation escape hatch by construction.

    The op names come from LEDGER_MUTATIONS, beside the Protocol that
    declares them, so an operation added to the ledger later is covered here
    without anyone remembering to copy it across.
    """
    index_path, _log_path = keys_and_store
    query = FileQuery(index_path)
    try:
        assert not (LEDGER_MUTATIONS & set(dir(query))), (
            "a query handle names a ledger mutation directly"
        )
        for path, value in _reachable(query):
            assert not isinstance(value, (ArrivalLog, ArrivalStore)), (
                f"{path} is a {type(value).__name__} — custody reachable "
                "from a read handle"
            )
            for op in LEDGER_MUTATIONS:
                assert not callable(getattr(value, op, None)), (
                    f"{path} exposes {op!r}, a ledger mutation, from a query "
                    "handle"
                )
    finally:
        query.close()


def test_a_query_cannot_be_constructed_from_a_ledger(tmp_path, keys_and_store):
    """Construction over detection: there is no parameter to pass one through.

    The separation above is a property of what FileQuery HOLDS. This is the
    stronger statement — a caller holding an ArrivalLog has no way to hand it
    to a query, so the reachable-attribute check cannot be defeated by a
    caller doing something unusual.
    """
    index_path, log_path = keys_and_store
    with pytest.raises((TypeError, AttributeError, OSError, ValueError)):
        FileQuery(ArrivalLog(log_path))  # type: ignore[arg-type]


# --- the adapter -----------------------------------------------------------


@pytest.fixture
def keys_and_store(tmp_path):
    """A minted log with a consumed projection beside it: (index, log)."""
    log_path = tmp_path / "s.arrival"
    ArrivalLog.mint(log_path, observer="kyle", signer=_sign, key=_KEY)
    store = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=_sign,
    )
    try:
        store.append(Fact.of("note", "kyle", message="one"))
    finally:
        store.close()
    return tmp_path / "s.db", log_path


@pytest.fixture
def ledger(tmp_path):
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY
    )
    return FileLedger(log)


def _draft(i: int) -> RecordDraft:
    return RecordDraft(
        kind="note", authored_at=100.0 + i, observer="kyle", body={"i": i}
    )


# The TEN op rows of the ratified §03 table, written out rather than derived.
# Deriving them from `ArrivalLedger` is what the assertion below is FOR, so a
# derived expectation would agree with the Protocol no matter what the Protocol
# said. This literal is the contract of record, standing beside the code.
#
# Nine came from §A.2's table; `head_at` is the tenth, ruled onto the contract
# at the slice-2 gate (`decision:design/arrival-slice2-contract-text`, ruling 3)
# because §07's `projected_through` obligation cannot be met without it.
RATIFIED_LEDGER_OPS = frozenset({
    "mint", "head", "head_at", "append", "replicate", "read", "scan",
    "verify", "export", "capabilities",
})


def _declared_surface(protocol: type) -> frozenset[str]:
    """The public names a Protocol class declares, from its own namespace.

    Plain class introspection — ``vars`` plus ``__annotations__`` — and NOT
    ``typing``'s ``__protocol_attrs__``, which is a private implementation
    detail that does not exist before Python 3.12. Both pyprojects declare
    ``requires-python >= 3.11``, so a test reaching for that attribute passes
    on the interpreter it was written on and errors on one the package
    supports.

    Annotations are included as well as callables so that an ATTRIBUTE added
    to the Protocol is caught the same way a method would be: the claim being
    pinned is "these ten rows and nothing else", and a row does not stop
    counting by being spelled as data.
    """
    namespace = vars(protocol)
    methods = {
        name
        for name, value in namespace.items()
        if not name.startswith("_") and callable(value)
    }
    attributes = {
        name
        for name in namespace.get("__annotations__", {})
        if not name.startswith("_")
    }
    return frozenset(methods | attributes)


def test_the_ledger_satisfies_the_ledger_surface_it_claims(ledger):
    """A location claim, not a conformance verdict.

    ``runtime_checkable`` compares METHOD NAMES only — Python cannot check
    signatures — so this says "these ops are offered", never "they behave".
    The vectors judge behaviour. It is asserted anyway because the surface
    silently shrinking is a real failure mode, and this catches it.
    """
    offered = {op for op in dir(ledger) if not op.startswith("_")}
    assert RATIFIED_LEDGER_OPS <= offered
    # WP2 completed the surface, so the adapter now satisfies the Protocol.
    # This is the assertion WP1 wrote inverted, and flipping it is what its
    # comment asked WP2 to do.
    assert isinstance(ledger, ArrivalLedger)
    # EXACT equality, both directions: an op declared beyond the ratified table
    # fails this, and one dropped from it fails this. `<=` above is about the
    # ADAPTER, which may legitimately offer more; this is about the PROTOCOL,
    # which may not.
    assert _declared_surface(ArrivalLedger) == RATIFIED_LEDGER_OPS
    # `import_prefix` is offered and is NOT declared on the Protocol: §08
    # describes portable import in prose and the ratified op table gives it no
    # row. It is in LEDGER_MUTATIONS regardless, because the custody/reads
    # ratchet covers what mutates, not what the Protocol happens to name.
    assert "import_prefix" in offered
    assert "import_prefix" not in _declared_surface(ArrivalLedger)
    assert "import_prefix" in LEDGER_MUTATIONS
    # `head_at` is the mirror case: ON the Protocol (ruling 3 gave it a row)
    # and NOT in LEDGER_MUTATIONS, because resolving a watermark reads the
    # record already there. Pinned rather than left to review memory — the two
    # sets answer different questions, and a read filed as a mutation would
    # make the custody/reads test refuse a handle that is allowed to hold it.
    assert "head_at" in _declared_surface(ArrivalLedger)
    assert "head_at" not in LEDGER_MUTATIONS


def test_the_query_satisfies_the_query_surface(keys_and_store):
    index_path, _ = keys_and_store
    query = FileQuery(index_path)
    try:
        assert isinstance(query, ArrivalQuery)
    finally:
        query.close()


def test_append_returns_a_commit_that_names_both_ends(ledger):
    """The shape §10's migration loop chains on (``head = commit.after``)."""
    before = ledger.head()
    commit = ledger.append(before, [_draft(1), _draft(2)])

    assert isinstance(commit, Commit)
    assert commit.before == before, "before must be the head it landed on"
    assert commit.after == ledger.head()
    assert commit.after.ordinal == before.ordinal + 2
    assert len(commit.records) == 2
    assert commit.durability.profile is DurabilityProfile.HOST


def test_append_translates_only_the_cas_refusal(ledger):
    """StaleHead becomes HeadMismatch; a placement fault does not.

    The reason StaleHead exists. ``AppendRejected`` covers both, and an
    adapter that mapped the parent would be claiming a head mismatch about a
    record that was refused for its shape.
    """
    from engine.arrival import AppendRejected, build_record

    stale = ledger.head()
    ledger.append(stale, [_draft(1)])

    with pytest.raises(HeadMismatch):
        ledger.append(stale, [_draft(2)])

    # A placement fault reaches the caller as itself, not as HeadMismatch.
    head = ledger._log.head()
    with pytest.raises(AppendRejected) as caught:
        ledger._log.append_record(
            build_record(
                lin=head["lin"], ordinal=head["ord"] + 9, prev=head["rh"],
                k="note", body={}, observer="kyle",
            )
        )
    assert not isinstance(caught.value, HeadMismatch)


def test_append_refuses_an_empty_request(ledger):
    with pytest.raises(ValueError):
        ledger.append(ledger.head(), [])


def test_append_carries_pre_signed_draft_and_verifies_authorship(tmp_path):
    """E1: RecordDraft.signature is carried through Entry and append_marked_many."""
    from engine.arrival import (
        KEY_INTRODUCTION_KIND,
        content_commitment,
        verify_authorship,
    )
    from tests.conftest import Custodian, ed25519_verify

    kyle = Custodian(tmp_path, "kyle")
    ana = Custodian(tmp_path, "ana")
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer=kyle.name, signer=kyle.signer, key=kyle.public
    )
    ledger = FileLedger(log)

    body = {"observer": ana.name, "key": ana.public}
    commitment = content_commitment(KEY_INTRODUCTION_KIND, 1.0, kyle.name, "", body)
    sig = kyle.signer(kyle.name, commitment)
    assert sig is not None

    draft = RecordDraft(
        kind=KEY_INTRODUCTION_KIND,
        authored_at=1.0,
        observer=kyle.name,
        origin="",
        body=body,
        signature=sig,
    )
    commit = ledger.append(ledger.head(), [draft])
    assert commit.after.ordinal == 1
    assert commit.records[0]["sig"] == sig

    rows = verify_authorship(log, ed25519_verify)
    assert len(rows) == 2
    assert (rows[1].ordinal, rows[1].observer, rows[1].key) == (1, kyle.name, kyle.public)


def test_append_unsigned_drafts_byte_identical_fixture(tmp_path):
    """E1: Unsigned drafts produce byte-identical logs to manual build_record with sig=None."""
    from engine.arrival import build_record, encode_record

    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY, at=0.0
    )
    ledger = FileLedger(log)

    drafts = [
        RecordDraft(
            kind="note",
            authored_at=float(i),
            observer="kyle",
            origin="",
            body={"val": i},
            signature=None,
        )
        for i in range(1, 4)
    ]
    commit = ledger.append(ledger.head(), drafts)
    assert commit.after.ordinal == 3

    ref_records = [log.genesis()]
    prev_rh = log.genesis()["rh"]
    for i in range(1, 4):
        rec = build_record(
            lin=log.lineage(),
            ordinal=i,
            prev=prev_rh,
            k="note",
            body={"val": i},
            observer="kyle",
            origin="",
            at=float(i),
            sig=None,
        )
        ref_records.append(rec)
        prev_rh = rec["rh"]

    expected_bytes = "".join(encode_record(r) + "\n" for r in ref_records).encode(
        "utf-8"
    )
    assert log.path.read_bytes() == expected_bytes


def test_a_configured_atomic_limit_refuses_before_any_mutation(tmp_path):
    """§04: refuse before mutation when the request exceeds the limit.

    Unset the limit is unbounded and ``capabilities()`` says so; set, it is a
    real refusal with a real gate — which is why the ceiling is configurable
    rather than an invented constant nothing could exercise.
    """
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY
    )
    limited = FileLedger(log, max_atomic_records=2)
    before = log.path.read_bytes()

    with pytest.raises(AtomicLimitExceeded):
        limited.append(limited.head(), [_draft(i) for i in range(3)])
    assert log.path.read_bytes() == before, "refused before any mutation"

    limited.append(limited.head(), [_draft(i) for i in range(2)])
    assert limited.head().ordinal == 2


def test_head_refuses_a_lineage_this_ledger_does_not_hold(ledger):
    with pytest.raises(NotAuthority):
        ledger.head(lineage="01NOTTHISLINEAGE0000000000")


def test_scan_yields_the_captured_prefix_and_no_later_record(ledger):
    """§06: prefix consistency and deterministic order."""
    ledger.append(ledger.head(), [_draft(i) for i in range(1, 4)])
    captured = ledger.head()
    # A record arriving after the capture must not appear in the scan.
    ledger.append(captured, [_draft(99)])

    scanned = list(ledger.scan(after=0, through=captured))
    assert [r["ord"] for r in scanned] == [1, 2, 3]


def test_scan_refuses_a_head_this_log_never_had(ledger):
    """A captured head from another log is not a snapshot of this one."""
    ledger.append(ledger.head(), [_draft(1)])
    head = ledger.head()
    forged = Head(
        lineage=head.lineage, ordinal=head.ordinal, record_hash="d" * 64
    )
    with pytest.raises(HeadMismatch):
        list(ledger.scan(through=forged))


def test_scan_refuses_when_the_log_ends_before_the_captured_head(ledger):
    """§06: absence before a captured head is corruption, not end of stream."""
    ledger.append(ledger.head(), [_draft(1)])
    head = ledger.head()
    beyond = Head(
        lineage=head.lineage, ordinal=head.ordinal + 5, record_hash="e" * 64
    )
    with pytest.raises(HeadMismatch):
        list(ledger.scan(through=beyond))


def test_open_verification_names_the_current_tip(ledger):
    ledger.append(ledger.head(), [_draft(1)])
    assert ledger.verify(Open()) == ledger.head()


def test_verify_refuses_a_torn_tail_rather_than_repairing_it(ledger):
    """The invariant §E asks Kyle to rule on, held here either way.

    A torn tail is left exactly as found. Verification takes no lock, and the
    lock is the only thing that licenses calling a tail torn rather than in
    flight — so this path could not truncate even if it wanted to. It refuses
    instead, which is the honest answer for an Open-level claim: the backend
    cannot identify a self-consistent tip here, and saying so beats
    manufacturing one by deleting the evidence.
    """
    from engine.arrival import ArrivalError

    ledger.append(ledger.head(), [_draft(1)])
    path = ledger._log.path
    path.write_bytes(path.read_bytes() + b'{"torn":')
    before = path.read_bytes()

    with pytest.raises(ArrivalError):
        ledger.verify(Open())
    assert path.read_bytes() == before, "verification rewrote the log"

    # Full is the same posture over the whole prefix: the reader treats an
    # unterminated final line as in-flight and stops, rather than cutting it.
    last = list(ledger._log.walk())[-1]
    head = Head(
        lineage=last["lin"], ordinal=last["ord"], record_hash=last["rh"]
    )
    assert ledger.verify(Full(through=head)) == head
    assert path.read_bytes() == before, "verification rewrote the log"


def test_full_verification_covers_the_head_it_claims(ledger):
    ledger.append(ledger.head(), [_draft(i) for i in range(1, 4)])
    head = ledger.head()
    assert ledger.verify(Full(through=head)) == head


def test_full_verification_stops_at_its_captured_prefix(ledger):
    """A malformed suffix is not evidence against an earlier Full(H) claim."""
    head = ledger.head()
    path = ledger._log.path
    path.write_bytes(path.read_bytes() + b'{}\n')

    assert ledger.verify(Full(through=head)) == head


def test_full_verification_refuses_a_head_it_cannot_find(ledger):
    head = ledger.head()
    absent = Head(
        lineage=head.lineage, ordinal=head.ordinal + 3, record_hash="f" * 64
    )
    with pytest.raises(HeadMismatch):
        ledger.verify(Full(through=absent))


def test_incremental_verification_is_absent_rather_than_faked(ledger):
    """An honest absent level beats one that lies about its cost.

    A verified suffix walk starts from a byte offset this backend keeps in a
    resume mark; a Head does not carry one, and finding the position would
    mean walking to it — Full's work under a name promising less.
    """
    head = ledger.head()
    with pytest.raises(NotSupported):
        ledger.verify(Incremental(through=head, checkpoint=head))
    assert VerificationLevel.INCREMENTAL not in (
        ledger.capabilities().verification_levels
    )


def test_deliberate_absence_refuses_under_the_contract_root(ledger):
    """Ruling 2: deliberate absence is a CONTRACT refusal, not a builtin.

    The claim is catchability at the root. A caller written against the
    contract writes one ``except ContractRefusal`` and handles every refusal
    the contract text names; ``NotImplementedError`` escapes that clause and
    reads as "unfinished code" rather than "this backend does not offer it",
    which is the opposite of what ``capabilities()`` already says about both
    of these.
    """
    head = ledger.head()

    with pytest.raises(ContractRefusal) as incremental:
        ledger.verify(Incremental(through=head, checkpoint=head))
    assert isinstance(incremental.value, NotSupported)

    # And the root really is the contract's, not the file backend's family:
    # a caller that never imported engine.arrival can still catch these.
    from engine.arrival import ArrivalError

    assert not issubclass(NotSupported, ArrivalError)


def test_capabilities_claims_nothing_the_adapter_does_not_have(ledger):
    """§12: an over-claim turns a deployment refusal into a runtime failure.

    Every claim here is cross-checked against the object, so the report
    cannot drift from the adapter — which is the whole failure mode a
    capability report has.
    """
    caps = ledger.capabilities()
    assert isinstance(caps, Capabilities)
    assert caps.profiles == frozenset({Profile.AUTHORITY, Profile.REPLICA})
    assert caps.export_codecs == (EXPORT_CODEC,)
    assert Profile.ARCHIVE not in caps.profiles, (
        "nothing here offers a read-only sealed mode"
    )
    assert not caps.idempotency_keys
    assert caps.max_atomic_records is None
    assert "flock" in caps.writer_concurrency
    assert "POSIX" in caps.writer_concurrency, (
        "§05 requires the local-storage scope to be advertised"
    )
    for op, claimed in (("replicate", Profile.REPLICA in caps.profiles),
                        ("export", bool(caps.export_codecs))):
        assert hasattr(ledger, op) == claimed, (
            f"capabilities and the adapter disagree about {op!r}"
        )


# --- the projection half ----------------------------------------------------


def test_the_projection_reports_the_prefix_it_actually_holds(keys_and_store):
    """§07: query results report the lineage and projected prefix they represent."""
    index_path, log_path = keys_and_store
    query = FileQuery(index_path)
    try:
        watermark = query.projected_through()
        assert isinstance(watermark, Watermark)
        assert watermark.lineage == ArrivalLog(log_path).lineage()
        assert watermark.ordinal == ArrivalLog(log_path).head()["ord"]
        assert query.lineage() == watermark.lineage
    finally:
        query.close()


def test_the_ledger_resolves_a_watermark_the_query_cannot(keys_and_store):
    """The custody/reads split, stated in the return types.

    The projection knows how far it got; only the ledger holds the record
    whose hash completes that into a head. This is why ``projected_through``
    returns a Watermark and not a Head — see
    ``finding:slice2-wp1-projection-has-no-head-hash``.
    """
    index_path, log_path = keys_and_store
    query = FileQuery(index_path)
    try:
        watermark = query.projected_through()
    finally:
        query.close()
    assert watermark is not None

    head = FileLedger(ArrivalLog(log_path)).head_at(watermark)
    assert head.ordinal == watermark.ordinal
    assert head.lineage == watermark.lineage
    assert head.record_hash, "the ledger supplies the field the query lacks"


def test_a_projection_of_another_log_is_refused_rather_than_answered(
    keys_and_store, tmp_path
):
    """A watermark names a lineage, and the ledger checks it is its own.

    The other log is grown to the same height first, so the ordinal resolves
    and the LINEAGE is the field that refuses — otherwise this would pass on
    a plain "no record there" and assert nothing about custody.
    """
    other = tmp_path / "other.arrival"
    other_log = ArrivalLog.mint(other, observer="kyle", signer=_sign, key=_KEY)
    index_path, _ = keys_and_store
    query = FileQuery(index_path)
    try:
        watermark = query.projected_through()
    finally:
        query.close()
    assert watermark is not None
    while other_log.head()["ord"] < watermark.ordinal:
        other_log.append("note", {}, observer="kyle")

    with pytest.raises(NotAuthority):
        FileLedger(ArrivalLog(other)).head_at(watermark)


def test_opening_a_projection_over_a_minted_log_consumes_its_genesis(tmp_path):
    """The watermark starts at 0, not at absent — the genesis is a record.

    Worth pinning because it is the one case where "the projection has
    consumed nothing" and "the projection holds no mark" look alike from the
    outside and are not the same state.
    """
    ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=_sign, key=_KEY
    )
    store = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=_sign,
    )
    store.close()
    query = FileQuery(tmp_path / "s.db")
    try:
        assert query.projected_through() == Watermark(
            lineage=ArrivalLog(tmp_path / "s.arrival").lineage(), ordinal=0
        )
    finally:
        query.close()


def test_a_store_with_no_arrival_mark_reports_no_watermark(tmp_path):
    """A projection that represents no lineage says so rather than guessing.

    §07: query results report the lineage and projected prefix they actually
    represent. A plain sqlite store represents neither.
    """
    from engine.sqlite_store import SqliteStore

    store = SqliteStore(
        path=tmp_path / "plain.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    store.append(Fact.of("note", "kyle", message="one"))
    store.close()

    query = FileQuery(tmp_path / "plain.db")
    try:
        assert query.projected_through() is None
        assert query.lineage() is None
    finally:
        query.close()
