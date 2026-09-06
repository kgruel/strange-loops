"""SDK source execution preserves captured custody and collector evidence."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
from atoms import Fact, SourceError
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_head_seam import AttestedLedger, NotWitnessed
from engine.arrival_registry import BackendRegistry
from engine.handle import WriteCredentials
from lang import genesis_payload, parse_vertex_file
from sign import ed25519

from sdk import (
    AdmissionFailed,
    ArrivalRefusal,
    SourceRunResult,
    TargetUnsupported,
    read_fact_by_id,
    run_sources,
    sync_target,
)


class _UnsignedCredentials:
    def for_write(self, _vertex: Path) -> WriteCredentials:
        return WriteCredentials()


def _target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    definitions: tuple[tuple[str, str], ...],
    *,
    boundary_by_kind: dict[str, str] | None = None,
) -> tuple[Path, ArrivalLog]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    keypair = ed25519.load_or_generate(tmp_path / "fixture-keys")

    def arrival_sign(_observer: str, digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain=ARRIVAL_DOMAIN)

    log = ArrivalLog.mint(
        tmp_path / "sources.arrival",
        observer="physical-custodian",
        signer=arrival_sign,
        key=keypair.public_b64,
        at=1.0,
    )
    paths: list[Path] = []
    boundaries = boundary_by_kind or {}
    for kind, cadence in definitions:
        path = tmp_path / f"{kind}.loop"
        path.write_text(
            f'kind "{kind}"\n'
            'observer "kyle"\n'
            f'source "collect-{kind}"\n'
            f"{cadence}",
            encoding="utf-8",
        )
        paths.append(path)
    source_text = "sources {\n" + "".join(
        f'  path "./{path.name}"\n' for path in paths
    ) + "}\n"
    loop_text = "".join(
        "  "
        + kind
        + " {\n"
        + '    fold { items "collect" 20 }\n'
        + (f"    {boundaries[kind]}\n" if kind in boundaries else "")
        + "  }\n"
        for kind, _cadence in definitions
    )
    vertex = tmp_path / "sources.vertex"
    vertex.write_text(
        f'name "sources"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        "strict true\n"
        "observers {\n  kyle { }\n  alice { }\n}\n"
        f"{source_text}"
        "loops {\n"
        f"{loop_text}"
        "}\n",
        encoding="utf-8",
    )
    declaration = json.dumps(genesis_payload(parse_vertex_file(vertex)))
    inner = ed25519.sign(
        keypair,
        fact_commitment_hash(
            "_decl.genesis",
            2.0,
            "physical-custodian",
            "test",
            declaration,
        ).encode(),
        domain=FACT_DOMAIN,
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "physical-custodian",
                "test",
                declaration,
                inner,
            )
        ),
        observer="physical-custodian",
        origin="test",
        at=2.0,
        signer=arrival_sign,
    )
    sync_target(vertex)
    return vertex, log


def test_sdk_run_sources_serializes_fixed_tiers_and_actual_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _target(
        tmp_path,
        monkeypatch,
        (("a", ""), ("b", 'on "_sync.a"\n')),
    )
    attempts = Counter()

    def factory(source):
        async def collect():
            attempts[source.kind] += 1
            yield Fact(source.kind, 10.0 + len(attempts), {"kind": source.kind}, observer="kyle")

        return collect()

    result = asyncio.run(
        run_sources(
            vertex,
            observer="alice",
            force=True,
            credentials=_UnsignedCredentials(),
            registry=BackendRegistry.with_builtin_backends(),
            collector_factory=factory,
            evaluated_at=9.0,
        )
    )
    assert isinstance(result, SourceRunResult)
    assert result.status == "ok"
    assert result.tier_decisions == ((0,), (1,))
    assert len(result.bases) == len(result.tiers) == 2
    assert all(tier.commit is not None for tier in result.tiers)
    assert result.tiers[1].basis.captured_head == result.tiers[0].commit.after
    assert attempts == Counter(a=1, b=1)
    wire = result.as_dict()
    assert wire["tiers"][0]["sources"][0]["facts"][0]["payload"] == {"kind": "a"}
    assert wire["tiers"][1]["commit"]["record_count"] >= 1
    assert "initial_capture" not in json.dumps(wire)
    for tier in result.tiers:
        fact_id = tier.sources[0].facts[0].id
        lookup = read_fact_by_id(vertex, fact_id)
        assert lookup.found and lookup.basis is not None
    json.dumps(wire)


def test_sdk_source_error_is_durable_error_not_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _target(tmp_path, monkeypatch, (("a", ""),))

    def factory(source):
        async def collect():
            yield Fact("a", 10.0, {"kept": True}, observer="kyle")
            raise SourceError(source.command, returncode=9, stderr="collector failed")

        return collect()

    result = asyncio.run(
        run_sources(
            vertex,
            observer="alice",
            credentials=_UnsignedCredentials(),
            collector_factory=factory,
            evaluated_at=9.0,
        )
    )
    source = result.tiers[0].sources[0]
    assert result.status == "error" and result.terminal is None
    assert source.status == "error" and source.stderr == "collector failed"
    assert source.facts[0].payload == {"kept": True}
    assert result.error_lifecycle_ids == result.durable_error_lifecycle_ids
    json.dumps(result.as_dict())


def test_sdk_non_json_fact_is_known_uncommitted_with_typed_payload_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _target(tmp_path, monkeypatch, (("a", ""),))
    before = log.path.read_bytes()

    def factory(source):
        async def collect():
            yield Fact("a", 10.0, {"bad": object()}, observer="kyle")

        return collect()

    result = asyncio.run(
        run_sources(
            vertex,
            observer="alice",
            credentials=_UnsignedCredentials(),
            collector_factory=factory,
            evaluated_at=9.0,
        )
    )
    assert result.status == "incomplete"
    assert result.known_uncommitted is result.tiers[0]
    assert result.unknown is None
    assert result.terminal is not None and result.terminal.category == "refused"
    fact = result.as_dict()["known_uncommitted"]["sources"][0]["facts"][0]
    assert fact["payload"] is None and fact["payload_serializable"] is False
    assert fact["payload_issues"] == [{"path": "$.bad", "type": "object"}]
    json.dumps(result.as_dict())
    assert log.path.read_bytes() == before


@pytest.mark.parametrize(
    ("payload", "ts", "payload_type"),
    [
        (None, 10.0, "NoneType"),
        (["not", "an", "object"], 10.0, "list"),
        ({}, float("nan"), "dict"),
    ],
)
def test_sdk_invalid_fact_envelope_remains_strict_json_serializable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload,
    ts: float,
    payload_type: str,
) -> None:
    vertex, log = _target(tmp_path, monkeypatch, (("a", ""),))
    before = log.path.read_bytes()

    def factory(source):
        async def collect():
            yield Fact("a", ts, payload, observer="kyle")

        return collect()

    result = asyncio.run(
        run_sources(
            vertex,
            observer="alice",
            credentials=_UnsignedCredentials(),
            collector_factory=factory,
            evaluated_at=9.0,
        )
    )
    assert result.known_uncommitted is not None
    fact = result.as_dict()["known_uncommitted"]["sources"][0]["facts"][0]
    assert fact["payload_type"] == payload_type
    if payload_type == "dict":
        assert fact["ts"] is None
        assert fact["envelope_issues"] == [
            {"field": "ts", "type": "float", "issue": "non-finite"}
        ]
    else:
        assert fact["payload"] == payload
        assert fact["payload_valid_object"] is False
        assert fact["payload_issues"][0]["issue"] == "expected-object"
    json.dumps(result.as_dict(), allow_nan=False)
    assert log.path.read_bytes() == before


def test_sdk_invalid_source_output_keeps_type_and_stable_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _target(tmp_path, monkeypatch, (("a", ""),))
    before = log.path.read_bytes()

    def factory(source):
        async def collect():
            yield Fact("a", 10.0, {"kept": True}, observer="kyle")
            yield {"not": "a fact"}

        return collect()

    result = asyncio.run(
        run_sources(
            vertex,
            observer="alice",
            credentials=_UnsignedCredentials(),
            collector_factory=factory,
            evaluated_at=9.0,
        )
    )
    source = result.known_uncommitted.sources[0]
    assert source.facts[0].payload == {"kept": True}
    assert source.error_type == "InvalidSourceOutput"
    assert result.terminal.category == "invalid-output"
    assert result.terminal.details == {
        "cause_type": "InvalidSourceOutput",
        "source_index": 0,
        "value_type": "dict",
    }
    json.dumps(result.as_dict())
    assert log.path.read_bytes() == before


def test_sdk_unknown_and_unwitnessed_source_outcomes_keep_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mode in ("unknown", "unwitnessed"):
        vertex, _log = _target(tmp_path / mode, monkeypatch, (("a", ""),))
        original = AttestedLedger.append
        attempts = 0

        def append_then_raise(
            self,
            expected,
            drafts,
            *,
            _append=original,
            _mode=mode,
        ):
            nonlocal attempts
            attempts += 1
            commit = _append(self, expected, drafts)
            if _mode == "unwitnessed":
                raise NotWitnessed("witness unavailable", head=commit.after, commit=commit)
            raise OSError("adapter reply lost")

        with monkeypatch.context() as patch:
            patch.setattr(AttestedLedger, "append", append_then_raise)

            def factory(source, _mode=mode):
                async def collect():
                    yield Fact("a", 10.0, {"mode": _mode}, observer="kyle")

                return collect()

            result = asyncio.run(
                run_sources(
                    vertex,
                    observer="alice",
                    credentials=_UnsignedCredentials(),
                    collector_factory=factory,
                    evaluated_at=9.0,
                )
            )
        assert attempts == 1 and result.status == "incomplete"
        assert result.terminal is not None
        if mode == "unknown":
            assert result.unknown is result.tiers[0]
            assert result.known_uncommitted is None
            assert result.terminal.category == "unknown"
            assert result.tiers[0].commit is None
            assert len(result.tiers[0].fact_ids) == 3  # domain, lifecycle, overall
        else:
            assert result.unknown is None and result.known_uncommitted is None
            assert result.terminal.category == "committed-unwitnessed"
            assert result.tiers[0].commit is not None
            assert result.tiers[0].witnessed is False
        assert result.tiers[0].sources[0].facts[0].payload == {"mode": mode}
        json.dumps(result.as_dict())


def test_sdk_exposes_unattempted_run_intent_and_dispatch_failure_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(path: Path, dispatcher=None):
        def factory(source):
            async def collect():
                yield Fact("a", 10.0, {"value": "run"}, observer="kyle")

            return collect()

        return await run_sources(
            path,
            observer="alice",
            credentials=_UnsignedCredentials(),
            collector_factory=factory,
            dispatcher=dispatcher,
            evaluated_at=9.0,
        )

    vertex, _log = _target(
        tmp_path / "absent",
        monkeypatch,
        (("a", ""),),
        boundary_by_kind={"a": 'boundary every=1 { run "captured-command" }'},
    )
    absent = asyncio.run(run(vertex))
    assert absent.tiers[0].dispatch_status == "not-requested"
    assert absent.tiers[0].dispatches[0].attempted is False
    assert absent.tiers[0].dispatches[0].command == "captured-command"

    failed_vertex, _failed_log = _target(
        tmp_path / "failed",
        monkeypatch,
        (("a", ""),),
        boundary_by_kind={"a": 'boundary every=1 { run "captured-command" }'},
    )
    calls = 0

    def fail_dispatch(_commit, _intents):
        nonlocal calls
        calls += 1
        raise OSError("dispatcher failed")

    failed = asyncio.run(run(failed_vertex, fail_dispatch))
    assert calls == 1 and failed.status == "incomplete"
    assert failed.terminal is not None and failed.terminal.category == "dispatch-failed"
    assert failed.tiers[0].commit is not None
    assert failed.tiers[0].dispatch_status == "failed"
    assert failed.tiers[0].dispatches[0].attempted is True


def test_sdk_source_projection_failure_retains_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _target(tmp_path, monkeypatch, (("a", ""),))

    def factory(source):
        async def collect():
            yield Fact("a", 10.0, {}, observer="kyle")

        return collect()

    monkeypatch.setattr(
        "engine.arrival_sources.sync_projection",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("projection failed")),
    )
    result = asyncio.run(
        run_sources(
            vertex,
            observer="alice",
            credentials=_UnsignedCredentials(),
            collector_factory=factory,
            evaluated_at=9.0,
        )
    )
    assert result.status == "incomplete"
    assert result.terminal is not None
    assert result.terminal.category == "committed-projection-failed"
    assert result.tiers[0].outcome == "committed-projection-failed"
    assert result.tiers[0].commit is not None


def test_sdk_run_sources_uses_no_legacy_fallback_or_key_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _target(tmp_path / "arrival", monkeypatch, (("a", ""),))
    assert not (vertex.parent / "keys").exists()

    def factory(source):
        async def collect():
            yield Fact("a", 10.0, {}, observer="kyle")

        return collect()

    result = asyncio.run(
        run_sources(
            vertex,
            observer="alice",
            collector_factory=factory,
            evaluated_at=9.0,
        )
    )
    assert result.status == "ok"
    assert not (vertex.parent / "keys").exists()

    with pytest.raises(AdmissionFailed):
        asyncio.run(
            run_sources(
                vertex,
                observer="mallory",
                credentials=_UnsignedCredentials(),
                collector_factory=factory,
            )
        )

    vertex.write_text(
        vertex.read_text(encoding="utf-8").replace(
            'role="authority"', 'role="replica"'
        ),
        encoding="utf-8",
    )
    before = log.path.read_bytes()
    with pytest.raises(ArrivalRefusal):
        asyncio.run(
            run_sources(
                vertex,
                observer="alice",
                credentials=_UnsignedCredentials(),
                collector_factory=factory,
            )
        )
    assert log.path.read_bytes() == before

    legacy = tmp_path / "legacy.vertex"
    legacy.write_text(
        'name "legacy"\nloops { note { fold { items "collect" 2 } } }\n',
        encoding="utf-8",
    )
    with pytest.raises(TargetUnsupported):
        asyncio.run(run_sources(legacy, observer="alice"))
