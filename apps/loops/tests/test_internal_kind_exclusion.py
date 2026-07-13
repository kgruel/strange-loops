"""Read-surface exclusion for the reserved `_decl.*` namespace (SPEC §9.4, S3).

Every read surface excludes declaration-event rows by default; an explicit
`--kind _decl.<x>` is the escape hatch. Companion to
`libs/engine/tests/test_store_reader.py::TestInternalKindExclusion` and
`libs/engine/tests/test_vertex_reader.py::TestInternalKindExclusion`, which
cover the engine-layer primitives this file's CLI-facing functions build on.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from atoms import Fact
from engine.sqlite_store import SqliteStore
from lang import parse_vertex_file
from lang.document import genesis_payload

_KDL = '''name "t"
store "{store}"
strict #true
loops {{
  decision {{ fold {{ items "by" "topic" }}
             search "message" }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


def _scaffold_and_absorb(tmp_path: Path) -> tuple[Path, Path]:
    """Real genesis via the absorb ceremony — mirrors `sl store absorb`."""
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_KDL.format(store=store))
    docs = genesis_payload(parse_vertex_file(vpath))["documents"]
    s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return vpath, store


def _append_decl_row(store: Path, *, kind: str, payload: dict, ts: float, row_id: str) -> None:
    """Hand-append a raw `_decl.*` row post-genesis (a receipt-style overlay,
    not another genesis — signature is irrelevant to these read-path tests).
    """
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (row_id, kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _emit_decision(store: Path, *, topic: str, message: str, ts: float) -> None:
    """Write a decision fact through SqliteStore (creates the schema on
    first use, so this also works against a not-yet-materialized store)."""
    s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    s.append(Fact.of("decision", "kyle", origin="", ts=ts, topic=topic, message=message))
    s.close()


class TestReadByteIdenticalAcrossAbsorb:
    """The exit criterion: `sl read project` renders byte-identical before
    and after `sl store absorb`."""

    def test_fold_state_unaffected_by_genesis(self, tmp_path):
        from loops.commands.fetch import fetch_fold

        store = tmp_path / "t.db"
        vpath = tmp_path / "t.vertex"
        vpath.write_text(_KDL.format(store=store))
        _emit_decision(store, topic="auth", message="JWT", ts=1000.0)

        before = fetch_fold(vpath)

        # Now absorb — a real genesis lands as a `_decl.genesis` row.
        docs = genesis_payload(parse_vertex_file(vpath))["documents"]
        s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
        s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
        s.close()

        after = fetch_fold(vpath)

        assert before.sections == after.sections
        assert before.unfolded == after.unfolded == {}


class TestLsKindsListingExcludes:
    def test_kinds_listing_excludes_decl_by_default(self, tmp_path):
        from loops.commands.vertices import _store_stats

        vpath, store = _scaffold_and_absorb(tmp_path)
        _emit_decision(store, topic="auth", message="JWT", ts=1000.0)

        stats = _store_stats(store)
        assert "decision" in {r["kind"] for r in stats["kind_stats"]}
        assert not any(r["kind"].startswith("_decl.") for r in stats["kind_stats"])

    def test_kinds_listing_include_internal_defeat(self, tmp_path):
        from loops.commands.vertices import _store_stats

        vpath, store = _scaffold_and_absorb(tmp_path)

        stats = _store_stats(store, include_internal=True)
        assert any(r["kind"] == "_decl.genesis" for r in stats["kind_stats"])

    def test_explicit_kind_descent_unaffected_regression(self, tmp_path):
        """`ls --kind _decl.genesis` already worked pre-S3 (fetch_kind_stat
        bypasses fact_kind_stats entirely) — regression guard, no S3 code
        change was needed here."""
        from loops.commands.ls import fetch_kind_stat

        vpath, store = _scaffold_and_absorb(tmp_path)

        result = fetch_kind_stat(str(vpath), "_decl.genesis")
        assert result.get("error") is None
        assert result["count"] == 1


class TestStoreCommandExcludes:
    def test_make_fetcher_excludes_decl_by_default(self, tmp_path):
        from loops.commands.store import make_fetcher

        vpath, store = _scaffold_and_absorb(tmp_path)
        _emit_decision(store, topic="auth", message="JWT", ts=1000.0)

        data = make_fetcher(store, zoom=0)()
        assert "decision" in data["facts"]["kinds"]
        assert not any(k.startswith("_decl.") for k in data["facts"]["kinds"])

    def test_make_fetcher_kind_defeat_narrows_to_one_entry(self, tmp_path):
        from loops.commands.store import make_fetcher

        vpath, store = _scaffold_and_absorb(tmp_path)
        _emit_decision(store, topic="auth", message="JWT", ts=1000.0)

        data = make_fetcher(store, zoom=0, kind="_decl.genesis")()
        assert set(data["facts"]["kinds"].keys()) == {"_decl.genesis"}


class TestMatchDoesNotSurfaceDeclPayloads:
    """`loops read <vertex> --match <text>` must not surface `_decl.*`
    payload content — verifies the FTS/substring paths are structurally
    safe (S1/S2 write-time reservation blocks a `.vertex` from declaring
    `search` on `_decl.*` today; nothing in S3 changes that, this is a
    regression guard, not a new fix)."""

    def test_distinctive_decl_payload_text_not_found(self, tmp_path):
        from loops.commands.fetch import fetch_fold
        from loops.surface import project, search

        vpath, store = _scaffold_and_absorb(tmp_path)
        _emit_decision(store, topic="auth", message="JWT over sessions", ts=1000.0)
        _append_decl_row(
            store,
            kind="_decl.receipt",
            payload={"note": "UNMISTAKABLE_DECL_SECRET_TOKEN"},
            ts=1100.0,
            row_id="F2",
        )

        surface = project(fetch_fold(vpath))
        hit = search(surface, "UNMISTAKABLE_DECL_SECRET_TOKEN", vertex_path=vpath)
        assert hit.rows == ()

        # Sanity: an ordinary declared-kind match DOES surface, proving the
        # search path itself works (the absence above isn't a broken query).
        ordinary_hit = search(surface, "JWT over sessions", vertex_path=vpath)
        assert len(ordinary_hit.rows) >= 1


class TestCliKindGateEscapeHatch:
    """The real CLI gate `--kind` goes through before `fetch_fold` ever runs:
    `_validate_kind_or_exit` (loops/commands/resolve.py) exits 2 for any
    kind the vertex doesn't declare — the vertex_fold-level raw fallback
    added in S3 is unreachable through `sl read`/`sl read --facts` without
    a matching carve-out here. This was NOT anticipated by the S3 brief
    (which describes the pre-fix behavior as "silently empty") — the real
    CLI behavior for an ordinary undeclared kind is already a loud, helpful
    exit 2, not silent-empty. Discovered by exercising `sl` directly, not
    from tracing alone."""

    def test_read_kind_gate_lets_internal_kind_through(self, tmp_path):
        from loops.main import main

        vpath, store = _scaffold_and_absorb(tmp_path)

        rc = main(["read", str(vpath), "--kind", "_decl.genesis", "--json"])
        assert rc == 0

    def test_read_kind_gate_still_rejects_ordinary_typo(self, tmp_path, capsys):
        import pytest
        from loops.main import main

        vpath, store = _scaffold_and_absorb(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            main(["read", str(vpath), "--kind", "decsion", "--plain"])
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "does not declare kind 'decsion'" in captured.err

    def test_facts_kind_gate_lets_internal_kind_through(self, tmp_path):
        """`stream.py` shares the same `_validate_kind_or_exit` chokepoint
        as `read` — the escape hatch must compose there too."""
        from loops.main import main

        vpath, store = _scaffold_and_absorb(tmp_path)

        rc = main(["read", str(vpath), "--facts", "--kind", "_decl.genesis", "--json"])
        assert rc == 0

