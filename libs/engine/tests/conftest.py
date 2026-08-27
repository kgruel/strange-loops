"""Shared fixtures for ticks tests.

Fixtures follow the principle: provide building blocks, not pre-wired scenarios.
Tests compose fixtures to express their specific intent.

The arrival test kit lives here too — one home for the key/signer/verifier
scaffolding the five arrival suites share, so a wire-format change touches
one file. (The subprocess worker script in ``test_arrival_gate`` keeps an
inline copy: a child process cannot import this conftest.)
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from engine import EventStore, FileWriter, Stream, Tailer
from tests.helpers import (
    CountProjection,
    Event,
    SumProjection,
    deserialize_event,
    serialize_event,
)

# --- the arrival test kit ---------------------------------------------------

# Domain-separation prefix for every real-crypto arrival test. The constant
# belongs to the COMPOSING layer in production (libs/custody); tests compose
# their own the same way.
ARRIVAL_DOMAIN = "test-arrival-v1"

# A shape-valid founding key (raw-32-byte base64 wire format) for tests that
# only need the grammar's shape check; nothing verifies against it.
STUB_KEY = base64.b64encode(b"k" * 32).decode()

# The one vertex source the arrival store/gate suites declare.
ARRIVAL_VERTEX_SRC = (
    'name "x"\nstore "./x.arrival"\nloops {\n'
    '  a { fold { n "inc" } }\n}\n'
)


def stub_sign(observer: str, commitment: str) -> str:
    """A deterministic stand-in signer with the store's injected shape."""
    return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()


def ed25519_verify(key_b64: str, signature: str, digest: str) -> bool:
    """The injected arrival verifier, composed from real Ed25519."""
    from sign import ed25519

    try:
        public = ed25519.public_key_from_b64(key_b64)
    except ValueError:
        return False
    return ed25519.verify(public, signature, digest.encode(), domain=ARRIVAL_DOMAIN)


class Custodian:
    """One observer's real Ed25519 keypair plus the injected signer shape."""

    def __init__(self, tmp_path: Path, name: str) -> None:
        from sign import ed25519

        self.name = name
        self.keypair = ed25519.load_or_generate(tmp_path / "keys" / name)
        self.public = self.keypair.public_b64

    def signer(self, observer: str, digest: str) -> str | None:
        from sign import ed25519

        return ed25519.sign(self.keypair, digest.encode(), domain=ARRIVAL_DOMAIN)


@pytest.fixture
def keys(tmp_path: Path) -> Custodian:
    """The one custodian the arrival suites mint and sign as."""
    return Custodian(tmp_path, "kyle")


@pytest.fixture
def signer(keys: Custodian):
    """That custodian's injected signer, as a fixture the tests can request."""
    return keys.signer


@pytest.fixture
def tmp_jsonl(tmp_path: Path) -> Path:
    """Temporary JSONL file path (not created yet)."""
    return tmp_path / "events.jsonl"


@pytest.fixture
def stream() -> Stream[Event]:
    """Fresh Stream[Event]."""
    return Stream[Event]()


@pytest.fixture
def event_store() -> EventStore[Event]:
    """In-memory EventStore (no persistence)."""
    return EventStore[Event]()


@pytest.fixture
def sum_projection() -> SumProjection:
    """SumProjection starting at 0."""
    return SumProjection(initial=0)


@pytest.fixture
def count_projection() -> CountProjection:
    """CountProjection starting at 0."""
    return CountProjection(initial=0)


@pytest.fixture
def file_writer(tmp_jsonl: Path) -> FileWriter[Event]:
    """FileWriter that serializes Event to JSONL."""
    return FileWriter(tmp_jsonl, serialize_event)


@pytest.fixture
def tailer(tmp_jsonl: Path) -> Tailer[Event]:
    """Tailer that deserializes Event from JSONL."""
    return Tailer(tmp_jsonl, deserialize_event)
