"""Provenance script for ``golden-ceremonies.jsonl`` — NOT a test.

Run once to (re)generate the positive golden log; ids and timestamps are
minted live, so regeneration produces a byte-different but shape-identical
log. The committed fixture is the cross-language contract the Go conformance
oracle (thread:loops-go-conformance-oracle) consumes; tests read the
committed bytes, never regenerate.

    uv run --package engine python libs/engine/tests/fixtures/jsonl/generate_golden.py

Shape (design:architecture/jsonl-declaration-ceremony-encoding):
genesis line, ordinary fact lines, a 2-row and a 3-row edit batch, and a
sealing tick — audit_deep passes over the result.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from atoms import Fact
from lang import parse_vertex
from lang.document import diff_documents, vertex_to_documents

from engine.declaration import resolve_declaration_documents
from engine.jsonl_store import JsonlStore
from engine.residence import log_path_for
from engine.tick import Tick

HERE = Path(__file__).parent
TARGET = HERE / "golden-ceremonies.jsonl"

BASE = (
    'name "x"\nstore "./x.jsonl"\nloops {\n'
    '  a { fold { n "inc" } }\n  b { fold { n "inc" } }\n}\n'
)
EDIT_TWO = (
    'name "x"\nstore "./x.jsonl"\nloops {\n'
    '  a { fold { n "latest" } }\n  b { fold { n "latest" } }\n}\n'
)
EDIT_THREE = (
    'name "x"\nstore "./x.jsonl"\nloops {\n'
    '  a { fold { n "latest" } }\n  c { fold { n "inc" } }\n'
    '  d { fold { n "inc" } }\n}\n'
)


def _fact_signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"golden:{observer}:{digest}".encode()).hexdigest()


def _tick_signer(digest: str) -> str:
    return hashlib.sha256(f"golden-tick:{digest}".encode()).hexdigest()


def _edit(store: JsonlStore, text: str, expect: int) -> None:
    head = resolve_declaration_documents(store._path)
    changes = diff_documents(head, vertex_to_documents(parse_vertex(text)))
    assert len(changes) == expect, (expect, [c.kind for c in changes])
    store.absorb_edit(changes, observer="golden", fact_signer=_fact_signer)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    store: JsonlStore = JsonlStore(
        path=tmp / "golden.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        tick_signer=_tick_signer,
    )
    docs = [d.as_json() for d in vertex_to_documents(parse_vertex(BASE))]
    store.absorb_genesis(docs, observer="golden", fact_signer=_fact_signer)
    store.append(Fact.of("note", "golden", message="an ordinary fact"))
    store.append(Fact.of("note", "golden", message="another ordinary fact"))
    _edit(store, EDIT_TWO, 2)  # 2-row batch
    _edit(store, EDIT_THREE, 3)  # 3-row batch (define c, d; retire b... shape-asserted)
    store.append_tick(
        Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1}, origin="golden")
    )
    store.close()
    shutil.copyfile(log_path_for(tmp / "golden.db"), TARGET)
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
