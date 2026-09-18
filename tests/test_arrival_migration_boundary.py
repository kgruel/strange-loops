"""Public SDK boundary checks for the offline migration sidecar.

These tests intentionally live in the repository integration suite: the SDK
must remain installable without making the quarantined ``migrate`` package a
runtime or test dependency.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.arrival_contract import Full
from engine.arrival_registry import BackendRegistry, descriptor_for
from engine.credentials import (
    CredentialPurpose,
    CredentialRequest,
    SigningDomain,
    WriteCredentials,
)
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


@pytest.mark.parametrize("source_format", ["jsonl", "sqlite"])
def test_copied_migration_adoption_and_mapped_write(
    tmp_path: Path, source_format: str
) -> None:
    """Rehearse the explicit source-copy -> migration -> adoption boundary.

    All originals here are synthetic. SQLite is copied through its backup API;
    the quiescent JSONL fixture is copied byte-for-byte. Report verification is
    deliberately performed at S, before adoption advances the ledger.
    """
    from sdk import MappedCredentialProvider, adopt_arrival, export_target, read_state

    original = tmp_path / "original"
    (original / "data").mkdir(parents=True)
    source = original / "data" / f"legacy.{source_format}"
    (_write_jsonl if source_format == "jsonl" else _write_sqlite)(source)
    provider = MappedCredentialProvider(
        tmp_path / "rehearsal-credentials",
        namespace="adoption-rehearsal",
        receipt_observer="alice",
    )
    binding = provider.create_binding("alice", token="rehearsal-alice")
    original_vertex = original / "alice.vertex"
    _write_vertex(original_vertex, binding.public_key, source.name)
    original_bytes = source.read_bytes()
    reviewed_bytes = original_vertex.read_bytes()
    reviewed_hash = hashlib.sha256(reviewed_bytes).hexdigest()

    rehearsal = tmp_path / "rehearsal"
    (rehearsal / "data").mkdir(parents=True)
    copied_source = rehearsal / "data" / source.name
    if source_format == "sqlite":
        with sqlite3.connect(source) as src, sqlite3.connect(copied_source) as dst:
            src.backup(dst)
    else:
        shutil.copyfile(source, copied_source)
    vertex = rehearsal / "alice.vertex"
    vertex.write_bytes(reviewed_bytes)
    copied_bytes = copied_source.read_bytes()
    registry_binding = provider.resolve(CredentialRequest(
        provider.namespace, "alice", SigningDomain.ARRIVAL,
        CredentialPurpose.INITIALIZATION,
    ))
    assert registry_binding is not None

    def migration_signer(observer: str, digest: str) -> str:
        assert observer == "alice"
        return registry_binding.sign_digest(digest)

    migrated = run_migration(
        copied_source, vertex, store_dir=rehearsal / "data", signer=migration_signer,
    )
    assert verify_migration_report(
        migrated.report_path, binding.public_key, verify=_verifier,
        target_path=migrated.target_path,
    )
    report_bytes = migrated.report_path.read_bytes()
    # External provenance stays outside the declaration's protocol payload.
    evidence = {
        "reviewed_sha256": reviewed_hash,
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report_verified_at": migrated.head.record_hash,
    }
    prefix = migrated.target_path.read_bytes()
    descriptor = resolve_arrival_target(vertex).store
    published_text = vertex.read_text(encoding="utf-8")
    sync_target(vertex)
    with pytest.raises(SdkError, match="adopted declaration|historized"):
        read_summary(vertex)

    # A caller cannot silently pass revised bytes under the reviewed hash.
    with pytest.raises(SdkError):
        adopt_arrival(
            vertex, selected_head=migrated.head,
            reviewed_text=reviewed_bytes.decode() + "\n// unreviewed\n",
            reviewed_sha256=reviewed_hash, declaration_text=published_text,
            observer="alice", credentials=provider,
        )
    assert migrated.target_path.read_bytes() == prefix

    adopted = adopt_arrival(
        vertex, selected_head=migrated.head, reviewed_text=reviewed_bytes.decode(),
        reviewed_sha256=reviewed_hash, declaration_text=published_text,
        observer="alice", credentials=provider,
    )
    assert adopted.commit is not None
    assert adopted.commit.before == migrated.head
    assert adopted.head == adopted.commit.after
    assert adopted.head.ordinal == migrated.head.ordinal + 1
    assert adopted.fact_id == migrated.lineage
    assert resolve_arrival_target(vertex).store == descriptor
    after_adoption = migrated.target_path.read_bytes()
    assert after_adoption.startswith(prefix)
    assert len(after_adoption.splitlines()) == len(prefix.splitlines()) + 1
    assert migrated.report_path.read_bytes() == report_bytes
    assert hashlib.sha256(report_bytes).hexdigest() == evidence["report_sha256"]

    for result in (
        inspect_declaration(vertex), read_summary(vertex), read_facts(vertex),
        read_ticks(vertex), read_state(vertex),
    ):
        assert result.basis is not None
        assert result.basis.captured_head == adopted.head
        json.dumps(result.as_dict(), allow_nan=False)
    facts = read_facts(vertex, include_internal=True, order="oldest", limit=100)
    anchors = [row for row in facts.items if row["kind"] == "_decl.genesis"]
    assert len(anchors) == 1 and anchors[0]["id"] == migrated.lineage
    original_fact = read_fact_by_id(vertex, "01ARZ3NDEKTSV4RRFFQ69G5FA0")
    assert original_fact.fact is not None

    receipt = emit_fact(
        vertex, "concept", {"text": "after adoption"}, observer="alice",
        id_override="adoption-rehearsal-followup", credentials=provider,
    )
    assert receipt.stored and receipt.signed and receipt.witnessed
    assert receipt.commit is not None and receipt.commit.before == adopted.head
    final = verify_target(vertex)
    assert final.verified_through == receipt.commit.after
    exported = rehearsal / "captured.jsonl"
    export = export_target(vertex, exported)
    assert export.head == receipt.commit.after
    assert exported.read_bytes() == migrated.target_path.read_bytes()
    for result in (adopted, receipt, final, export):
        json.dumps(result.as_dict(), allow_nan=False)
    assert source.read_bytes() == original_bytes
    assert original_vertex.read_bytes() == reviewed_bytes
    assert copied_source.read_bytes() == copied_bytes


@pytest.mark.parametrize("stop_phase", ["after-intent", "after-append"])
def test_adoption_process_exit_recovers_reserved_draft_without_credentials(
    tmp_path: Path, stop_phase: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit a real child process at a durable boundary, then reconcile once."""
    from sdk import MappedCredentialProvider, recover_arrival_adoption

    data = tmp_path / "data"
    data.mkdir()
    source = data / "legacy.jsonl"
    _write_jsonl(source)
    provider = MappedCredentialProvider(
        tmp_path / "credentials", namespace="interrupted-adoption", receipt_observer="alice",
    )
    created = provider.create_binding("alice", token="create-alice")
    vertex = tmp_path / "alice.vertex"
    _write_vertex(vertex, created.public_key, source.name)
    reviewed = vertex.read_text()
    signed = provider.resolve(CredentialRequest(
        provider.namespace, "alice", SigningDomain.ARRIVAL, CredentialPurpose.INITIALIZATION,
    ))
    assert signed is not None
    migrated = run_migration(
        source, vertex, store_dir=data, signer=lambda _observer, digest: signed.sign_digest(digest),
    )
    prefix = migrated.target_path.read_bytes()
    script = r'''
import hashlib, json, os, sys
from pathlib import Path
import engine.arrival_adoption as engine_adoption
from engine.arrival_contract import Head
from sdk import MappedCredentialProvider, adopt_arrival
target, root, namespace, reviewed, head_json, stop = sys.argv[1:]
original_apply = engine_adoption.apply_arrival_adoption
def stop_at(phase):
    if phase == stop:
        os._exit(86)
def interrupted(registry, plan):
    return original_apply(registry, plan, failure_hook=stop_at)
engine_adoption.apply_arrival_adoption = interrupted
provider = MappedCredentialProvider(Path(root), namespace=namespace, receipt_observer="alice")
adopt_arrival(
    target, selected_head=Head(**json.loads(head_json)), reviewed_text=reviewed,
    reviewed_sha256=hashlib.sha256(reviewed.encode()).hexdigest(),
    declaration_text=Path(target).read_text(), observer="alice", credentials=provider,
)
raise AssertionError("durable stop phase was not reached")
'''
    run = subprocess.run(
        [sys.executable, "-c", script, str(vertex), str(provider.root), provider.namespace,
         reviewed, json.dumps({"lineage": migrated.head.lineage,
                               "ordinal": migrated.head.ordinal,
                               "record_hash": migrated.head.record_hash}), stop_phase],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert run.returncode == 86, run.stderr
    intent = vertex.with_name(vertex.name + ".arrival-adopt.intent")
    assert intent.exists()
    reserved = json.loads(intent.read_text())["drafts"][0]
    before_recovery = migrated.target_path.read_bytes()
    expected_extra = 1 if stop_phase == "after-append" else 0
    assert len(before_recovery.splitlines()) == len(prefix.splitlines()) + expected_extra

    # Recovery cannot depend on the original private-key location or provider.
    provider.root.rename(tmp_path / "credentials-offline")
    def refuse_credentials(*_args, **_kwargs):
        raise AssertionError("recovery resolved signing credentials")
    monkeypatch.setattr(MappedCredentialProvider, "for_write", refuse_credentials)
    monkeypatch.setattr(MappedCredentialProvider, "resolve", refuse_credentials)
    authentic_intent = intent.read_bytes()
    for mutation in ("binding", "inner-signature", "outer-signature"):
        changed = json.loads(authentic_intent)
        if mutation == "binding":
            changed["bindings"][0]["public_key"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        elif mutation == "inner-signature":
            changed["drafts"][0]["body"]["signature"] = "bogus"
        else:
            changed["drafts"][0]["signature"] = "bogus"
        # Keep the duplicate draft representations consistent: consistency
        # alone must not stand in for signature and captured-key verification.
        changed["exact_drafts"] = json.dumps(
            changed["drafts"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        intent.write_text(json.dumps(changed))
        with pytest.raises(SdkError):
            recover_arrival_adoption(intent)
        assert migrated.target_path.read_bytes() == before_recovery
        assert intent.exists()
    intent.write_bytes(authentic_intent)
    recovered = recover_arrival_adoption(intent)
    assert recovered.head is not None
    assert recovered.head.ordinal == migrated.head.ordinal + 1
    assert recovered.captured_head == migrated.head
    assert recovered.commit is not None
    assert recovered.commit.before == migrated.head
    assert recovered.commit.after == recovered.head
    final = migrated.target_path.read_bytes()
    assert final.startswith(prefix)
    assert len(final.splitlines()) == len(prefix.splitlines()) + 1
    record = json.loads(final.splitlines()[-1])
    assert record["body"] == reserved["body"]
    assert record["sig"] == reserved["signature"]
    assert not intent.exists()
    assert read_summary(vertex).basis.captured_head == recovered.head
    with pytest.raises(SdkError):
        recover_arrival_adoption(intent)
    assert migrated.target_path.read_bytes() == final


def _mapped_migration_fixture(tmp_path: Path):
    """A real signed migration for adoption's SDK boundary fault tests."""
    from sdk import MappedCredentialProvider

    data = tmp_path / "data"
    data.mkdir()
    source = data / "legacy.jsonl"
    _write_jsonl(source)
    provider = MappedCredentialProvider(
        tmp_path / "credentials", namespace="adoption-faults", receipt_observer="alice",
    )
    binding = provider.create_binding("alice", token="create-alice")
    vertex = tmp_path / "alice.vertex"
    _write_vertex(vertex, binding.public_key, source.name)
    reviewed = vertex.read_text()
    signer = provider.resolve(CredentialRequest(
        provider.namespace, "alice", SigningDomain.ARRIVAL, CredentialPurpose.INITIALIZATION,
    ))
    assert signer is not None
    migration = run_migration(
        source, vertex, store_dir=data, signer=lambda _observer, digest: signer.sign_digest(digest),
    )
    return provider, binding, vertex, reviewed, migration


@pytest.mark.parametrize("broken_domain", [SigningDomain.FACT, SigningDomain.ARRIVAL])
def test_adoption_independently_verifies_custom_mapped_signatures(
    tmp_path: Path, broken_domain: SigningDomain,
) -> None:
    from engine.credentials import ResolvedCredential
    from sdk import adopt_arrival

    provider, _binding, vertex, reviewed, migration = _mapped_migration_fixture(tmp_path)
    before = migration.target_path.read_bytes()

    def resolve(request):
        genuine = provider.resolve(request)
        assert genuine is not None
        if request.domain is broken_domain:
            return ResolvedCredential(genuine.evidence, lambda _digest: "junk-signature")
        return genuine

    untrustworthy = WriteCredentials(
        binding_namespace=provider.namespace,
        binding_resolver=resolve,
        signature_verifier=lambda *_args: True,
    )
    with pytest.raises(SdkError, match="sign|verif"):
        adopt_arrival(
            vertex, selected_head=migration.head, reviewed_text=reviewed,
            reviewed_sha256=hashlib.sha256(reviewed.encode()).hexdigest(),
            declaration_text=vertex.read_text(), observer="alice", credentials=untrustworthy,
        )
    assert migration.target_path.read_bytes() == before
    assert not vertex.with_name(vertex.name + ".arrival-adopt.intent").exists()


def test_adoption_verifies_actual_binding_when_observer_has_two_valid_keys(tmp_path: Path) -> None:
    from engine.admission import fact_commitment_hash
    from engine.arrival import content_commitment
    from engine.arrival_contract import RecordDraft
    from sdk import MappedCredentialProvider, adopt_arrival

    provider, original, vertex, reviewed, migration = _mapped_migration_fixture(tmp_path)
    selected = MappedCredentialProvider(
        tmp_path / "second-credentials", namespace="selected-key", receipt_observer="alice",
    )
    second = selected.create_binding("alice", token="create-second-key")
    signer = provider.resolve(CredentialRequest(
        provider.namespace, "alice", SigningDomain.ARRIVAL, CredentialPurpose.KEY_INTRODUCTION,
    ))
    assert signer is not None
    body = {"observer": "alice", "key": second.public_key}
    digest = content_commitment("key", 1002.0, "alice", "", body)
    registry = BackendRegistry.with_builtin_backends()
    descriptor = descriptor_for(parse_vertex_file(vertex), vertex)
    assert descriptor is not None
    ledger, query = registry.open(descriptor)
    try:
        introduction = ledger.append(migration.head, (
            RecordDraft("key", 1002.0, "alice", "", body, signer.sign_digest(digest)),
        ))
    finally:
        query.close()
        ledger.close()
    result = adopt_arrival(
        vertex, selected_head=introduction.after, reviewed_text=reviewed,
        reviewed_sha256=hashlib.sha256(reviewed.encode()).hexdigest(),
        declaration_text=vertex.read_text(), observer="alice", credentials=selected,
    )
    assert result.commit is not None and result.commit.before == introduction.after
    record = result.commit.records[0]
    fact = record["body"]
    inner = fact_commitment_hash(
        fact["kind"], fact["ts"], fact["observer"], fact["origin"], fact["payload"],
    )
    outer = content_commitment(
        record["k"], record["at"], record["observer"], record["origin"], fact,
    )
    for domain, signature, commitment in (
        (SigningDomain.FACT, fact["signature"], inner),
        (SigningDomain.ARRIVAL, record["sig"], outer),
    ):
        assert selected.verify(domain, second.public_key, signature, commitment)
        assert not provider.verify(domain, original.public_key, signature, commitment)
    assert read_summary(vertex).basis.captured_head == result.head


@pytest.mark.parametrize(
    "maintenance", ["missing", "no-catch-up", "rebuild-only", "catch-up-and-rebuild"],
)
def test_adoption_refuses_unusable_maintenance_before_resolving_credentials(
    tmp_path: Path, maintenance: str,
) -> None:
    from engine.arrival_maintenance import MaintenanceCapabilities
    from engine.arrival_registry import _file_binding, _open_file_backend
    from sdk import adopt_arrival

    provider, _binding, vertex, reviewed, migration = _mapped_migration_fixture(tmp_path)
    before = migration.target_path.read_bytes()
    calls = []

    class UnsupportedMaintenance:
        def capabilities(self):
            return MaintenanceCapabilities(
                catch_up=maintenance == "catch-up-and-rebuild",
                rebuild=maintenance in {"rebuild-only", "catch-up-and-rebuild"},
            )

        def catch_up(self, _head):
            calls.append("catch-up")
            raise AssertionError("preflight must not mutate projections")

        def close(self):
            calls.append("closed")

    registry = BackendRegistry()
    registry.register(
        "file", _open_file_backend, binding_provider=_file_binding,
        maintenance_opener=None if maintenance == "missing" else lambda _d: UnsupportedMaintenance(),
    )

    def resolve(request):
        calls.append("resolve")
        return provider.resolve(request)

    credentials = WriteCredentials(
        binding_namespace=provider.namespace,
        binding_resolver=resolve,
        signature_verifier=provider.verify,
    )
    with pytest.raises(SdkError, match="maintenance|catch-up|rebuild"):
        adopt_arrival(
            vertex, selected_head=migration.head, reviewed_text=reviewed,
            reviewed_sha256=hashlib.sha256(reviewed.encode()).hexdigest(),
            declaration_text=vertex.read_text(), observer="alice", credentials=credentials,
            registry=registry,
        )
    assert "resolve" not in calls and "catch-up" not in calls
    if maintenance != "missing":
        assert "closed" in calls
    assert migration.target_path.read_bytes() == before
    assert not vertex.with_name(vertex.name + ".arrival-adopt.intent").exists()


def test_sdk_retires_proven_superseded_intent_then_adopts_fresh_selected_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.arrival_adoption as engine_adoption
    from engine.arrival_body import body_of_fact_row
    from engine.arrival_contract import RecordDraft
    from sdk import ArrivalRefusal, adopt_arrival, recover_arrival_adoption

    provider, _binding, vertex, reviewed, migration = _mapped_migration_fixture(tmp_path)
    kwargs = {
        "selected_head": migration.head,
        "reviewed_text": reviewed,
        "reviewed_sha256": hashlib.sha256(reviewed.encode()).hexdigest(),
        "declaration_text": vertex.read_text(),
        "observer": "alice",
        "credentials": provider,
    }
    actual_apply = engine_adoption.apply_arrival_adoption

    def stop_after_intent(phase):
        if phase == "after-intent":
            raise OSError("reserve the original adoption before any append")

    with monkeypatch.context() as patch:
        patch.setattr(
            engine_adoption, "apply_arrival_adoption",
            lambda registry, plan: actual_apply(registry, plan, failure_hook=stop_after_intent),
        )
        with pytest.raises(ArrivalRefusal):
            adopt_arrival(vertex, **kwargs)
    intent = vertex.with_name(vertex.name + ".arrival-adopt.intent")
    assert intent.exists()
    registry = BackendRegistry.with_builtin_backends()
    descriptor = descriptor_for(parse_vertex_file(vertex), vertex)
    assert descriptor is not None
    ledger, query = registry.open(descriptor)
    try:
        body = body_of_fact_row((
            "interleaved-before-adoption", "concept", 1002.0, "alice", "", "{}", None,
        ))
        intervening = ledger.append(migration.head, (RecordDraft("fact", 1002.0, "alice", "", body),))
    finally:
        query.close()
        ledger.close()
    prefix = migration.target_path.read_bytes()
    with pytest.raises(ArrivalRefusal, match="superseded.*retired"):
        recover_arrival_adoption(intent)
    assert not intent.exists()
    assert migration.target_path.read_bytes() == prefix
    kwargs["selected_head"] = intervening.after
    adopted = adopt_arrival(vertex, **kwargs)
    assert adopted.commit is not None and adopted.commit.before == intervening.after
    assert migration.target_path.read_bytes().startswith(prefix)
    anchors = [
        row for row in read_facts(vertex, include_internal=True, limit=100).items
        if row["kind"] == "_decl.genesis"
    ]
    assert len(anchors) == 1
    assert anchors[0]["id"] == migration.lineage
