"""Captured exact export through attested ledger contracts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import suppress
from typing import Any

from .arrival_contract import (
    ExportedPrefix,
    Full,
    Head,
    HeadMismatch,
    NotAuthority,
    NotSupported,
    Profile,
    StoreDescriptor,
    Watermark,
)
from .arrival_head_seam import AttestedLedger, Compared, Indeterminate, PreGenesis
from .arrival_registry import BackendRegistry


def _close(handle: Any) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _require_role(descriptor: StoreDescriptor) -> None:
    if descriptor.role not in (Profile.AUTHORITY, Profile.REPLICA):
        raise NotAuthority("exact transfer requires an explicit Authority or Replica role")


def _captured(ledger: AttestedLedger) -> Head:
    comparison = ledger.opened.comparison
    if isinstance(comparison, Compared):
        return comparison.presented
    if isinstance(comparison, Indeterminate):
        raise comparison.refusal
    if isinstance(comparison, PreGenesis):
        if comparison.ledger_refusal is not None:
            raise comparison.ledger_refusal
        raise HeadMismatch("the export source has no captured head")
    raise TypeError("registry opener returned an unsupported head comparison")


def _verify_prefix(ledger: AttestedLedger, captured: Head, through: Head) -> None:
    if through.lineage != captured.lineage or through.ordinal > captured.ordinal:
        raise HeadMismatch("selected prefix lies outside the captured ledger head")
    if ledger.head_at(Watermark(through.lineage, through.ordinal)) != through:
        raise HeadMismatch("selected prefix hash differs from captured ledger membership")
    if ledger.verify(Full(through=through)) != through:
        raise HeadMismatch("full verification did not establish the selected prefix")


class CapturedExport:
    """A single-use exact byte stream that retains its adapter resources."""

    def __init__(
        self, ledger: AttestedLedger, query: Any, captured: Head, prefix: ExportedPrefix
    ) -> None:
        self.captured_head = captured
        self.head = prefix.head
        self.codec = prefix.codec
        self.manifest: Mapping[str, Any] = dict(prefix.manifest)
        self._prefix = prefix
        self._ledger = ledger
        self._query = query
        self._closed = False
        self.records = self._records()

    def _records(self) -> Iterator[bytes]:
        try:
            if self._closed:
                raise ValueError("captured export is closed")
            yield from self._prefix.records
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close(self._prefix.records)
        _close(self._query)
        _close(self._ledger)

    def __enter__(self) -> CapturedExport:
        if self._closed:
            raise ValueError("captured export is closed")
        return self

    def __exit__(self, *_unused: Any) -> None:
        self.close()


def open_export(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    *,
    through: Head | None = None,
    codec: str = "arrival-jsonl-v1",
) -> CapturedExport:
    """Verify and retain one exact prefix; no projection snapshot is required."""
    _require_role(descriptor)
    ledger, query = registry.open(descriptor)
    try:
        if not isinstance(ledger, AttestedLedger):
            raise TypeError("registry opener must return an AttestedLedger")
        captured = _captured(ledger)
        selected = captured if through is None else through
        if codec not in ledger.capabilities().export_codecs:
            raise NotSupported(f"backend does not advertise export codec {codec!r}")
        _verify_prefix(ledger, captured, selected)
        prefix = ledger.export(through=selected, codec=codec)
        if prefix.head != selected or prefix.codec != codec:
            _close(prefix.records)
            raise HeadMismatch("backend export differs from the requested prefix or codec")
        return CapturedExport(ledger, query, captured, prefix)
    except BaseException:
        _close(query)
        _close(ledger)
        raise
