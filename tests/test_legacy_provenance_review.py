"""Adversarial review cases for the offline legacy provenance verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from custody.signing import ARRIVAL_DOMAIN, TICK_DOMAIN
from engine.arrival import KEY_INTRODUCTION_KIND, ArrivalLog
from engine.arrival_body import body_of_fact_row, body_of_tick_row
from engine.jsonl_codec import (
    deserialize_records,
    serialize_fact_row,
    serialize_tick_row,
)
from engine.row_commitment import fact_row_hash, tick_commitment_hash, tick_row_hash
from sign import ed25519


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_BASE = _load("legacy_provenance_base_review", Path(__file__).with_name("test_legacy_provenance.py"))
_VERIFY = _BASE._VERIFY
_PREPARE = _BASE._PREPARE
_RUNNER = _load(
    "arrival_rehearsal_runner_base_review",
    Path(__file__).with_name("test_arrival_rehearsal_runner.py"),
)


def _verify(fixture, **overrides):
    values = {
        "reviewed_source_sha256": fixture.source_hash,
        "reviewed_manifest_sha256": fixture.manifest_hash,
        "migration_lineage": fixture.lineage,
        "migration_ordinal": fixture.ordinal,
        "migration_record_hash": fixture.record_hash,
    }
    values.update(overrides)
    return _VERIFY.verify_legacy_provenance(
        fixture.original, fixture.prepared, fixture.manifest, fixture.arrival, **values
    )


def _repin_manifest(fixture) -> None:
    value = json.loads(fixture.manifest.read_text())
    source_hash = hashlib.sha256(fixture.original.read_bytes()).hexdigest()
    value["source_sha256_before"] = source_hash
    value["source_sha256_after"] = source_hash
    value["output_sha256"] = hashlib.sha256(fixture.prepared.read_bytes()).hexdigest()
    fixture.manifest.write_text(json.dumps(value, sort_keys=True))
    fixture.source_hash = source_hash
    fixture.manifest_hash = hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()


def _copy_arrival(fixture, path: Path) -> None:
    shutil.copyfile(fixture.arrival, path)
    fixture.arrival = path


def _prepared_tick(fixture, index: int = 1) -> tuple:
    return deserialize_records(fixture.prepared.read_text().splitlines()[index])[0][1]


def _append_post_tick(fixture, path: Path, row: tuple) -> None:
    lines = fixture.arrival.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[: fixture.ordinal + 1]))
    log = ArrivalLog(path)
    log.append(
        "tick", body_of_tick_row(row), observer="custodian", origin=row[4], at=row[2]
    )
    fixture.arrival = path


def _remint_prefix(fixture, path: Path, *, reorder: bool) -> None:
    """Build a valid Arrival prefix whose source row(s) differ from prepared."""
    rows = [deserialize_records(line)[0] for line in fixture.prepared.read_text().splitlines()]
    if reorder:
        rows[0], rows[1] = rows[1], rows[0]
    else:
        kind, row = rows[0]
        changed = list(row)
        changed[5] = '{"changed":true}'
        rows[0] = (kind, tuple(changed))

    def signer(_observer: str, digest: str) -> str:
        return ed25519.sign(
            fixture.keypair, digest.encode(), domain=ARRIVAL_DOMAIN
        )

    log = ArrivalLog.mint(
        path,
        observer="custodian",
        key=fixture.keypair.public_b64,
        signer=signer,
        lineage=fixture.lineage,
        at=0.0,
    )
    head = None
    for kind, row in rows:
        head = log.append(
            kind,
            body_of_fact_row(row) if kind == "fact" else body_of_tick_row(row),
            observer=row[3] if kind == "fact" else "custodian",
            origin=row[4],
            at=row[2],
        )
    assert head is not None
    fixture.arrival = path
    fixture.ordinal = head["ord"]
    fixture.record_hash = head["rh"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewed_manifest_sha256", "0" * 64),
        ("migration_record_hash", "0" * 64),
        ("migration_lineage", "wrong-lineage"),
        ("migration_ordinal", "minus"),
    ],
)
def test_refuses_wrong_review_and_migration_pins(tmp_path: Path, field: str, value: str) -> None:
    fixture = _BASE._fixture(tmp_path / field)
    if field == "migration_ordinal":
        with pytest.raises(_VERIFY.ProvenanceRefused):
            _verify(fixture, migration_ordinal=fixture.ordinal - 1)
        with pytest.raises(_VERIFY.ProvenanceRefused):
            _verify(fixture, migration_ordinal=fixture.ordinal + 1)
    else:
        with pytest.raises(_VERIFY.ProvenanceRefused):
            _verify(fixture, **{field: value})


def test_refuses_manifest_entries_that_are_extra_or_reordered(tmp_path: Path) -> None:
    fixture = _BASE._fixture(tmp_path / "extra")
    value = json.loads(fixture.manifest.read_text())
    entry = dict(value["affected_rows"][0])
    entry["coordinate"] += 100
    value["affected_rows"].append(entry)
    fixture.manifest.write_text(json.dumps(value))
    fixture.manifest_hash = hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()
    with pytest.raises(_VERIFY.ProvenanceRefused):
        _verify(fixture)

    fixture = _BASE._fixture(tmp_path / "reordered")
    value = json.loads(fixture.manifest.read_text())
    value["affected_rows"][0]["coordinate"] = 2
    fixture.manifest.write_text(json.dumps(value))
    fixture.manifest_hash = hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()
    with pytest.raises(_VERIFY.ProvenanceRefused):
        _verify(fixture)


def test_refuses_eligible_row_left_untransformed(tmp_path: Path) -> None:
    fixture = _BASE._fixture(tmp_path)
    extra = {
        "t": "fact", "id": "f-extra", "kind": "note", "ts": 9.0,
        "observer": "", "origin": "legacy", "payload": "{}",
    }
    source = tmp_path / "source-with-two-eligible.jsonl"
    source.write_bytes(fixture.original.read_bytes() + json.dumps(extra, separators=(",", ":")).encode() + b"\n")
    prepared = tmp_path / "prepared-with-two-eligible.jsonl"
    manifest = tmp_path / "prepared-with-two-eligible.manifest.json"
    _PREPARE.prepare_legacy_unattributed(source, prepared, manifest)
    prepared_lines = prepared.read_bytes().splitlines(keepends=True)
    prepared_lines[-1] = source.read_bytes().splitlines(keepends=True)[-1]
    prepared.write_bytes(b"".join(prepared_lines))
    value = json.loads(manifest.read_text())
    value["affected_rows"] = value["affected_rows"][:1]
    value["output_sha256"] = hashlib.sha256(prepared.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(value))
    fixture.original = source
    fixture.prepared = prepared
    fixture.manifest = manifest
    fixture.source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    fixture.manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(_VERIFY.ProvenanceRefused, match="eligible line"):
        _verify(fixture)


def test_refuses_signed_changed_row(tmp_path: Path) -> None:
    fixture = _BASE._fixture(tmp_path)
    lines = fixture.original.read_bytes().splitlines(keepends=True)
    row = json.loads(lines[0])
    row["signature"] = "signed-legacy"
    lines[0] = json.dumps(row, separators=(",", ":")).encode() + b"\n"
    fixture.original.write_bytes(b"".join(lines))
    value = json.loads(fixture.manifest.read_text())
    source_hash = hashlib.sha256(fixture.original.read_bytes()).hexdigest()
    value["source_sha256_before"] = source_hash
    value["source_sha256_after"] = source_hash
    value["affected_rows"][0]["original_line_sha256"] = hashlib.sha256(lines[0]).hexdigest()
    fixture.manifest.write_text(json.dumps(value))
    fixture.source_hash = source_hash
    fixture.manifest_hash = hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()
    with pytest.raises(_VERIFY.ProvenanceRefused, match="signed empty-observer"):
        _verify(fixture)


@pytest.mark.parametrize("mutation", ["bytes", "reorder", "torn"])
def test_refuses_mutated_reordered_or_torn_migration_prefix(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _BASE._fixture(tmp_path / mutation)
    target = tmp_path / mutation / "arrival-copy"
    _copy_arrival(fixture, target)
    if mutation == "bytes":
        raw = target.read_bytes()
        target.write_bytes(raw.replace(b'"legacy"', b'"changed"', 1))
    elif mutation == "reorder":
        lines = target.read_bytes().splitlines(keepends=True)
        lines[1], lines[2] = lines[2], lines[1]
        target.write_bytes(b"".join(lines))
    else:
        target.write_bytes(target.read_bytes() + b'{"v":')
    with pytest.raises(_VERIFY.ProvenanceRefused):
        _verify(fixture)


@pytest.mark.parametrize("reorder", [False, True])
def test_refuses_valid_arrival_prefix_with_mutated_or_reordered_rows(
    tmp_path: Path, reorder: bool
) -> None:
    fixture = _BASE._fixture(tmp_path / ("reorder" if reorder else "mutate"))
    _remint_prefix(fixture, tmp_path / ("reordered.arrival" if reorder else "mutated.arrival"), reorder=reorder)
    with pytest.raises(_VERIFY.ProvenanceRefused, match="migration prefix row mismatch"):
        _verify(fixture)


def test_refuses_duplicate_post_migration_id(tmp_path: Path) -> None:
    fixture = _BASE._fixture(tmp_path)
    target = tmp_path / "duplicate.arrival"
    _copy_arrival(fixture, target)
    duplicate = deserialize_records(fixture.prepared.read_text().splitlines()[0])[0][1]
    log = ArrivalLog(target)
    log.append("fact", body_of_fact_row(duplicate), observer=duplicate[3], origin=duplicate[4], at=9.0)
    with pytest.raises(_VERIFY.ProvenanceRefused, match="duplicate row id"):
        _verify(fixture)


@pytest.mark.parametrize("window_start,end_cursor", [("", "f2"), ("f1", "")])
def test_refuses_original_cursor_discontinuity_or_reversal(
    tmp_path: Path, window_start: str, end_cursor: str
) -> None:
    fixture = _BASE._fixture(tmp_path / repr((window_start, end_cursor)))
    original_lines = fixture.original.read_bytes().splitlines(keepends=True)
    prepared_lines = fixture.prepared.read_bytes().splitlines(keepends=True)
    _kind, row = deserialize_records(original_lines[3])[0]
    row = list(row)
    row[7] = window_start
    row[8] = end_cursor
    encoded = serialize_tick_row(tuple(row)).encode() + b"\n"
    original_lines[3] = encoded
    prepared_lines[3] = encoded
    fixture.original.write_bytes(b"".join(original_lines))
    fixture.prepared.write_bytes(b"".join(prepared_lines))
    _repin_manifest(fixture)
    expected = "reversed window" if window_start == "f1" else "cursor discontinuity"
    with pytest.raises(_VERIFY.ProvenanceRefused, match=expected):
        _verify(fixture)


@pytest.mark.parametrize("placement", ["after-chained", "before-chained"])
def test_refuses_historical_unchained_tick_claims(
    tmp_path: Path, placement: str
) -> None:
    fixture = _BASE._fixture(tmp_path / placement)
    original = fixture.original.read_bytes().splitlines(keepends=True)
    prepared_original = fixture.prepared.read_bytes().splitlines(keepends=True)
    fact1 = deserialize_records(original[0])[0][1]
    tick1 = deserialize_records(original[1])[0][1]
    fact2 = deserialize_records(original[2])[0][1]
    tick2 = list(deserialize_records(original[3])[0][1])
    if placement == "after-chained":
        unchained = (
            "t-un", "note", 2.5, None, "legacy", "{}", None, None, None, None, None
        )
        tick2[6] = tick_row_hash(unchained)
        rows = [fact1, tick1, unchained, fact2, tuple(tick2)]
    else:
        claimed = (
            "t-claimed", "note", 1.5, None, "legacy", "{}", None, "", fact1[0], None, None
        )
        tick1 = list(tick1)
        tick1[6] = tick_row_hash(claimed)
        rows = [fact1, claimed, tuple(tick1), fact2, tuple(tick2)]
    encoded = b"".join(
        (serialize_fact_row(row) if len(row) == 7 else serialize_tick_row(row)).encode() + b"\n"
        for row in rows
    )
    prepared_rows = list(rows)
    prepared_rows[0] = deserialize_records(prepared_original[0])[0][1]
    prepared_encoded = b"".join(
        (serialize_fact_row(row) if len(row) == 7 else serialize_tick_row(row)).encode() + b"\n"
        for row in prepared_rows
    )
    fixture.original.write_bytes(encoded)
    fixture.prepared.write_bytes(prepared_encoded)
    _repin_manifest(fixture)
    with pytest.raises(_VERIFY.ProvenanceRefused, match="unchained|pre-chain tick"):
        _verify(fixture)


@pytest.mark.parametrize("kind", ["bad-window", "unchained", "bad-prev"])
def test_refuses_bad_post_migration_tick_attestation(tmp_path: Path, kind: str) -> None:
    fixture = _BASE._fixture(tmp_path / kind)
    prior = _prepared_tick(fixture, 3)
    if kind == "unchained":
        row = ("post-unchained", "note", 8.0, None, "legacy", "{}", None, None, None, None, None)
    elif kind == "bad-prev":
        row = ("post-bad-prev", "note", 8.0, None, "legacy", "{}", "0" * 64, "f1", "f2", prior[9], None)
    else:
        row = ("post-bad-window", "note", 8.0, None, "legacy", "{}", tick_row_hash(prior), "f2", "f2", "0" * 64, None)
    _append_post_tick(fixture, tmp_path / f"{kind}.arrival", row)
    expected = "post-migration tick window mismatch" if kind == "bad-window" else None
    with pytest.raises(_VERIFY.ProvenanceRefused, match=expected):
        _verify(fixture)


def test_refuses_forged_post_migration_key_introduction(tmp_path: Path) -> None:
    fixture = _BASE._fixture(tmp_path)
    target = tmp_path / "forged-key.arrival"
    lines = fixture.arrival.read_bytes().splitlines(keepends=True)
    target.write_bytes(b"".join(lines[: fixture.ordinal + 1]))
    wrong_private = Ed25519PrivateKey.generate()
    wrong = ed25519.Keypair(private=wrong_private, public=wrong_private.public_key())
    named_private = Ed25519PrivateKey.generate()
    named = ed25519.Keypair(private=named_private, public=named_private.public_key())
    log = ArrivalLog(target)
    log.append(
        KEY_INTRODUCTION_KIND,
        {"observer": "mallory", "key": named.public_b64},
        observer="custodian",
        signer=lambda _observer, digest: ed25519.sign(
            wrong, digest.encode(), domain=ARRIVAL_DOMAIN
        ),
        at=8.0,
    )
    fixture.arrival = target
    with pytest.raises(_VERIFY.ProvenanceRefused, match="signature"):
        _verify(fixture)


def test_engine_generated_fresh_seal_passes_provenance_verifier(tmp_path: Path) -> None:
    sandbox, vertex, source, keys = _RUNNER._inputs(tmp_path, seal=True, signed_tick=True)
    pair = ed25519.load(keys)
    first = ("01ARZ3NDEKTSV4RRFFQ69G5FA0", "concept", 1000.0, "", "legacy", '{"text":"migrated"}', None)
    tick_window = hashlib.sha256(fact_row_hash(first).encode()).hexdigest()
    tick = ("01ARZ3NDEKTSV4RRFFQ69G5FT1", "alice", 1001.0, 1000.0, "alice", "{}", None, "", first[0], tick_window)
    signature = ed25519.sign(
        pair, tick_commitment_hash(tick).encode(), domain=TICK_DOMAIN
    )
    tick = (*tick, signature)
    source.write_text(serialize_fact_row(first) + "\n" + serialize_tick_row(tick) + "\n")
    prepared = sandbox / "input" / "prepared.jsonl"
    manifest = sandbox / "input" / "prepared.manifest.json"
    _PREPARE.prepare_legacy_unattributed(source, prepared, manifest)
    vertex.write_text(
        vertex.read_text(encoding="utf-8").replace("../../input/legacy.jsonl", "../../input/prepared.jsonl"),
        encoding="utf-8",
    )
    output = sandbox / "output"
    result = subprocess.run(
        _RUNNER._command(sandbox, vertex, prepared, keys, output, runtime_epoch="fresh", emit_kind="seal", expect_tick=True),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads((output / "evidence.json").read_text())
    selected = evidence["migration"]["selected_head"]
    input_paths = (source, prepared, manifest, Path(evidence["migration"]["target_path"]))
    input_hashes_before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths}
    directory_before = tuple(
        sorted(str(path.relative_to(sandbox)) for path in sandbox.rglob("*"))
    )
    verified = _VERIFY.verify_legacy_provenance(
        source,
        prepared,
        manifest,
        Path(evidence["migration"]["target_path"]),
        reviewed_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        reviewed_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        migration_lineage=selected["lineage"],
        migration_ordinal=selected["ordinal"],
        migration_record_hash=selected["record_hash"],
    )
    assert verified["status"] == "preserved-boundaries-with-audited-transformation"
    assert verified["preparation"]["transformed_rows"] == 1
    assert verified["commitments"]["original_tick_chain"] == "structurally-verified"
    assert verified["commitments"]["unchained_historical_ticks"] == 0
    assert verified["trust"]["pins"] == "caller-supplied"
    assert verified["trust"]["pin_independence_verified"] is False
    assert verified["arrival"]["post_migration_ticks_verified"] >= 1
    assert input_hashes_before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths
    }
    assert directory_before == tuple(
        sorted(str(path.relative_to(sandbox)) for path in sandbox.rglob("*"))
    )
