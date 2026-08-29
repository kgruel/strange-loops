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
from engine.arrival_registry import BackendRegistry, descriptor_for
from engine.arrival_store import ArrivalStore
from engine.jsonl_store import open_canonical_store
from engine.residence import canonical_mode, canonical_store_path, index_path_for
from tests.conftest import STUB_KEY as _KEY
from tests.conftest import stub_sign as _sign

REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_a_registered_opener_is_what_open_calls():
    calls: list[StoreDescriptor] = []
    registry = BackendRegistry()
    registry.register("probe", lambda d: (calls.append(d), ("L", "Q"))[1])  # type: ignore[arg-type,return-value]
    descriptor = StoreDescriptor(backend="probe", location="/x/y")
    assert registry.open(descriptor) == ("L", "Q")
    assert calls == [descriptor]


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
        # exact nine-op equality, this one just confirms the opener's return
        # reaches the surface it declares.
        assert isinstance(ledger, ArrivalLedger)
        assert isinstance(query, ArrivalQuery)
    finally:
        query.close()


def test_opening_a_store_whose_projection_is_absent_refuses(tmp_path):
    """Observed behavior, pinned — NOT a policy this WP chose.

    ``FileQuery`` builds a read handle over the sibling index, and
    ``StoreReader`` refuses a path that does not exist. So a minted log with
    no projection beside it cannot be opened through the registry, even
    though its LEDGER half is perfectly openable.

    Whether an absent projection should be materialized on the way in is
    exactly the boundary the F2 addendum puts to Kyle at the slice-2 gate
    ("absent ⇒ create is permitted; present ⇒ touch is forbidden"). Inventing
    an answer here would be this WP ruling on a question it was not given, so
    the adapter's behavior passes through unchanged and this test records
    what it is. See finding:slice2-wp4-registry-open-needs-a-projection.
    """
    log_path = tmp_path / "s.arrival"
    ArrivalLog.mint(log_path, observer="kyle", signer=_sign, key=_KEY)
    registry = BackendRegistry.with_builtin_backends()
    with pytest.raises(FileNotFoundError):
        registry.open(StoreDescriptor(backend="file", location=str(log_path)))


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
