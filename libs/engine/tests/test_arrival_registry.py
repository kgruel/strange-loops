"""Which adapter opens which artifact — the registry, and the parity probe.

Slice 2 / WP4 (``design:arrival-break-slice2-backend-contract`` §B.4, §D.4).

The parity probe at the bottom is the exit criterion that makes slice 2's
scope call safe. Slice 2 builds the registry; it rewires nothing. That is
only defensible if the new path and the old path name the SAME artifact for
every vertex in the repo — otherwise "additive" would be a claim rather than
a fact, and slice 5 would be rewiring consumers onto a resolution nobody had
compared against the one it replaces.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex, parse_vertex_file
from lang.ast import BackendDecl, VertexFile

from engine.arrival import ArrivalLog
from engine.arrival_contract import (
    ArrivalLedger,
    ArrivalQuery,
    StoreDescriptor,
    UnknownBackend,
)
from engine.arrival_head_seam import AttestedLedger, PreGenesis
from engine.arrival_registry import BackendRegistry, descriptor_for
from engine.arrival_store import ArrivalStore
from engine.jsonl_store import open_canonical_store
from engine.residence import canonical_mode, canonical_store_path, index_path_for
from tests.conftest import STUB_KEY as _KEY
from tests.conftest import stub_sign as _sign

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolated_state_root(tmp_path, monkeypatch):
    """Point the head-journal state root at a temporary directory.

    Slice 3 made ``BackendRegistry.open`` compare on open, so every test here
    that opens a store now reads — and on first contact writes — a head
    journal under ``$XDG_STATE_HOME``. Autouse rather than per-test: one
    forgotten opt-in is one test writing head observations into the
    developer's real ``~/.local/state/loops``, corrupting the very memory the
    design exists to protect, and that failure would be invisible until after
    it had happened.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


def _vertex(tmp_path: Path, store_line: str) -> Path:
    path = tmp_path / "t.vertex"
    path.write_text(
        f'name "t"\n{store_line}\nloops {{ ping {{ fold {{ n "inc" }} }} }}\n'
    )
    return path


# ---------------------------------------------------------------------------
# descriptor_for — the four arms
# ---------------------------------------------------------------------------


def test_explicit_backend_is_taken_at_its_word(tmp_path):
    vpath = _vertex(tmp_path, 'store "./s.arrival" backend="file"')
    descriptor = descriptor_for(parse_vertex_file(vpath), vpath)
    assert descriptor == StoreDescriptor(
        backend="file", location=str(tmp_path / "s.arrival")
    )


def test_explicit_backend_is_not_cross_checked_against_the_suffix(tmp_path):
    """Explicit wins, and no suffix gets a vote.

    Under §02 the suffix carries no meaning once the backend is declared. A
    "do they agree?" check would re-admit inference through the back door on
    the very change that removes it — so a declared backend that disagrees
    with the suffix resolves to the DECLARED one, with no complaint.
    """
    vpath = _vertex(tmp_path, 'store "./s.arrival" backend="duckdb"')
    descriptor = descriptor_for(parse_vertex_file(vpath), vpath)
    assert descriptor is not None
    assert descriptor.backend == "duckdb"


def test_unregistered_backend_names_still_describe(tmp_path):
    """Naming is separate from opening.

    A vertex may declare a backend this host has no adapter for; describing
    it must still work, because the refusal belongs to the registry that
    knows what is installed, not to path arithmetic that does not.
    """
    ast = parse_vertex('name "t"\nstore "./s.pg" backend="postgres"\n'
                       'loops { ping { fold { n "inc" } } }')
    descriptor = descriptor_for(ast, None)
    assert descriptor is not None
    assert descriptor.backend == "postgres"


def test_undeclared_arrival_store_infers_the_file_backend(tmp_path):
    """The transitional arm that keeps slices 3-4 unstranded.

    Every .arrival store in the wild predates the grammar that would let it
    declare a backend. This arm dies in slice 5.
    """
    vpath = _vertex(tmp_path, 'store "./s.arrival"')
    descriptor = descriptor_for(parse_vertex_file(vpath), vpath)
    assert descriptor == StoreDescriptor(
        backend="file", location=str(tmp_path / "s.arrival")
    )


@pytest.mark.parametrize("locator", ["./s.jsonl", "./s.db", "./s.sqlite"])
def test_modes_with_no_ledger_describe_nothing(tmp_path, locator):
    """None is the honest answer, not a refusal.

    jsonl and sqlite stores have no ledger. "No adapter describes this" is a
    fact about the store, not a fault — they keep resolving through
    open_canonical_store exactly as today.
    """
    vpath = _vertex(tmp_path, f'store "{locator}"')
    assert descriptor_for(parse_vertex_file(vpath), vpath) is None


def test_a_vertex_with_no_store_describes_nothing():
    """An aggregate or a loops-only vertex declares no location at all."""
    ast = parse_vertex('name "agg"\ncombine {\n  vertex "/x/y.vertex"\n}\n')
    assert ast.store is None
    assert descriptor_for(ast, None) is None


def test_a_relative_locator_resolves_against_the_vertex_not_the_cwd(tmp_path):
    """A vertex is portable; a cwd is not."""
    nested = tmp_path / "sub"
    nested.mkdir()
    vpath = _vertex(nested, 'store "./s.arrival" backend="file"')
    descriptor = descriptor_for(parse_vertex_file(vpath), vpath)
    assert descriptor is not None
    assert Path(descriptor.location) == nested / "s.arrival"


def test_role_and_lineage_are_left_unset(tmp_path):
    """Deferred deliberately — nothing in slices 2-4 reads them."""
    vpath = _vertex(tmp_path, 'store "./s.arrival" backend="file"')
    descriptor = descriptor_for(parse_vertex_file(vpath), vpath)
    assert descriptor is not None
    assert descriptor.role is None
    assert descriptor.lineage is None


# ---------------------------------------------------------------------------
# BackendRegistry
# ---------------------------------------------------------------------------


def test_an_unknown_backend_refuses_and_names_what_is_registered():
    registry = BackendRegistry.with_builtin_backends()
    descriptor = StoreDescriptor(backend="duckdb", location="/x/y.duckdb")
    with pytest.raises(UnknownBackend) as excinfo:
        registry.open(descriptor)
    message = str(excinfo.value)
    assert "duckdb" in message
    assert "file" in message  # the refusal names the alternatives


def test_an_empty_registry_refuses_everything():
    registry = BackendRegistry()
    assert registry.registered() == ()
    with pytest.raises(UnknownBackend):
        registry.open(StoreDescriptor(backend="file", location="/x/y.arrival"))


def test_re_registering_a_name_refuses():
    """A silent overwrite would let import order decide which adapter
    answers to a name, and the failure would surface as a store opening
    through the wrong codec rather than as an error at the mistake."""
    registry = BackendRegistry.with_builtin_backends()
    with pytest.raises(ValueError, match="already registered"):
        registry.register("file", lambda d: (None, None))  # type: ignore[arg-type]


def test_a_registered_opener_is_what_open_calls(tmp_path):
    """The registered opener is called, and its custody half comes back wrapped.

    Slice 3 §D.1 put the compare-on-open seam here, so ``open`` no longer
    returns the opener's pair verbatim: the custody half is wrapped in
    ``AttestedLedger`` and the reads half passes through untouched. The claim
    this test was written to make — that the registry calls the opener it was
    given, with the descriptor it was given — is unchanged, so it is asserted
    directly rather than through an equality that also happened to pin the
    absence of a wrapper.

    The stub's halves are strings, which name no head: the seam asks a ledger
    for one, gets an ``AttributeError`` instead, and — with nothing remembered
    for this location — reports pre-genesis and writes nothing. That is the
    same no-claim branch a location about to be minted into takes, and it is
    exercised properly against real stores below.
    """
    calls: list[StoreDescriptor] = []
    registry = BackendRegistry()
    registry.register("probe", lambda d: (calls.append(d), ("L", "Q"))[1])  # type: ignore[arg-type,return-value]
    descriptor = StoreDescriptor(backend="probe", location=str(tmp_path / "y"))
    ledger, query = registry.open(descriptor)
    assert calls == [descriptor]
    assert query == "Q"
    assert isinstance(ledger, AttestedLedger)
    assert isinstance(ledger.opened.comparison, PreGenesis)


def test_the_file_opener_hands_back_both_halves(tmp_path):
    _vpath, log_path = _minted_arrival_vertex(tmp_path, 'store "./s.arrival"')
    registry = BackendRegistry.with_builtin_backends()
    ledger, query = registry.open(
        StoreDescriptor(backend="file", location=str(log_path))
    )
    try:
        # A location claim, not a conformance verdict: this says which ops
        # the opener's custody half offers, never that they behave.
        offered = {op for op in dir(ledger) if not op.startswith("_")}
        assert {"mint", "head", "append", "read", "scan", "verify"} <= offered
        # WP2 landed `replicate` and `export`, so the opener's custody half
        # now satisfies the full ArrivalLedger protocol. This pin was born as
        # its negation ("WP2 closes the gap") while the WPs built in
        # parallel; the surface test in test_arrival_contract.py owns the
        # exact ten-op equality, this one just confirms the opener's return
        # reaches the surface it declares.
        assert isinstance(ledger, ArrivalLedger)
        assert isinstance(query, ArrivalQuery)
    finally:
        query.close()


def test_opening_a_store_whose_projection_is_absent_now_succeeds(tmp_path):
    """The §0.4 fix, and what it did and did not change.

    This test was born as its own negation. It pinned the OBSERVED behavior
    that ``FileQuery`` built its read handle eagerly and ``StoreReader``
    refuses a path that does not exist, so a minted log with no projection
    beside it could not be opened through the registry at all — recorded as
    ``finding:slice2-wp4-registry-open-needs-a-projection``, explicitly as
    behavior rather than as a policy anyone chose.

    Slice 3 chose. That refusal blocked ``mint`` through the registry, which
    is the path slice 4's sidecar takes to get its bootstrap receipt, and it
    sat against the F2 carve-out that explicitly anticipates an absent
    projection. The reader is now built on first use, so **opening** no longer
    requires a projection.

    What did NOT change is the honest half, and it is asserted here so the
    update is not a quiet widening: asking for rows still refuses with the
    same ``FileNotFoundError`` from the same place, because nothing creates an
    index — the carve-out permits materialising one and permitted is not
    required. The projection reports no position rather than guessing at one.
    """
    log_path = tmp_path / "s.arrival"
    ArrivalLog.mint(log_path, observer="kyle", signer=_sign, key=_KEY)
    registry = BackendRegistry.with_builtin_backends()

    ledger, query = registry.open(
        StoreDescriptor(backend="file", location=str(log_path))
    )
    try:
        # The ledger half is reachable and answers about the minted genesis —
        # the whole point of the fix, and what makes `mint` reachable.
        assert ledger.head().ordinal == 0
        # A projection that has consumed nothing represents no lineage and
        # reports no watermark. Saying so is different from guessing.
        assert query.projected_through() is None
        assert query.lineage() is None
        # And the refusal that remains, unmoved: rows still need an index.
        with pytest.raises(FileNotFoundError):
            _ = query.reader
    finally:
        query.close()


def test_closing_a_query_that_never_read_does_not_build_a_reader(tmp_path):
    """Closing must not be what constructs the thing the fix deferred.

    A ``close()`` that went through the property would raise
    ``FileNotFoundError`` for a query opened over an absent projection and
    never read — moving the refusal to a stranger place rather than removing
    it, and breaking every ``finally: query.close()`` in the suite.
    """
    log_path = tmp_path / "s.arrival"
    ArrivalLog.mint(log_path, observer="kyle", signer=_sign, key=_KEY)
    _ledger, query = BackendRegistry.with_builtin_backends().open(
        StoreDescriptor(backend="file", location=str(log_path))
    )
    query.close()  # no reader was ever built, so there is nothing to close


def test_importing_the_registry_does_not_drag_the_adapter_in():
    """Adapters are imported lazily, inside their opener.

    ``import engine.arrival_registry`` is what a caller reaches for to NAME a
    descriptor. Naming must not cost a database driver and a file codec —
    the same property that keeps the contract module separate from the
    adapter, held one level up.
    """
    source = (
        "import sys\n"
        "import engine.arrival_registry\n"
        "assert 'sqlite3' not in sys.modules, 'sqlite3 was imported'\n"
        "assert 'engine.arrival' not in sys.modules, 'the adapter was imported'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Parity probe (§D.4 exit 3)
# ---------------------------------------------------------------------------


def _tracked_vertices() -> list[Path]:
    """Every ``.vertex`` git tracks, so the probe is hermetic.

    A filesystem walk would sweep in ``.loops/`` — gitignored, machine-local,
    and different on every checkout — which would make the probe's result
    depend on whose machine ran it.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.vertex", ".vertex"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / p for p in out.split("\0") if p]


def test_the_probe_has_something_to_probe():
    assert _tracked_vertices(), "no tracked .vertex files — the probe is vacuous"


def test_every_tracked_vertex_resolves_identically_under_both_paths():
    """The claim that makes "additive" a fact rather than a promise.

    For every vertex the repo tracks: the registry either describes no
    adapter (and the store keeps resolving through open_canonical_store
    untouched), or it names exactly the artifact the legacy path names.

    NOTE, stated so the gate is not surprised: no tracked vertex is
    arrival-canonical today, so this sweep exercises the jsonl, sqlite and
    no-store arms only. The arrival arm is covered by the minted fixtures
    below, which is the only place it CAN be covered until a real vertex
    declares one.
    """
    for vertex_path in _tracked_vertices():
        ast = parse_vertex_file(vertex_path)
        descriptor = descriptor_for(ast, vertex_path)
        if ast.store is None:
            assert descriptor is None, vertex_path
            continue
        canonical = canonical_store_path(ast.store, vertex_path)
        if canonical_mode(canonical) in ("jsonl", "sqlite"):
            assert descriptor is None, vertex_path
        else:
            assert descriptor is not None, vertex_path
            assert Path(descriptor.location) == canonical, vertex_path


def _minted_arrival_vertex(tmp_path: Path, store_line: str) -> tuple[Path, Path]:
    """A vertex over a real minted .arrival store with a consumed projection."""
    vpath = _vertex(tmp_path, store_line)
    log_path = tmp_path / "s.arrival"
    ArrivalLog.mint(log_path, observer="kyle", signer=_sign, key=_KEY)
    store = ArrivalStore(
        path=index_path_for(log_path),
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=_sign,
    )
    try:
        store.append(Fact.of("note", "kyle", message="one"))
    finally:
        store.close()
    return vpath, log_path


@pytest.mark.parametrize(
    "store_line",
    [
        'store "./s.arrival" backend="file"',  # explicit arm
        'store "./s.arrival"',                 # transitional inferred arm
    ],
)
def test_the_registry_opens_the_artifact_the_legacy_path_opens(
    tmp_path, store_line
):
    """Both arrival arms name — and open — the same artifact as today's path."""
    vpath, log_path = _minted_arrival_vertex(tmp_path, store_line)
    ast = parse_vertex_file(vpath)

    descriptor = descriptor_for(ast, vpath)
    assert descriptor is not None
    assert descriptor.backend == "file"

    legacy = open_canonical_store(
        canonical_store_path(ast.store, vpath),
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    try:
        assert isinstance(legacy, ArrivalStore)
        # The naming half: the descriptor points at the same log, and its
        # sibling index is the same index the legacy store opened.
        assert Path(descriptor.location) == legacy.log_path
        legacy_head = ArrivalLog(legacy.log_path).head()
    finally:
        legacy.close()

    # The opening half: the ledger the registry hands back is over that
    # artifact, not merely named after it.
    ledger, query = BackendRegistry.with_builtin_backends().open(descriptor)
    try:
        assert ledger.head().ordinal == legacy_head["ord"]
        watermark = query.projected_through()
        assert watermark is not None
        assert watermark.lineage == ArrivalLog(log_path).lineage()
    finally:
        query.close()


def test_a_declared_backend_does_not_change_where_the_store_lives(tmp_path):
    """Declaring the backend is not a relocation.

    The same vertex with and without ``backend="file"`` must resolve to the
    same location — the property that lets slice 5's adopt ceremony write the
    arm into existing vertices without moving anybody's data.
    """
    vpath = _vertex(tmp_path, 'store "./s.arrival"')
    inferred = descriptor_for(parse_vertex_file(vpath), vpath)

    vpath.write_text(
        vpath.read_text().replace(
            'store "./s.arrival"', 'store "./s.arrival" backend="file"'
        )
    )
    declared = descriptor_for(parse_vertex_file(vpath), vpath)

    assert inferred == declared


def test_a_vertex_file_constructed_in_memory_describes_the_same_way(tmp_path):
    """descriptor_for reads the AST, not the file — so a resolved
    declaration (which never touches disk as text) describes identically."""
    ast = VertexFile(
        name="t",
        loops={},
        store=Path("./s.arrival"),
        store_backend=BackendDecl(name="file"),
    )
    vpath = tmp_path / "t.vertex"
    descriptor = descriptor_for(ast, vpath)
    assert descriptor == StoreDescriptor(
        backend="file", location=str(tmp_path / "s.arrival")
    )
