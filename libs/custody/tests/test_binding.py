from __future__ import annotations

import threading
from multiprocessing import get_context
from pathlib import Path

import custody.binding as binding_module
import pytest
from custody import ensure_signing_key
from custody.binding import (
    BindingConflict,
    BindingMutationIncomplete,
    BindingRecoveryRequired,
    MappedCredentialProvider,
)
from engine.credentials import CredentialPurpose, CredentialRequest, SigningDomain


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "xdg"
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(root / "loops"))


def _request(observer: str, domain: SigningDomain = SigningDomain.FACT) -> CredentialRequest:
    return CredentialRequest("example/team", observer, domain, CredentialPurpose.AUTHORSHIP)


def _create_in_process(root: str, token: str, queue) -> None:
    """Top-level target so macOS spawn exercises the POSIX file lock."""
    try:
        result = MappedCredentialProvider(Path(root), namespace="example/team").create_binding(
            "alice", token=token
        )
        queue.put(("ok", result.key_ref, result.public_key))
    except (BindingRecoveryRequired, ValueError) as exc:  # returned to the parent
        queue.put(("error", type(exc).__name__, str(exc)))


def test_create_resolve_is_exact_and_domain_separated(tmp_path: Path) -> None:
    provider = MappedCredentialProvider(tmp_path / "bindings", namespace="example/team")
    created = provider.create_binding("Alice", token="create-alice")

    fact = provider.resolve(_request("Alice", SigningDomain.FACT))
    arrival = provider.resolve(_request("Alice", SigningDomain.ARRIVAL))
    other_case = provider.resolve(_request("alice"))

    assert fact is not None and arrival is not None
    assert fact.evidence.key_ref == arrival.evidence.key_ref == created.key_ref
    assert fact.evidence.public_key == arrival.evidence.public_key == created.public_key
    signature = fact.sign_digest("digest")
    assert provider.verify(SigningDomain.FACT, created.public_key, signature, "digest")
    assert not provider.verify(SigningDomain.ARRIVAL, created.public_key, signature, "digest")
    assert other_case is None


@pytest.mark.parametrize("observer", [".", "/", "ed25519.key", "a\0b"])
def test_binding_labels_are_hashed_identity_not_path_components(
    tmp_path: Path, observer: str
) -> None:
    provider = MappedCredentialProvider(tmp_path / "bindings", namespace="space\0/")
    created = provider.create_binding(observer, token=f"token:{observer}")
    resolved = provider.resolve(
        CredentialRequest(
            "space\0/", observer, SigningDomain.FACT, CredentialPurpose.AUTHORSHIP
        )
    )

    assert resolved is not None
    assert resolved.evidence.key_ref == created.key_ref


def test_resolution_of_missing_or_bad_public_evidence_never_repairs(tmp_path: Path) -> None:
    provider = MappedCredentialProvider(tmp_path / "bindings", namespace="example/team")
    assert provider.resolve(_request("missing")) is None
    assert not (tmp_path / "bindings").exists()

    created = provider.create_binding("alice", token="create-alice")
    public = tmp_path / "bindings" / "keys-v1" / created.key_ref / "ed25519.pub"
    public.write_text("not-the-private-key\n", encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt-binding"):
        provider.resolve(_request("alice"))
    assert public.read_text(encoding="utf-8") == "not-the-private-key\n"


def test_pending_slot_recovers_only_its_named_token(tmp_path: Path) -> None:
    fired = False

    def interrupt(phase: str, _intent: dict[str, object]) -> None:
        nonlocal fired
        if phase == "intent-published" and not fired:
            fired = True
            raise RuntimeError("simulated process interruption")

    provider = MappedCredentialProvider(
        tmp_path / "bindings", namespace="example/team", _creation_hook=interrupt
    )
    with pytest.raises(BindingMutationIncomplete) as raised:
        provider.create_binding("alice", token="token-one")
    assert raised.value.token == "token-one"
    assert raised.value.phase == "intent-published"

    with pytest.raises(BindingRecoveryRequired):
        provider.create_binding("alice", token="token-two")
    recovered = provider.recover_binding("alice", token="token-one")
    assert recovered.binding_created
    assert provider.resolve(_request("alice")) is not None


def test_mutation_lock_leaves_one_winner_and_no_competing_key(tmp_path: Path) -> None:
    provider = MappedCredentialProvider(tmp_path / "bindings", namespace="example/team")
    started = threading.Barrier(2)
    outcomes: list[object] = []

    def create(token: str) -> None:
        started.wait()
        try:
            outcomes.append(provider.create_binding("alice", token=token))
        except BindingRecoveryRequired as exc:  # asserted below
            outcomes.append(exc)

    first = threading.Thread(target=create, args=("one",))
    second = threading.Thread(target=create, args=("two",))
    first.start()
    second.start()
    first.join()
    second.join()

    successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(successes) == 2
    assert not failures
    assert len({outcome.key_ref for outcome in successes}) == 1
    assert sum(outcome.binding_created for outcome in successes) == 1
    assert len(list((tmp_path / "bindings" / "keys-v1").iterdir())) == 1


def test_process_lock_converges_absent_provider_root(tmp_path: Path) -> None:
    root = tmp_path / "bindings"
    context = get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_create_in_process, args=(str(root), token, queue))
        for token in ("process-one", "process-two")
    ]
    for process in processes:
        process.start()
    outcomes = [queue.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert [outcome[0] for outcome in outcomes] == ["ok", "ok"]
    assert len({outcome[1] for outcome in outcomes}) == 1
    assert len({outcome[2] for outcome in outcomes}) == 1
    assert len(tuple((root / "keys-v1").iterdir())) == 1


def test_existing_reference_can_be_bound_in_a_second_namespace(tmp_path: Path) -> None:
    root = tmp_path / "bindings"
    first = MappedCredentialProvider(root, namespace="one")
    created = first.create_binding("alice", token="one")
    second = MappedCredentialProvider(root, namespace="two")

    copied = second.bind_existing_ref(
        "alice", created.key_ref, created.public_key, token="two"
    )
    resolved = second.resolve(
        CredentialRequest("two", "alice", SigningDomain.TICK, CredentialPurpose.RECEIPT)
    )

    assert copied.key_ref == created.key_ref
    assert resolved is not None
    assert resolved.evidence.public_key == created.public_key


def test_recovery_refuses_published_slot_substituted_with_another_valid_key(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bindings"
    provider = MappedCredentialProvider(root, namespace="example/team")
    alice = provider.create_binding("alice", token="alice-token")
    bob = provider.create_binding("bob", token="bob-token")
    alice_slot = root / "bindings-v1" / f"{provider._slot(provider.namespace, 'alice')}.json"
    value = binding_module.json.loads(alice_slot.read_text(encoding="utf-8"))
    value.update(key_ref=bob.key_ref, public_key=bob.public_key)
    alice_slot.write_text(binding_module.json.dumps(value) + "\n", encoding="utf-8")
    index = root / "intents-v1" / f"{binding_module._digest('alice-token')}.json"
    index.unlink()
    before = alice_slot.read_bytes()

    with pytest.raises(BindingConflict, match="retained intent"):
        provider.create_binding("alice", token="fresh-token")
    with pytest.raises(BindingConflict, match="retained intent"):
        provider.create_binding("alice", token="alice-token")
    with pytest.raises(BindingConflict, match="retained intent"):
        provider.recover_binding("alice", token="alice-token")

    assert alice.key_ref != bob.key_ref
    assert alice_slot.read_bytes() == before
    assert not index.exists()


def test_recovery_restores_index_after_pending_before_index_interruption(tmp_path: Path) -> None:
    root = tmp_path / "bindings"
    provider = MappedCredentialProvider(root, namespace="example/team")
    publish = binding_module._publish_no_clobber

    class Interrupted(BaseException):
        pass

    def interrupt_index(path: Path, *args, **kwargs):
        if path.parent.name == "intents-v1":
            raise Interrupted()
        return publish(path, *args, **kwargs)

    binding_module._publish_no_clobber = interrupt_index
    try:
        with pytest.raises(Interrupted):
            provider.create_binding("alice", token="one-token")
    finally:
        binding_module._publish_no_clobber = publish

    recovered = provider.recover_binding("alice", token="one-token")
    assert recovered.observer == "alice"
    assert (root / "intents-v1" / f"{binding_module._digest('one-token')}.json").exists()
    with pytest.raises(BindingConflict):
        provider.create_binding("bob", token="one-token")
    assert len(tuple((root / "bindings-v1").glob("*.json"))) == 1


def test_recovery_postpublication_fault_retains_typed_reconciliation_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bindings"

    class Interrupted(BaseException):
        pass

    def stop_after_key(phase: str, _intent: dict[str, object]) -> None:
        if phase == "key-published":
            raise Interrupted()

    initial = MappedCredentialProvider(
        root, namespace="example/team", _creation_hook=stop_after_key
    )
    with pytest.raises(Interrupted):
        initial.create_binding("alice", token="recovery-token")

    def fail_after_binding(phase: str, _intent: dict[str, object]) -> None:
        if phase == "binding-published":
            raise OSError("simulated durable post-publication failure")

    recovering = MappedCredentialProvider(
        root, namespace="example/team", _creation_hook=fail_after_binding
    )
    with pytest.raises(BindingMutationIncomplete) as raised:
        recovering.recover_binding("alice", token="recovery-token")

    assert raised.value.token == "recovery-token"
    assert raised.value.phase == "binding-published"
    assert raised.value.key_ref
    assert len(tuple((root / "bindings-v1").glob("*.json"))) == 1


def test_creation_syncs_each_provider_owned_directory_entry_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "nested" / "bindings"
    observed: list[Path] = []
    original = binding_module._fsync_directory

    def record(path: Path) -> None:
        observed.append(path)
        original(path)

    monkeypatch.setattr(binding_module, "_fsync_directory", record)
    created = MappedCredentialProvider(root, namespace="example/team").create_binding(
        "alice", token="durable-create"
    )

    key_dir = root / "keys-v1" / created.key_ref
    assert root.parent in observed
    assert root in observed
    assert root / "pending-v1" in observed
    assert root / "intents-v1" in observed
    assert root / "keys-v1" in observed
    assert root / "bindings-v1" in observed
    assert key_dir in observed
    assert observed.index(root.parent) < observed.index(root)
    assert observed.index(root) < observed.index(root / "keys-v1")


def test_retry_resyncs_existing_root_parent_after_interrupted_mkdir_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "created-ancestor" / "bindings"
    original = binding_module._fsync_directory
    interrupted = False
    retry_calls: list[Path] = []

    def fail_once(path: Path) -> None:
        nonlocal interrupted
        if path == root.parent.parent and not interrupted:
            interrupted = True
            raise OSError("interrupted parent directory sync")
        if interrupted:
            retry_calls.append(path)
        original(path)

    monkeypatch.setattr(binding_module, "_fsync_directory", fail_once)
    provider = MappedCredentialProvider(root, namespace="example/team")
    with pytest.raises(OSError, match="interrupted parent directory sync"):
        provider.create_binding("alice", token="retry-root")

    assert root.parent.is_dir()
    assert not root.exists()
    recovered = provider.create_binding("alice", token="retry-root")

    assert recovered.binding_created
    assert root.parent.parent in retry_calls
    assert (root / "bindings-v1").is_dir()


def test_recovery_resyncs_existing_key_ref_parent_after_interrupted_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bindings"
    keys = root / "keys-v1"
    original = binding_module._fsync_directory
    interrupted = False
    retry_calls: list[Path] = []

    def fail_once(path: Path) -> None:
        nonlocal interrupted
        if path == keys and not interrupted:
            interrupted = True
            raise OSError("interrupted key-ref directory sync")
        if interrupted:
            retry_calls.append(path)
        original(path)

    monkeypatch.setattr(binding_module, "_fsync_directory", fail_once)
    provider = MappedCredentialProvider(root, namespace="example/team")
    with pytest.raises(BindingMutationIncomplete) as raised:
        provider.create_binding("alice", token="retry-key-ref")

    assert raised.value.phase == "key-published"
    pending = root / "pending-v1" / f"{provider._slot(provider.namespace, 'alice')}.json"
    key_ref = binding_module.json.loads(pending.read_text(encoding="utf-8"))["key_ref"]
    assert isinstance(key_ref, str)
    assert (keys / key_ref).is_dir()

    recovered = provider.recover_binding("alice", token="retry-key-ref")

    assert recovered.key_ref == key_ref
    assert keys in retry_calls
    assert len(tuple((root / "bindings-v1").glob("*.json"))) == 1


def test_completed_retry_resyncs_validated_binding_after_link_sync_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bindings"
    bindings = root / "bindings-v1"
    original = binding_module._fsync_directory
    interrupted = False
    retry_calls: list[Path] = []

    def fail_once(path: Path) -> None:
        nonlocal interrupted
        if path == bindings and not interrupted:
            interrupted = True
            raise OSError("interrupted binding link sync")
        if interrupted:
            retry_calls.append(path)
        original(path)

    monkeypatch.setattr(binding_module, "_fsync_directory", fail_once)
    provider = MappedCredentialProvider(root, namespace="example/team")
    with pytest.raises(BindingMutationIncomplete) as raised:
        provider.create_binding("alice", token="retry-binding-link")

    assert raised.value.phase == "binding-published"
    assert len(tuple(bindings.glob("*.json"))) == 1
    completed = provider.create_binding("alice", token="retry-binding-link")

    assert not completed.binding_created
    assert bindings in retry_calls
    assert root / "pending-v1" in retry_calls
    assert root / "intents-v1" in retry_calls
    assert root / "keys-v1" / completed.key_ref in retry_calls


def test_import_recovery_resyncs_published_key_dir_without_legacy_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "legacy" / "alice.vertex"
    source.parent.mkdir()
    ensure_signing_key(source, observer="alice")

    root = tmp_path / "bindings"
    original = binding_module._fsync_directory
    interrupted = False
    key_dir_syncs = 0
    retry_calls: list[Path] = []

    def fail_once(path: Path) -> None:
        nonlocal interrupted, key_dir_syncs
        if path.parent.name == "keys-v1":
            key_dir_syncs += 1
        # The first sync follows the copied private key; interrupt the sync
        # immediately after the public-key link is visible.
        if path.parent.name == "keys-v1" and key_dir_syncs == 2 and not interrupted:
            interrupted = True
            raise OSError("interrupted imported key directory sync")
        if interrupted:
            retry_calls.append(path)
        original(path)

    monkeypatch.setattr(binding_module, "_fsync_directory", fail_once)
    provider = MappedCredentialProvider(root, namespace="example/team")
    with pytest.raises(BindingMutationIncomplete) as raised:
        provider.import_legacy(source, "alice", token="retry-import")

    assert raised.value.phase == "key-published"
    key_dirs = tuple((root / "keys-v1").iterdir())
    assert len(key_dirs) == 1
    key_dir = key_dirs[0]
    assert (key_dir / "ed25519.key").is_file()
    assert (key_dir / "ed25519.pub").is_file()
    (source.parent / "keys").rename(source.parent / "keys-moved-away")

    recovered = provider.recover_binding("alice", token="retry-import")

    assert recovered.key_ref == key_dir.name
    assert key_dir in retry_calls
    assert len(tuple((root / "bindings-v1").glob("*.json"))) == 1
