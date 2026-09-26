"""Descriptor-first SDK sealing uses captured vertex boundary evidence."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog, content_commitment
from engine.arrival_body import body_of_fact_row
from engine.arrival_file_backend import FileLedger
from engine.arrival_head_seam import AttestedLedger, NotWitnessed
from engine.credentials import CredentialPurpose, CredentialRequest, SigningDomain
from engine.handle import WriteCredentials
from engine.row_commitment import tick_commitment_hash
from lang import genesis_payload, parse_vertex_file
from sign import ed25519

from sdk import (
    ArrivalRefusal,
    CommittedOutcomeUnknown,
    CommittedProjectionFailed,
    CommittedUnwitnessed,
    MappedCredentialProvider,
    SdkValueError,
    edit_declaration,
    init_vertex,
)
from sdk.seal import SealReceipt, seal_fact
from sdk.types import TargetUnsupported


@pytest.fixture(autouse=True)
def _isolated_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "LOOPS_HOME"
    ):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))


class _Credentials:
    def for_write(self, _vertex: Path) -> WriteCredentials:
        return WriteCredentials()


def _target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    conditional: bool = False,
    loop_only: bool = False,
    boundary: bool = True,
) -> tuple[Path, ArrivalLog]:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    keypair = ed25519.load_or_generate(tmp_path / "keys")

    def arrival_sign(_observer: str, digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain=ARRIVAL_DOMAIN)

    def fact_sign(digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain=FACT_DOMAIN)

    log = ArrivalLog.mint(
        tmp_path / "seal.arrival", observer="custodian", signer=arrival_sign,
        key=keypair.public_b64, at=1.0,
    )
    vertex = tmp_path / "seal.vertex"
    if conditional:
        loops = (
            "  seal { fold { count \"inc\" } }\n"
            '  boundary when="seal" { condition "count" ">=" 2 }\n'
        )
    elif loop_only:
        loops = (
            "  seal {\n    fold { count \"inc\" }\n    boundary every=1\n  }\n"
            '  boundary when="seal"\n'
        )
    else:
        loops = "  item { fold { items \"collect\" 5 } }\n"
        if boundary:
            loops += '  boundary when="seal" status="closed"\n'
    vertex.write_text(
        f'name "sealed-vertex"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\nstrict true\n'
        "observers { alice { } }\nloops {\n"
        + loops
        + "}\n",
        encoding="utf-8",
    )
    declaration = json.dumps(genesis_payload(parse_vertex_file(vertex)))
    signature = fact_sign(
        fact_commitment_hash("_decl.genesis", 2.0, "custodian", "test", declaration)
    )
    log.append(
        "fact",
        body_of_fact_row((
            log.lineage(), "_decl.genesis", 2.0, "custodian", "test", declaration, signature,
        )),
        observer="custodian", origin="test", at=2.0, signer=arrival_sign,
    )
    from sdk import sync_target

    sync_target(vertex)
    return vertex, log


def test_seal_fact_merges_match_and_only_counts_own_vertex_tick(tmp_path, monkeypatch):
    vertex, log = _target(tmp_path, monkeypatch)

    result = seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)

    assert isinstance(result, SealReceipt)
    assert result.sealed is True
    assert result.vertex_name == "sealed-vertex"
    assert result.boundary_match == {"status": "closed"}
    assert result.receipt.tick_mark == "sealed-vertex"
    records = FileLedger(log).scan()
    fact = next(record for record in records if record["body"].get("kind") == "seal")
    assert json.loads(fact["body"]["payload"]) == {"status": "closed"}


def test_seal_fact_condition_commits_before_later_invocation_reaches_threshold(
    tmp_path, monkeypatch
):
    vertex, log = _target(tmp_path, monkeypatch, conditional=True)
    before = sum(1 for _ in FileLedger(log).scan())

    first = seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    second = seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=4.0)

    assert first.receipt.stored is True
    assert first.sealed is False
    assert first.receipt.tick_id is None
    assert second.receipt.stored is True
    assert second.sealed is True
    assert second.receipt.tick_mark == "sealed-vertex"
    assert sum(1 for _ in FileLedger(log).scan()) == before + 3


def test_loop_tick_named_seal_is_not_a_vertex_seal(tmp_path, monkeypatch):
    vertex, _log = _target(tmp_path, monkeypatch, loop_only=True)

    result = seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)

    assert result.receipt.tick_mark == "seal"
    assert result.receipt.tick_id is not None
    assert result.vertex_name == "sealed-vertex"
    assert result.sealed is False


def test_seal_refuses_missing_boundary_and_conflicting_match_without_mutating_ledger(
    tmp_path, monkeypatch
):
    vertex, log = _target(tmp_path, monkeypatch)
    before = log.path.read_bytes()
    vertex.write_text(
        vertex.read_text(encoding="utf-8").replace('boundary when="seal" status="closed"', ""),
        encoding="utf-8",
    )

    # The captured declaration, not this stale local locator cache, remains authoritative.
    result = seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    assert result.sealed is True

    after_stale_cache = log.path.read_bytes()
    with pytest.raises(ArrivalRefusal, match="conflicts"):
        seal_fact(
            vertex, {"status": "open"}, observer="alice", credentials=_Credentials(), ts=4.0
        )
    assert log.path.read_bytes() == after_stale_cache

    missing, missing_log = _target(tmp_path / "missing", monkeypatch, boundary=False)
    before_missing = missing_log.path.read_bytes()
    with pytest.raises(ArrivalRefusal, match="no boundary"):
        seal_fact(missing, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    assert missing_log.path.read_bytes() == before_missing
    assert before != b""


def test_seal_capture_once_and_full_head_cas_refuses_intervening_append(
    tmp_path, monkeypatch
):
    vertex, log = _target(tmp_path, monkeypatch)
    from engine import runtime_write

    original_capture = runtime_write.capture_runtime
    original_prepare = runtime_write.prepare_boundary_write
    captures = 0

    def counted_capture(*args, **kwargs):
        nonlocal captures
        captures += 1
        return original_capture(*args, **kwargs)

    def prepare_then_advance(*args, **kwargs):
        plan = original_prepare(*args, **kwargs)
        log.append(
            "fact",
            body_of_fact_row(("interloper", "item", 3.5, "alice", "test", "{}", None)),
            observer="alice", origin="test", at=3.5,
        )
        return plan

    monkeypatch.setattr(runtime_write, "capture_runtime", counted_capture)
    monkeypatch.setattr(runtime_write, "prepare_boundary_write", prepare_then_advance)
    with pytest.raises(ArrivalRefusal) as raised:
        seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)

    assert captures == 1
    assert raised.value.details["captured_head"]["ordinal"] == 1
    records = FileLedger(log).scan()
    assert [record["body"].get("id") for record in records][-1] == "interloper"
    assert not any(record["body"].get("kind") == "seal" for record in records)


def test_seal_duplicate_is_a_noop_but_differing_duplicate_refuses(tmp_path, monkeypatch):
    vertex, log = _target(tmp_path, monkeypatch)
    first = seal_fact(
        vertex, {"extra": "same"}, observer="alice", credentials=_Credentials(), ts=3.0,
        id_override="stable-seal",
    )
    before_retry = log.path.read_bytes()
    retry = seal_fact(
        vertex, {"extra": "same"}, observer="alice", credentials=_Credentials(), ts=3.0,
        id_override="stable-seal",
    )

    assert first.sealed is True
    assert retry.receipt.stored is False
    assert retry.receipt.tick_id is None
    assert retry.sealed is False
    assert log.path.read_bytes() == before_retry
    with pytest.raises(ArrivalRefusal, match="different content"):
        seal_fact(
            vertex, {"extra": "different"}, observer="alice", credentials=_Credentials(), ts=3.0,
            id_override="stable-seal",
        )
    assert log.path.read_bytes() == before_retry


def test_seal_rejects_incomplete_boundary_metadata_before_execute(tmp_path, monkeypatch):
    vertex, log = _target(tmp_path, monkeypatch)
    from engine import runtime_write

    original = runtime_write.prepare_boundary_write

    def incomplete(*args, **kwargs):
        return replace(original(*args, **kwargs), boundary_match=None)

    monkeypatch.setattr(runtime_write, "prepare_boundary_write", incomplete)
    monkeypatch.setattr(
        runtime_write, "execute_ordinary_write", lambda *_args, **_kwargs: pytest.fail("executed")
    )
    before = log.path.read_bytes()
    with pytest.raises(SdkValueError, match="incomplete captured evidence"):
        seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    assert log.path.read_bytes() == before


def test_seal_stays_on_resolved_arrival_path_if_locator_is_replaced(tmp_path, monkeypatch):
    vertex, _log = _target(tmp_path, monkeypatch)
    module = importlib.import_module("sdk.seal")
    original = module._arrival_descriptor
    calls = 0

    def resolve_then_replace(path):
        nonlocal calls
        calls += 1
        resolved = original(path)
        vertex.write_text('name "legacy"\nstore "legacy.db"\nloops { }\n', encoding="utf-8")
        return resolved

    monkeypatch.setattr(module, "_arrival_descriptor", resolve_then_replace)
    result = module.seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    assert calls == 1
    assert result.receipt.write_path == "arrival"
    assert result.sealed is True


def _mapped_seal_target(tmp_path: Path) -> tuple[Path, ArrivalLog, MappedCredentialProvider]:
    provider = MappedCredentialProvider(
        tmp_path / "custody", namespace="seal-test", receipt_observer="alice"
    )
    provider.create_binding("alice", token="bind-alice")
    target = tmp_path / "mapped.vertex"
    initialized = init_vertex(
        target, name="mapped-seal", store_type="arrival", observer="alice",
        location=str(tmp_path / "mapped.arrival"), credentials=provider,
    )
    proposal = target.with_name("mapped-proposal.vertex")
    proposal.write_text(
        target.read_text(encoding="utf-8")[:-2] + '  boundary when="seal"\n}\n',
        encoding="utf-8",
    )
    edit_declaration(
        target, proposal.read_text(encoding="utf-8"), observer="alice", credentials=provider
    )
    assert initialized.store is not None
    return target, ArrivalLog(initialized.store.location), provider


def test_seal_mapped_author_and_receipt_signatures_and_signed_era_binding_refusal(tmp_path):
    target, log, provider = _mapped_seal_target(tmp_path)
    sealed = seal_fact(
        target, {}, observer="alice", credentials=provider, ts=3.0, id_override="mapped-seal"
    )
    assert sealed.sealed is True and sealed.receipt.tick_id is not None
    fact_record = next(record for record in log.walk() if record["body"].get("id") == "mapped-seal")
    fact_binding = provider.resolve(CredentialRequest(
        provider.namespace, "alice", SigningDomain.FACT, CredentialPurpose.AUTHORSHIP
    ))
    arrival_binding = provider.resolve(CredentialRequest(
        provider.namespace, "alice", SigningDomain.ARRIVAL, CredentialPurpose.AUTHORSHIP
    ))
    assert fact_binding is not None and arrival_binding is not None
    assert provider.verify(
        SigningDomain.FACT, fact_binding.evidence.public_key, fact_record["body"]["signature"],
        fact_commitment_hash("seal", 3.0, "alice", "", fact_record["body"]["payload"]),
    )
    assert provider.verify(
        SigningDomain.ARRIVAL, arrival_binding.evidence.public_key, fact_record["sig"],
        content_commitment(
            "fact", fact_record["at"], fact_record["observer"],
            fact_record["origin"], fact_record["body"],
        ),
    )
    tick_record = next(
        record for record in log.walk() if record["body"].get("id") == sealed.receipt.tick_id
    )
    receipt_binding = provider.resolve(CredentialRequest(
        provider.namespace, "alice", SigningDomain.TICK, CredentialPurpose.RECEIPT
    ))
    assert receipt_binding is not None
    row = tick_record["body"]
    assert provider.verify(
        SigningDomain.TICK, receipt_binding.evidence.public_key, row["signature"],
        tick_commitment_hash(tuple(row[key] for key in (
            "id", "name", "ts", "since", "origin", "payload", "prev_hash", "window_start",
            "fact_cursor", "window_hash",
        ))),
    )

    no_receipt = MappedCredentialProvider(tmp_path / "custody", namespace="seal-test")
    before_ledger = log.path.read_bytes()
    before_custody = {
        path.relative_to(no_receipt.root): path.read_bytes()
        for path in no_receipt.root.rglob("*") if path.is_file()
    }
    with pytest.raises(ArrivalRefusal, match="missing-required"):
        seal_fact(target, {}, observer="alice", credentials=no_receipt, ts=4.0)
    assert log.path.read_bytes() == before_ledger
    assert {
        path.relative_to(no_receipt.root): path.read_bytes()
        for path in no_receipt.root.rglob("*") if path.is_file()
    } == before_custody


def test_seal_preserves_real_durable_unknown_projection_and_witness_outcomes(
    tmp_path, monkeypatch
):
    vertex, log = _target(tmp_path, monkeypatch)
    original_append = AttestedLedger.append
    calls = 0

    def append_then_raise(self, expected, drafts):
        nonlocal calls
        calls += 1
        original_append(self, expected, drafts)
        raise OSError("completion response lost")

    with monkeypatch.context() as patch:
        patch.setattr(AttestedLedger, "append", append_then_raise)
        with pytest.raises(CommittedOutcomeUnknown) as unknown:
            seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    assert calls == 1
    assert unknown.value.details["captured_head"]["ordinal"] == 1
    assert unknown.value.details["fact_id"] and unknown.value.details["tick_id"]
    assert FileLedger(log).head().ordinal == 3

    vertex, log = _target(tmp_path / "projection", monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(
            "engine.arrival_maintenance.sync_projection",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("projection down")),
        )
        with pytest.raises(CommittedProjectionFailed) as projection:
            seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    assert projection.value.details["commit"]["after"]["ordinal"] == FileLedger(log).head().ordinal
    assert projection.value.details["fact_id"] and projection.value.details["tick_id"]

    vertex, log = _target(tmp_path / "witness", monkeypatch)
    def append_then_unwitnessed(self, expected, drafts):
        commit = original_append(self, expected, drafts)
        raise NotWitnessed("witness lost", head=commit.after, commit=commit)
    with monkeypatch.context() as patch:
        patch.setattr(AttestedLedger, "append", append_then_unwitnessed)
        with pytest.raises(CommittedUnwitnessed) as witness:
            seal_fact(vertex, {}, observer="alice", credentials=_Credentials(), ts=3.0)
    assert witness.value.details["commit"]["after"]["ordinal"] == FileLedger(log).head().ordinal
    assert witness.value.details["fact_id"] and witness.value.details["tick_id"]


def test_seal_fact_never_uses_legacy_writer(tmp_path):
    vertex = tmp_path / "legacy.vertex"
    vertex.write_text('name "legacy"\nstore "legacy.db"\nloops { }\n', encoding="utf-8")

    with pytest.raises(TargetUnsupported):
        seal_fact(vertex, {}, observer="alice", credentials=_Credentials())
