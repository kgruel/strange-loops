"""Explicit, namespace-scoped local signing-key bindings.

This module deliberately does not inspect a vertex locator while resolving a
credential.  Locator-derived custody remains in :mod:`custody.signing`; a
mapped binding is an explicit local record keyed by exact namespace and
observer strings.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISDIR, S_ISREG

from engine.credentials import (
    CredentialBindingEvidence,
    CredentialBindingRefused,
    CredentialRequest,
    ResolvedCredential,
    SigningDomain,
    WriteCredentials,
)
from sign import ed25519

from .signing import (
    ARRIVAL_DOMAIN,
    FACT_DOMAIN,
    TICK_DOMAIN,
    _observer_key_dir,
    _self_key_dir,
    _self_observer,
    keys_dir_for,
)

__all__ = [
    "BindingConflict",
    "BindingCreationResult",
    "BindingMutationIncomplete",
    "BindingRecoveryRequired",
    "MappedCredentialProvider",
]

_SCHEMA = "loops.custody/binding/v1"
_INTENT_SCHEMA = "loops.custody/binding-intent/v1"
_KEY_REF = re.compile(r"^[0-9a-f]{32}$")


class BindingConflict(ValueError):
    """An explicit mutation conflicts with an already published binding."""


class BindingRecoveryRequired(ValueError):
    """A different durable mutation token owns this namespace/observer slot."""


class BindingMutationIncomplete(ValueError):
    """A durable binding mutation needs reconciliation rather than blind retry."""

    def __init__(
        self,
        *,
        namespace: str,
        observer: str,
        token: str,
        key_ref: str,
        phase: str,
    ) -> None:
        super().__init__("mapped binding mutation outcome is incomplete or unknown")
        self.namespace = namespace
        self.observer = observer
        self.token = token
        self.key_ref = key_ref
        self.phase = phase


@dataclass(frozen=True)
class BindingCreationResult:
    """The durable result of an explicit local binding mutation."""

    namespace: str
    observer: str
    key_ref: str
    public_key: str
    provenance: str
    token: str
    binding_created: bool
    key_created: bool


def _exact(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _frame(*values: str) -> bytes:
    encoded = [value.encode("utf-8") for value in values]
    return b"".join(len(value).to_bytes(8, "big") + value for value in encoded)


def _digest(*values: str) -> str:
    return hashlib.sha256(_frame(*values)).hexdigest()


def _domain_prefix(domain: SigningDomain) -> str:
    prefixes = {
        SigningDomain.FACT: FACT_DOMAIN,
        SigningDomain.ARRIVAL: ARRIVAL_DOMAIN,
        SigningDomain.TICK: TICK_DOMAIN,
    }
    try:
        return prefixes[domain]
    except KeyError as exc:  # defensive for a future neutral enum member
        raise ValueError(f"unsupported signing domain {domain!r}") from exc


def _lstat_kind(path: Path) -> int | None:
    try:
        return path.lstat().st_mode
    except FileNotFoundError:
        return None


def _regular(path: Path, *, required: bool = True) -> bool:
    mode = _lstat_kind(path)
    if mode is None:
        if required:
            raise FileNotFoundError(path)
        return False
    if not S_ISREG(mode):
        raise ValueError(f"mapped custody path is not a regular file: {path}")
    return True


def _directory(path: Path, *, create: bool = False) -> None:
    """Validate a directory and durably publish newly needed ancestors.

    Mutation callers pass ``create=True``.  It fsyncs each parent even when a
    prior interrupted attempt already made the child, so retry never assumes a
    successful ``mkdir`` made its directory entry durable.
    """
    mode = _lstat_kind(path)
    if mode is None:
        if not create:
            raise FileNotFoundError(path)
        parent = path.parent
        # The configured provider root may sit below a trusted alias such as
        # macOS /tmp. Recurse only through missing ancestors; existing parent
        # aliases retain the longstanding caller-configured-root behavior.
        if parent != path and _lstat_kind(parent) is None:
            _directory(parent, create=True)
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError:
            # Another process may have created it between lstat and mkdir.
            # Recheck its real type below; never treat a symlink as convergence.
            pass
        mode = _lstat_kind(path)
    if mode is None or not S_ISDIR(mode):
        raise ValueError(f"mapped custody path is not a directory: {path}")
    if create:
        _fsync_parent_chain(path)


def _fsync_parent_chain(path: Path) -> None:
    """Durably retain ``path``'s entry without reclassifying trusted parents.

    ``path`` itself is always lstat-validated by :func:`_directory`, so a
    provider-owned root or subdirectory can never converge through a symlink.
    Its already-existing ancestors, however, may include a caller-configured
    alias such as macOS ``/tmp``.  We deliberately open those ancestors only
    to fsync their directory entries; we do not apply the provider-owned
    no-symlink policy to them.

    Walking the whole lexical parent chain also makes a retry safe after an
    interruption just after ``mkdir A/B`` but before fsyncing ``A``'s parent:
    the retry may find both directories already present, yet still flushes the
    old ``A`` entry before it relies on ``B``.
    """
    parent = path.parent
    while parent != parent.parent:
        _fsync_directory(parent)
        parent = parent.parent
    _fsync_directory(parent)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_no_clobber(path: Path, payload: bytes, *, mode: int = 0o600) -> bool:
    """Atomically publish bytes, returning false if another complete file won."""
    _directory(path.parent, create=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        _fsync_directory(path.parent)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class MappedCredentialProvider:
    """Resolve explicit namespace/observer bindings without locator inference.

    ``resolve`` and ``verify`` are read-only.  Binding creation, import, and
    existing-reference publication are separate durable mutations serialized by
    one provider-root advisory lock.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        namespace: str,
        receipt_observer: str | None = None,
        _creation_hook: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.namespace = _exact(namespace, "namespace")
        self.receipt_observer = (
            _exact(receipt_observer, "receipt_observer")
            if receipt_observer is not None
            else None
        )
        # Test-only fault injection. It is intentionally absent from public
        # results and never called by read resolution.
        self._creation_hook = _creation_hook

    @property
    def mapped(self) -> bool:
        """Allow SDK compatibility arms to refuse mapped-to-legacy downgrade."""
        return True

    def for_write(self, vertex: Path) -> WriteCredentials:
        """Return lazy mapped credentials; ``vertex`` selects no local key."""
        del vertex
        return WriteCredentials(
            binding_namespace=self.namespace,
            receipt_observer=self.receipt_observer,
            binding_resolver=self.resolve,
            signature_verifier=self.verify,
        )

    def _slot(self, namespace: str, observer: str) -> str:
        return _digest(namespace, observer)

    def _binding_path(self, namespace: str, observer: str) -> Path:
        return self.root / "bindings-v1" / f"{self._slot(namespace, observer)}.json"

    def _pending_path(self, namespace: str, observer: str) -> Path:
        return self.root / "pending-v1" / f"{self._slot(namespace, observer)}.json"

    def _intent_path(self, token: str) -> Path:
        return self.root / "intents-v1" / f"{_digest(token)}.json"

    def _key_dir(self, key_ref: str) -> Path:
        if not _KEY_REF.fullmatch(key_ref):
            raise ValueError("mapped custody key reference is malformed")
        return self.root / "keys-v1" / key_ref

    def _root_dir(self, *, create: bool) -> bool:
        """Validate the configured root without making reads persistent."""
        mode = _lstat_kind(self.root)
        if mode is None:
            if not create:
                return False
            _directory(self.root, create=True)
        elif not S_ISDIR(mode):
            raise ValueError("mapped custody root is not a directory")
        return True

    def _subdir(self, name: str, *, create: bool) -> Path | None:
        if not self._root_dir(create=create):
            return None
        path = self.root / name
        mode = _lstat_kind(path)
        if mode is None:
            if not create:
                return None
            _directory(path, create=True)
        elif not S_ISDIR(mode):
            raise ValueError(f"mapped custody path is not a directory: {path}")
        return path

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        self._root_dir(create=True)
        lock_path = self.root / ".bindings-v1.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        try:
            if not S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("mapped custody lock is not a regular file")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read_json(self, path: Path) -> dict[str, object] | None:
        if not _regular(path, required=False):
            return None
        try:
            def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"duplicate field {key!r}")
                    result[key] = value
                return result

            loaded = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed mapped custody record: {path}") from exc
        if not isinstance(loaded, dict):
            raise TypeError(f"mapped custody record is not an object: {path}")
        return loaded

    def _binding_record(self, namespace: str, observer: str) -> dict[str, object] | None:
        parent = self._subdir("bindings-v1", create=False)
        if parent is None:
            return None
        record = self._read_json(parent / f"{self._slot(namespace, observer)}.json")
        if record is None:
            return None
        expected = {
            "schema": _SCHEMA,
            "namespace": namespace,
            "observer": observer,
        }
        if any(record.get(key) != value for key, value in expected.items()):
            raise ValueError("mapped custody binding does not match its slot")
        for key in ("key_ref", "algorithm", "public_key", "provenance"):
            if not isinstance(record.get(key), str) or not record[key]:
                raise ValueError(f"mapped custody binding lacks {key}")
        if record["algorithm"] != "ed25519":
            raise ValueError("mapped custody binding has unsupported algorithm")
        self._key_dir(str(record["key_ref"]))
        return record

    def _load_keypair(self, key_ref: str, *, require_public_file: bool = False):
        keys = self._subdir("keys-v1", create=False)
        if keys is None:
            raise FileNotFoundError(self.root / "keys-v1")
        key_dir = keys / key_ref
        mode = _lstat_kind(key_dir)
        if mode is None or not S_ISDIR(mode):
            raise FileNotFoundError(key_dir)
        private_path = key_dir / "ed25519.key"
        _regular(private_path)
        pair = ed25519.load(key_dir)
        public_path = key_dir / "ed25519.pub"
        exists = _regular(public_path, required=False)
        if require_public_file and not exists:
            raise ValueError("mapped custody key is missing its public evidence")
        if exists and public_path.read_text(encoding="utf-8") != pair.public_b64 + "\n":
            raise ValueError("mapped custody public evidence disagrees with private key")
        return pair

    def _validated_binding(self, namespace: str, observer: str) -> dict[str, object] | None:
        record = self._binding_record(namespace, observer)
        if record is None:
            return None
        pair = self._load_keypair(str(record["key_ref"]))
        if pair.public_b64 != record["public_key"]:
            raise ValueError("mapped custody binding public key disagrees with private key")
        return record

    def _completed_key_reference(self, key_ref: str, expected_public_key: str) -> None:
        """Require explicit reuse to name a published, validated binding."""
        bindings = self._subdir("bindings-v1", create=False)
        if bindings is None:
            raise FileNotFoundError("no completed mapped binding names this key reference")
        found = False
        for path in bindings.iterdir():
            if path.suffix != ".json":
                continue
            record = self._read_json(path)
            if record is None or record.get("key_ref") != key_ref:
                continue
            if (
                record.get("schema") != _SCHEMA
                or not isinstance(record.get("namespace"), str)
                or not isinstance(record.get("observer"), str)
                or record.get("public_key") != expected_public_key
            ):
                raise ValueError("published mapped binding is malformed")
            slot = f"{self._slot(str(record['namespace']), str(record['observer']))}.json"
            if path.name != slot:
                raise ValueError("published mapped binding is stored in the wrong slot")
            pair = self._load_keypair(key_ref, require_public_file=True)
            if pair.public_b64 != expected_public_key:
                raise ValueError("published mapped binding disagrees with its key object")
            found = True
        if not found:
            raise FileNotFoundError("no completed mapped binding names this key reference")

    def _evidence(
        self, request: CredentialRequest, record: dict[str, object]
    ) -> CredentialBindingEvidence:
        return CredentialBindingEvidence(
            request=request,
            key_ref=str(record["key_ref"]),
            algorithm="ed25519",
            public_key=str(record["public_key"]),
            provenance=str(record["provenance"]),
        )

    def resolve(self, request: CredentialRequest) -> ResolvedCredential | None:
        """Resolve one credential without locks, mkdirs, repair, or fallback."""
        if request.namespace != self.namespace:
            raise CredentialBindingRefused("request-mismatch", request=request)
        try:
            record = self._validated_binding(request.namespace, request.observer)
            if record is None:
                pending_dir = self._subdir("pending-v1", create=False)
                pending = (
                    None
                    if pending_dir is None
                    else self._read_json(pending_dir / f"{self._slot(request.namespace, request.observer)}.json")
                )
                if pending is not None:
                    raise CredentialBindingRefused("recovery-required", request=request)
                return None
            pair = self._load_keypair(str(record["key_ref"]))
            evidence = self._evidence(request, record)
        except CredentialBindingRefused:
            raise
        except (OSError, ValueError) as exc:
            raise CredentialBindingRefused("corrupt-binding", request=request) from exc
        return ResolvedCredential(
            evidence=evidence,
            sign_digest=lambda digest: ed25519.sign(
                pair, digest.encode(), domain=_domain_prefix(request.domain)
            ),
        )

    def verify(
        self, domain: SigningDomain, public_key: str, signature: str, digest: str
    ) -> bool:
        """Verify under the custody-owned domain prefix without persistence."""
        try:
            public = ed25519.public_key_from_b64(public_key)
        except ValueError:
            return False
        return ed25519.verify(public, signature, digest.encode(), domain=_domain_prefix(domain))

    def _new_intent(
        self,
        observer: str,
        *,
        token: str,
        provenance: str,
        key_ref: str | None = None,
        expected_public_key: str | None = None,
    ) -> dict[str, object]:
        _exact(observer, "observer")
        _exact(token, "token")
        key_ref = key_ref or uuid.uuid4().hex
        self._key_dir(key_ref)
        return {
            "schema": _INTENT_SCHEMA,
            "namespace": self.namespace,
            "observer": observer,
            "token": token,
            "key_ref": key_ref,
            "provenance": provenance,
            "expected_public_key": expected_public_key,
            "stage": "pending",
        }

    def _pending_by_token(self, token: str) -> dict[str, object] | None:
        """Find a durable token reservation while holding the provider lock."""
        pending_dir = self._subdir("pending-v1", create=False)
        if pending_dir is None:
            return None
        found: dict[str, object] | None = None
        for path in pending_dir.iterdir():
            if path.suffix != ".json":
                continue
            record = self._read_json(path)
            if record is None or record.get("token") != token:
                continue
            namespace = record.get("namespace")
            observer = record.get("observer")
            if not isinstance(namespace, str) or not isinstance(observer, str):
                raise TypeError("mapped pending intent lacks exact slot identity")
            expected_name = f"{self._slot(namespace, observer)}.json"
            if path.name != expected_name:
                raise ValueError("mapped pending intent is stored in the wrong slot")
            if found is not None:
                raise BindingConflict("mapped binding token owns multiple pending slots")
            found = record
        return found

    def _ensure_token_index(self, intent: dict[str, object]) -> None:
        """Publish or validate the token index for an already durable intent."""
        token = str(intent["token"])
        intents = self._subdir("intents-v1", create=True)
        assert intents is not None
        path = intents / f"{_digest(token)}.json"
        if _publish_no_clobber(path, _json_bytes(intent)):
            return
        existing = self._read_json(path)
        if existing != intent:
            raise BindingConflict("mapped binding token already names another intent")
        _fsync_directory(intents)

    def _publish_completion(self, intent: dict[str, object]) -> None:
        """Record a validated completed intent without deleting recovery evidence."""
        complete = dict(intent)
        complete["stage"] = "complete"
        intents = self._subdir("intents-v1", create=True)
        assert intents is not None
        completion = intents / f"{_digest(str(intent['token']))}.complete.json"
        if not _publish_no_clobber(completion, _json_bytes(complete)):
            existing = self._read_json(completion)
            if existing != complete:
                raise BindingConflict("mapped binding completion receipt conflicts with its intent")
            _fsync_directory(intents)

    def _assert_published_intent(
        self,
        published: dict[str, object],
        intent: dict[str, object],
        *,
        require_token_index: bool = True,
    ) -> None:
        """Ensure a material-valid slot still names this exact retained intent."""
        for name in ("namespace", "observer", "key_ref", "provenance"):
            if published.get(name) != intent.get(name):
                raise BindingConflict("published mapped binding contradicts its retained intent")
        expected_public = intent.get("expected_public_key")
        if expected_public is not None and published.get("public_key") != expected_public:
            raise BindingConflict("published mapped binding contradicts its expected public key")
        intents = self._subdir("intents-v1", create=False)
        if intents is None:
            if require_token_index:
                raise BindingConflict("published mapped binding has no token-index evidence")
            return
        indexed = self._read_json(intents / f"{_digest(str(intent['token']))}.json")
        if require_token_index and indexed != intent:
            raise BindingConflict("published mapped binding contradicts its token index")
        completion = self._read_json(
            intents / f"{_digest(str(intent['token']))}.complete.json"
        )
        if completion is not None:
            complete = dict(intent)
            complete["stage"] = "complete"
            if completion != complete:
                raise BindingConflict("published mapped binding contradicts its completion receipt")

    def _intent_for(
        self, observer: str, *, token: str, provenance: str, key_ref: str | None = None,
        expected_public_key: str | None = None,
    ) -> dict[str, object]:
        intents = self._subdir("intents-v1", create=False)
        token_record = (
            None if intents is None else self._read_json(intents / f"{_digest(token)}.json")
        )
        if token_record is not None and (
            token_record.get("namespace") != self.namespace
            or token_record.get("observer") != observer
        ):
            raise BindingConflict("mapped binding token already names another intent")
        pending_for_token = self._pending_by_token(token)
        if pending_for_token is not None:
            if token_record is not None and token_record != pending_for_token:
                raise BindingConflict("mapped binding pending slot contradicts its token index")
            if (
                pending_for_token.get("namespace") != self.namespace
                or pending_for_token.get("observer") != observer
            ):
                raise BindingConflict("mapped binding token already owns another pending slot")
        pending_dir = self._subdir("pending-v1", create=False)
        slot_pending = (
            None
            if pending_dir is None
            else self._read_json(
                pending_dir / f"{self._slot(self.namespace, observer)}.json"
            )
        )
        completed = self._validated_binding(self.namespace, observer)
        if completed is not None:
            indexed_slot: dict[str, object] | None = None
            if slot_pending is not None:
                # A caller may legitimately retry an already-completed binding
                # under a fresh operation token. The selected published material
                # must still agree with this slot's original durable intent.
                self._assert_published_intent(
                    completed, slot_pending, require_token_index=False
                )
                indexed_slot = (
                    None
                    if intents is None
                    else self._read_json(
                        intents / f"{_digest(str(slot_pending['token']))}.json"
                    )
                )
                if indexed_slot is not None:
                    self._assert_published_intent(completed, slot_pending)
            if pending_for_token is not None:
                # The pending marker may be the only durable token evidence
                # after interruption between its publication and token-index
                # publication. Never restore that index until the published
                # slot proves it still names this exact intent.
                self._assert_published_intent(
                    completed, pending_for_token, require_token_index=False
                )
            if (
                (expected_public_key is not None and completed["public_key"] != expected_public_key)
                or (key_ref is not None and completed["key_ref"] != key_ref)
                or (
                    token_record is not None
                    and (
                        token_record.get("provenance") != provenance
                        or token_record.get("key_ref") != completed["key_ref"]
                    )
                )
            ):
                raise BindingConflict("existing mapped binding has a different public key")
            bindings = self._subdir("bindings-v1", create=False)
            assert bindings is not None
            # These writes all precede a completed result. Their contents have
            # been checked above, so a retry can now safely make any link whose
            # prior fsync was interrupted durable.
            _fsync_directory(bindings)
            _fsync_directory(self._key_dir(str(completed["key_ref"])))
            if slot_pending is not None:
                assert pending_dir is not None
                _fsync_directory(pending_dir)
                if intents is not None and indexed_slot is not None:
                    _fsync_directory(intents)
            if pending_for_token is not None:
                # The pending marker may be the only durable token evidence
                # after interruption between its publication and token-index
                # publication. Restore that index only after the published
                # slot has passed the retained-intent check above.
                self._ensure_token_index(pending_for_token)
                self._assert_published_intent(completed, pending_for_token)
                self._publish_completion(pending_for_token)
            return {
                "completed": True,
                "key_ref": completed["key_ref"],
                "public_key": completed["public_key"],
                "provenance": completed["provenance"],
                "token": token,
            }
        pending = slot_pending
        if pending is not None:
            if pending_for_token is not None and pending_for_token != pending:
                raise BindingConflict("mapped binding slot contradicts its token reservation")
            if pending.get("token") != token:
                raise BindingRecoveryRequired(
                    "a different durable token owns this mapped binding slot"
                )
            if (
                pending.get("namespace") != self.namespace
                or pending.get("observer") != observer
                or pending.get("provenance") != provenance
                or (key_ref is not None and pending.get("key_ref") != key_ref)
                or (
                    expected_public_key is not None
                    and pending.get("expected_public_key") != expected_public_key
                )
            ):
                raise BindingConflict("mapped binding token was reused with different intent")
            assert pending_dir is not None
            _fsync_directory(pending_dir)
            self._ensure_token_index(pending)
            return pending
        intent = self._new_intent(
            observer,
            token=token,
            provenance=provenance,
            key_ref=key_ref,
            expected_public_key=expected_public_key,
        )
        pending_dir = self._subdir("pending-v1", create=True)
        assert pending_dir is not None
        # The slot marker contains the complete intent. If a process dies before
        # the token index is linked, callers which know observer/token can still
        # recover coherently; no directory scan or candidate deletion occurs.
        if not _publish_no_clobber(
            pending_dir / f"{self._slot(self.namespace, observer)}.json", _json_bytes(intent)
        ):
            return self._intent_for(
                observer,
                token=token,
                provenance=provenance,
                key_ref=key_ref,
                expected_public_key=expected_public_key,
            )
        self._ensure_token_index(intent)
        return intent

    def _pending_for_recovery(self, observer: str, token: str) -> dict[str, object]:
        pending_dir = self._subdir("pending-v1", create=False)
        if pending_dir is None:
            raise BindingRecoveryRequired("no durable mapped binding intent exists")
        pending = self._read_json(
            pending_dir / f"{self._slot(self.namespace, observer)}.json"
        )
        if pending is None:
            raise BindingRecoveryRequired("no durable mapped binding intent exists")
        if (
            pending.get("schema") != _INTENT_SCHEMA
            or pending.get("namespace") != self.namespace
            or pending.get("observer") != observer
            or pending.get("token") != token
            or pending.get("stage") != "pending"
            or pending.get("provenance") not in {"created", "legacy-import", "existing-ref"}
            or not isinstance(pending.get("key_ref"), str)
        ):
            raise BindingRecoveryRequired("mapped binding recovery token does not match a pending intent")
        if self._pending_by_token(token) != pending:
            raise BindingConflict("mapped binding token owns a contradictory pending slot")
        self._key_dir(str(pending["key_ref"]))
        return pending

    def _hook(self, phase: str, intent: dict[str, object]) -> None:
        if self._creation_hook is not None:
            self._creation_hook(phase, dict(intent))

    def _ensure_created_key(self, intent: dict[str, object]):
        key_ref = str(intent["key_ref"])
        keys = self._subdir("keys-v1", create=True)
        assert keys is not None
        key_dir = keys / key_ref
        _directory(key_dir, create=True)
        mode = _lstat_kind(key_dir)
        created = False
        if mode is None:  # defensive: _directory above must establish it
            raise FileNotFoundError(key_dir)
        if not S_ISDIR(mode):
            raise ValueError("mapped custody candidate key path is not a directory")
        private = key_dir / "ed25519.key"
        public = key_dir / "ed25519.pub"
        if _lstat_kind(private) is None:
            # This intent exclusively reserved the candidate ref. It is safe
            # to resume a crash before private-key publication completed.
            if _lstat_kind(public) is not None:
                raise ValueError("incomplete candidate has public evidence without private key")
            pair = ed25519.load_or_generate(key_dir)
            _fsync_directory(key_dir)
            created = True
        else:
            pair = self._load_keypair(key_ref)
            if _lstat_kind(public) is None:
                # A crash between durable private and public publication is
                # resumable only for this retained, provider-owned intent.
                _publish_no_clobber(public, (pair.public_b64 + "\n").encode(), mode=0o644)
                _fsync_directory(key_dir)
            pair = self._load_keypair(key_ref, require_public_file=True)
        # A prior attempt may have published both key files and then failed to
        # fsync this directory. Validate the pair first, then make the retry
        # retain those existing entries before returning success.
        _fsync_directory(key_dir)
        self._hook("key-published", intent)
        return pair, created

    def _copy_key(self, source: Path, intent: dict[str, object]):
        source_pair = self._load_external_key(source)
        keys = self._subdir("keys-v1", create=True)
        assert keys is not None
        key_dir = keys / str(intent["key_ref"])
        _directory(key_dir, create=True)
        if _lstat_kind(key_dir / "ed25519.key") is None:
            _publish_no_clobber(
                key_dir / "ed25519.key", (source / "ed25519.key").read_bytes()
            )
            _publish_no_clobber(
                key_dir / "ed25519.pub", (source_pair.public_b64 + "\n").encode(), mode=0o644
            )
            _fsync_directory(key_dir)
            created = True
        else:
            source_pair = self._load_keypair(
                str(intent["key_ref"]), require_public_file=True
            )
            created = False
        candidate = self._load_keypair(str(intent["key_ref"]), require_public_file=True)
        if candidate.public_b64 != source_pair.public_b64:
            raise BindingConflict("copied candidate disagrees with the validated source key")
        _fsync_directory(key_dir)
        self._hook("key-published", intent)
        return candidate, created

    def _load_external_key(self, key_dir: Path):
        mode = _lstat_kind(key_dir)
        if mode is None or not S_ISDIR(mode):
            raise FileNotFoundError(key_dir)
        private = key_dir / "ed25519.key"
        _regular(private)
        pair = ed25519.load(key_dir)
        public = key_dir / "ed25519.pub"
        if _regular(public, required=False) and public.read_text(encoding="utf-8") != pair.public_b64 + "\n":
            raise ValueError("source custody public evidence disagrees with private key")
        return pair

    def _publish_binding(self, intent: dict[str, object], pair) -> tuple[dict[str, object], bool]:
        expected = intent.get("expected_public_key")
        if expected is not None and pair.public_b64 != expected:
            raise BindingConflict("candidate key does not match expected public key")
        record: dict[str, object] = {
            "schema": _SCHEMA,
            "namespace": self.namespace,
            "observer": intent["observer"],
            "key_ref": intent["key_ref"],
            "algorithm": "ed25519",
            "public_key": pair.public_b64,
            "provenance": intent["provenance"],
        }
        bindings = self._subdir("bindings-v1", create=True)
        assert bindings is not None
        published = _publish_no_clobber(
            bindings / f"{self._slot(self.namespace, str(intent['observer']))}.json", _json_bytes(record)
        )
        if not published:
            existing = self._binding_record(self.namespace, str(intent["observer"]))
            assert existing is not None
            if existing["public_key"] != pair.public_b64:
                raise BindingConflict("another binding won with a different public key")
            _fsync_directory(bindings)
            return existing, False
        self._hook("binding-published", intent)
        # Intent files are retained as durable recovery evidence. The marker is
        # deliberately not removed automatically, avoiding unsafe cleanup races.
        self._publish_completion(intent)
        return record, True

    def _mutate(
        self,
        observer: str,
        *,
        token: str,
        provenance: str,
        key_ref: str | None = None,
        expected_public_key: str | None = None,
        source_key_dir: Path | None = None,
        _locked: bool = False,
    ) -> BindingCreationResult:
        with (nullcontext() if _locked else self._mutation_lock()):
            intent = self._intent_for(
                observer,
                token=token,
                provenance=provenance,
                key_ref=key_ref,
                expected_public_key=expected_public_key,
            )
            if intent.get("completed"):
                return BindingCreationResult(
                    namespace=self.namespace,
                    observer=observer,
                    key_ref=str(intent["key_ref"]),
                    public_key=str(intent["public_key"]),
                    provenance=str(intent["provenance"]),
                    token=token,
                    binding_created=False,
                    key_created=False,
                )
            phase = "intent-published"
            try:
                self._hook(phase, intent)
                if source_key_dir is None:
                    phase = "key-published"
                    pair, key_created = self._ensure_created_key(intent)
                else:
                    phase = "key-published"
                    pair, key_created = self._copy_key(source_key_dir, intent)
                phase = "binding-published"
                record, binding_created = self._publish_binding(intent, pair)
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    raise
                raise BindingMutationIncomplete(
                    namespace=self.namespace,
                    observer=observer,
                    token=token,
                    key_ref=str(intent["key_ref"]),
                    phase=phase,
                ) from exc
            return BindingCreationResult(
                namespace=self.namespace,
                observer=observer,
                key_ref=str(record["key_ref"]),
                public_key=str(record["public_key"]),
                provenance=str(record["provenance"]),
                token=token,
                binding_created=binding_created,
                key_created=key_created,
            )

    def create_binding(self, observer: str, *, token: str) -> BindingCreationResult:
        """Create or recover one explicit mapped key binding."""
        return self._mutate(observer, token=token, provenance="created")

    def recover_binding(self, observer: str, *, token: str) -> BindingCreationResult:
        """Resume the exact token's durable binding intent without a new key."""
        _exact(observer, "observer")
        _exact(token, "token")
        with self._mutation_lock():
            intent = self._pending_for_recovery(observer, token)
            phase = "intent-published"
            try:
                # A published slot is authority over its candidate. Validate it
                # against the retained pending marker so a missing/moved key can
                # never be regenerated under an already-named reference.
                published = self._binding_record(self.namespace, observer)
                if published is not None:
                    self._validated_binding(self.namespace, observer)
                    self._assert_published_intent(
                        published, intent, require_token_index=False
                    )
                    pending_dir = self._subdir("pending-v1", create=False)
                    assert pending_dir is not None
                    bindings = self._subdir("bindings-v1", create=False)
                    assert bindings is not None
                    _fsync_directory(pending_dir)
                    _fsync_directory(bindings)
                    _fsync_directory(self._key_dir(str(published["key_ref"])))
                    # Restore the token index only after the material-valid
                    # slot proves it is the retained intent's exact binding.
                    self._ensure_token_index(intent)
                    self._assert_published_intent(published, intent)
                    phase = "binding-published"
                    self._publish_completion(intent)
                    return BindingCreationResult(
                        namespace=self.namespace,
                        observer=observer,
                        key_ref=str(published["key_ref"]),
                        public_key=str(published["public_key"]),
                        provenance=str(published["provenance"]),
                        token=str(intent["token"]),
                        binding_created=False,
                        key_created=False,
                    )
                pending_dir = self._subdir("pending-v1", create=False)
                assert pending_dir is not None
                _fsync_directory(pending_dir)
                self._ensure_token_index(intent)
                provenance = str(intent["provenance"])
                if provenance == "created":
                    phase = "key-published"
                    pair, key_created = self._ensure_created_key(intent)
                else:
                    # Import and existing-reference intents have already selected a
                    # durable candidate. Recovery never reopens the legacy source
                    # or creates a replacement key under the reserved reference.
                    key_ref = str(intent["key_ref"])
                    try:
                        pair = self._load_keypair(key_ref)
                    except FileNotFoundError as exc:
                        if provenance == "legacy-import":
                            raise BindingRecoveryRequired(
                                "legacy import candidate is absent; repeat the explicit import with this token"
                            ) from exc
                        raise
                    expected = intent.get("expected_public_key")
                    if expected is not None and pair.public_b64 != expected:
                        raise BindingConflict("recovery candidate disagrees with its intent")
                    key_dir = self._key_dir(key_ref)
                    public = key_dir / "ed25519.pub"
                    if _lstat_kind(public) is None:
                        if provenance != "legacy-import":
                            raise BindingRecoveryRequired(
                                "existing-reference candidate lacks durable public evidence"
                            )
                        _publish_no_clobber(
                            public, (pair.public_b64 + "\n").encode(), mode=0o644
                        )
                        _fsync_directory(key_dir)
                    pair = self._load_keypair(key_ref, require_public_file=True)
                    # A legacy import can have linked both key files before a
                    # directory fsync was interrupted. Validate the retained
                    # candidate first, then retain that existing directory
                    # before publishing its binding; recovery never needs the
                    # original legacy source for this step.
                    _fsync_directory(key_dir)
                    key_created = False
                phase = "binding-published"
                record, binding_created = self._publish_binding(intent, pair)
                return BindingCreationResult(
                    namespace=self.namespace,
                    observer=observer,
                    key_ref=str(record["key_ref"]),
                    public_key=str(record["public_key"]),
                    provenance=str(record["provenance"]),
                    token=token,
                    binding_created=binding_created,
                    key_created=key_created,
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    raise
                if isinstance(
                    exc, (BindingConflict, BindingRecoveryRequired, FileNotFoundError, ValueError)
                ):
                    raise
                raise BindingMutationIncomplete(
                    namespace=self.namespace,
                    observer=observer,
                    token=token,
                    key_ref=str(intent["key_ref"]),
                    phase=phase,
                ) from exc

    def bind_existing_ref(
        self,
        observer: str,
        key_ref: str,
        expected_public_key: str,
        *,
        token: str,
    ) -> BindingCreationResult:
        """Deliberately reuse an already managed key in this namespace slot."""
        _exact(expected_public_key, "expected_public_key")
        with self._mutation_lock():
            self._completed_key_reference(key_ref, expected_public_key)
            return self._mutate(
                observer,
                token=token,
                provenance="existing-ref",
                key_ref=key_ref,
                expected_public_key=expected_public_key,
                source_key_dir=self._key_dir(key_ref),
                _locked=True,
            )

    def import_legacy(
        self, vertex_path: Path | str, observer: str, *, token: str
    ) -> BindingCreationResult:
        """Copy one explicitly selected legacy key after load-only validation."""
        vertex = Path(vertex_path)
        self_observer = _self_observer(vertex)
        if observer == self_observer:
            source = _self_key_dir(vertex)
        else:
            source = _observer_key_dir(keys_dir_for(vertex), observer)
        if source is None:
            raise FileNotFoundError("legacy custody key is absent")
        # Validate before publishing any intent/candidate. A bad legacy .pub is
        # evidence conflict, never something a mapped import repairs.
        pair = self._load_external_key(source)
        return self._mutate(
            observer,
            token=token,
            provenance="legacy-import",
            expected_public_key=pair.public_b64,
            source_key_dir=source,
        )
