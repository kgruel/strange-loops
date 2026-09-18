#!/usr/bin/env python3
"""Prepare a reviewed JSONL copy with explicit legacy unattributed labels.

This is an offline, pre-migration preparation utility.  It does not import the
migration or Arrival protocol packages, create keys, or make an authorship
claim.  Its one transformation replaces an *exactly empty* ``observer`` on a
flat, unsigned legacy fact with ``legacy/unattributed``.  The accompanying
manifest makes the otherwise deliberate semantic change reviewable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POLICY = "legacy-unattributed-v1"
NORMALIZED_OBSERVER = "legacy/unattributed"


class PreparationError(Exception):
    """Base error for offline unattributed-row preparation."""


class PreparationRefused(PreparationError):
    """Input or destination does not satisfy the preparation policy."""


class SourceChanged(PreparationError):
    """The copied source changed while preparation was in progress."""


@dataclass(frozen=True)
class AffectedRow:
    """One reviewed row whose empty observer was made explicit."""

    coordinate: int
    fact_id: str
    original_line_sha256: str
    normalized_line_sha256: str

    def manifest_value(self) -> dict[str, object]:
        return {
            "coordinate": self.coordinate,
            "id": self.fact_id,
            "normalized_line_sha256": self.normalized_line_sha256,
            "original_line_sha256": self.original_line_sha256,
        }


@dataclass(frozen=True)
class PreparationResult:
    """Published paths and hashes for a successful offline preparation."""

    source_path: Path
    output_path: Path
    manifest_path: Path
    source_sha256: str
    output_sha256: str
    affected_rows: tuple[AffectedRow, ...]


def _json_object(line: bytes, coordinate: int) -> dict[str, Any]:
    try:
        value = json.loads(
            line.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PreparationRefused(
            f"line {coordinate} is not a valid UTF-8 JSON object: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise PreparationRefused(
            f"line {coordinate} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _reject_nonfinite(value: str) -> None:
    raise PreparationRefused(f"non-finite JSON constant {value!r} is not permitted")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PreparationRefused(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _split_ending(raw_line: bytes) -> tuple[bytes, bytes]:
    if raw_line.endswith(b"\r\n"):
        return raw_line[:-2], b"\r\n"
    if raw_line.endswith(b"\n"):
        return raw_line[:-1], b"\n"
    return raw_line, b""


def _normalized_line(obj: dict[str, Any], ending: bytes) -> bytes:
    try:
        encoded = json.dumps(
            obj,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PreparationRefused(
            f"fact cannot be represented as canonical JSON: {exc}"
        ) from exc
    return encoded + ending


def _affected_line(
    raw_line: bytes, coordinate: int
) -> tuple[AffectedRow | None, bytes | None]:
    content, ending = _split_ending(raw_line)
    if not content.strip():
        return None, None
    obj = _json_object(content, coordinate)
    if obj.get("t") != "fact":
        return None, None

    if "observer" not in obj or obj["observer"] is None:
        raise PreparationRefused(
            f"line {coordinate} is a fact with a missing or null observer; "
            "only exact empty-string observers are eligible"
        )
    if obj["observer"] != "":
        return None, None
    if "rows" in obj:
        raise PreparationRefused(
            f"line {coordinate} is not a flat fact; batch-like rows are not eligible"
        )
    if obj.get("signature") is not None:
        raise PreparationRefused(
            f"line {coordinate} is an empty-observer fact with a signature; "
            "preparation would invalidate its authorship claim"
        )
    fact_id = obj.get("id")
    if not isinstance(fact_id, str):
        raise PreparationRefused(
            f"line {coordinate} has no string fact id for the audit manifest"
        )

    obj["observer"] = NORMALIZED_OBSERVER
    normalized = _normalized_line(obj, ending)
    return (
        AffectedRow(
            coordinate=coordinate,
            fact_id=fact_id,
            original_line_sha256=hashlib.sha256(raw_line).hexdigest(),
            normalized_line_sha256=hashlib.sha256(normalized).hexdigest(),
        ),
        normalized,
    )


def _scan(source: Path) -> tuple[AffectedRow, ...]:
    affected: list[AffectedRow] = []
    with source.open("rb") as handle:
        for coordinate, raw_line in enumerate(handle, start=1):
            changed, _normalized = _affected_line(raw_line, coordinate)
            if changed is not None:
                affected.append(changed)
    if not affected:
        raise PreparationRefused(
            "source contains no eligible unsigned flat facts with observer=''"
        )
    return tuple(affected)


def _write_staged_output(
    source: Path, destination: Path
) -> tuple[Path, tuple[AffectedRow, ...]]:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".stage", dir=destination.parent
    )
    staged = Path(temp_name)
    affected: list[AffectedRow] = []
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            for coordinate, raw_line in enumerate(input_file, start=1):
                changed, normalized = _affected_line(raw_line, coordinate)
                if changed is None:
                    output.write(raw_line)
                else:
                    assert normalized is not None
                    output.write(normalized)
                    affected.append(changed)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged, tuple(affected)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _validate_paths(
    source: Path, output: Path, manifest: Path
) -> tuple[Path, Path, Path]:
    source_path = _canonical_path(source)
    output_path = _canonical_path(output)
    manifest_path = _canonical_path(manifest)
    if not source_path.is_file():
        raise PreparationRefused(
            f"source must be an existing regular file: {source_path}"
        )
    if source_path in {output_path, manifest_path} or output_path == manifest_path:
        raise PreparationRefused(
            "source, output, and manifest must name three distinct paths"
        )
    for label, path in (("output", output_path), ("manifest", manifest_path)):
        if path.exists() or path.is_symlink():
            raise PreparationRefused(
                f"{label} already exists and will not be overwritten: {path}"
            )
        if not path.parent.is_dir():
            raise PreparationRefused(
                f"{label} parent directory does not exist: {path.parent}"
            )
    return source_path, output_path, manifest_path


def _stage_json(destination: Path, value: dict[str, object]) -> Path:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".stage", dir=destination.parent
    )
    staged = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True).encode("utf-8"))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _publish_exclusive(staged: Path, destination: Path) -> None:
    try:
        os.link(staged, destination)
    except FileExistsError as exc:
        raise PreparationRefused(
            f"destination appeared during preparation and was not overwritten: {destination}"
        ) from exc
    finally:
        staged.unlink(missing_ok=True)


def prepare_legacy_unattributed(
    source: Path | str, output: Path | str, manifest: Path | str
) -> PreparationResult:
    """Prepare an exclusive reviewed copy and audit manifest from copied JSONL.

    All validation happens before either final destination is published.  The
    source is hashed before validation and again after staging; a changed source
    aborts and leaves no published output or manifest.
    """
    source_path, output_path, manifest_path = _validate_paths(
        Path(source), Path(output), Path(manifest)
    )
    source_before = _sha256(source_path)
    reviewed = _scan(source_path)
    if _sha256(source_path) != source_before:
        raise SourceChanged("source changed while validation was in progress")

    staged_output: Path | None = None
    staged_manifest: Path | None = None
    published_output = False
    try:
        staged_output, staged_rows = _write_staged_output(source_path, output_path)
        if staged_rows != reviewed:
            raise SourceChanged("source changed while the prepared copy was staged")
        source_after = _sha256(source_path)
        if source_after != source_before:
            raise SourceChanged("source changed while the prepared copy was staged")

        output_sha256 = _sha256(staged_output)
        manifest_value: dict[str, object] = {
            "affected_rows": [row.manifest_value() for row in reviewed],
            "normalized_observer": NORMALIZED_OBSERVER,
            "output_path": str(output_path),
            "output_sha256": output_sha256,
            "policy": POLICY,
            "source_path": str(source_path),
            "source_sha256_after": source_after,
            "source_sha256_before": source_before,
        }
        staged_manifest = _stage_json(manifest_path, manifest_value)
        _publish_exclusive(staged_output, output_path)
        staged_output = None
        published_output = True
        _publish_exclusive(staged_manifest, manifest_path)
        staged_manifest = None
        return PreparationResult(
            source_path=source_path,
            output_path=output_path,
            manifest_path=manifest_path,
            source_sha256=source_before,
            output_sha256=output_sha256,
            affected_rows=reviewed,
        )
    except BaseException:
        if published_output:
            output_path.unlink(missing_ok=True)
        raise
    finally:
        if staged_output is not None:
            staged_output.unlink(missing_ok=True)
        if staged_manifest is not None:
            staged_manifest.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare copied JSONL blank observers as audited legacy/unattributed facts."
    )
    parser.add_argument(
        "source", type=Path, help="copied legacy JSONL source (read only)"
    )
    parser.add_argument("output", type=Path, help="new prepared JSONL destination")
    parser.add_argument(
        "manifest", type=Path, help="new JSON audit manifest destination"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare_legacy_unattributed(args.source, args.output, args.manifest)
    except PreparationError as exc:
        print(f"preparation refused: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "affected_rows": len(result.affected_rows),
                "manifest": str(result.manifest_path),
                "output": str(result.output_path),
                "output_sha256": result.output_sha256,
                "source_sha256": result.source_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
