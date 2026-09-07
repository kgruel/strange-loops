"""Independent persisted-binding interruption and refusal contracts."""

from hashlib import sha256
from pathlib import Path

import pytest
from custody import ensure_signing_key
from custody.binding import MappedCredentialProvider
from engine.credentials import CredentialPurpose, CredentialRequest, SigningDomain
from sign import ed25519


class Interrupted(BaseException):
    pass


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops"))


def _fingerprints(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _request(observer="alice"):
    return CredentialRequest("work", observer, SigningDomain.FACT, CredentialPurpose.AUTHORSHIP)


def test_recovery_without_an_intent_never_creates_a_binding(tmp_path):
    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    with pytest.raises((ValueError, FileNotFoundError)):
        provider.recover_binding("alice", token="unknown")
    assert not list(root.glob("keys-v1/*/ed25519.key"))
    assert not list(root.glob("bindings-v1/*.json"))


def test_completed_binding_is_revalidated_by_creation_retry(tmp_path):
    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    created = provider.create_binding("alice", token="first")
    public_file = root / "keys-v1" / created.key_ref / "ed25519.pub"
    public_file.write_text("contradictory public evidence\n")
    before = _fingerprints(root)
    with pytest.raises(ValueError):
        provider.create_binding("alice", token="retry")
    assert _fingerprints(root) == before


def test_token_reuse_does_not_poison_a_second_observer_slot(tmp_path):
    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    provider.create_binding("alice", token="one-operation")
    before = _fingerprints(root)
    with pytest.raises(ValueError):
        provider.create_binding("bob", token="one-operation")
    assert _fingerprints(root) == before
    assert provider.resolve(_request("bob")) is None


def test_import_recovery_uses_published_candidate_after_source_is_gone(tmp_path):
    target = tmp_path / "legacy" / "alice.vertex"
    target.parent.mkdir()
    original = ensure_signing_key(target, observer="alice")
    root = tmp_path / "mapped"

    def interrupt(phase, _intent):
        if phase == "key-published":
            raise Interrupted()

    provider = MappedCredentialProvider(root, namespace="work", _creation_hook=interrupt)
    with pytest.raises(Interrupted):
        provider.import_legacy(target, "alice", token="import-alice")
    candidate_paths = tuple(root.glob("keys-v1/*/ed25519.key"))
    assert len(candidate_paths) == 1
    candidate_hash = sha256(candidate_paths[0].read_bytes()).hexdigest()
    (target.parent / "keys").rename(target.parent / "keys-moved-away")
    recovered = MappedCredentialProvider(root, namespace="work").recover_binding(
        "alice", token="import-alice"
    )
    assert recovered.public_key == original.public_b64
    assert sha256(candidate_paths[0].read_bytes()).hexdigest() == candidate_hash
    assert len(tuple(root.glob("keys-v1/*/ed25519.key"))) == 1


def test_recovery_retains_private_key_when_public_publication_was_interrupted(
    tmp_path, monkeypatch
):
    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    publish_public = ed25519._publish_public

    def interrupt(_key_dir, _keypair):
        raise Interrupted()

    monkeypatch.setattr(ed25519, "_publish_public", interrupt)
    with pytest.raises(Interrupted):
        provider.create_binding("alice", token="private-first")
    private_files = tuple(root.glob("keys-v1/*/ed25519.key"))
    assert len(private_files) == 1
    private_hash = sha256(private_files[0].read_bytes()).hexdigest()
    original_public = ed25519.load(private_files[0].parent).public_b64
    monkeypatch.setattr(ed25519, "_publish_public", publish_public)
    recovered = provider.recover_binding("alice", token="private-first")
    assert recovered.public_key == original_public
    assert sha256(private_files[0].read_bytes()).hexdigest() == private_hash
    assert len(tuple(root.glob("keys-v1/*/ed25519.key"))) == 1


def test_resolution_refuses_symlinked_intermediate_key_directory(tmp_path):
    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    provider.create_binding("alice", token="create")
    real_keys = tmp_path / "relocated-keys"
    (root / "keys-v1").rename(real_keys)
    (root / "keys-v1").symlink_to(real_keys, target_is_directory=True)
    before = _fingerprints(real_keys)
    with pytest.raises(ValueError):
        provider.resolve(_request())
    assert _fingerprints(real_keys) == before


def test_recovery_never_replaces_a_missing_key_named_by_a_published_binding(tmp_path):
    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    created = provider.create_binding("alice", token="published")
    (root / "keys-v1" / created.key_ref).rename(tmp_path / "unavailable-original-key")
    before = _fingerprints(root)
    with pytest.raises((ValueError, FileNotFoundError)):
        provider.recover_binding("alice", token="published")
    assert _fingerprints(root) == before
    assert not (root / "keys-v1" / created.key_ref).exists()


@pytest.mark.parametrize(
    "method, token",
    [
        ("recover_binding", "alice-token"),
        ("create_binding", "alice-token"),
        ("create_binding", "fresh-token"),
    ],
)
def test_recovery_refuses_valid_key_that_contradicts_its_original_intent(
    tmp_path, method, token
):
    import json

    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    provider.create_binding("alice", token="alice-token")
    bob = provider.create_binding("bob", token="bob-token")
    for path in (root / "bindings-v1").glob("*.json"):
        record = json.loads(path.read_text())
        if record["observer"] == "alice":
            record.update(key_ref=bob.key_ref, public_key=bob.public_key)
            path.write_text(json.dumps(record) + "\n")
    before = _fingerprints(root)
    with pytest.raises(ValueError):
        getattr(provider, method)("alice", token=token)
    assert _fingerprints(root) == before


@pytest.mark.parametrize("resume", ["none", "create", "recover"])
def test_token_is_reserved_even_when_its_index_publication_was_interrupted(
    tmp_path, monkeypatch, resume
):
    from custody import binding

    root = tmp_path / "mapped"
    provider = MappedCredentialProvider(root, namespace="work")
    publish = binding._publish_no_clobber

    def interrupt_index(path, *args, **kwargs):
        if path.parent.name == "intents-v1":
            raise Interrupted()
        return publish(path, *args, **kwargs)

    monkeypatch.setattr(binding, "_publish_no_clobber", interrupt_index)
    with pytest.raises(Interrupted):
        provider.create_binding("alice", token="one-token")
    monkeypatch.setattr(binding, "_publish_no_clobber", publish)
    if resume == "create":
        provider.create_binding("alice", token="one-token")
    elif resume == "recover":
        provider.recover_binding("alice", token="one-token")
    before = _fingerprints(root)
    with pytest.raises(ValueError):
        provider.create_binding("bob", token="one-token")
    assert _fingerprints(root) == before
    assert provider.resolve(_request("bob")) is None
