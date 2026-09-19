#!/usr/bin/env python3
"""Verify an audited legacy preparation through a pinned Arrival prefix.

This offline verifier makes no historical authorship claim. It verifies the
Arrival hash chain and registry-forming signatures, while treating the
independently supplied original/manifest hashes and migration head as trust
anchors. It never repairs or rewrites an input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from custody.signing import ARRIVAL_DOMAIN
from engine.arrival import (
    GENESIS_KIND,
    KEY_INTRODUCTION_KIND,
    ArrivalLog,
    content_commitment,
)
from engine.arrival_projection import rows_of_record
from engine.jsonl_codec import deserialize_records
from engine.row_commitment import fact_row_hash, tick_row_hash
from sign import ed25519

POLICY = "legacy-unattributed-v1"
NORMALIZED_OBSERVER = "legacy/unattributed"
SCHEMA = "loops.legacy-provenance/v1"
_MANIFEST_KEYS = {
    "affected_rows", "normalized_observer", "output_path", "output_sha256",
    "policy", "source_path", "source_sha256_after", "source_sha256_before",
}
_ENTRY_KEYS = {
    "coordinate", "id", "normalized_line_sha256", "original_line_sha256",
}


class ProvenanceError(Exception):
    """Base class for safe, metadata-only verification failures."""


class ProvenanceRefused(ProvenanceError):
    """The supplied artifacts do not prove the requested relationship."""


@dataclass(frozen=True)
class _SourceEvidence:
    rows: int
    facts: int
    ticks: int
    changed: int
    unchanged: int
    unchained_ticks: int
    explained_windows: int
    unchanged_windows: int
    changed_facts: tuple[bool, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ends_with_newline(path: Path) -> bool:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            return False
        stream.seek(-1, os.SEEK_END)
        return stream.read(1) == b"\n"


def _hex(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ProvenanceRefused(f"{label} must be a lowercase SHA-256 hex digest")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ProvenanceRefused(f"{label} must be a lowercase SHA-256 hex digest") from exc
    if decoded.hex() != value:
        raise ProvenanceRefused(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceRefused("JSON input contains a duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ProvenanceRefused("JSON input contains a non-finite number")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except ProvenanceRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProvenanceRefused(f"{label} is not a valid UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ProvenanceRefused(f"{label} must be a JSON object")
    return value


def _regular(path: Path | str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise ProvenanceRefused(f"{label} must be an existing regular file")
    return resolved


def _decode_flat(raw: bytes, coordinate: int, label: str) -> tuple[str, tuple]:
    content, _ending = _split_ending(raw)
    framed = _json_object(content, f"{label} line {coordinate}")
    if framed.get("t") not in {"fact", "tick"} or "rows" in framed:
        raise ProvenanceRefused(f"{label} line {coordinate} is not one flat row")
    try:
        records = deserialize_records(raw.decode("utf-8"))
    except Exception as exc:
        raise ProvenanceRefused(
            f"{label} line {coordinate} is not supported flat JSONL"
        ) from exc
    if len(records) != 1:
        raise ProvenanceRefused(f"{label} line {coordinate} is not one flat row")
    kind, row = records[0]
    if kind not in {"fact", "tick"}:
        raise ProvenanceRefused(f"{label} line {coordinate} has an unsupported row kind")
    if kind == "fact" and row[1].startswith("_decl."):
        raise ProvenanceRefused(
            f"{label} line {coordinate} uses the reserved declaration namespace"
        )
    return kind, row


def _split_ending(raw: bytes) -> tuple[bytes, bytes]:
    if raw.endswith(b"\r\n"):
        return raw[:-2], b"\r\n"
    if raw.endswith(b"\n"):
        return raw[:-1], b"\n"
    return raw, b""


def _expected_normalized(raw: bytes, coordinate: int) -> bytes:
    content, ending = _split_ending(raw)
    value = _json_object(content, f"original line {coordinate}")
    if (
        value.get("t") != "fact"
        or value.get("observer") != ""
        or "rows" in value
        or value.get("signature") is not None
        or not isinstance(value.get("id"), str)
    ):
        raise ProvenanceRefused(
            f"changed line {coordinate} is not an unsigned flat empty-observer fact"
        )
    value["observer"] = NORMALIZED_OBSERVER
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8") + ending
    except (TypeError, ValueError) as exc:
        raise ProvenanceRefused(
            f"changed line {coordinate} cannot be normalized exactly"
        ) from exc


class _TickChain:
    def __init__(self, label: str) -> None:
        self.label = label
        self.fact_ids: list[str] = []
        self.fact_hashes: list[str] = []
        self.positions: dict[str, int] = {}
        self.all_ids: set[str] = set()
        self.changed: list[bool] = []
        self.previous: tuple | None = None
        self.last_cursor: str | None = None
        self.ticks = 0
        self.chained = 0
        self.unchained = 0

    def fact(self, row: tuple, *, changed: bool = False) -> None:
        fact_id = row[0]
        if fact_id in self.all_ids:
            raise ProvenanceRefused(f"{self.label} has a duplicate row id")
        self.all_ids.add(fact_id)
        self.positions[fact_id] = len(self.fact_ids)
        self.fact_ids.append(fact_id)
        self.fact_hashes.append(fact_row_hash(row))
        self.changed.append(changed)

    def _position(self, fact_id: str, coordinate: int) -> int:
        if fact_id == "":
            return 0
        position = self.positions.get(fact_id)
        if position is None:
            raise ProvenanceRefused(
                f"{self.label} tick at coordinate {coordinate} has a missing or future cursor"
            )
        return position + 1

    def tick(
        self, row: tuple, coordinate: int, *, require_window: bool
    ) -> tuple[str | None, bool]:
        self.ticks += 1
        if row[0] in self.all_ids:
            raise ProvenanceRefused(f"{self.label} has a duplicate row id")
        self.all_ids.add(row[0])
        if row[9] is None:
            if require_window:
                raise ProvenanceRefused(
                    f"{self.label} post-migration tick at coordinate {coordinate} is unchained"
                )
            if self.chained > 0:
                raise ProvenanceRefused(
                    f"{self.label} returns to an unchained tick at coordinate {coordinate}"
                )
            if any(row[index] is not None for index in (6, 7, 8)):
                raise ProvenanceRefused(
                    f"{self.label} pre-chain tick carries chain fields at coordinate {coordinate}"
                )
            self.unchained += 1
            self.previous = row
            return None, False
        self.chained += 1
        expected_previous = (
            tick_row_hash(self.previous) if self.previous is not None else None
        )
        if row[6] != expected_previous:
            raise ProvenanceRefused(
                f"{self.label} tick predecessor mismatch at coordinate {coordinate}"
            )
        if self.last_cursor is not None and row[7] != self.last_cursor:
            raise ProvenanceRefused(
                f"{self.label} tick cursor discontinuity at coordinate {coordinate}"
            )
        lo = self._position(row[7], coordinate)
        hi = self._position(row[8], coordinate)
        if lo > hi:
            raise ProvenanceRefused(
                f"{self.label} tick has a reversed window at coordinate {coordinate}"
            )
        digest = hashlib.sha256()
        for fact_digest in self.fact_hashes[lo:hi]:
            digest.update(fact_digest.encode())
        calculated = digest.hexdigest()
        transformed = any(self.changed[lo:hi])
        self.last_cursor = row[8]
        self.previous = row
        return calculated, transformed


def _manifest(path: Path, expected_hash: str) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash:
        raise ProvenanceRefused("preparation manifest does not match its reviewed hash")
    value = _json_object(raw, "preparation manifest")
    if set(value) != _MANIFEST_KEYS:
        raise ProvenanceRefused("preparation manifest has an unsupported shape")
    if value.get("policy") != POLICY or value.get("normalized_observer") != NORMALIZED_OBSERVER:
        raise ProvenanceRefused("preparation manifest names an unsupported policy")
    for field in ("source_sha256_before", "source_sha256_after", "output_sha256"):
        _hex(value.get(field), f"manifest {field}")
    if not isinstance(value.get("source_path"), str) or not isinstance(
        value.get("output_path"), str
    ):
        raise ProvenanceRefused("preparation manifest paths are malformed")
    entries = value.get("affected_rows")
    if not isinstance(entries, list) or not entries:
        raise ProvenanceRefused("preparation manifest has no affected-row audit")
    previous = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise ProvenanceRefused("preparation manifest row entry is malformed")
        coordinate = entry.get("coordinate")
        if type(coordinate) is not int or coordinate <= previous:
            raise ProvenanceRefused(
                "preparation manifest row coordinates must be unique and increasing"
            )
        previous = coordinate
        if not isinstance(entry.get("id"), str) or not entry["id"]:
            raise ProvenanceRefused("preparation manifest row id is malformed")
        _hex(entry.get("original_line_sha256"), "manifest original-line hash")
        _hex(entry.get("normalized_line_sha256"), "manifest normalized-line hash")
    return value, actual_hash


def _verify_sources(
    original: Path,
    prepared: Path,
    manifest: dict[str, Any],
    reviewed_source_hash: str,
) -> _SourceEvidence:
    original_hash = _sha256(original)
    prepared_hash = _sha256(prepared)
    if original_hash != reviewed_source_hash:
        raise ProvenanceRefused("original source does not match its reviewed hash")
    if manifest["source_sha256_before"] != reviewed_source_hash or manifest[
        "source_sha256_after"
    ] != reviewed_source_hash:
        raise ProvenanceRefused("manifest source hashes do not match the reviewed source")
    if prepared_hash != manifest["output_sha256"]:
        raise ProvenanceRefused("prepared source does not match the manifest output hash")

    entries = iter(manifest["affected_rows"])
    pending = next(entries, None)
    original_chain = _TickChain("original source")
    prepared_chain = _TickChain("prepared source")
    facts = ticks = changed = unchanged = explained = unchanged_windows = 0
    changed_facts: list[bool] = []
    with original.open("rb") as left, prepared.open("rb") as right:
        coordinate = 0
        while True:
            raw = left.readline()
            cooked = right.readline()
            if not raw and not cooked:
                break
            coordinate += 1
            if not raw or not cooked:
                raise ProvenanceRefused("original and prepared sources have different row counts")
            raw_kind, raw_row = _decode_flat(raw, coordinate, "original")
            cooked_kind, cooked_row = _decode_flat(cooked, coordinate, "prepared")
            is_changed = raw != cooked
            if raw_kind == "fact" and raw_row[3] == "" and raw_row[6] is not None:
                raise ProvenanceRefused(
                    f"signed empty-observer fact at coordinate {coordinate} is unsupported"
                )
            if is_changed:
                if pending is None or pending["coordinate"] != coordinate:
                    raise ProvenanceRefused(
                        f"changed line {coordinate} is absent from the manifest audit"
                    )
                expected = _expected_normalized(raw, coordinate)
                if cooked != expected:
                    raise ProvenanceRefused(
                        f"changed line {coordinate} is not the exact authorized transformation"
                    )
                if pending["id"] != raw_row[0]:
                    raise ProvenanceRefused(
                        f"manifest row id disagrees at coordinate {coordinate}"
                    )
                expected_row = (*raw_row[:3], NORMALIZED_OBSERVER, *raw_row[4:])
                if cooked_row != expected_row:
                    raise ProvenanceRefused(
                        f"changed row differs beyond observer at coordinate {coordinate}"
                    )
                if pending["original_line_sha256"] != hashlib.sha256(raw).hexdigest():
                    raise ProvenanceRefused(
                        f"manifest original-line hash disagrees at coordinate {coordinate}"
                    )
                if pending["normalized_line_sha256"] != hashlib.sha256(cooked).hexdigest():
                    raise ProvenanceRefused(
                        f"manifest normalized-line hash disagrees at coordinate {coordinate}"
                    )
                pending = next(entries, None)
                changed += 1
            else:
                if pending is not None and pending["coordinate"] == coordinate:
                    raise ProvenanceRefused(
                        f"manifest claims unchanged line {coordinate} was transformed"
                    )
                unchanged += 1
                if raw_kind == "fact" and raw_row[3] == "" and raw_row[6] is None:
                    raise ProvenanceRefused(
                        f"eligible line {coordinate} was not transformed or audited"
                    )
            if raw_kind != cooked_kind:
                raise ProvenanceRefused(f"row kind changed at coordinate {coordinate}")
            if raw_kind == "fact":
                if raw_row[0] != cooked_row[0]:
                    raise ProvenanceRefused(f"fact identity changed at coordinate {coordinate}")
                facts += 1
                original_chain.fact(raw_row)
                prepared_chain.fact(cooked_row, changed=is_changed)
                changed_facts.append(is_changed)
            else:
                ticks += 1
                if raw_row != cooked_row:
                    raise ProvenanceRefused(f"tick row changed at coordinate {coordinate}")
                original_window, _ = original_chain.tick(
                    raw_row, coordinate, require_window=False
                )
                prepared_window, transformed = prepared_chain.tick(
                    cooked_row, coordinate, require_window=False
                )
                if original_window is not None and original_window != raw_row[9]:
                    raise ProvenanceRefused(
                        f"original tick window mismatch at coordinate {coordinate}"
                    )
                if prepared_window is not None and prepared_window != cooked_row[9]:
                    if not transformed or prepared_window == original_window:
                        raise ProvenanceRefused(
                            f"unexplained prepared tick window mismatch at coordinate {coordinate}"
                        )
                    explained += 1
                elif prepared_window is not None:
                    unchanged_windows += 1
        if pending is not None:
            raise ProvenanceRefused("preparation manifest has unused affected-row entries")

    if changed != len(manifest["affected_rows"]):
        raise ProvenanceRefused("preparation manifest is incomplete")
    if _sha256(original) != original_hash or _sha256(prepared) != prepared_hash:
        raise ProvenanceRefused("a source changed during verification")
    return _SourceEvidence(
        coordinate, facts, ticks, changed, unchanged, original_chain.unchained,
        explained, unchanged_windows, tuple(changed_facts),
    )


def _prepared_rows(path: Path) -> Iterator[tuple[str, tuple]]:
    with path.open("rb") as stream:
        for coordinate, raw in enumerate(stream, 1):
            yield _decode_flat(raw, coordinate, "prepared")


def _verify_registry_signature(
    record: dict[str, Any], keys: dict[str, list[str]], coordinate: int
) -> None:
    signature = record.get("sig")
    if not isinstance(signature, str):
        raise ProvenanceRefused(
            f"migration metadata at ordinal {coordinate} is unsigned"
        )
    digest = content_commitment(
        record["k"], record["at"], record["observer"], record["origin"], record["body"]
    ).encode()
    valid = False
    for encoded in keys.get(record["observer"], ()):
        try:
            public = ed25519.public_key_from_b64(encoded)
        except ValueError:
            continue
        if ed25519.verify(public, signature, digest, domain=ARRIVAL_DOMAIN):
            valid = True
            break
    if not valid:
        raise ProvenanceRefused(
            f"migration metadata signature does not verify at ordinal {coordinate}"
        )


def _verify_arrival(
    arrival: Path,
    prepared: Path,
    source: _SourceEvidence,
    *,
    lineage: str,
    migration_ordinal: int,
    migration_hash: str,
) -> dict[str, Any]:
    before_hash = _sha256(arrival)
    if not _ends_with_newline(arrival):
        raise ProvenanceRefused("Arrival target has an incomplete trailing record")
    metadata_count = migration_ordinal + 1 - source.rows
    if metadata_count < 1:
        raise ProvenanceRefused("pinned migration head cannot contain the prepared source")
    expected = iter(_prepared_rows(prepared))
    chain = _TickChain("Arrival target")
    registry: dict[str, list[str]] = {}
    facts = ticks = post_ticks = historical_explained = historical_unchanged = 0
    record_count = 0
    final_head: dict[str, Any] | None = None
    historical_tick_index = 0
    records = None
    try:
        records = ArrivalLog(arrival).walk()
        for record in records:
            ordinal = record["ord"]
            record_count += 1
            final_head = {
                "lineage": record["lin"],
                "ordinal": ordinal,
                "record_hash": record["rh"],
            }
            if record["lin"] != lineage:
                raise ProvenanceRefused("Arrival target lineage differs from pinned S")
            if ordinal < metadata_count:
                if ordinal == 0:
                    if record["k"] != GENESIS_KIND:
                        raise ProvenanceRefused("migration prefix does not begin with genesis")
                    key = record["body"]["key"]
                    _verify_registry_signature(record, {record["observer"]: [key]}, ordinal)
                    registry[record["observer"]] = [key]
                else:
                    if record["k"] != KEY_INTRODUCTION_KIND:
                        raise ProvenanceRefused(
                            f"non-protocol record appears before source at ordinal {ordinal}"
                        )
            if ordinal > 0 and record["k"] == KEY_INTRODUCTION_KIND:
                _verify_registry_signature(record, registry, ordinal)
                registry.setdefault(record["body"]["observer"], []).append(
                    record["body"]["key"]
                )
            if metadata_count <= ordinal <= migration_ordinal:
                try:
                    wanted = next(expected)
                except StopIteration as exc:
                    raise ProvenanceRefused(
                        "migration prefix contains extra source rows"
                    ) from exc
                actual = rows_of_record(record)
                if len(actual) != 1 or actual[0] != wanted:
                    raise ProvenanceRefused(
                        f"migration prefix row mismatch at ordinal {ordinal}"
                    )
            if ordinal == migration_ordinal and record["rh"] != migration_hash:
                raise ProvenanceRefused("Arrival record at S does not match the pinned hash")

            for kind, row in rows_of_record(record):
                if kind == "fact":
                    facts += 1
                    fact_index = len(chain.fact_ids)
                    chain.fact(
                        row,
                        changed=(
                            ordinal <= migration_ordinal
                            and fact_index < len(source.changed_facts)
                            and source.changed_facts[fact_index]
                        ),
                    )
                else:
                    ticks += 1
                    require = ordinal > migration_ordinal
                    calculated, transformed = chain.tick(
                        row, ordinal, require_window=require
                    )
                    if ordinal <= migration_ordinal:
                        historical_tick_index += 1
                        if calculated is not None and calculated != row[9]:
                            if not transformed:
                                raise ProvenanceRefused(
                                    f"unexplained historical Arrival window mismatch at ordinal {ordinal}"
                                )
                            historical_explained += 1
                        elif calculated is not None:
                            historical_unchanged += 1
                    else:
                        post_ticks += 1
                        if calculated != row[9]:
                            raise ProvenanceRefused(
                                f"post-migration tick window mismatch at ordinal {ordinal}"
                            )
        try:
            next(expected)
        except StopIteration:
            pass
        else:
            raise ProvenanceRefused("migration prefix is missing prepared source rows")
    except ProvenanceRefused:
        raise
    except Exception as exc:
        raise ProvenanceRefused("Arrival target failed complete structural verification") from exc
    finally:
        for iterator in (expected, records):
            closer = getattr(iterator, "close", None)
            if callable(closer):
                closer()
    if record_count <= migration_ordinal:
        raise ProvenanceRefused("Arrival target does not reach pinned migration head S")
    assert final_head is not None
    if historical_tick_index != source.ticks:
        raise ProvenanceRefused("migration prefix tick count differs from prepared source")
    if historical_explained != source.explained_windows:
        raise ProvenanceRefused("historical transformed-window evidence differs after migration")
    if historical_unchanged != source.unchanged_windows:
        raise ProvenanceRefused("historical unchanged-window evidence differs after migration")
    if _sha256(arrival) != before_hash:
        raise ProvenanceRefused("Arrival target changed during verification")
    return {
        "sha256": before_hash,
        "records": record_count,
        "captured_head": final_head,
        "facts": facts,
        "ticks": ticks,
        "protocol_metadata_records": metadata_count,
        "source_first_ordinal": metadata_count,
        "source_last_ordinal": migration_ordinal,
        "post_migration_ticks_verified": post_ticks,
    }


def verify_legacy_provenance(
    original: Path | str,
    prepared: Path | str,
    manifest: Path | str,
    arrival: Path | str,
    *,
    reviewed_source_sha256: str,
    reviewed_manifest_sha256: str,
    migration_lineage: str,
    migration_ordinal: int,
    migration_record_hash: str,
) -> dict[str, Any]:
    """Return metadata-only evidence or refuse without changing an artifact."""
    source_hash = _hex(reviewed_source_sha256, "reviewed source hash")
    manifest_hash = _hex(reviewed_manifest_sha256, "reviewed manifest hash")
    migration_hash = _hex(migration_record_hash, "migration record hash")
    if not migration_lineage or type(migration_ordinal) is not int or migration_ordinal < 0:
        raise ProvenanceRefused("migration head S is malformed")
    original_path = _regular(original, "original source")
    prepared_path = _regular(prepared, "prepared source")
    manifest_path = _regular(manifest, "preparation manifest")
    arrival_path = _regular(arrival, "Arrival target")
    if len({original_path, prepared_path, manifest_path, arrival_path}) != 4:
        raise ProvenanceRefused("all four input artifacts must be distinct")

    manifest_value, actual_manifest_hash = _manifest(manifest_path, manifest_hash)
    source = _verify_sources(
        original_path, prepared_path, manifest_value, source_hash
    )
    arrival_evidence = _verify_arrival(
        arrival_path,
        prepared_path,
        source,
        lineage=migration_lineage,
        migration_ordinal=migration_ordinal,
        migration_hash=migration_hash,
    )
    if _sha256(manifest_path) != actual_manifest_hash:
        raise ProvenanceRefused("preparation manifest changed during verification")
    if _sha256(original_path) != source_hash:
        raise ProvenanceRefused("original source changed during verification")
    if _sha256(prepared_path) != manifest_value["output_sha256"]:
        raise ProvenanceRefused("prepared source changed during verification")
    return {
        "schema": SCHEMA,
        "status": "preserved-boundaries-with-audited-transformation",
        "trust": {
            "reviewed_source_sha256": source_hash,
            "reviewed_manifest_sha256": manifest_hash,
            "migration_head": {
                "lineage": migration_lineage,
                "ordinal": migration_ordinal,
                "record_hash": migration_hash,
            },
            "pins": "caller-supplied",
            "pin_independence_verified": False,
            "migration_report_signature_verified": False,
        },
        "preparation": {
            "policy": POLICY,
            "source_sha256": source_hash,
            "prepared_sha256": manifest_value["output_sha256"],
            "rows": source.rows,
            "facts": source.facts,
            "ticks": source.ticks,
            "transformed_rows": source.changed,
            "byte_identical_rows": source.unchanged,
        },
        "commitments": {
            "original_tick_chain": "structurally-verified",
            "unchained_historical_ticks": source.unchained_ticks,
            "unchanged_historical_windows": source.unchanged_windows,
            "explained_transformation_windows": source.explained_windows,
            "historical_authorship_verified": False,
            "ordinary_envelope_signatures_verified": False,
            "inner_fact_tick_signatures_verified": False,
            "meaning": "old commitments bind the pinned original rows; mapped rows carry no historical authorship claim",
        },
        "arrival": {
            **arrival_evidence,
            "record_hash_chain": "verified",
            "registry_forming_signatures": "verified",
            "prepared_rows_at_pinned_prefix": "exact-in-order",
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify audited legacy provenance through a pinned Arrival migration prefix."
    )
    parser.add_argument("original", type=Path)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("arrival", type=Path)
    parser.add_argument("--reviewed-source-sha256", required=True)
    parser.add_argument("--reviewed-manifest-sha256", required=True)
    parser.add_argument("--migration-lineage", required=True)
    parser.add_argument("--migration-ordinal", required=True, type=int)
    parser.add_argument("--migration-record-hash", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def _publish_output(path: Path, value: dict[str, Any], inputs: set[Path]) -> None:
    resolved = path.expanduser().resolve(strict=False)
    if resolved in inputs:
        raise ProvenanceRefused("output must not alias an input artifact")
    if resolved.exists() or resolved.is_symlink():
        raise ProvenanceRefused("output already exists and will not be overwritten")
    if not resolved.parent.is_dir():
        raise ProvenanceRefused("output parent directory does not exist")
    fd, raw = tempfile.mkstemp(prefix=f".{resolved.name}.", suffix=".stage", dir=resolved.parent)
    staged = Path(raw)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True).encode())
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staged, resolved)
        except FileExistsError as exc:
            raise ProvenanceRefused("output appeared during verification") from exc
    finally:
        staged.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_legacy_provenance(
            args.original,
            args.prepared,
            args.manifest,
            args.arrival,
            reviewed_source_sha256=args.reviewed_source_sha256,
            reviewed_manifest_sha256=args.reviewed_manifest_sha256,
            migration_lineage=args.migration_lineage,
            migration_ordinal=args.migration_ordinal,
            migration_record_hash=args.migration_record_hash,
        )
        if args.output is None:
            print(json.dumps(result, sort_keys=True))
        else:
            inputs = {
                Path(item).expanduser().resolve(strict=False)
                for item in (args.original, args.prepared, args.manifest, args.arrival)
            }
            _publish_output(args.output, result, inputs)
    except ProvenanceError as exc:
        print(f"provenance verification refused: {exc}", file=sys.stderr)
        return 2
    # CLI errors must never echo malformed row content through a dependency's
    # exception. Library callers still receive the typed refusals above.
    except Exception as exc:  # noqa: BLE001
        print(
            "provenance verification refused: unexpected input or storage "
            f"failure ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
