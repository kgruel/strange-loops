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
    AmbiguousLineage,
    Unhistorized,
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

    def test_foreign_genesis_is_inert_on_marked_store(self, tmp_path):
        # A merged-in foreign genesis must NOT disturb a marked store's
        # resolution (SPEC §9.2: foreign lineages are inert citizens) — the
        # own_lineage marker, not row count, decides identity.
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)  # stamps store_meta.own_lineage
        _append_decl_row(
            store, kind=DECL_GENESIS,
            payload={"protocol": 1, "documents": [
                {"kind": "_decl.kind-defined", "subject": "HIJACK", "payload": {}}
            ]},
            ts=_genesis_ts(store) + 10, row_id="genesis-foreign",
        )
        resolved = load_declaration(vpath)
        assert set(resolved.loops) == {"decision", "thread"}  # not HIJACK

    def test_two_genesis_without_marker_raises(self, tmp_path):
        # Pre-marker store (marker stripped) + several genesis rows → refuse.
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        _append_decl_row(
            store, kind=DECL_GENESIS,
            payload={"protocol": 1, "documents": []},
            ts=_genesis_ts(store) + 10, row_id="genesis2",
        )
        conn = sqlite3.connect(str(store))
        conn.execute("DELETE FROM store_meta WHERE key = 'own_lineage'")
        conn.commit()
        conn.close()
        with pytest.raises(AmbiguousLineage):
            resolve_declaration_documents(store)
        # And the seam surfaces it too (not swallowed into a silent fallback).
        with pytest.raises(AmbiguousLineage):
            load_declaration(vpath)

    def test_marker_without_genesis_row_is_corruption(self, tmp_path):
        from engine.declaration import DeclarationResolutionError

        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        conn = sqlite3.connect(str(store))
        conn.execute(
            "UPDATE store_meta SET value = 'no-such-genesis' "
            "WHERE key = 'own_lineage'"
        )
        conn.commit()
        conn.close()
        with pytest.raises(DeclarationResolutionError):
            resolve_declaration_documents(store)

    def test_unmarked_genesis_refuses_until_adopted(self, tmp_path):
        # Facts alone cannot prove which genesis is self — even a singleton.
        # An unmarked store refuses with adopt guidance; the explicit adopt
        # ceremony (human intent) claims identity and resolution resumes.
        from atoms import Fact

        from engine.declaration import UnadoptedLineage

        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        conn = sqlite3.connect(str(store))
        conn.execute("DELETE FROM store_meta WHERE key = 'own_lineage'")
        conn.commit()
        conn.close()
        with pytest.raises(UnadoptedLineage):
            load_declaration(vpath)
        s = SqliteStore(
            path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        )
        receipt = s.adopt_lineage()
        s.close()
        assert receipt["genesis_count"] == 1
        resolved = load_declaration(vpath)
        assert set(resolved.loops) == {"decision", "thread"}

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
    def test_genesis_after_cutoff_is_unhistorized_genesis_floor(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        before = _genesis_ts(store) - 100
        result = resolve_declaration_documents(store, as_of=before)
        assert isinstance(result, Unhistorized)
        # The seam projects the GENESIS documents (SPEC §9.2 earliest known
        # state) — never the current file, which may have drifted since.
        vpath.write_text(vpath.read_text().replace("strict #true", "strict #false"))
        resolved = load_declaration(vpath, as_of=before)
        assert resolved.strict is True  # genesis floor, not the mutated file
        assert set(resolved.loops) == {"decision", "thread"}

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


# ---------------------------------------------------------------------------
# Env ingress (SPEC §9.5 secrets-indirection)
# ---------------------------------------------------------------------------

_ENV_VERTEX_KDL = '''name "t"
store "{store}"
sources sequential {{
  source "curl -s https://x.example" {{
    kind "ping"
    env TOKEN="hunter2" MODE="fast"
  }}
}}
loops {{
  ping {{ fold {{ n "inc" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


class TestEnvIngress:
    """Env VALUES are ingress: never absorbed, re-attached from the file."""

    def _scaffold_env(self, tmp_path):
        store = tmp_path / "t.db"
        vpath = tmp_path / "t.vertex"
        vpath.write_text(_ENV_VERTEX_KDL.format(store=store))
        return vpath, store

    def test_secret_never_enters_store_payloads(self, tmp_path):
        vpath, store = self._scaffold_env(tmp_path)
        _absorb(vpath, store)
        conn = sqlite3.connect(str(store))
        payloads = [r[0] for r in conn.execute("SELECT payload FROM facts")]
        conn.close()
        assert not any("hunter2" in p for p in payloads)

    def test_resolution_reattaches_values_from_file(self, tmp_path):
        vpath, store = self._scaffold_env(tmp_path)
        _absorb(vpath, store)
        resolved = load_declaration(vpath)
        (block,) = resolved.sources_blocks
        (src,) = block.sources
        assert dict(src.env) == {"TOKEN": "hunter2", "MODE": "fast"}

    def test_env_value_edit_is_live_without_ceremony(self, tmp_path):
        # Values are ingress — like the store locator, the file's edit takes
        # effect immediately; no declaration event required.
        vpath, store = self._scaffold_env(tmp_path)
        _absorb(vpath, store)
        vpath.write_text(vpath.read_text().replace("hunter2", "rotated"))
        resolved = load_declaration(vpath)
        assert dict(resolved.sources_blocks[0].sources[0].env)["TOKEN"] == "rotated"

    def test_env_key_set_is_declaration_shape(self, tmp_path):
        # ADDING a key is a shape change: inert until absorbed (the resolved
        # key set is store-authoritative), surfaced by the edit ceremony.
        vpath, store = self._scaffold_env(tmp_path)
        _absorb(vpath, store)
        vpath.write_text(
            vpath.read_text().replace('MODE="fast"', 'MODE="fast" EXTRA="new"')
        )
        resolved = load_declaration(vpath)
        assert set(dict(resolved.sources_blocks[0].sources[0].env)) == {
            "TOKEN", "MODE",
        }  # EXTRA not resolved until absorb

    def test_colliding_commands_do_not_cross_wire_values(self, tmp_path):
        # Two sources sharing a command must each get their OWN env value —
        # occurrence identity, not command identity (re-review #4).
        store = tmp_path / "t.db"
        vpath = tmp_path / "t.vertex"
        vpath.write_text(f'''name "t"
store "{store}"
sources sequential {{
  source "curl -s https://x.example" {{
    kind "ping"
    env TOKEN="first"
  }}
  source "curl -s https://x.example" {{
    kind "pong"
    env TOKEN="second"
  }}
}}
loops {{
  ping {{ fold {{ n "inc" }} }}
  pong {{ fold {{ n "inc" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
''')
        _absorb(vpath, store)
        resolved = load_declaration(vpath)
        (block,) = resolved.sources_blocks
        values = [dict(s.env)["TOKEN"] for s in block.sources]
        assert values == ["first", "second"]


class TestSourcePins:
    """No-auto-enact at the execution tier: pinned sources refuse drift."""

    def _scaffold_loop(self, tmp_path):
        store = tmp_path / "t.db"
        vpath = tmp_path / "t.vertex"
        loop = tmp_path / "feed.loop"
        loop.write_text(
            'kind "ping"\nobserver "t"\nsource "echo hi"\nevery "30s"\n'
        )
        vpath.write_text(f'''name "t"
store "{store}"
sources {{
  path "./feed.loop"
}}
loops {{
  ping {{ fold {{ n "inc" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
''')
        return vpath, store, loop

    def test_pinned_source_unchanged_passes(self, tmp_path):
        from engine.declaration import verify_source_pins

        vpath, store, _loop = self._scaffold_loop(tmp_path)
        _absorb(vpath, store)
        verify_source_pins(vpath)  # no raise

    def test_drifted_source_refuses(self, tmp_path):
        from engine.declaration import SourceDrift, verify_source_pins

        vpath, store, loop = self._scaffold_loop(tmp_path)
        _absorb(vpath, store)
        loop.write_text(loop.read_text().replace("echo hi", "curl evil"))
        with pytest.raises(SourceDrift):
            verify_source_pins(vpath)

    def test_pre_genesis_is_a_noop(self, tmp_path):
        from engine.declaration import verify_source_pins

        vpath, _store, loop = self._scaffold_loop(tmp_path)  # never absorbed
        loop.write_text("anything")
        verify_source_pins(vpath)  # no pins, no raise


class TestDeclarationStatus:
    """load_declaration_status — the honesty channel for rendering surfaces."""

    def test_store_status_at_head_and_asof(self, tmp_path):
        from engine.declaration import load_declaration_status

        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        _ast, status = load_declaration_status(vpath)
        assert status == "store"
        _ast, status = load_declaration_status(
            vpath, as_of=_genesis_ts(store) + 1
        )
        assert status == "store"

    def test_unhistorized_status_before_genesis(self, tmp_path):
        from engine.declaration import load_declaration_status

        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        ast, status = load_declaration_status(
            vpath, as_of=_genesis_ts(store) - 100
        )
        assert status == "unhistorized"
        assert set(ast.loops) == {"decision", "thread"}  # genesis floor

    def test_pre_genesis_is_file_status(self, tmp_path):
        from engine.declaration import load_declaration_status

        vpath, _store = _scaffold(tmp_path)  # never absorbed
        _ast, status = load_declaration_status(vpath)
        assert status == "file-pre-genesis"

    def test_storeless_aggregate_under_asof_is_flagged(self, tmp_path):
        from engine.declaration import load_declaration_status

        vpath = tmp_path / "agg.vertex"
        vpath.write_text(
            'name "agg"\ncombine {\n  vertex "/tmp/nonexistent.vertex"\n}\n'
        )
        _ast, status = load_declaration_status(vpath, as_of=123.0)
        assert status == "aggregate-head"
        # Without a cursor there is no historical claim to caveat.
        _ast, status = load_declaration_status(vpath)
        assert status == "file-pre-genesis"

    def test_structural_edit_of_duplicates_never_cross_wires(self, tmp_path):
        # Delete the FIRST of two same-command sources in the file without
        # re-absorbing: ordinal identity is unsound for that group, so
        # re-attachment SKIPS it (empty values, loud at runtime) rather than
        # routing the survivor's value onto the stored first source
        # (branch-review #2).
        store = tmp_path / "t.db"
        vpath = tmp_path / "t.vertex"
        two = f'''name "t"
store "{store}"
sources sequential {{
  source "curl -s https://x.example" {{
    kind "ping"
    env TOKEN="first"
  }}
  source "curl -s https://x.example" {{
    kind "pong"
    env TOKEN="second"
  }}
}}
loops {{
  ping {{ fold {{ n "inc" }} }}
  pong {{ fold {{ n "inc" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''
        vpath.write_text(two)
        _absorb(vpath, store)
        # File drops the FIRST duplicate; declaration still has both.
        one = two.replace('''  source "curl -s https://x.example" {{
    kind "ping"
    env TOKEN="first"
  }}
'''.replace("{{", "{").replace("}}", "}"), "")
        vpath.write_text(one)
        resolved = load_declaration(vpath)
        (block,) = resolved.sources_blocks
        values = [dict(s.env).get("TOKEN", "") for s in block.sources]
        # Both stored sources resolve EMPTY — never "second" on the first.
        assert values == ["", ""]

    def test_id_lookup_scoped_by_kind(self, tmp_path):
        from engine.vertex_reader import vertex_fact_by_id

        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        # Unlock alone must not return a row of a DIFFERENT kind.
        found = vertex_fact_by_id(
            vpath, lineage, include_internal=True, kind="_decl.kind-defined"
        )
        assert found is None
        found = vertex_fact_by_id(
            vpath, lineage, include_internal=True, kind="_decl.genesis"
        )
        assert found is not None

    def test_cross_block_move_resolves_empty_not_cross_wired(self, tmp_path):
        # Move one of two same-command sources to a second block without
        # re-absorbing: no (block, command) group is count-stable for the
        # moved source, and there is NO command-level fallback — both blocks'
        # affected sources resolve empty rather than borrowing another
        # block's value (branch-review round 2 #1).
        store = tmp_path / "t.db"
        vpath = tmp_path / "t.vertex"
        two_one_block = f'''name "t"
store "{store}"
sources sequential {{
  source "echo same" {{
    kind "ping"
    env TOKEN="A"
  }}
  source "echo same" {{
    kind "pong"
    env TOKEN="B"
  }}
}}
loops {{
  ping {{ fold {{ n "inc" }} }}
  pong {{ fold {{ n "inc" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''
        vpath.write_text(two_one_block)
        _absorb(vpath, store)
        split_blocks = two_one_block.replace('''  source "echo same" {
    kind "pong"
    env TOKEN="B"
  }
}
loops''', '''}
sources sequential {
  source "echo same" {
    kind "pong"
    env TOKEN="B"
  }
}
loops''')
        vpath.write_text(split_blocks)
        resolved = load_declaration(vpath)
        values = [
            dict(s.env).get("TOKEN", "")
            for b in resolved.sources_blocks
            for s in b.sources
        ]
        assert "A" in values or values == ["", ""] or values == [""] * len(values)
        # The load-bearing assertion: pong NEVER borrows A (nor ping B).
        (block,) = resolved.sources_blocks[:1]
        kinds_to_token = {
            s.kind: dict(s.env).get("TOKEN", "")
            for b in resolved.sources_blocks
            for s in b.sources
        }
        assert kinds_to_token.get("pong", "") in ("", "B")
        assert kinds_to_token.get("ping", "") in ("", "A")

    def test_id_prefix_ambiguity_scoped_by_kind(self, tmp_path):
        # Two facts sharing an id prefix across kinds are NOT ambiguous when
        # only one has the requested kind (branch-review round 2 #2).
        from engine.vertex_reader import vertex_fact_by_id

        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        conn = sqlite3.connect(str(store))
        for fid, kind in (("abc1", "decision"), ("abc2", "thread")):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, payload) "
                "VALUES (?, ?, 100.0, 'kyle', '{}')",
                (fid, kind),
            )
        conn.commit()
        conn.close()
        with pytest.raises(ValueError):
            vertex_fact_by_id(vpath, "abc")  # genuinely ambiguous unscoped
        found = vertex_fact_by_id(vpath, "abc", kind="decision")
        assert found is not None and found["id"] == "abc1"

    def test_combined_lookup_propagates_child_ambiguity(self, tmp_path):
        # Within-store prefix ambiguity in an aggregation member must raise,
        # not read as absent (branch-review round 3).
        from engine.vertex_reader import vertex_fact_by_id

        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        conn = sqlite3.connect(str(store))
        for fid in ("abc1", "abc2"):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, payload) "
                "VALUES (?, 'decision', 100.0, 'kyle', '{}')",
                (fid,),
            )
        conn.commit()
        conn.close()
        agg = tmp_path / "agg.vertex"
        agg.write_text(f'name "agg"\ncombine {{\n  vertex "{vpath}"\n}}\n')
        with pytest.raises(ValueError):
            vertex_fact_by_id(agg, "abc", kind="decision")
