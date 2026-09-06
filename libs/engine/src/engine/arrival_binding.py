"""Adapter-owned identity for the arrival head-attestation seam.

The registry knows which adapter interprets a descriptor location.  The head
seam must therefore receive the adapter's binding spelling and must not turn an
opaque DSN or service URL into a local filesystem path.  The file policy keeps
the historical canonical-path journal spelling and live inode alias check;
other policies produce a backend-namespaced opaque key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .arrival_contract import StoreDescriptor

__all__ = [
    "BindingIdentity",
    "BindingProbeError",
    "BindingProvider",
    "file_binding",
    "is_opaque_key_for",
    "opaque_binding",
]


Identity = tuple[int, int]


class BindingProbeError(OSError):
    """A file identity could not be established despite a present path."""


@dataclass(frozen=True)
class BindingIdentity:
    """The adapter's stable journal key and optional alias evidence.

    ``key`` is the only value persisted in the historical head journal.
    ``filesystem_identity`` is live evidence and is never persisted.  A
    non-file identity has no filesystem evidence, so the seam cannot call
    ``Path.resolve`` or ``Path.stat`` for it.
    """

    backend: str
    key: str
    filesystem_identity: Identity | None = None
    filesystem_aliases: bool = False

    @property
    def filesystem(self) -> bool:
        """Whether this binding participates in file alias detection."""

        return self.filesystem_aliases


BindingProvider = Callable[["StoreDescriptor"], BindingIdentity]


def file_binding(location: str) -> BindingIdentity:
    """Apply the built-in file policy to a location.

    The canonical path remains the historical ``bindings.jsonl`` spelling.
    The live device/inode pair is only supplied to the seam for alias
    detection; it is deliberately not part of the journal key.
    """

    canonical = str(Path(location).resolve())
    try:
        stat = Path(canonical).stat()
    except FileNotFoundError:
        identity = None
    except OSError as exc:
        raise BindingProbeError(
            f"{canonical} exists and storage would not stat it ({exc})"
        ) from exc
    else:
        identity = (stat.st_dev, stat.st_ino)
    return BindingIdentity("file", canonical, identity, True)


def opaque_binding(backend: str, location: str) -> BindingIdentity:
    """Return a stable, collision-free key without interpreting ``location``.

    ``backend:`` is outside the file adapter's absolute canonical-path
    namespace. Length framing separates backend and locator fields, so backend
    names and locators containing ``:`` cannot collide with another pair. The
    exact locator is otherwise retained byte-for-byte.
    """

    return BindingIdentity(
        backend,
        f"backend:{len(backend)}:{backend}:{len(location)}:{location}",
    )


def is_opaque_key_for(backend: str, key: str) -> bool:
    """Whether ``key`` has the framed namespace owned by ``backend``."""

    prefix = f"backend:{len(backend)}:{backend}:"
    if not key.startswith(prefix):
        return False
    framed = key[len(prefix) :]
    length_text, separator, locator = framed.partition(":")
    if not separator or not length_text.isdecimal():
        return False
    return len(locator) == int(length_text)
