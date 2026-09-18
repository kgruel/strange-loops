"""Contract tests for the offline blank-observer preparation utility."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_legacy_unattributed.py"
_SPEC = importlib.util.spec_from_file_location("prepare_legacy_unattributed", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_PREP = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PREP
_SPEC.loader.exec_module(_PREP)


def _line(**value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def _fact(
    *,
    observer: object = "alice",
    signature: object = ...,
    fact_id: str = "fact-1",
    payload: str = '{"text":"keep exact"}',
) -> dict[str, object]:
    value: dict[str, object] = {
        "t": "fact",
        "id": fact_id,
        "kind": "note",
        "ts": 12.5,
        "observer": observer,
        "origin": "legacy",
        "payload": payload,
    }
    if signature is not ...:
        value["signature"] = signature
    return value


def test_preparation_maps_only_unsigned_empty_flat_facts_and_audits_them(
    tmp_path: Path,
) -> None:
    source = tmp_path / "copied.jsonl"
    output = tmp_path / "prepared.jsonl"
    manifest = tmp_path / "prepared.manifest.json"
    normal = b'{ "t" : "fact", "id" : "normal", "kind":"note", "ts":7, "observer":"alice", "origin":"old", "payload":"{\\"a\\":1}", "signature":"carry-me" }\r\n'
    tick = b'{"t":"tick","id":"tick-1","name":"pulse","ts":8,"since":null,"origin":"old","payload":"{}"}\n'
    blank = _line(**_fact(observer="", fact_id="blank-1"))
    null_signature = _line(**_fact(observer="", signature=None, fact_id="blank-2"))
    source_bytes = normal + tick + blank + null_signature
    source.write_bytes(source_bytes)

    result = _PREP.prepare_legacy_unattributed(source, output, manifest)

    output_lines = output.read_bytes().splitlines(keepends=True)
    assert output_lines[:2] == [normal, tick]
    original_blank = json.loads(blank)
    prepared_blank = json.loads(output_lines[2])
    original_null = json.loads(null_signature)
    prepared_null = json.loads(output_lines[3])
    for before, after in (
        (original_blank, prepared_blank),
        (original_null, prepared_null),
    ):
        assert after["observer"] == "legacy/unattributed"
        assert {key: value for key, value in after.items() if key != "observer"} == {
            key: value for key, value in before.items() if key != "observer"
        }
    assert source.read_bytes() == source_bytes
    assert len(result.affected_rows) == 2
    assert [row.coordinate for row in result.affected_rows] == [3, 4]
    assert [row.fact_id for row in result.affected_rows] == ["blank-1", "blank-2"]

    audit = json.loads(manifest.read_text())
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    assert audit["policy"] == "legacy-unattributed-v1"
    assert audit["normalized_observer"] == "legacy/unattributed"
    assert audit["source_sha256_before"] == source_hash
    assert audit["source_sha256_after"] == source_hash
    assert audit["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert [entry["coordinate"] for entry in audit["affected_rows"]] == [3, 4]
    assert [entry["id"] for entry in audit["affected_rows"]] == ["blank-1", "blank-2"]
    assert (
        audit["affected_rows"][0]["original_line_sha256"]
        == hashlib.sha256(blank).hexdigest()
    )
    assert (
        audit["affected_rows"][0]["normalized_line_sha256"]
        == hashlib.sha256(output_lines[2]).hexdigest()
    )


def test_signed_empty_observer_refuses_without_publishing(tmp_path: Path) -> None:
    source = tmp_path / "copied.jsonl"
    output = tmp_path / "prepared.jsonl"
    manifest = tmp_path / "prepared.manifest.json"
    source.write_bytes(_line(**_fact(observer="", signature="signed-legacy")))

    with pytest.raises(_PREP.PreparationRefused, match="signature"):
        _PREP.prepare_legacy_unattributed(source, output, manifest)

    assert not output.exists()
    assert not manifest.exists()


@pytest.mark.parametrize("observer", [None, ...])
def test_missing_or_null_observer_refuses_without_publishing(
    tmp_path: Path, observer: object
) -> None:
    source = tmp_path / "copied.jsonl"
    output = tmp_path / "prepared.jsonl"
    manifest = tmp_path / "prepared.manifest.json"
    row = _fact(observer=observer)
    if observer is ...:
        del row["observer"]
    source.write_bytes(_line(**row))

    with pytest.raises(_PREP.PreparationRefused, match="missing or null observer"):
        _PREP.prepare_legacy_unattributed(source, output, manifest)

    assert not output.exists()
    assert not manifest.exists()


def test_existing_destination_and_source_alias_are_refused(tmp_path: Path) -> None:
    source = tmp_path / "copied.jsonl"
    manifest = tmp_path / "prepared.manifest.json"
    source.write_bytes(_line(**_fact(observer="")))
    existing = tmp_path / "prepared.jsonl"
    existing.write_text("must remain")

    with pytest.raises(_PREP.PreparationRefused, match="already exists"):
        _PREP.prepare_legacy_unattributed(source, existing, manifest)
    assert existing.read_text() == "must remain"
    assert not manifest.exists()

    with pytest.raises(_PREP.PreparationRefused, match="three distinct paths"):
        _PREP.prepare_legacy_unattributed(source, source, manifest)


def test_no_eligible_rows_refuses_and_keeps_normal_rows_unwritten(
    tmp_path: Path,
) -> None:
    source = tmp_path / "copied.jsonl"
    output = tmp_path / "prepared.jsonl"
    manifest = tmp_path / "prepared.manifest.json"
    source.write_bytes(
        _line(**_fact(observer="alice", signature="carry"))
        + _line(
            t="tick",
            id="tick-1",
            name="pulse",
            ts=1.0,
            since=None,
            origin="old",
            payload="{}",
        )
    )

    with pytest.raises(_PREP.PreparationRefused, match="no eligible"):
        _PREP.prepare_legacy_unattributed(source, output, manifest)

    assert not output.exists()
    assert not manifest.exists()


def test_nonfinite_json_is_refused_before_any_destination_is_published(
    tmp_path: Path,
) -> None:
    source = tmp_path / "copied.jsonl"
    output = tmp_path / "prepared.jsonl"
    manifest = tmp_path / "prepared.manifest.json"
    source.write_bytes(
        b'{"t":"fact","id":"blank","kind":"note","ts":NaN,'
        b'"observer":"","origin":"old","payload":"{}"}\n'
    )

    with pytest.raises(_PREP.PreparationRefused, match="non-finite"):
        _PREP.prepare_legacy_unattributed(source, output, manifest)

    assert not output.exists()
    assert not manifest.exists()
