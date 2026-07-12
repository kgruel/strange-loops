"""Store-backed declaration resolver — the honesty net (SPEC §9.5 S2).

The exit criterion is :class:`TestFileDissolvesToLocator` — once a store's
lineage is opened, mutating the ``.vertex`` file changes NOTHING; the store's
declaration is canonical. Before genesis, the file is still authoritative (the
pre-genesis fallback carries every existing store in the wider suites).

The rest exercises the fold's protocol rules: self-lineage scoping (foreign
declarations inert on arrival, since merge already crosses stores today),
tombstones, unknown-kind forward-compat, the two-genesis and protocol-too-new
fail-closed conditions, and the ``as_of`` cutoff (including the
unhistorized-before-genesis marker).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex_file
from lang.document import (
    DECL_GENESIS,
    DECL_KIND_DEFINED,
    DECL_KIND_RETIRED,
    genesis_payload,
    vertex_to_documents,
)

from engine.declaration import (
    UNHISTORIZED,
    AmbiguousLineage,
    UnsupportedProtocol,
    load_declaration,
    resolve_declaration_documents,
)
from engine.sqlite_store import SqliteStore

# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


_VERTEX_KDL = '''name "t"
store "{store}"
strict #true
loops {{
  decision {{ fold {{ items "by" "topic" }}
             search "message" }}
  thread {{ fold {{ items "by" "name" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    """Write a .vertex file + its (empty) store path. Not yet absorbed."""
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    return vpath, store


def _absorb(vpath: Path, store: Path) -> str:
    """Open the store's lineage from the file's declaration; return lineage id."""
    ast = parse_vertex_file(vpath)
    docs = genesis_payload(ast)["documents"]
    s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    receipt = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return receipt["lineage"]


def _append_decl_row(
    store: Path,
    *,
    kind: str,
    payload: dict,
    ts: float,
    row_id: str,
) -> None:
    """Hand-append a raw ``_decl.*`` overlay/tombstone row.

    No edit ceremony exists yet (S4), so overlay rows are constructed directly
    against the provisional payload shape the resolver reads. Signatures are
    irrelevant to resolution (lineage + protocol are the gates), so NULL.
    """
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (row_id, kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _genesis_ts(store: Path) -> float:
    conn = sqlite3.connect(str(store))
    ts = conn.execute(
        "SELECT ts FROM facts WHERE kind = ?", (DECL_GENESIS,)
    ).fetchone()[0]
    conn.close()
    return ts


# ---------------------------------------------------------------------------
# THE HONEST TEST — the slice's exit criterion
# ---------------------------------------------------------------------------


class TestFileDissolvesToLocator:
    """Post-genesis, the store is canonical and file mutations are inert."""

    def test_pre_genesis_file_mutation_takes_effect(self, tmp_path):
        # Before absorb, the file IS the authority — mutation is honored.
        vpath, _store = _scaffold(tmp_path)
        assert load_declaration(vpath).strict is True

        vpath.write_text(vpath.read_text().replace("strict #true", "strict #false"))
        assert load_declaration(vpath).strict is False  # file still authoritative

    def test_post_genesis_file_mutation_is_inert(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)

        # Mutate every declaration surface in the file: flip strict, rename a
        # kind, drop the observer. All must be ignored — the store wins.
        mutated = (
            vpath.read_text()
            .replace("strict #true", "strict #false")
            .replace("thread {", "friction {")
            .replace('kyle { key "AAAA" }', 'eve { key "ZZZZ" }')
        )
        vpath.write_text(mutated)

        resolved = load_declaration(vpath)
        assert resolved.strict is True  # store's strict, not the file's
        assert set(resolved.loops) == {"decision", "thread"}  # not "friction"
        assert [o.name for o in resolved.observers] == ["kyle"]  # not "eve"

    def test_resolved_ast_equals_file_ast_modulo_residence(self, tmp_path):
        # A freshly-absorbed store resolves to the same declaration the file
        # parsed to (the round-trip S0 guarantees, now through the store).
        vpath, store = _scaffold(tmp_path)
        file_ast = parse_vertex_file(vpath)
        _absorb(vpath, store)
        resolved = load_declaration(vpath)
        assert vertex_to_documents(resolved) == vertex_to_documents(file_ast)
        # Residence is re-attached from the file locator, not the documents.
        assert resolved.store == file_ast.store
        assert resolved.path == vpath

    def test_no_store_field_falls_back_to_file(self, tmp_path):
        # A pure declaration file (no store locator) is always the file AST.
        vpath = tmp_path / "obs.vertex"
        vpath.write_text(
            'name "obs"\n'
            'loops {\n  ping { fold { items "latest" } }\n}\n'
            'observers {\n  kyle { key "AAAA" }\n}\n'
        )
        resolved = load_declaration(vpath)
        assert [o.name for o in resolved.observers] == ["kyle"]

    def test_store_absent_falls_back_to_file(self, tmp_path):
        # Locator points at a store that doesn't exist yet → file AST.
        vpath, _store = _scaffold(tmp_path)  # store never created
        assert load_declaration(vpath).strict is True


# ---------------------------------------------------------------------------
# Self-lineage scoping
# ---------------------------------------------------------------------------


class TestSelfLineageScoping:
    def test_self_lineage_overlay_folds(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        # A self-lineage overlay redefines the "decision" kind (adds a preview).
        _append_decl_row(
            store,
            kind=DECL_KIND_DEFINED,
            payload={
                "lineage": lineage,
                "subject": "decision",
                "payload": {"order": 1, "preview": ["topic"], "folds": [
                    {"target": "items", "op": {"op": "by", "key_field": "topic"}}
                ]},
            },
            ts=_genesis_ts(store) + 10,
            row_id="overlay1",
        )
        resolved = load_declaration(vpath)
        assert resolved.loops["decision"].preview_fields == ("topic",)

    def test_foreign_lineage_overlay_is_inert(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        # A FOREIGN lineage (as a merge would physically carry) must not fold.
        _append_decl_row(
            store,
            kind=DECL_KIND_DEFINED,
            payload={
                "lineage": "some-other-stores-genesis-id",
                "subject": "decision",
                "payload": {"order": 1, "preview": ["HIJACKED"]},
            },
            ts=_genesis_ts(store) + 10,
            row_id="foreign1",
        )
        resolved = load_declaration(vpath)
        assert resolved.loops["decision"].preview_fields == ()  # unchanged

    def test_absent_lineage_overlay_is_inert(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        _append_decl_row(
            store,
            kind=DECL_KIND_DEFINED,
            payload={"subject": "decision", "payload": {"order": 1, "preview": ["X"]}},
            ts=_genesis_ts(store) + 10,
            row_id="nolineage1",
        )
        resolved = load_declaration(vpath)
        assert resolved.loops["decision"].preview_fields == ()


# ---------------------------------------------------------------------------
# Tombstones, unknown kinds, fail-closed conditions
# ---------------------------------------------------------------------------


class TestTombstonesAndForwardCompat:
    def test_tombstone_removes_a_kind(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        _append_decl_row(
            store,
            kind=DECL_KIND_RETIRED,
            payload={"lineage": lineage, "subject": "thread"},
            ts=_genesis_ts(store) + 10,
            row_id="retire1",
        )
        resolved = load_declaration(vpath)
        assert set(resolved.loops) == {"decision"}  # thread tombstoned

    def test_foreign_lineage_tombstone_is_inert(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        _append_decl_row(
            store,
            kind=DECL_KIND_RETIRED,
            payload={"lineage": "foreign", "subject": "thread"},
            ts=_genesis_ts(store) + 10,
            row_id="retire-foreign",
        )
        resolved = load_declaration(vpath)
        assert set(resolved.loops) == {"decision", "thread"}  # not removed

    def test_redefine_after_tombstone_wins_by_replay_order(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        base_ts = _genesis_ts(store)
        _append_decl_row(
            store, kind=DECL_KIND_RETIRED,
            payload={"lineage": lineage, "subject": "thread"},
            ts=base_ts + 10, row_id="r-retire",
        )
        _append_decl_row(
            store, kind=DECL_KIND_DEFINED,
            payload={"lineage": lineage, "subject": "thread",
                     "payload": {"order": 5, "folds": [
                         {"target": "items", "op": {"op": "by", "key_field": "name"}}]}},
            ts=base_ts + 20, row_id="r-redefine",
        )
        resolved = load_declaration(vpath)
        assert "thread" in resolved.loops  # re-defined after the tombstone

    def test_unknown_decl_kind_is_ignored(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        _append_decl_row(
            store,
            kind="_decl.some-future-kind",
            payload={"lineage": lineage, "subject": "whatever", "payload": {}},
            ts=_genesis_ts(store) + 10,
            row_id="future1",
        )
        resolved = load_declaration(vpath)  # no crash, no effect
        assert set(resolved.loops) == {"decision", "thread"}

    def test_receipt_kinds_do_not_affect_resolution(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        _append_decl_row(
            store, kind="_decl.merged",
            payload={"lineage": lineage, "source": "x"},
            ts=_genesis_ts(store) + 10, row_id="merged1",
        )
        resolved = load_declaration(vpath)
        assert set(resolved.loops) == {"decision", "thread"}

    def test_two_genesis_raises(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        # Physically inject a second genesis (a merge could carry a foreign one).
        _append_decl_row(
            store, kind=DECL_GENESIS,
            payload={"protocol": 1, "documents": []},
            ts=_genesis_ts(store) + 10, row_id="genesis2",
        )
        with pytest.raises(AmbiguousLineage):
            resolve_declaration_documents(store)
        # And the seam surfaces it too (not swallowed into a silent fallback).
        with pytest.raises(AmbiguousLineage):
            load_declaration(vpath)

    def test_protocol_too_new_raises(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        # Absorb, then rewrite the genesis payload's protocol to a future version.
        _absorb(vpath, store)
        conn = sqlite3.connect(str(store))
        row = conn.execute(
            "SELECT id, payload FROM facts WHERE kind = ?", (DECL_GENESIS,)
        ).fetchone()
        payload = json.loads(row[1])
        payload["protocol"] = 999
        conn.execute(
            "UPDATE facts SET payload = ? WHERE id = ?", (json.dumps(payload), row[0])
        )
        conn.commit()
        conn.close()
        with pytest.raises(UnsupportedProtocol):
            resolve_declaration_documents(store)


# ---------------------------------------------------------------------------
# as_of cutoff
# ---------------------------------------------------------------------------


class TestAsOf:
    def test_genesis_after_cutoff_is_unhistorized(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        before = _genesis_ts(store) - 100
        assert resolve_declaration_documents(store, as_of=before) is UNHISTORIZED
        # The seam falls back to the file for the pre-genesis era.
        assert load_declaration(vpath, as_of=before).strict is True

    def test_no_genesis_is_none_not_unhistorized(self, tmp_path):
        # A store that never opened a lineage is None (distinct from UNHISTORIZED).
        vpath, store = _scaffold(tmp_path)
        SqliteStore(  # create the store file with schema but no genesis
            path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        ).append(Fact(kind="decision", ts=1.0, payload={"topic": "a"}, observer="kyle"))
        assert resolve_declaration_documents(store) is None

    def test_overlay_after_cutoff_does_not_participate(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        gts = _genesis_ts(store)
        _append_decl_row(
            store, kind=DECL_KIND_DEFINED,
            payload={"lineage": lineage, "subject": "decision",
                     "payload": {"order": 1, "preview": ["late"]}},
            ts=gts + 100, row_id="late-overlay",
        )
        # Cutoff BETWEEN genesis and the overlay → overlay excluded.
        docs = resolve_declaration_documents(store, as_of=gts + 50)
        assert isinstance(docs, list)
        decision = next(d for d in docs if d["subject"] == "decision")
        assert decision["payload"].get("preview") != ["late"]
        # Cutoff AFTER the overlay → overlay included.
        docs2 = resolve_declaration_documents(store, as_of=gts + 200)
        decision2 = next(d for d in docs2 if d["subject"] == "decision")
        assert decision2["payload"].get("preview") == ["late"]
