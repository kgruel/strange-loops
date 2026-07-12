"""Emit-path declaration checks follow the store, not the file (SPEC §9.5 S2).

The app-layer half of the honest test: once a store's lineage is opened, the
emit path's strict resolution (:func:`_resolve_strict`) and kind/fold-key
classification (:func:`classify_emit_status`) read the store's canonical
declaration — mutating the ``.vertex`` file is inert.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from atoms import Fact
from engine.sqlite_store import SqliteStore
from lang import parse_vertex_file
from lang.document import genesis_payload

from loops.commands.emit import _resolve_strict
from loops.commands.resolve import classify_emit_status


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


_KDL = '''name "t"
store "{store}"
strict #true
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _scaffold_and_absorb(tmp_path: Path) -> Path:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_KDL.format(store=store))
    docs = genesis_payload(parse_vertex_file(vpath))["documents"]
    s = SqliteStore(path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return vpath


def test_resolve_strict_follows_store_after_file_flip(tmp_path):
    vpath = _scaffold_and_absorb(tmp_path)
    # File flips strict off — the store still says strict.
    vpath.write_text(vpath.read_text().replace("strict #true", "strict #false"))
    args = argparse.Namespace(strict=False)
    effective, declared = _resolve_strict(args, vpath)
    assert declared is True  # from the store's declaration, not the file
    assert effective is True


def test_classify_emit_status_follows_store_after_kind_rename(tmp_path):
    vpath = _scaffold_and_absorb(tmp_path)
    # File renames the only declared kind — the store still declares "decision".
    vpath.write_text(vpath.read_text().replace("decision {", "renamed {"))

    declared = classify_emit_status(vpath, "decision", {"topic": "a"})
    assert declared.kind_declared is True  # store canonical
    assert declared.fold_key_field == "topic"

    undeclared = classify_emit_status(vpath, "renamed", {})
    assert undeclared.kind_declared is False  # the file's rename is inert


def test_pre_genesis_file_flip_takes_effect(tmp_path):
    # Without absorb, the file is authoritative — flipping strict is honored.
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_KDL.format(store=store))
    args = argparse.Namespace(strict=False)
    assert _resolve_strict(args, vpath)[1] is True
    vpath.write_text(vpath.read_text().replace("strict #true", "strict #false"))
    assert _resolve_strict(args, vpath)[1] is False
