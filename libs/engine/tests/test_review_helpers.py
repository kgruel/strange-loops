"""Review-projection engine helpers (0.9.0 S4).

``fact_signatures`` (verbatim per-fact signature lookup, the ONLY source the
canonical review projection has) and ``declaration_generation`` (the review
declaration-generation disclosure: a residence-honest content fingerprint plus
the adopted-store ``decl_head`` ULID). Both are read-only; both degrade rather
than raise. The CLI end-to-end wiring is covered in
apps/loops/tests/test_review.py — this pins the engine surface directly.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from atoms import Fact
from lang import parse_vertex_file
from lang.document import (
    DECL_KIND_DEFINED,
    genesis_payload,
    vertex_to_documents,
)

from engine import declaration_generation, fact_signatures
from engine.sqlite_store import SqliteStore

_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
  thread {{ fold {{ items "by" "name" }} }}
}}
'''


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    return vpath, store


def _empty(store: Path) -> None:
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _append(store, kind, ts, *, fid, signature=None, **payload) -> str:
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, 'kyle', '', ?, ?)",
        (fid, kind, ts, json.dumps(payload), signature),
    )
    conn.commit()
    conn.close()
    return fid


def _absorb(vpath: Path, store: Path) -> str:
    ast = parse_vertex_file(vpath)
    docs = genesis_payload(ast)["documents"]
    s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    receipt = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return receipt["lineage"]


# ---------------------------------------------------------------------------
# fact_signatures
# ---------------------------------------------------------------------------


class TestFactSignatures:
    def test_verbatim_and_null(self, tmp_path):
        _, store = _scaffold(tmp_path)
        _empty(store)
        _append(store, "decision", 1.0, fid="A", topic="a", signature="SIG-A")
        _append(store, "decision", 2.0, fid="B", topic="b")  # NULL signature
        got = fact_signatures(store, ["A", "B"])
        assert got == {"A": "SIG-A", "B": None}

    def test_unknown_id_and_dedupe_and_order(self, tmp_path):
        _, store = _scaffold(tmp_path)
        _empty(store)
        _append(store, "decision", 1.0, fid="A", topic="a", signature="s")
        got = fact_signatures(store, ["B", "A", "A", "B"])
        assert got == {"B": None, "A": "s"}
        assert list(got.keys()) == ["B", "A"]  # first-seen order preserved

    def test_empty_ids(self, tmp_path):
        _, store = _scaffold(tmp_path)
        _empty(store)
        assert fact_signatures(store, []) == {}

    def test_pre_signature_store_all_none(self, tmp_path):
        store = tmp_path / "old.db"
        conn = sqlite3.connect(str(store))
        conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, kind TEXT)")
        conn.execute("INSERT INTO facts (id, kind) VALUES ('X', 'decision')")
        conn.commit()
        conn.close()
        assert fact_signatures(store, ["X", "Y"]) == {"X": None, "Y": None}

    def test_missing_store_degrades(self, tmp_path):
        assert fact_signatures(tmp_path / "nope.db", ["A"]) == {"A": None}

    def test_read_only_no_mutation(self, tmp_path):
        _, store = _scaffold(tmp_path)
        _empty(store)
        _append(store, "decision", 1.0, fid="A", topic="a", signature="s")
        before = store.read_bytes()
        fact_signatures(store, ["A"])
        assert store.read_bytes() == before


# ---------------------------------------------------------------------------
# declaration_generation
# ---------------------------------------------------------------------------


class TestDeclarationGeneration:
    def test_pre_genesis(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _empty(store)
        gen = declaration_generation(vpath)
        assert gen["status"] == "file-pre-genesis"
        assert gen["lineage"] is None
        assert gen["decl_head"] is None
        assert gen["review_fingerprint"].startswith("sha256:")

    def test_fingerprint_recipe(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _empty(store)
        ast = parse_vertex_file(vpath)
        canonical = json.dumps(
            [d.as_json() for d in vertex_to_documents(ast)],
            sort_keys=True, separators=(",", ":"),
        )
        expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert declaration_generation(vpath)["review_fingerprint"] == expected

    def test_semantic_edit_moves_cosmetic_does_not(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _empty(store)
        base = declaration_generation(vpath)["review_fingerprint"]
        # cosmetic: a comment the parser discards
        vpath.write_text(vpath.read_text() + "\n// note\n")
        assert declaration_generation(vpath)["review_fingerprint"] == base
        # semantic: a new declared kind
        vpath.write_text(
            vpath.read_text().replace(
                "loops {", 'loops {\n  friction { fold { items "by" "name" } }'
            )
        )
        assert declaration_generation(vpath)["review_fingerprint"] != base

    def test_adopted_genesis_only_head_is_lineage(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        gen = declaration_generation(vpath)
        assert gen["status"] == "store"
        assert gen["lineage"] == lineage
        assert gen["decl_head"] == lineage  # only event in the lineage

    def test_adopted_decl_head_advances_to_latest_self_overlay(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        # Overlay rows are appended after the genesis, so they are later in
        # receipt order and win the declaration head. The far-future timestamps
        # are belt-and-braces for the `as_of` lens, not what decides the head.
        _append(
            store, DECL_KIND_DEFINED, 2_000_000_000.0, fid="OVERLAY1",
            lineage=lineage, subject="decision", payload={"order": 0},
        )
        # A LATER foreign-lineage row must NOT become the head.
        _append(
            store, DECL_KIND_DEFINED, 2_100_000_000.0, fid="FOREIGN",
            lineage="someone-else", subject="x", payload={},
        )
        gen = declaration_generation(vpath)
        assert gen["lineage"] == lineage
        assert gen["decl_head"] == "OVERLAY1"

    def test_read_only_no_mutation(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        before = store.read_bytes()
        declaration_generation(vpath)
        assert store.read_bytes() == before
