"""Contract tests for offline legacy provenance verification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from custody.signing import ARRIVAL_DOMAIN
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row, body_of_tick_row
from engine.jsonl_codec import (
    deserialize_records,
    serialize_fact_row,
    serialize_tick_row,
)
from engine.row_commitment import fact_row_hash, tick_row_hash
from sign import ed25519

_ROOT = Path(__file__).parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_VERIFY = _load("verify_legacy_provenance", _ROOT / "scripts/verify_legacy_provenance.py")
_PREPARE = _load(
    "prepare_legacy_unattributed_for_provenance",
    _ROOT / "scripts/prepare_legacy_unattributed.py",
)


def _hashes(*rows: tuple) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(fact_row_hash(row).encode())
    return digest.hexdigest()


@dataclass
class Fixture:
    original: Path
    prepared: Path
    manifest: Path
    arrival: Path
    source_hash: str
    manifest_hash: str
    lineage: str
    ordinal: int
    record_hash: str
    keypair: ed25519.Keypair
    final_tick: tuple

    def verify(self):
        return _VERIFY.verify_legacy_provenance(
            self.original,
            self.prepared,
            self.manifest,
            self.arrival,
            reviewed_source_sha256=self.source_hash,
            reviewed_manifest_sha256=self.manifest_hash,
            migration_lineage=self.lineage,
            migration_ordinal=self.ordinal,
            migration_record_hash=self.record_hash,
        )


def _fixture(
    tmp_path: Path,
    *,
    bad_original_window: bool = False,
    bad_original_predecessor: bool = False,
) -> Fixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    original = tmp_path / "original.jsonl"
    prepared = tmp_path / "prepared.jsonl"
    manifest = tmp_path / "manifest.json"
    arrival = tmp_path / "target.arrival"
    first = ("f1", "note", 1.0, "", "legacy", '{"n":1}', None)
    first_window = "0" * 64 if bad_original_window else _hashes(first)
    tick1 = (
        "t1", "note", 2.0, None, "legacy", "{}",
        "f" * 64 if bad_original_predecessor else None, "", "f1",
        first_window, None,
    )
    second = ("f2", "note", 3.0, "alice", "legacy", '{"n":2}', None)
    tick2 = (
        "t2", "note", 4.0, 2.0, "legacy", "{}", tick_row_hash(tick1),
        "f1", "f2", _hashes(second), None,
    )
    original.write_text(
        serialize_fact_row(first) + "\n"
        + serialize_tick_row(tick1) + "\n"
        + serialize_fact_row(second) + "\n"
        + serialize_tick_row(tick2) + "\n"
    )
    _PREPARE.prepare_legacy_unattributed(original, prepared, manifest)

    private = Ed25519PrivateKey.generate()
    keypair = ed25519.Keypair(private=private, public=private.public_key())

    def signer(_observer: str, digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain=ARRIVAL_DOMAIN)

    log = ArrivalLog.mint(
        arrival, observer="custodian", key=keypair.public_b64,
        signer=signer, lineage="01ARZ3NDEKTSV4RRFFQ69G5FAV", at=0.0,
    )
    migration_head = None
    for raw in prepared.read_text().splitlines():
        kind, row = deserialize_records(raw)[0]
        body = body_of_fact_row(row) if kind == "fact" else body_of_tick_row(row)
        migration_head = log.append(
            kind, body, observer=row[3] if kind == "fact" else "custodian",
            origin=row[4], at=row[2],
        )
    assert migration_head is not None
    third = ("f3", "note", 5.0, "alice", "legacy", '{"n":3}', None)
    log.append("fact", body_of_fact_row(third), observer="alice", origin="legacy", at=5.0)
    tick3 = (
        "t3", "note", 6.0, 4.0, "legacy", "{}", tick_row_hash(tick2),
        "f2", "f3", _hashes(third), None,
    )
    log.append("tick", body_of_tick_row(tick3), observer="custodian", origin="legacy", at=6.0)
    return Fixture(
        original=original,
        prepared=prepared,
        manifest=manifest,
        arrival=arrival,
        source_hash=hashlib.sha256(original.read_bytes()).hexdigest(),
        manifest_hash=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        lineage=migration_head["lin"],
        ordinal=migration_head["ord"],
        record_hash=migration_head["rh"],
        keypair=keypair,
        final_tick=tick3,
    )


def test_verifies_exact_mapping_prefix_and_later_chain_without_authorship_claim(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    result = fixture.verify()

    assert result["status"] == "preserved-boundaries-with-audited-transformation"
    assert result["preparation"] == {
        "policy": "legacy-unattributed-v1",
        "source_sha256": fixture.source_hash,
        "prepared_sha256": hashlib.sha256(fixture.prepared.read_bytes()).hexdigest(),
        "rows": 4,
        "facts": 2,
        "ticks": 2,
        "transformed_rows": 1,
        "byte_identical_rows": 3,
    }
    assert result["commitments"]["explained_transformation_windows"] == 1
    assert result["commitments"]["unchanged_historical_windows"] == 1
    assert result["commitments"]["unchained_historical_ticks"] == 0
    assert result["commitments"]["original_tick_chain"] == "structurally-verified"
    assert result["commitments"]["historical_authorship_verified"] is False
    assert result["commitments"]["ordinary_envelope_signatures_verified"] is False
    assert result["commitments"]["inner_fact_tick_signatures_verified"] is False
    assert result["arrival"]["post_migration_ticks_verified"] == 1
    assert result["arrival"]["prepared_rows_at_pinned_prefix"] == "exact-in-order"
    assert result["arrival"]["captured_head"]["ordinal"] == fixture.ordinal + 2
    assert result["trust"]["migration_report_signature_verified"] is False
    assert result["trust"]["pins"] == "caller-supplied"
    assert result["trust"]["pin_independence_verified"] is False
    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, list):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    assert "f1" not in set(leaves(result))
    assert "custodian" not in set(leaves(result))


def test_refuses_bad_pins_and_incomplete_manifest(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.source_hash = "0" * 64
    with pytest.raises(_VERIFY.ProvenanceRefused, match="reviewed hash"):
        fixture.verify()


def test_refuses_self_consistent_manifest_for_unauthorized_payload_change(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    lines = fixture.prepared.read_bytes().splitlines(keepends=True)
    changed = json.loads(lines[0])
    changed["payload"] = '{"n":999}'
    lines[0] = json.dumps(changed, separators=(",", ":")).encode() + b"\n"
    fixture.prepared.write_bytes(b"".join(lines))
    manifest = json.loads(fixture.manifest.read_text())
    manifest["output_sha256"] = hashlib.sha256(fixture.prepared.read_bytes()).hexdigest()
    manifest["affected_rows"][0]["normalized_line_sha256"] = hashlib.sha256(
        lines[0]
    ).hexdigest()
    fixture.manifest.write_text(json.dumps(manifest))
    fixture.manifest_hash = hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()

    with pytest.raises(_VERIFY.ProvenanceRefused, match="exact authorized transformation"):
        fixture.verify()

    fixture = _fixture(tmp_path / "second")
    value = json.loads(fixture.manifest.read_text())
    value["affected_rows"] = []
    fixture.manifest.write_text(json.dumps(value))
    fixture.manifest_hash = hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()
    with pytest.raises(_VERIFY.ProvenanceRefused, match="no affected-row audit"):
        fixture.verify()


def test_refuses_broken_original_window_before_explaining_mapping(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, bad_original_window=True)
    with pytest.raises(_VERIFY.ProvenanceRefused, match="original tick window mismatch"):
        fixture.verify()


def test_refuses_orphan_first_chained_predecessor(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, bad_original_predecessor=True)
    with pytest.raises(_VERIFY.ProvenanceRefused, match="predecessor mismatch"):
        fixture.verify()


def test_historical_unchained_ticks_are_structural_pre_chain_only() -> None:
    prechain = (
        "pre", "note", 1.0, None, "legacy", "{}", None, None, None, None, None,
    )
    chain = _VERIFY._TickChain("probe")
    assert chain.tick(prechain, 1, require_window=False) == (None, False)
    assert chain.unchained == 1

    malformed = (*prechain[:6], "f" * 64, *prechain[7:])
    with pytest.raises(_VERIFY.ProvenanceRefused, match="carries chain fields"):
        _VERIFY._TickChain("probe").tick(malformed, 1, require_window=False)

    fact = ("fact", "note", 2.0, "alice", "", "{}", None)
    chained = (
        "sealed", "note", 3.0, None, "legacy", "{}", None, "", "fact",
        _hashes(fact), None,
    )
    after_chain = _VERIFY._TickChain("probe")
    after_chain.fact(fact)
    after_chain.tick(chained, 2, require_window=False)
    with pytest.raises(_VERIFY.ProvenanceRefused, match="returns to an unchained"):
        after_chain.tick(prechain, 3, require_window=False)


def test_refuses_arbitrary_record_in_protocol_metadata_prefix(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    replacement = tmp_path / "injected.arrival"

    def signer(_observer: str, digest: str) -> str:
        return ed25519.sign(fixture.keypair, digest.encode(), domain=ARRIVAL_DOMAIN)

    log = ArrivalLog.mint(
        replacement, observer="custodian", key=fixture.keypair.public_b64,
        signer=signer, lineage=fixture.lineage, at=0.0,
    )
    injected = ("injected", "note", 0.5, "alice", "", "{}", None)
    log.append("fact", body_of_fact_row(injected), observer="alice", at=0.5)
    head = None
    for raw in fixture.prepared.read_text().splitlines():
        kind, row = deserialize_records(raw)[0]
        head = log.append(
            kind,
            body_of_fact_row(row) if kind == "fact" else body_of_tick_row(row),
            observer=row[3] if kind == "fact" else "custodian",
            origin=row[4], at=row[2],
        )
    assert head is not None
    fixture.arrival = replacement
    fixture.ordinal = head["ord"]
    fixture.record_hash = head["rh"]
    with pytest.raises(_VERIFY.ProvenanceRefused, match="non-protocol record"):
        fixture.verify()


def test_refuses_post_migration_window_or_future_cursor(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    lines = fixture.arrival.read_bytes().splitlines(keepends=True)
    # Rebuild only through S, then append a structurally valid bad later tick.
    truncated = tmp_path / "bad-post.arrival"
    truncated.write_bytes(b"".join(lines[: fixture.ordinal + 1]))
    log = ArrivalLog(truncated)
    bad = (
        "bad", "note", 8.0, None, "legacy", "{}", tick_row_hash(
            deserialize_records(fixture.prepared.read_text().splitlines()[-1])[0][1]
        ),
        "f2", "future", "0" * 64, None,
    )
    log.append("tick", body_of_tick_row(bad), observer="custodian", origin="legacy", at=8.0)
    fixture.arrival = truncated
    with pytest.raises(_VERIFY.ProvenanceRefused, match="missing or future cursor"):
        fixture.verify()


def test_cli_output_is_exclusive_and_cannot_alias_input(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    args = [
        str(fixture.original), str(fixture.prepared), str(fixture.manifest),
        str(fixture.arrival), "--reviewed-source-sha256", fixture.source_hash,
        "--reviewed-manifest-sha256", fixture.manifest_hash,
        "--migration-lineage", fixture.lineage,
        "--migration-ordinal", str(fixture.ordinal),
        "--migration-record-hash", fixture.record_hash,
        "--output", str(fixture.original),
    ]
    assert _VERIFY.main(args) == 2
    assert hashlib.sha256(fixture.original.read_bytes()).hexdigest() == fixture.source_hash

    alias = tmp_path / "source-alias.json"
    alias.symlink_to(fixture.original)
    args[-1] = str(alias)
    assert _VERIFY.main(args) == 2
    assert alias.is_symlink()

    output = tmp_path / "evidence.json"
    args[-1] = str(output)
    assert _VERIFY.main(args) == 0
    assert json.loads(output.read_text())["schema"] == "loops.legacy-provenance/v1"
    assert _VERIFY.main(args) == 2
