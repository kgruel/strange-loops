"""Operation-fresh signing credentials for engine write coordinators.

This module contains values only.  It has no store, projection, or custody
dependency, so supported Arrival coordinators can accept signer injection
without importing the legacy SQLite handle implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = ["CredentialProvider", "WriteCredentials"]


@dataclass(frozen=True)
class WriteCredentials:
    """The distinct domain-separated signers supplied for one write.

    ``tick_signer`` signs tick commitments, ``fact_signer`` signs inner fact
    commitments, and ``arrival_signer`` signs outer Arrival envelopes.  A
    missing signer means that axis is unsigned; one signer is never used as a
    fallback for another.
    """

    tick_signer: Callable[[str], str] | None = None
    fact_signer: Callable[[str, str], str | None] | None = None
    arrival_signer: Callable[[str, str], str | None] | None = None


class CredentialProvider(Protocol):
    """Supply credentials at the moment of each write operation."""

    def for_write(self, vertex: Path) -> WriteCredentials: ...
