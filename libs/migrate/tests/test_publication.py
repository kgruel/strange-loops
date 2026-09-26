"""Disposable-file coverage for the offline descriptor publication primitive."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from engine.arrival_contract import Head

import migrate.publication as publication
from migrate import (
    PublicationError,
    PublicationRefused,
    PublicationRequest,
    publish_candidate_descriptor,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _request(tmp_path: Path, **changes: object) -> PublicationRequest:
    live = tmp_path / "live" / "project.vertex"
    candidate = tmp_path / "review" / "candidate.vertex"
    source = tmp_path / "live" / "project.jsonl"
    store = tmp_path / "arrival" / "lineage.arrival"
    backup = tmp_path / "archive" / "project.vertex.prepublish"
    receipt = tmp_path / "receipts" / "publication.json"
    for directory in {path.parent for path in (live, candidate, source, store, backup, receipt)}:
        directory.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'{"t":"fact"}\n')
    store.write_bytes(b"synthetic Arrival bytes at A\n")
    suffix = 'loops { concept { fold { items "collect" 1 } } }\n'
    live.write_text('name "project"\nstore "project.jsonl"\n' + suffix, encoding="utf-8")
    candidate.write_text(
        f'name "project"\nstore "{store}" backend="file" '
        'lineage="lineage-1" role="authority"\n' + suffix,
        encoding="utf-8",
    )
    values: dict[str, object] = {
        "live_vertex": live,
        "candidate_vertex": candidate,
        "legacy_live_source": source,
        "arrival_store": store,
        "backup_path": backup,
        "receipt_path": receipt,
        "live_vertex_sha256": _sha(live.read_bytes()),
        "candidate_vertex_sha256": _sha(candidate.read_bytes()),
        "legacy_source_sha256": _sha(source.read_bytes()),
        "arrival_store_sha256": _sha(store.read_bytes()),
        "reviewed_adoption_head": Head("lineage-1", 4, "a" * 64),
        "provenance_reference": "receipt:provenance-at-A",
        "quiescence_transcript_reference": "transcript:maintenance-window",
    }
    values.update(changes)
    return PublicationRequest(**values)  # type: ignore[arg-type]


def _stage(request: PublicationRequest) -> Path:
    return request.live_vertex.parent / f".{request.live_vertex.name}.arrival-cutover"


def test_success_preserves_data_and_records_observed_vs_asserted_claims(tmp_path: Path) -> None:
    request = _request(tmp_path)
    source_before = request.legacy_live_source.read_bytes()
    store_before = request.arrival_store.read_bytes()

    result = publish_candidate_descriptor(request)

    assert result.backup_path.read_bytes() == (
        b'name "project"\nstore "project.jsonl"\nloops { concept { fold { items "collect" 1 } } }\n'
    )
    assert result.live_vertex.read_bytes() == request.candidate_vertex.read_bytes()
    assert request.legacy_live_source.read_bytes() == source_before
    assert request.arrival_store.read_bytes() == store_before
    assert not _stage(request).exists()
    receipt = json.loads(request.receipt_path.read_text(encoding="utf-8"))
    assert receipt["observed"]["sha256"]["arrival_store"] == request.arrival_store_sha256
    assert receipt["caller_assertions_not_verified_here"]["reviewed_adoption_head"]["ordinal"] == 4
    assert (
        receipt["caller_assertions_not_verified_here"]["provenance_reference"]
        == "receipt:provenance-at-A"
    )


@pytest.mark.parametrize(
    "field",
    [
        "live_vertex_sha256",
        "candidate_vertex_sha256",
        "legacy_source_sha256",
        "arrival_store_sha256",
    ],
)
def test_each_independent_pin_refuses_without_artifacts(tmp_path: Path, field: str) -> None:
    request = _request(tmp_path, **{field: "0" * 64})

    with pytest.raises(PublicationRefused) as raised:
        publish_candidate_descriptor(request)

    assert raised.value.effect == "not_attempted"
    assert not request.backup_path.exists()
    assert not request.receipt_path.exists()
    assert not _stage(request).exists()


@pytest.mark.parametrize(
    "replacement",
    [
        'store "relative.arrival" backend="file" lineage="lineage-1" role="authority"',
        'store "/wrong.arrival" backend="file" lineage="lineage-1" role="authority"',
        'store "/tmp/nope" backend="sqlite" lineage="lineage-1" role="authority"',
        'store "/tmp/nope" backend="file" lineage="lineage-1" role="replica"',
        'store "/tmp/nope" backend="file" lineage="other" role="authority"',
        'store "/tmp/a" backend="file" lineage="lineage-1" role="authority"\n'
        'store "/tmp/b" backend="file" lineage="lineage-1" role="authority"',
    ],
)
def test_descriptor_properties_refuse_before_artifacts(tmp_path: Path, replacement: str) -> None:
    request = _request(tmp_path)
    if '"/wrong.arrival"' in replacement:
        replacement = replacement.replace(
            "/wrong.arrival", str(request.arrival_store.parent / "wrong.arrival")
        )
    elif '"/tmp/nope"' in replacement:
        replacement = replacement.replace("/tmp/nope", str(request.arrival_store))
    request.candidate_vertex.write_text(
        f'name "project"\n{replacement}\nloops {{ concept {{ fold {{ items "collect" 1 }} }} }}\n',
        encoding="utf-8",
    )
    request = PublicationRequest(
        **{
            **request.__dict__,
            "candidate_vertex_sha256": _sha(request.candidate_vertex.read_bytes()),
        }
    )

    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    assert not request.backup_path.exists()
    assert not _stage(request).exists()


def test_existing_stage_receipt_bad_backup_and_matching_backup(tmp_path: Path) -> None:
    request = _request(tmp_path)
    _stage(request).write_bytes(b"old evidence")
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    _stage(request).unlink()
    request.receipt_path.write_bytes(b"old receipt")
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    request.receipt_path.unlink()
    request.backup_path.write_bytes(b"wrong")
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    request.backup_path.write_bytes(request.live_vertex.read_bytes())

    publish_candidate_descriptor(request)
    assert request.backup_path.read_bytes() != request.candidate_vertex.read_bytes()


def test_symlink_and_hard_link_aliases_refuse(tmp_path: Path) -> None:
    request = _request(tmp_path)
    link = request.candidate_vertex.parent / "linked.vertex"
    link.symlink_to(request.candidate_vertex)
    linked_request = PublicationRequest(
        **{
            **request.__dict__,
            "candidate_vertex": link,
            "candidate_vertex_sha256": _sha(link.read_bytes()),
        }
    )
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(linked_request)

    request = _request(tmp_path / "hard")
    request.legacy_live_source.unlink()
    os.link(request.live_vertex, request.legacy_live_source)
    aliased_request = PublicationRequest(
        **{
            **request.__dict__,
            "legacy_source_sha256": _sha(request.legacy_live_source.read_bytes()),
        }
    )
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(aliased_request)


@pytest.mark.parametrize("role", ["legacy", "arrival"])
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_descriptor_declared_alias_refuses_before_artifacts(
    tmp_path: Path, role: str, link_kind: str
) -> None:
    request = _request(tmp_path)
    data = request.legacy_live_source if role == "legacy" else request.arrival_store
    alias = data.with_name("alias" + data.suffix)
    if link_kind == "symlink":
        alias.symlink_to(data)
    else:
        os.link(data, alias)
    vertex = request.live_vertex if role == "legacy" else request.candidate_vertex
    original_text = vertex.read_text(encoding="utf-8")
    location = '"project.jsonl"' if role == "legacy" else f'"{data}"'
    vertex.write_text(original_text.replace(location, f'"{alias}"'), encoding="utf-8")
    pin = "live_vertex_sha256" if role == "legacy" else "candidate_vertex_sha256"
    request = replace(request, **{pin: _sha(vertex.read_bytes())})
    before = request.live_vertex.read_bytes()

    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)

    assert request.live_vertex.read_bytes() == before
    assert not request.backup_path.exists()
    assert not request.receipt_path.exists()
    assert not _stage(request).exists()


def test_candidate_cannot_substitute_another_absolute_parent_spelling(tmp_path: Path) -> None:
    request = _request(tmp_path)
    alias = tmp_path / "arrival-alias"
    alias.symlink_to(request.arrival_store.parent, target_is_directory=True)
    candidate = request.candidate_vertex
    candidate.write_text(
        candidate.read_text(encoding="utf-8").replace(
            str(request.arrival_store), str(alias / request.arrival_store.name)
        ),
        encoding="utf-8",
    )
    request = replace(request, candidate_vertex_sha256=_sha(candidate.read_bytes()))
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    assert not request.backup_path.exists()


def test_publication_is_not_an_arrival_to_arrival_routing_change(tmp_path: Path) -> None:
    request = _request(tmp_path)
    live = request.live_vertex
    live.write_text(
        live.read_text(encoding="utf-8").replace(
            'store "project.jsonl"',
            'store "project.jsonl" backend="file" lineage="old" role="authority"',
        ),
        encoding="utf-8",
    )
    request = replace(request, live_vertex_sha256=_sha(live.read_bytes()))
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    assert not request.backup_path.exists()


@pytest.mark.parametrize("role", ["backup_path", "receipt_path", "stage_path"])
def test_existing_cyclic_symlink_artifacts_have_typed_refusal(tmp_path: Path, role: str) -> None:
    request = _request(tmp_path)
    artifact = _stage(request) if role == "stage_path" else getattr(request, role)
    artifact.symlink_to(artifact.name)
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    assert artifact.is_symlink()
    assert request.live_vertex.read_bytes() != request.candidate_vertex.read_bytes()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("live_vertex", Path("relative.vertex")),
        ("receipt_path", "/absolute-but-not-Path"),
        ("live_vertex_sha256", "A" * 64),
        ("arrival_store_sha256", "short"),
        ("reviewed_adoption_head", Head("", 4, "a" * 64)),
        ("reviewed_adoption_head", Head("lineage-1", True, "a" * 64)),
        ("reviewed_adoption_head", Head("lineage-1", -1, "a" * 64)),
        ("reviewed_adoption_head", Head("lineage-1", 4, "short")),
        ("provenance_reference", " "),
        ("quiescence_transcript_reference", None),
    ],
)
def test_malformed_request_refuses_without_artifacts(
    tmp_path: Path, field: str, value: object
) -> None:
    original = _request(tmp_path)
    request = replace(original, **{field: value})
    with pytest.raises(PublicationRefused) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.effect == "not_attempted"
    assert not original.backup_path.exists()
    assert not original.receipt_path.exists()
    assert not _stage(original).exists()


def test_stage_drift_during_final_preflight_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    original = publication._validate_descriptors
    calls = 0

    def change_stage(*args: object) -> None:
        nonlocal calls
        original(*args)  # type: ignore[arg-type]
        calls += 1
        if calls == 2:
            _stage(request).write_bytes(b"unexpected stage content")

    monkeypatch.setattr(publication, "_validate_descriptors", change_stage)
    with pytest.raises(PublicationRefused) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.effect == "not_attempted"
    assert _sha(request.live_vertex.read_bytes()) == request.live_vertex_sha256
    assert not request.receipt_path.exists()


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o644, 0o444])
def test_publication_preserves_permissions_with_private_backup_and_receipt(
    tmp_path: Path, mode: int
) -> None:
    request = _request(tmp_path)
    request.live_vertex.chmod(mode)
    result = publish_candidate_descriptor(request)
    assert request.live_vertex.stat().st_mode & 0o7777 == mode
    assert result.live_vertex_mode == mode
    assert request.backup_path.stat().st_mode & 0o7777 == 0o600
    assert request.receipt_path.stat().st_mode & 0o7777 == 0o600
    receipt = json.loads(request.receipt_path.read_text(encoding="utf-8"))
    assert receipt["observed"]["file_modes"] == {
        "live_vertex_before": mode, "live_vertex_after": mode,
    }


@pytest.mark.parametrize("role", ["live", "stage"])
def test_mode_drift_before_replace_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    request = _request(tmp_path)
    request.live_vertex.chmod(0o644)
    original_write = publication._write_exclusive_and_sync

    def change_mode(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        original_write(path, data, mode=mode)
        if path == _stage(request):
            (request.live_vertex if role == "live" else path).chmod(0o600)

    monkeypatch.setattr(publication, "_write_exclusive_and_sync", change_mode)
    with pytest.raises(PublicationRefused, match="file mode changed") as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "final_preflight"
    assert raised.value.effect == "not_attempted"
    assert _sha(request.live_vertex.read_bytes()) == request.live_vertex_sha256


def test_stage_mode_failure_retains_private_stage_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request.live_vertex.chmod(0o644)
    original_chmod = os.fchmod

    def refuse_mode(fd: int, mode: int) -> None:
        if mode == 0o644:
            raise OSError("injected stage chmod failure")
        original_chmod(fd, mode)

    monkeypatch.setattr(publication.os, "fchmod", refuse_mode)
    with pytest.raises(PublicationRefused) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "stage"
    assert _stage(request).stat().st_mode & 0o7777 == 0o600
    assert _sha(request.live_vertex.read_bytes()) == request.live_vertex_sha256


def test_descriptor_hash_drift_is_not_relabeled_as_a_parse_error(tmp_path: Path) -> None:
    request = _request(tmp_path)
    paths, pins = publication._validate_request(request)
    request.candidate_vertex.write_bytes(b"changed")
    with pytest.raises(PublicationRefused, match="candidate vertex SHA-256") as raised:
        publication._validate_descriptors(request, paths, pins)
    assert raised.value.phase == "preflight"
    assert raised.value.pins == pins


def test_drift_before_replace_retains_stage_and_never_replaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    original = publication._write_exclusive_and_sync

    def drift(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        original(path, data, mode=mode)
        if path == _stage(request):
            request.legacy_live_source.write_bytes(b"drift")

    monkeypatch.setattr(publication, "_write_exclusive_and_sync", drift)
    with pytest.raises(PublicationRefused) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.effect == "not_attempted"
    assert request.live_vertex.read_bytes() != request.candidate_vertex.read_bytes()
    assert _stage(request).exists()


def test_backup_write_and_fsync_failures_leave_live_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)

    def fail_write(path: Path, data: bytes) -> None:
        raise OSError("injected backup write")

    with monkeypatch.context() as patch:
        patch.setattr(publication, "_write_exclusive_and_sync", fail_write)
        with pytest.raises(PublicationRefused) as raised:
            publish_candidate_descriptor(request)
        assert raised.value.effect == "not_attempted"
        assert request.live_vertex.read_bytes() != request.candidate_vertex.read_bytes()

    request = _request(tmp_path / "fsync")
    real_fsync = os.fsync
    calls = 0

    def fail_first_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected backup fsync")
        real_fsync(fd)

    monkeypatch.setattr(publication.os, "fsync", fail_first_fsync)
    with pytest.raises(PublicationRefused) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.effect == "not_attempted"
    assert calls == 1
    assert request.backup_path.read_bytes() == request.live_vertex.read_bytes()
    assert request.live_vertex.read_bytes() != request.candidate_vertex.read_bytes()


@pytest.mark.parametrize("artifact", ["stage", "receipt"])
def test_artifact_write_then_failure_retains_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: str
) -> None:
    request = _request(tmp_path)
    fail_path = _stage(request) if artifact == "stage" else request.receipt_path
    original_write = publication._write_exclusive_and_sync

    def fail_after_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        original_write(path, data, mode=mode)
        if path == fail_path:
            raise OSError("injected after artifact write/fsync")

    monkeypatch.setattr(publication, "_write_exclusive_and_sync", fail_after_write)
    with pytest.raises(PublicationError) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == artifact
    assert raised.value.effect == ("not_attempted" if artifact == "stage" else "known_published")
    assert fail_path.is_file()
    assert request.backup_path.is_file()
    evidence = fail_path.read_bytes()
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    assert fail_path.read_bytes() == evidence


def test_matching_backup_is_synced_before_stage_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request.backup_path.write_bytes(request.live_vertex.read_bytes())
    real_fsync = publication.os.fsync
    real_write = publication._write_exclusive_and_sync
    calls: list[int] = []

    def capture_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    def check_stage(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        if path == _stage(request):
            assert len(calls) == 2  # Existing backup file and its parent directory.
        real_write(path, data, mode=mode)

    monkeypatch.setattr(publication.os, "fsync", capture_fsync)
    monkeypatch.setattr(publication, "_write_exclusive_and_sync", check_stage)
    publish_candidate_descriptor(request)


def test_zero_byte_write_refuses_without_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr(publication.os, "write", lambda *_args: 0)
    with pytest.raises(PublicationRefused) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "backup"
    assert request.backup_path.read_bytes() == b""
    assert _sha(request.live_vertex.read_bytes()) == request.live_vertex_sha256


def test_final_read_failure_does_not_claim_verified_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    original_require_hash = publication._require_hash

    def fail_final_read(*args: object, phase: str = "preflight") -> None:
        if args[2] == "published live vertex":
            raise PublicationRefused("injected final read", phase="final_live_verify")
        original_require_hash(*args, phase=phase)  # type: ignore[arg-type]

    monkeypatch.setattr(publication, "_require_hash", fail_final_read)
    with pytest.raises(PublicationError) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "final_live_verify"
    assert raised.value.effect == "replace_returned_unverified"
    assert request.live_vertex.read_bytes() == request.candidate_vertex.read_bytes()


@pytest.mark.parametrize("mismatch", ["bytes", "mode"])
def test_final_mismatch_does_not_claim_verified_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    request = _request(tmp_path)
    request.live_vertex.chmod(0o644)
    real_replace = os.replace

    def replace_then_change(source: Path, destination: Path) -> None:
        real_replace(source, destination)
        if mismatch == "bytes":
            destination.write_bytes(b"unexpected live content")
        else:
            destination.chmod(0o600)

    monkeypatch.setattr(publication.os, "replace", replace_then_change)
    with pytest.raises(PublicationError) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "final_live_verify"
    assert raised.value.effect == "replace_returned_unverified"
    assert raised.value.as_dict()["effect_scope"] == "live-descriptor-replacement"
    assert not request.receipt_path.exists()
    assert _sha(request.backup_path.read_bytes()) == request.live_vertex_sha256


def test_replace_then_raise_is_honest_about_unknown_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    real_replace = os.replace

    def replace_then_raise(source: Path, destination: Path) -> None:
        real_replace(source, destination)
        raise OSError("injected after replacement")

    monkeypatch.setattr(publication.os, "replace", replace_then_raise)
    with pytest.raises(PublicationError) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "replace"
    assert raised.value.effect == "replace_entered_unknown"
    assert request.live_vertex.read_bytes() == request.candidate_vertex.read_bytes()
    assert not request.receipt_path.exists()


@pytest.mark.parametrize("point", ["before", "after"])
def test_real_process_termination_retains_evidence_and_refuses_blind_retry(
    tmp_path: Path, point: str
) -> None:
    request = _request(tmp_path)
    payload = {
        "paths": {
            name: str(getattr(request, name))
            for name in (
                "live_vertex",
                "candidate_vertex",
                "legacy_live_source",
                "arrival_store",
                "backup_path",
                "receipt_path",
            )
        },
        "pins": {
            name: getattr(request, name)
            for name in (
                "live_vertex_sha256",
                "candidate_vertex_sha256",
                "legacy_source_sha256",
                "arrival_store_sha256",
            )
        },
    }
    payload_path = tmp_path / "request.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    script = """
import json, os, sys
from pathlib import Path
from engine.arrival_contract import Head
from migrate import PublicationRequest, publish_candidate_descriptor
import migrate.publication as publication
payload = json.loads(Path(sys.argv[1]).read_text())
request = PublicationRequest(
    **{key: Path(value) for key, value in payload[\"paths\"].items()},
    **payload[\"pins\"],
    reviewed_adoption_head=Head(\"lineage-1\", 4, \"a\" * 64),
    provenance_reference=\"receipt:provenance-at-A\",
    quiescence_transcript_reference=\"transcript:maintenance-window\",
)
real_replace = publication.os.replace
def stop_before(source, destination):
    os._exit(19)
def stop_after(source, destination):
    real_replace(source, destination)
    os._exit(20)
publication.os.replace = stop_before if sys.argv[2] == \"before\" else stop_after
publish_candidate_descriptor(request)
"""
    env = {
        **os.environ,
        "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "LOOPS_HOME": str(tmp_path / "loops-home"),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script, str(payload_path), point],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == (19 if point == "before" else 20)
    assert not request.receipt_path.exists()
    with pytest.raises(PublicationRefused):
        publish_candidate_descriptor(request)
    if point == "before":
        assert _stage(request).exists()
        assert request.live_vertex.read_bytes() != request.candidate_vertex.read_bytes()
    else:
        assert not _stage(request).exists()
        assert request.live_vertex.read_bytes() == request.candidate_vertex.read_bytes()


def test_directory_failure_is_unverified_but_receipt_failure_is_known_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    original_sync = publication._sync_directory
    calls = 0

    def fail_live_directory(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected live directory fsync")
        original_sync(path)

    monkeypatch.setattr(publication, "_sync_directory", fail_live_directory)
    with pytest.raises(PublicationError) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "live_directory_fsync"
    assert raised.value.effect == "replace_returned_unverified"
    assert request.live_vertex.read_bytes() == request.candidate_vertex.read_bytes()
    assert not request.receipt_path.exists()

    request = _request(tmp_path / "receipt")
    original_write = publication._write_exclusive_and_sync

    def fail_receipt(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        if path == request.receipt_path:
            raise OSError("injected receipt write")
        original_write(path, data, mode=mode)

    monkeypatch.setattr(publication, "_write_exclusive_and_sync", fail_receipt)
    with pytest.raises(PublicationError) as raised:
        publish_candidate_descriptor(request)
    assert raised.value.phase == "receipt"
    assert raised.value.effect == "known_published"
    assert request.live_vertex.read_bytes() == request.candidate_vertex.read_bytes()
