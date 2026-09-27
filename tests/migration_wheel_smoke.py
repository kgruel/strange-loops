"""Exercise the retained offline migration API from a clean installed root wheel.

Run with the installed interpreter outside the checkout. All data and keys are
synthetic; this is not an operator migration or live-publication command.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def _source(path: Path, source_format: str) -> None:
    rows = [
        {
            "id": f"01ARZ3NDEKTSV4RRFFQ69G5FA{index}",
            "kind": "concept",
            "ts": float(2 - index),  # receipt order is not event-time order
            "observer": "alice",
            "origin": "wheel-smoke",
            "payload": json.dumps({"text": f"legacy-{index}"}),
        }
        for index in range(2)
    ]
    if source_format == "jsonl":
        path.write_text(
            "".join(json.dumps({"t": "fact", **row}) + "\n" for row in rows),
            encoding="utf-8",
        )
        return
    connection = sqlite3.connect(path)
    try:
        connection.executescript("""
            CREATE TABLE facts (
                id TEXT PRIMARY KEY, kind TEXT, ts REAL, observer TEXT,
                origin TEXT, payload TEXT, signature TEXT
            );
            CREATE TABLE ticks (
                id TEXT PRIMARY KEY, name TEXT, ts REAL, since REAL,
                origin TEXT, payload TEXT, prev_hash TEXT, window_start TEXT,
                fact_cursor TEXT, window_hash TEXT, signature TEXT
            );
        """)
        connection.executemany(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
            "VALUES (:id, :kind, :ts, :observer, :origin, :payload)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def _exercise(root: Path, source_format: str) -> None:
    from custody.signing import ARRIVAL_DOMAIN
    from engine.arrival_contract import Full
    from engine.arrival_registry import BackendRegistry, descriptor_for
    from lang import parse_vertex_file
    from migrate import identity, run_migration, verify_migration_report
    from sign import ed25519

    root.mkdir()
    source = root / f"legacy.{source_format}"
    _source(source, source_format)
    original = source.read_bytes()
    pair = ed25519.load_or_generate(root / "synthetic-keys")
    vertex = root / "alice.vertex"
    vertex.write_text(
        f'''name "alice"
store "./{source.name}"
observers {{ alice {{ key "{pair.public_b64}"; }}; }}
loops {{ concept {{ fold {{ items "collect" 100; }}; }}; }}
''',
        encoding="utf-8",
    )

    def signer(observer: str, digest: str) -> str | None:
        if observer != "alice":
            return None
        return ed25519.sign(pair, digest.encode(), domain=ARRIVAL_DOMAIN)

    def verify(key: str, signature: str, digest: str) -> bool:
        return ed25519.verify(
            ed25519.public_key_from_b64(key),
            signature,
            digest.encode(),
            domain=ARRIVAL_DOMAIN,
        )

    outcome = run_migration(
        source,
        vertex,
        store_dir=root / "staged",
        signer=signer,
        transform_rule=identity(),
    )
    assert source.read_bytes() == original
    assert not outcome.exceptions.dropped_units
    assert not outcome.exceptions.keyless_declared_observers
    assert not outcome.exceptions.undeclared_row_observers
    assert verify_migration_report(
        outcome.report_path,
        pair.public_b64,
        verify=verify,
        target_path=outcome.target_path,
    )
    report = json.loads(outcome.report_path.read_text(encoding="utf-8"))["body"]
    assert report["equivalence_diff"] == {
        "matched": True,
        "source_rows": 2,
        "target_rows": 2,
        "mismatches": [],
    }
    descriptor = descriptor_for(parse_vertex_file(vertex), vertex)
    assert descriptor is not None
    assert descriptor.lineage == outcome.lineage
    assert Path(descriptor.location) == outcome.target_path
    ledger, _query = BackendRegistry.with_builtin_backends().open(descriptor)
    assert ledger.verify(Full(through=outcome.head)) == outcome.head

    # An exact explicit resume re-verifies the published candidate; it must not
    # rewrite the descriptor or append the historical rows a second time.
    descriptor_bytes = vertex.read_bytes()
    target_bytes = outcome.target_path.read_bytes()
    resumed = run_migration(
        source,
        vertex,
        store_dir=root / "staged",
        signer=signer,
        transform_rule=identity(),
        resume_target=outcome.target_path,
    )
    assert resumed.head == outcome.head
    assert vertex.read_bytes() == descriptor_bytes
    assert outcome.target_path.read_bytes() == target_bytes
    assert source.read_bytes() == original
    print(
        f"installed offline migration: {source_format}, two rows, zero drops, explicit resume"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(
        prefix="loops-migration-wheel-smoke-"
    ) as temporary:
        root = Path(temporary)
        for name in tuple(os.environ):
            if name in {
                "PYTHONPATH",
                "PYTHONHOME",
                "LOOPS_CLAUDE_HOOK_CONFIG",
            } or name.startswith("HOOK_"):
                os.environ.pop(name)
        for name in (
            "HOME",
            "LOOPS_HOME",
            "XDG_STATE_HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
        ):
            path = root / name.lower()
            path.mkdir()
            os.environ[name] = str(path)

        import migrate
        import sdk

        install_root = Path(sys.prefix).resolve()
        for module in (migrate, sdk):
            assert Path(module.__file__).resolve().is_relative_to(install_root)
        assert importlib.util.find_spec("loops") is None
        assert importlib.util.find_spec("painted") is None
        for source_format in ("jsonl", "sqlite"):
            _exercise(root / source_format, source_format)


if __name__ == "__main__":
    main()
