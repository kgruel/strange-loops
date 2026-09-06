"""Portable exact export artifacts over captured Arrival custody."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from engine.arrival_contract import Commit, Head
from engine.arrival_registry import BackendRegistry
from engine.arrival_transfer import open_export

from .errors import normalize_exception
from .target import _arrival_descriptor
from .types import SdkError, StoreDescriptorInfo, TargetUnsupported, _commit_dict


@dataclass(frozen=True)
class ExportResult:
    source: str
    output: str
    store: StoreDescriptorInfo
    captured_head: Head
    head: Head
    codec: str
    manifest: dict[str, Any]
    byte_count: int
    schema: str = "loops.sdk/export/v2"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExportPublicationError(SdkError):
    """An output artifact failed to publish or establish directory durability."""

    def __init__(self, result: ExportResult, *, published: bool, cause: BaseException) -> None:
        super().__init__(f"export artifact publication failed: {cause}")
        self.result = result
        self.published = published
        self.cause = cause

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "loops.sdk/error/v1",
            "type": type(self).__name__,
            "message": str(self),
            "outcome": (
                "artifact-durability-unknown" if self.published else "artifact-not-published"
            ),
            "result": self.result.as_dict(),
            "published": self.published,
            "source_type": type(self.cause).__name__,
        }


def export_target(
    target: Path | str,
    output: Path | str,
    *,
    through: Head | None = None,
    codec: str = "arrival-jsonl-v1",
    registry: BackendRegistry | None = None,
) -> ExportResult:
    """Publish a complete exact wire prefix exclusively at ``output``.

    The manifest travels in the result. No second artifact or archive framing
    is added. Existing output files are never replaced, and a late source
    refusal cannot publish a truncated successful-looking export. Source read
    errors retain their source classification; output I/O failures carry an
    ExportPublicationError with the artifact's publication state.
    """
    resolved = _arrival_descriptor(target)
    if resolved is None:
        raise TargetUnsupported("export requires an explicit Arrival descriptor target")
    source, _ast, descriptor = resolved
    destination = Path(output).absolute()
    active = registry if registry is not None else BackendRegistry.with_builtin_backends()
    temp: Path | None = None
    try:
        with open_export(active, descriptor, through=through, codec=codec) as exported:
            # Refuse a backend's non-JSON manifest before writing any output.
            manifest = json.loads(json.dumps(dict(exported.manifest), allow_nan=False))
            result = ExportResult(
                source=str(source), output=str(destination),
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                captured_head=exported.captured_head, head=exported.head,
                codec=exported.codec, manifest=manifest, byte_count=0,
            )
            published = False

            @contextmanager
            def publication_errors():
                try:
                    yield
                except OSError as exc:
                    raise ExportPublicationError(
                        result, published=published, cause=exc
                    ) from exc

            with publication_errors():
                fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
                temp = Path(name)
                try:
                    stream = os.fdopen(fd, "wb")
                except BaseException:
                    os.close(fd)
                    raise
            byte_count = 0
            try:
                # Pull source chunks outside output error classification.
                for chunk in exported.records:
                    with publication_errors():
                        byte_count += stream.write(chunk)
                with publication_errors():
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException as failure:
                # Closing buffered output can fail too. Preserve the original
                # source/output classification and attach the cleanup failure.
                try:
                    stream.close()
                except OSError as cleanup_error:
                    failure.add_note(f"export output cleanup also failed: {cleanup_error}")
                raise
            else:
                with publication_errors():
                    stream.close()
            result = ExportResult(
                source=result.source, output=result.output, store=result.store,
                captured_head=result.captured_head, head=result.head,
                codec=result.codec, manifest=manifest, byte_count=byte_count,
            )
            with publication_errors():
                os.link(temp, destination)
                published = True
                directory_fd = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return result
    except Exception as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc
    finally:
        if temp is not None:
            with suppress(OSError):
                temp.unlink()


@dataclass(frozen=True)
class RestoreForwardResult:
    source: str
    receiver: str
    source_store: StoreDescriptorInfo
    receiver_store: StoreDescriptorInfo
    captured_head: Head
    before: Head
    after: Head
    commit: Commit | None
    schema: str = "loops.sdk/restore-forward/v2"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source,
            "receiver": self.receiver,
            "source_store": asdict(self.source_store),
            "receiver_store": asdict(self.receiver_store),
            "captured_head": asdict(self.captured_head),
            "before": asdict(self.before),
            "after": asdict(self.after),
            "commit": _commit_dict(self.commit),
        }


def restore_forward(
    source: Path | str,
    receiver: Path | str,
    *,
    through: Head | None = None,
    registry: BackendRegistry | None = None,
) -> RestoreForwardResult:
    """Restore an existing exact copy through the current witnessed head.

    Both targets require explicit Arrival descriptors. The receiver retains
    its declared role. Its declaration cache and projection remain at their
    existing versions; projection catch-up is a separate explicit operation.
    Unknown outcomes carry the exact before/target heads for reconciliation.
    """
    resolved_source = _arrival_descriptor(source)
    resolved_receiver = _arrival_descriptor(receiver)
    if resolved_source is None or resolved_receiver is None:
        raise TargetUnsupported("restore-forward requires two explicit Arrival descriptors")
    source_path, _source_ast, source_store = resolved_source
    receiver_path, _receiver_ast, receiver_store = resolved_receiver
    active = registry if registry is not None else BackendRegistry.with_builtin_backends()
    try:
        result = active.restore_forward(source_store, receiver_store, through=through)
        return RestoreForwardResult(
            source=str(source_path), receiver=str(receiver_path),
            source_store=StoreDescriptorInfo.from_descriptor(source_store),
            receiver_store=StoreDescriptorInfo.from_descriptor(receiver_store),
            captured_head=result.captured_head, before=result.before,
            after=result.after, commit=result.commit,
        )
    except Exception as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc
