"""Exact export publishes complete artifacts and preserves failure evidence."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from engine.arrival import ArrivalError
from engine.arrival_file_backend import FileLedger, file_projection_path

from sdk import ArrivalRefusal, ExportPublicationError, export_target, init_vertex, read_summary


@pytest.fixture(autouse=True)
def isolated_witness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.mark.parametrize("store_name", ["ledger.arrival", "ledger.db", "ledger.odd"])
def test_exact_export_and_projection_do_not_depend_on_ledger_suffix(tmp_path, store_name):
    target = tmp_path / "source.vertex"
    initialized = init_vertex(
        target, backend="file", location=store_name, observer="alice"
    )
    ledger_path = Path(initialized.store.location)
    original = ledger_path.read_bytes()
    output = tmp_path / "export.jsonl"
    result = export_target(target, output)
    assert output.read_bytes() == original
    assert ledger_path.read_bytes() == original
    assert result.byte_count == len(original)
    assert result.head == result.captured_head
    assert result.manifest["count"] == len(original.splitlines())
    assert file_projection_path(ledger_path) != ledger_path
    assert read_summary(target).basis.captured_head == result.head
    json.dumps(result.as_dict(), allow_nan=False)


def test_existing_output_is_not_replaced(tmp_path):
    target = tmp_path / "source.vertex"
    init_vertex(target, store_type="arrival", observer="alice")
    output = tmp_path / "export.jsonl"
    output.write_bytes(b"existing artifact")
    with pytest.raises(ExportPublicationError) as caught:
        export_target(target, output)
    assert caught.value.published is False
    assert output.read_bytes() == b"existing artifact"
    assert list(tmp_path.glob(".export.jsonl.*")) == []


def test_late_source_failure_never_publishes_partial_output(tmp_path, monkeypatch):
    target = tmp_path / "source.vertex"
    init_vertex(target, store_type="arrival", observer="alice")
    output = tmp_path / "export.jsonl"
    original = FileLedger.export

    def damaged(self, **kwargs):
        prefix = original(self, **kwargs)

        def records():
            try:
                yield next(prefix.records)
                raise ArrivalError("injected late source refusal")
            finally:
                prefix.records.close()

        return replace(prefix, records=records())

    monkeypatch.setattr(FileLedger, "export", damaged)
    with pytest.raises(ArrivalRefusal, match="late source refusal"):
        export_target(target, output)
    assert not output.exists()
    assert list(tmp_path.glob(".export.jsonl.*")) == []


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_source_io_failure_retains_source_error_and_closes_stream(
    tmp_path, monkeypatch, error_type
):
    target = tmp_path / "source.vertex"
    init_vertex(target, store_type="arrival", observer="alice")
    output = tmp_path / "export.jsonl"
    original = FileLedger.export
    failure = error_type("source drain failed")
    closed = []

    def damaged(self, **kwargs):
        prefix = original(self, **kwargs)

        def records():
            try:
                yield next(prefix.records)
                raise failure
            finally:
                prefix.records.close()
                closed.append(True)

        return replace(prefix, records=records())

    monkeypatch.setattr(FileLedger, "export", damaged)
    with pytest.raises(error_type) as caught:
        export_target(target, output)
    assert caught.value is failure
    assert closed == [True]
    assert not output.exists()
    assert list(tmp_path.glob(".export.jsonl.*")) == []


def test_output_sync_failure_retains_publication_error(tmp_path, monkeypatch):
    target = tmp_path / "source.vertex"
    init_vertex(target, store_type="arrival", observer="alice")
    output = tmp_path / "export.jsonl"
    failure = OSError("output data sync failed")

    def fail_sync(fd):
        raise failure

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(ExportPublicationError) as caught:
        export_target(target, output)
    assert caught.value.cause is failure
    assert caught.value.published is False
    assert not output.exists()
    assert list(tmp_path.glob(".export.jsonl.*")) == []


@pytest.mark.parametrize("error_type", [ArrivalError, PermissionError])
def test_source_failure_survives_output_close_failure(tmp_path, monkeypatch, error_type):
    target = tmp_path / "source.vertex"
    init_vertex(target, store_type="arrival", observer="alice")
    output = tmp_path / "export.jsonl"
    original_export = FileLedger.export
    original_fdopen = os.fdopen
    failure = error_type("source drain failed")
    closed = []

    class FailingClose:
        def __init__(self, stream):
            self.stream = stream

        def write(self, chunk):
            return self.stream.write(chunk)

        def close(self):
            self.stream.close()
            closed.append(True)
            raise OSError("output close failed too")

    def damaged(self, **kwargs):
        prefix = original_export(self, **kwargs)

        def records():
            try:
                yield next(prefix.records)
                raise failure
            finally:
                prefix.records.close()

        return replace(prefix, records=records())

    monkeypatch.setattr(FileLedger, "export", damaged)
    monkeypatch.setattr(os, "fdopen", lambda *a, **kw: FailingClose(original_fdopen(*a, **kw)))
    expected = ArrivalRefusal if error_type is ArrivalError else PermissionError
    with pytest.raises(expected) as caught:
        export_target(target, output)
    original_failure = caught.value.__cause__ if expected is ArrivalRefusal else caught.value
    assert original_failure is failure
    assert any("output close failed too" in note for note in failure.__notes__)
    assert closed == [True]
    assert not output.exists()
    assert list(tmp_path.glob(".export.jsonl.*")) == []


def test_directory_sync_failure_reports_complete_visible_artifact(tmp_path, monkeypatch):
    target = tmp_path / "source.vertex"
    initialized = init_vertex(target, store_type="arrival", observer="alice")
    original_bytes = Path(initialized.store.location).read_bytes()
    output = tmp_path / "export.jsonl"
    original_fsync = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(ExportPublicationError) as caught:
        export_target(target, output)
    assert caught.value.published is True
    assert output.read_bytes() == original_bytes
    assert caught.value.as_dict()["outcome"] == "artifact-durability-unknown"
    json.dumps(caught.value.as_dict(), allow_nan=False)
