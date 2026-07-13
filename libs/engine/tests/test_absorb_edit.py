"""Edit-ceremony primitive + resolver round-trip (SPEC §9.2 S4).

``SqliteStore.absorb_edit`` appends the change rows for a re-absorb as ONE
atomic, signed, self-lineage-scoped transaction. The headline property is the
round-trip: ``absorb(edit(file))`` then the store resolver ≡ ``parse(edited)``.
Signing uses a fake callable (engine's contract is the callable, not Ed25519 —
same posture as test_absorb_genesis).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex
from lang.document import (
    DECL_KIND_DEFINED,
    DECL_KIND_RETIRED,
    Change,
    diff_documents,
    documents_to_vertex,
    vertex_to_documents,
)

from engine.declaration import resolve_declaration_documents
from engine.sqlite_store import (
    AmbiguousGenesis,
    NoGenesis,
    SqliteStore,
    UnsignableEdit,
)


def _signer(secret: str | None):
    def signer(observer: str, digest: str) -> str | None:
        if secret is None:
            return None
        return hashlib.sha256(f"{secret}:{observer}:{digest}".encode()).hexdigest()

    return signer


def _store(path: Path) -> SqliteStore[Fact]:
    return SqliteStore(path=path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)


def _genesis(store: SqliteStore, ast) -> str:
    docs = [d.as_json() for d in vertex_to_documents(ast)]
    return store.absorb_genesis(docs, observer="obs", fact_signer=_signer("k"))["lineage"]


BASE = 'name "x"\nstore "./x.db"\nloops {\n  a { fold { n "inc" } }\n  b { fold { n "inc" } }\n}\n'


class TestAbsorbEditPrimitive:
    def test_empty_changes_is_noop(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        before = s.total
        receipt = s.absorb_edit([], observer="obs", fact_signer=_signer("k"))
        assert receipt["defined"] == 0 and receipt["retired"] == 0
        assert s.total == before  # nothing written
        s.close()

    def test_defined_row_is_signed_and_lineage_scoped(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        lineage = _genesis(s, parse_vertex(BASE))
        ch = Change(
            kind=DECL_KIND_DEFINED,
            subject="a",
            payload={"folds": [], "order": 0},
            annotation="modified",
        )
        s.absorb_edit([ch], observer="obs", fact_signer=_signer("k"))
        s.close()

        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT payload, signature FROM facts WHERE kind=? ORDER BY rowid DESC LIMIT 1",
            (DECL_KIND_DEFINED,),
        ).fetchone()
        conn.close()
        payload, signature = row
        p = json.loads(payload)
        assert signature  # signed
        assert p["lineage"] == lineage  # self-lineage stamped
        assert p["subject"] == "a"
        assert p["change"] == "modified"
        assert p["payload"] == {"folds": [], "order": 0}

    def test_tombstone_row_has_no_payload_doc(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        ch = Change(kind=DECL_KIND_RETIRED, subject="b", payload=None, annotation="removed")
        r = s.absorb_edit([ch], observer="obs", fact_signer=_signer("k"))
        assert r["retired"] == 1 and r["defined"] == 0
        s.close()

        conn = sqlite3.connect(str(db))
        payload = conn.execute(
            "SELECT payload FROM facts WHERE kind=?", (DECL_KIND_RETIRED,)
        ).fetchone()[0]
        conn.close()
        p = json.loads(payload)
        assert p["subject"] == "b" and p["change"] == "removed"
        assert "payload" not in p  # a tombstone carries no document

    def test_no_genesis_refuses(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        ch = Change(kind=DECL_KIND_DEFINED, subject="a", payload={"order": 0}, annotation="added")
        with pytest.raises(NoGenesis):
            s.absorb_edit([ch], observer="obs", fact_signer=_signer("k"))
        s.close()

    def test_foreign_genesis_does_not_block_edit(self, tmp_path):
        # A merged-foreign genesis row is inert on a marked store: the edit
        # stamps the OWN lineage (from store_meta), not the foreign one.
        db = tmp_path / "x.db"
        s = _store(db)
        lineage = _genesis(s, parse_vertex(BASE))  # stamps own_lineage
        s.append(
            Fact(
                kind="_decl.genesis",
                ts=9.0,
                payload={"protocol": 1, "documents": []},
                observer="foreign",
            )
        )
        ch = Change(
            kind=DECL_KIND_DEFINED, subject="a", payload={"order": 0}, annotation="modified"
        )
        receipt = s.absorb_edit([ch], observer="obs", fact_signer=_signer("k"))
        assert receipt["lineage"] == lineage
        s.close()

    def test_ambiguous_genesis_refuses_when_unmarked(self, tmp_path):
        # Without the marker (pre-marker store), several genesis rows make
        # the self-lineage indeterminate — conservative refusal.
        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        s.append(
            Fact(
                kind="_decl.genesis",
                ts=9.0,
                payload={"protocol": 1, "documents": []},
                observer="foreign",
            )
        )
        s._conn.execute("DELETE FROM store_meta WHERE key = 'own_lineage'")
        s._conn.commit()
        ch = Change(
            kind=DECL_KIND_DEFINED, subject="a", payload={"order": 0}, annotation="modified"
        )
        with pytest.raises(AmbiguousGenesis):
            s.absorb_edit([ch], observer="obs", fact_signer=_signer("k"))
        s.close()

    def test_ceremony_shares_one_effective_ts(self, tmp_path):
        # All rows of one edit ceremony carry ONE ts, so a historical as_of
        # cursor can never land between them and observe a half-applied
        # ontology (e.g. a rename showing both old and new kinds).
        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        changes = [
            Change(kind=DECL_KIND_DEFINED, subject="c", payload={"order": 2}, annotation="added"),
            Change(kind=DECL_KIND_RETIRED, subject="b", payload=None, annotation="removed"),
        ]
        s.absorb_edit(changes, observer="obs", fact_signer=_signer("k"))
        s.close()
        conn = sqlite3.connect(str(db))
        ts_values = {
            r[0]
            for r in conn.execute(
                "SELECT ts FROM facts WHERE kind IN (?, ?)",
                (DECL_KIND_DEFINED, DECL_KIND_RETIRED),
            )
        }
        conn.close()
        assert len(ts_values) == 1

    def test_stale_expected_head_refuses(self, tmp_path):
        from engine.sqlite_store import StaleDeclarationHead

        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        head = s.declaration_head()
        assert head is not None
        # A concurrent edit lands after the head was captured...
        s.absorb_edit(
            [Change(kind=DECL_KIND_DEFINED, subject="a", payload={"order": 0},
                    annotation="modified")],
            observer="obs", fact_signer=_signer("k"),
        )
        # ...so applying a diff computed against the old head refuses.
        with pytest.raises(StaleDeclarationHead):
            s.absorb_edit(
                [Change(kind=DECL_KIND_DEFINED, subject="b", payload={"order": 1},
                        annotation="modified")],
                observer="obs", fact_signer=_signer("k"), expected_head=head,
            )
        # And the current head is accepted.
        s.absorb_edit(
            [Change(kind=DECL_KIND_DEFINED, subject="b", payload={"order": 1},
                    annotation="modified")],
            observer="obs", fact_signer=_signer("k"),
            expected_head=s.declaration_head(),
        )
        s.close()

    def test_non_vocabulary_kind_refuses(self, tmp_path):
        from engine.sqlite_store import ReservedKindViolation

        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        before = s.total
        for bad_kind in ("_decl.genesis", "_decl.merged", "decision"):
            ch = Change(kind=bad_kind, subject="x", payload={"order": 0}, annotation="added")
            with pytest.raises(ReservedKindViolation):
                s.absorb_edit([ch], observer="obs", fact_signer=_signer("k"))
        assert s.total == before  # nothing written
        s.close()

    def test_unsignable_rolls_back_whole_batch(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        before = s.total
        chs = [
            Change(
                kind=DECL_KIND_DEFINED, subject="a", payload={"order": 0}, annotation="modified"
            ),
            Change(
                kind=DECL_KIND_DEFINED, subject="b", payload={"order": 1}, annotation="modified"
            ),
        ]
        with pytest.raises(UnsignableEdit):
            s.absorb_edit(chs, observer="obs", fact_signer=_signer(None))
        assert s.total == before  # atomic: nothing written
        s.close()

    def test_partial_signing_failure_rolls_back(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        before = s.total
        calls = {"n": 0}

        def flaky(observer: str, digest: str) -> str | None:
            calls["n"] += 1
            return None if calls["n"] >= 2 else "sig"

        chs = [
            Change(
                kind=DECL_KIND_DEFINED, subject="a", payload={"order": 0}, annotation="modified"
            ),
            Change(
                kind=DECL_KIND_DEFINED, subject="b", payload={"order": 1}, annotation="modified"
            ),
        ]
        with pytest.raises(UnsignableEdit):
            s.absorb_edit(chs, observer="obs", fact_signer=flaky)
        assert s.total == before  # the first (signed) row rolled back with the batch
        s.close()


class TestEditRoundTrip:
    """absorb(edit(file)) then resolver ≡ parse(edited file); re-absorb is a no-op."""

    def _reabsorb(self, db: Path, s: SqliteStore, edited_ast):
        head = resolve_declaration_documents(db)
        assert isinstance(head, list)
        changes = diff_documents(head, vertex_to_documents(edited_ast))
        s.absorb_edit(changes, observer="obs", fact_signer=_signer("k"))
        return changes

    def test_add_kind_roundtrip_and_idempotent(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        a = parse_vertex(BASE)
        _genesis(s, a)

        b = parse_vertex(
            'name "x"\nstore "./x.db"\nloops {\n  a { fold { n "inc" } }\n'
            '  b { fold { n "inc" } }\n  c { fold { n "latest" } }\n}\n'
        )
        changes = self._reabsorb(db, s, b)
        assert any(c.subject == "c" and c.annotation == "added" for c in changes)

        # Resolver reflects the edit ≡ parse(edited file) (residence reattached).
        head = resolve_declaration_documents(db)
        projected = documents_to_vertex(head, path=b.path, store=b.store)
        assert projected == b

        # Re-absorbing the unchanged file emits nothing (idempotence).
        before = s.total
        again = self._reabsorb(db, s, b)
        assert again == []
        assert s.total == before
        s.close()

    def test_remove_kind_roundtrip(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        a = parse_vertex(BASE)
        _genesis(s, a)

        b = parse_vertex('name "x"\nstore "./x.db"\nloops {\n  a { fold { n "inc" } }\n}\n')
        changes = self._reabsorb(db, s, b)
        assert any(c.kind == DECL_KIND_RETIRED and c.subject == "b" for c in changes)

        head = resolve_declaration_documents(db)
        assert isinstance(head, list)
        assert not any(d["kind"] == DECL_KIND_DEFINED and d["subject"] == "b" for d in head)
        projected = documents_to_vertex(head, path=b.path, store=b.store)
        assert projected == b
        s.close()

    def test_modify_then_modify_again(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        a = parse_vertex(BASE)
        _genesis(s, a)

        b = parse_vertex(
            'name "x"\nstore "./x.db"\nloops {\n  a { fold { n "latest" } }\n'
            '  b { fold { n "inc" } }\n}\n'
        )
        self._reabsorb(db, s, b)
        head = resolve_declaration_documents(db)
        assert documents_to_vertex(head, path=b.path, store=b.store) == b

        c = parse_vertex(
            'name "x"\nstore "./x.db"\nloops {\n  a { fold { n "latest" } }\n'
            '  b { fold { n "latest" } }\n}\n'
        )
        self._reabsorb(db, s, c)
        head = resolve_declaration_documents(db)
        assert documents_to_vertex(head, path=c.path, store=c.store) == c
        s.close()


class TestSingletonEdits:
    def test_vertex_and_lens_defined_are_editable(self, tmp_path):
        # Flipping strict / editing a lens produces _decl.vertex-defined /
        # _decl.lens-defined changes — the allowlist must admit the two
        # singletons or legitimate edits fail (re-review #5).
        from lang.document import DECL_LENS_DEFINED, DECL_VERTEX_DEFINED

        db = tmp_path / "x.db"
        s = _store(db)
        _genesis(s, parse_vertex(BASE))
        changes = [
            Change(kind=DECL_VERTEX_DEFINED, subject="x",
                   payload={"name": "x", "strict": True}, annotation="modified"),
            Change(kind=DECL_LENS_DEFINED, subject="x",
                   payload={"order": 9}, annotation="modified"),
        ]
        receipt = s.absorb_edit(changes, observer="obs", fact_signer=_signer("k"))
        assert receipt["defined"] == 2
        s.close()
