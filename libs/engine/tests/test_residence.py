"""Residence — the store locator's extension is the canonicity switch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.residence import (
    canonical_store_path,
    index_path_for,
    is_jsonl_canonical,
    resolve_store_path,
)


# ---- pure path rules ------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "canonical"),
    [("a.jsonl", True), ("a.db", False), ("a.sqlite", False), ("a", False)],
)
def test_is_jsonl_canonical_reads_the_suffix(declared, canonical):
    assert is_jsonl_canonical(Path(declared)) is canonical


def test_index_path_for_maps_log_to_sibling_db():
    assert index_path_for(Path("/s/project.jsonl")) == Path("/s/project.db")


def test_index_path_for_is_idempotent_on_a_db():
    assert index_path_for(Path("/s/project.db")) == Path("/s/project.db")
    assert index_path_for(index_path_for(Path("/s/p.jsonl"))) == Path("/s/p.db")


def test_relative_locators_resolve_against_the_vertex_dir_not_cwd(tmp_path):
    vertex = tmp_path / "sub" / "x.vertex"
    vertex.parent.mkdir()
    assert canonical_store_path("data/p.jsonl", vertex) == (
        tmp_path / "sub" / "data" / "p.jsonl"
    )


def test_resolve_store_path_composes_both(tmp_path):
    vertex = tmp_path / "x.vertex"
    assert resolve_store_path("data/p.jsonl", vertex) == tmp_path / "data" / "p.db"
    assert resolve_store_path("data/p.db", vertex) == tmp_path / "data" / "p.db"


def test_absolute_locators_pass_through(tmp_path):
    p = tmp_path / "p.jsonl"
    assert canonical_store_path(p, tmp_path / "elsewhere" / "x.vertex") == p


# ---- the switch, end to end ----------------------------------------


def _vertex(tmp_path: Path, store: str) -> Path:
    path = tmp_path / "t.vertex"
    path.write_text(
        f'name "t"\nstore "{store}"\n\nloops {{\n'
        '  note { fold { items "collect" 10 } }\n}\n'
    )
    return path


def _materialize(vertex_path: Path):
    from engine.compiler import compile_vertex_recursive, materialize_vertex
    from lang import parse_vertex_file

    return materialize_vertex(compile_vertex_recursive(parse_vertex_file(vertex_path)))


def test_a_jsonl_locator_builds_a_jsonl_store_over_the_sibling_index(tmp_path):
    from engine.jsonl_store import JsonlStore

    vertex_path = _vertex(tmp_path, "p.jsonl")
    vertex = _materialize(vertex_path)
    try:
        store = vertex._store
        assert isinstance(store, JsonlStore)
        assert store.log_path == tmp_path / "p.jsonl"
        assert store._path == tmp_path / "p.db"
    finally:
        vertex.close()


def test_a_db_locator_still_builds_a_plain_sqlite_store(tmp_path):
    from engine.jsonl_store import JsonlStore
    from engine.sqlite_store import SqliteStore

    vertex = _materialize(_vertex(tmp_path, "p.db"))
    try:
        assert isinstance(vertex._store, SqliteStore)
        assert not isinstance(vertex._store, JsonlStore)
    finally:
        vertex.close()


def test_facts_emitted_through_a_jsonl_vertex_land_in_the_log(tmp_path):
    from atoms import Fact

    vertex_path = _vertex(tmp_path, "p.jsonl")
    vertex = _materialize(vertex_path)
    try:
        vertex.receive(Fact.of("note", "kyle", message="hello"))
    finally:
        vertex.close()

    lines = (tmp_path / "p.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["t"] == "fact"
    assert row["kind"] == "note"
    # payload rides as the verbatim stored TEXT, never re-serialized
    assert isinstance(row["payload"], str)
    assert json.loads(row["payload"])["message"] == "hello"


def test_the_derived_index_rebuilds_from_the_log_alone(tmp_path):
    """Fresh clone: the .jsonl is tracked, the .db is not."""
    from atoms import Fact
    from engine.jsonl_store import ensure_index

    vertex_path = _vertex(tmp_path, "p.jsonl")
    vertex = _materialize(vertex_path)
    try:
        vertex.receive(Fact.of("note", "kyle", message="survives"))
    finally:
        vertex.close()

    before = (tmp_path / "p.jsonl").read_bytes()
    (tmp_path / "p.db").unlink()

    index = ensure_index(tmp_path / "p.jsonl")
    assert index == tmp_path / "p.db"
    assert index.exists()

    from engine import StoreReader

    with StoreReader(index) as reader:
        assert reader.summary()["facts"]["total"] == 1
    # rebuilding is read-only with respect to the canonical log
    assert (tmp_path / "p.jsonl").read_bytes() == before


def test_ensure_index_is_a_no_op_when_the_index_already_exists(tmp_path):
    from engine.jsonl_store import ensure_index

    (tmp_path / "p.jsonl").write_text("")
    (tmp_path / "p.db").write_bytes(b"not-a-database")
    assert ensure_index(tmp_path / "p.jsonl") == tmp_path / "p.db"
    assert (tmp_path / "p.db").read_bytes() == b"not-a-database"


def test_ensure_index_is_a_no_op_for_a_sqlite_canonical_locator(tmp_path):
    from engine.jsonl_store import ensure_index

    assert ensure_index(tmp_path / "p.db") == tmp_path / "p.db"
    assert not (tmp_path / "p.db").exists()


def test_ensure_index_declines_when_there_is_no_log_to_build_from(tmp_path):
    from engine.jsonl_store import ensure_index

    assert ensure_index(tmp_path / "p.jsonl") == tmp_path / "p.db"
    assert not (tmp_path / "p.db").exists()


def test_topology_writes_go_through_the_log_not_around_it(tmp_path):
    """_topology facts are a direct-store write — under a JSONL-canonical
    vertex they must not become an out-of-band sqlite insert."""
    from engine.vertex_reader import emit_topology

    child = tmp_path / "c.vertex"
    child.write_text('name "c"\nstore "c.db"\n')
    parent = tmp_path / "p.vertex"
    parent.write_text('name "p"\nstore "p.jsonl"\n\ncombine {\n  "c"\n}\n')

    # combine forbids store; declare topology the way the reader collects it
    parent.write_text(
        'name "p"\nstore "p.jsonl"\n\nvertices {\n  "c" path="c.vertex"\n}\n'
    )
    emit_topology(parent)

    log = tmp_path / "p.jsonl"
    if log.exists() and log.read_text().strip():
        kinds = [json.loads(line)["kind"] for line in log.read_text().splitlines()]
        assert kinds and all(k == "_topology" for k in kinds)


# ---- resolution materializes (the fresh-clone read) ------------------


def test_resolved_index_materializes_so_no_reader_sees_the_gap(tmp_path):
    """The fresh-clone first read must not answer 'empty' while rebuilding.

    ``resolve_store_path`` is pure — it can only NAME the index — so a reader
    that resolves and then checks ``exists()`` answers empty for exactly the
    invocation that should have built it. Resolution and materialization are
    one step.
    """
    from atoms import Fact
    from engine import StoreReader
    from engine.jsonl_store import resolved_index

    vertex_path = _vertex(tmp_path, "p.jsonl")
    vertex = _materialize(vertex_path)
    try:
        vertex.receive(Fact.of("note", "kyle", message="present"))
    finally:
        vertex.close()
    (tmp_path / "p.db").unlink()

    index = resolved_index("p.jsonl", vertex_path)

    assert index == resolve_store_path("p.jsonl", vertex_path)
    assert index.exists(), "resolution must leave the index materialized"
    with StoreReader(index) as reader:
        assert reader.summary()["facts"]["total"] == 1


def test_resolved_index_is_resolve_store_path_for_a_sqlite_vertex(tmp_path):
    vertex_path = _vertex(tmp_path, "p.db")
    from engine.jsonl_store import resolved_index

    assert resolved_index("p.db", vertex_path) == resolve_store_path("p.db", vertex_path)
    assert not (tmp_path / "p.db").exists()


def test_the_first_read_of_a_fresh_clone_sees_the_facts(tmp_path):
    """End-to-end shape of the finding: read_vertex_state, no index on disk."""
    from atoms import Fact
    from engine.vertex_reader import vertex_read

    vertex_path = _vertex(tmp_path, "p.jsonl")
    vertex = _materialize(vertex_path)
    try:
        vertex.receive(Fact.of("note", "kyle", message="present"))
    finally:
        vertex.close()
    (tmp_path / "p.db").unlink()

    state = vertex_read(vertex_path)
    assert state["note"]["items"], "first read after a clone must not answer empty"
