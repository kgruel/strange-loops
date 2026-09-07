"""Public SDK boundary checks for the offline migration sidecar.

These tests intentionally live in the repository integration suite: the SDK
must remain installable without making the quarantined ``migrate`` package a
runtime or test dependency.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.arrival_contract import Full
from engine.arrival_registry import BackendRegistry, descriptor_for
from engine.credentials import WriteCredentials
from lang import parse_vertex_file
from migrate.sidecar import run_migration, verify_migration_report
from sdk import (
    SdkError,
    edit_declaration,
    emit_fact,
    inspect_declaration,
    read_fact_by_id,
    read_facts,
    read_summary,
    read_ticks,
    resolve_arrival_target,
    sync_target,
    verify_target,
)
from sign import ed25519


@pytest.fixture(autouse=True)
def _isolate_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep custody and projection state out of the user's environment."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops"))


class _StaticCredentials:
    def __init__(self, pair) -> None:
        self.pair = pair

    def for_write(self, _vertex: Path) -> WriteCredentials:
        return WriteCredentials(
            fact_signer=lambda _observer, digest: ed25519.sign(
                self.pair, digest.encode(), domain=FACT_DOMAIN
            ),
            arrival_signer=lambda _observer, digest: ed25519.sign(
                self.pair, digest.encode(), domain=ARRIVAL_DOMAIN
            ),
        )


def _signer(pair):
    return lambda _observer, digest: ed25519.sign(
        pair, digest.encode(), domain=ARRIVAL_DOMAIN
    )


def _verifier(key: str, signature: str, digest: str) -> bool:
    try:
        public = ed25519.public_key_from_b64(key)
    except ValueError:
        return False
    return ed25519.verify(public, signature, digest.encode(), domain=ARRIVAL_DOMAIN)


def _write_vertex(path: Path, public_key: str, source_name: str) -> None:
    path.write_text(
        f'''name "alice"
store "./data/{source_name}"

observers {{
  alice {{
    key "{public_key}"
  }}
}}

loops {{
  concept {{ fold {{ items "collect" 100 }} }}
}}
''',
        encoding="utf-8",
    )


def _write_jsonl(path: Path) -> None:
    rows = [
        {
            "t": "fact",
            "id": "01ARZ3NDEKTSV4RRFFQ69G5FA0",
            "kind": "concept",
            "ts": 1000.0,
            "observer": "alice",
            "origin": "legacy",
            "payload": '{"text":"migrated"}',
        },
        {
            "t": "tick",
            "id": "01ARZ3NDEKTSV4RRFFQ69G5FT1",
            "name": "heartbeat",
            "ts": 1001.0,
            "since": 1000.0,
            "origin": "system",
            "payload": '{"seq":1}',
            "prev_hash": None,
            "window_start": None,
            "fact_cursor": None,
            "window_hash": None,
        },
    ]
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))


def _write_sqlite(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE facts (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, ts REAL NOT NULL,
                observer TEXT NOT NULL, origin TEXT NOT NULL,
                payload TEXT NOT NULL, signature TEXT
            );
            CREATE TABLE ticks (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, ts REAL NOT NULL,
                since REAL, origin TEXT NOT NULL, payload TEXT NOT NULL,
                prev_hash TEXT, window_start TEXT, fact_cursor TEXT,
                window_hash TEXT, signature TEXT
            );
            INSERT INTO facts VALUES
              ('01ARZ3NDEKTSV4RRFFQ69G5FA0', 'concept', 1000.0,
               'alice', 'legacy', '{"text":"migrated"}', NULL);
            INSERT INTO ticks VALUES
              ('01ARZ3NDEKTSV4RRFFQ69G5FT1', 'heartbeat', 1001.0, 1000.0,
               'system', '{"seq":1}', NULL, NULL, NULL, NULL, NULL);
            """
        )


@pytest.mark.parametrize("source_format", ["jsonl", "sqlite"])
def test_migrated_descriptor_reaches_public_sdk_boundary(
    tmp_path: Path, source_format: str
) -> None:
    """Migration output is structurally readable, but lacks adopted declaration history."""
    data = tmp_path / "data"
    data.mkdir()
    source = data / ("legacy.jsonl" if source_format == "jsonl" else "legacy.sqlite")
    if source_format == "jsonl":
        _write_jsonl(source)
    else:
        _write_sqlite(source)
    source_before = source.read_bytes()

    pair = ed25519.load_or_generate(tmp_path / "keys" / "alice")
    vertex = tmp_path / "alice.vertex"
    _write_vertex(vertex, pair.public_b64, source.name)
    outcome = run_migration(source, vertex, store_dir=data, signer=_signer(pair))

    # The migration's low-level records and report remain independently verifiable.
    assert verify_migration_report(
        outcome.report_path,
        pair.public_b64,
        verify=_verifier,
        target_path=outcome.target_path,
    )
    descriptor = descriptor_for(parse_vertex_file(vertex), vertex)
    assert descriptor is not None
    assert descriptor.backend == "file"
    assert descriptor.lineage == outcome.lineage
    assert descriptor.role is not None and descriptor.role.value == "authority"
    target_bytes_before_sync = outcome.target_path.read_bytes()
    registry = BackendRegistry.with_builtin_backends()
    ledger, query = registry.open(descriptor)
    try:
        head = ledger.verify(Full(through=outcome.head))
        records = list(ledger.scan(through=head))
        assert head == outcome.head
        assert [record["k"] for record in records] == ["genesis", "fact", "tick"]
        genesis, fact, tick = records
        assert genesis["v"] == 1
        assert genesis["lin"] == outcome.lineage
        assert genesis["ord"] == 0
        assert genesis["prev"] is None
        assert genesis["at"] == 0.0
        assert genesis["observer"] == "alice"
        assert genesis["origin"] == ""
        assert genesis["body"] == {
            "protocol": 1,
            "lineage": outcome.lineage,
            "key": pair.public_b64,
        }
        assert isinstance(genesis["sig"], str) and genesis["sig"]
        assert isinstance(genesis["rh"], str) and len(genesis["rh"]) == 64
        assert fact == {
            "v": 1,
            "lin": outcome.lineage,
            "ord": 1,
            "prev": genesis["rh"],
            "at": 1000.0,
            "k": "fact",
            "observer": "alice",
            "origin": "legacy",
            "body": {
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FA0",
                "kind": "concept",
                "ts": 1000.0,
                "observer": "alice",
                "origin": "legacy",
                "payload": '{"text":"migrated"}',
            },
            "rh": fact["rh"],
        }
        assert tick == {
            "v": 1,
            "lin": outcome.lineage,
            "ord": 2,
            "prev": fact["rh"],
            "at": 1001.0,
            "k": "tick",
            "observer": "alice",
            "origin": "system",
            "body": {
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FT1",
                "name": "heartbeat",
                "ts": 1001.0,
                "since": 1000.0,
                "origin": "system",
                "payload": '{"seq":1}',
                "prev_hash": None,
                "window_start": None,
                "fact_cursor": None,
                "window_hash": None,
            },
            "rh": tick["rh"],
        }
        assert "sig" not in fact
        assert "sig" not in tick
    finally:
        query.close()
        ledger.close()

    resolved = resolve_arrival_target(vertex)
    assert resolved.store.lineage == outcome.lineage
    assert resolved.store.role == "authority"
    verified = verify_target(vertex)
    assert verified.store == resolved.store
    assert verified.captured_head == outcome.head
    assert verified.verified_through == outcome.head
    synced = sync_target(vertex)
    assert synced.store == resolved.store
    assert synced.captured_head == outcome.head
    assert synced.target == outcome.head
    assert synced.projected_before is None
    assert synced.projected_after == outcome.head
    assert synced.agreement is True
    assert outcome.target_path.read_bytes() == target_bytes_before_sync

    # Reads and writes must not substitute the current locator for an absent
    # adopted declaration. These operations may create/update a derived index,
    # so compare the authority log and descriptor around all refusal checks.
    ledger_before_refusals = outcome.target_path.read_bytes()
    descriptor_before_refusals = vertex.read_bytes()
    operations = [
        lambda: read_summary(vertex),
        lambda: read_facts(vertex),
        lambda: read_fact_by_id(vertex, "01ARZ3NDEKTSV4RRFFQ69G5FA0"),
        lambda: read_ticks(vertex),
        lambda: inspect_declaration(vertex),
        lambda: edit_declaration(
            vertex,
            vertex.read_text(encoding="utf-8"),
            observer="alice",
            credentials=_StaticCredentials(pair),
        ),
        lambda: emit_fact(
            vertex,
            "concept",
            {"text": "must refuse"},
            observer="alice",
            credentials=_StaticCredentials(pair),
        ),
    ]
    for operation in operations:
        with pytest.raises(
            SdkError, match="adopted declaration|historized(?: effective)? declarations?"
        ):
            operation()
    assert outcome.target_path.read_bytes() == ledger_before_refusals
    assert vertex.read_bytes() == descriptor_before_refusals
    assert source.read_bytes() == source_before
