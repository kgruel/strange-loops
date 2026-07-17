"""Durable lineage-qualified handles, end-to-end (capstone B1a/B1b).

The A10-narrowed contract: an ADOPTED store advertises a portable
``fact:<lineage>/<id>`` handle that round-trips through the CLI address parser
and is lineage-checked on the way back; an UNADOPTED store has no durable handle;
a lineage-qualified handle refuses against the wrong lineage or an unadopted
store. Bare ``fact:<id>`` stays a same-store convenience.

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex_file
from lang.document import genesis_payload

from engine import durable_handle, resolve_witness_position
from engine.sqlite_store import SqliteStore, gen_id
from loops.cli.witness_address import AddressError, resolve_at_address

_KDL = (
    'name "t"\nstore "{store}"\n'
    'loops {{\n  decision {{ fold {{ items "by" "topic" }} }}\n}}\n'
    'observers {{\n  kyle {{ key "AAAA" }}\n}}\n'
)


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


def _adopt(tmp_path: Path) -> tuple[Path, str]:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_KDL.format(store=store))
    ast = parse_vertex_file(vpath)
    s = SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    lineage = s.absorb_genesis(
        genesis_payload(ast)["documents"], observer="kyle", fact_signer=_signer
    )["lineage"]
    s.close()
    return store, lineage


def _fresh(store: Path) -> None:
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _append(store: Path, ts: float, topic: str) -> str:
    conn = sqlite3.connect(str(store))
    fid = gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, 'decision', ?, 'kyle', '', ?, NULL)",
        (fid, ts, json.dumps({"topic": topic})),
    )
    conn.commit()
    conn.close()
    return fid


def test_durable_handle_round_trips_through_the_address_parser(tmp_path):
    store, lineage = _adopt(tmp_path)
    f1 = _append(store, 100, "a")
    pos = resolve_witness_position(store, f1)
    handle = durable_handle(pos)
    assert handle == f"fact:{lineage}/{f1}"
    # The advertised portable handle resolves back to the same position.
    back = resolve_at_address(store, handle)
    assert back.fact_id == f1 and back.rowid == pos.rowid and back.lineage == lineage


def test_wrong_lineage_qualified_handle_is_refused(tmp_path):
    store, _lineage = _adopt(tmp_path)
    f1 = _append(store, 100, "a")
    with pytest.raises(AddressError):
        resolve_at_address(store, f"fact:01WRONGLINEAGE00000000000/{f1}")


def test_lineage_qualified_handle_on_unadopted_store_is_refused(tmp_path):
    store = tmp_path / "u.db"
    _fresh(store)
    f1 = _append(store, 100, "a")
    with pytest.raises(AddressError):
        resolve_at_address(store, f"fact:01SOMELINEAGE0000000000000/{f1}")


def test_bare_fact_id_still_resolves_same_store(tmp_path):
    store, _lineage = _adopt(tmp_path)
    f1 = _append(store, 100, "a")
    pos = resolve_at_address(store, f"fact:{f1}")
    assert pos.fact_id == f1


def test_unadopted_position_has_no_durable_handle(tmp_path):
    store = tmp_path / "u.db"
    _fresh(store)
    _append(store, 100, "a")
    pos = resolve_witness_position(store, "head")
    assert durable_handle(pos) is None
