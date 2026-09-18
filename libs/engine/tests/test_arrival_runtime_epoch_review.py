"""Independent review probes for the fresh Arrival runtime epoch."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from lang.document import vertex_to_documents
from lang.loader import parse_vertex

from engine.arrival_contract import (
    DeclarationAnchor,
    Fact,
    FactPage,
    Head,
    ReadBasis,
    Tick,
    Watermark,
)
from engine.declaration import (
    DeclarationResolutionError,
    UnsupportedProtocol,
    _runtime_epoch_payload,
    runtime_epoch_from_anchor,
)
from engine.runtime_write import _build_effective_arrival_candidate


class Snapshot:
    def __init__(self, head: Head, *, documents=(), anchor_ordinal=0):
        self.represented = Watermark(head.lineage, head.ordinal)
        self.view_generation = "test-view"
        payload = {
            "protocol": 2,
            "documents": list(documents),
            "runtime_epoch": "fresh-after-anchor-v1",
        }
        self.declaration_anchor = DeclarationAnchor(
            own_lineage=head.lineage,
            genesis=Fact(
                id=head.lineage,
                kind="_decl.genesis",
                ts=0.0,
                observer="kyle",
                origin="",
                payload=payload,
                arrival_ordinal=anchor_ordinal,
                arrival_seq=0,
                payload_text=json.dumps(payload, separators=(",", ":")),
                signature="inner-signature",
            ),
        )
        self._facts = (self.declaration_anchor.genesis,)
        self._ticks = ()

    def facts(self, _request):
        return FactPage(self._facts, None, False, "oldest")

    def ticks(self, _request):
        return self._ticks

    def close(self):
        return None


def _head() -> Head:
    return Head("lineage", 7, "head-hash")


def _fake_declaration_record(snapshot: Snapshot) -> dict:
    genesis = snapshot.declaration_anchor.genesis
    assert genesis is not None
    return {
        "k": "fact",
        "lin": snapshot.declaration_anchor.own_lineage,
        "ord": genesis.arrival_ordinal,
        "observer": genesis.observer,
        "origin": genesis.origin,
        "sig": "outer-signature",
        "body": {
            "id": genesis.id,
            "kind": genesis.kind,
            "ts": genesis.ts,
            "observer": genesis.observer,
            "origin": genesis.origin,
            "payload": genesis.payload_text,
            "signature": genesis.signature,
        },
    }


def _fresh_snapshot(*, facts=(), ticks=()):
    effective = parse_vertex(
        'name "effective"\n'
        "loops {\n"
        "  boundary every=1\n"
        '  note { fold { count "inc" } }\n'
        "}\n"
    )
    documents = [document.as_json() for document in vertex_to_documents(effective)]
    snapshot = Snapshot(_head(), documents=documents, anchor_ordinal=5)
    genesis = snapshot.declaration_anchor.genesis
    assert genesis is not None
    payload = {
        "protocol": 2,
        "documents": documents,
        "runtime_epoch": "fresh-after-anchor-v1",
    }
    genesis = replace(
        genesis,
        payload=payload,
        payload_text=json.dumps(payload, separators=(",", ":")),
        signature="inner-signature",
    )
    snapshot.declaration_anchor = replace(snapshot.declaration_anchor, genesis=genesis)
    snapshot._facts = (genesis, *facts)
    snapshot._ticks = tuple(ticks)
    return snapshot, parse_vertex(
        'name "locator"\nloops { note { fold { count "inc" } } }\n'
    )


def test_fresh_candidate_excludes_history_but_keeps_global_evidence():
    before = Fact(
        "before", "note", 1.0, "kyle", "", {"inc": 9}, 4, 0, '{"inc":9}'
    )
    after = Fact(
        "after", "note", 2.0, "kyle", "", {"inc": 2}, 6, 0, '{"inc":2}'
    )
    snapshot, locator = _fresh_snapshot(facts=(before, after))
    wire = _fake_declaration_record(snapshot)
    wire["sig"] = "outer-signature"

    candidate, _effective, _docs, _sources, all_facts, _all_ticks, runtime_facts, _runtime_ticks = (
        _build_effective_arrival_candidate(
            snapshot,
            ReadBasis(_head().lineage, _head(), _head(), "test-view"),
            locator,
            wire_genesis_record=wire,
        )
    )

    assert candidate.state("note") == {"count": 1}
    assert [fact.id for fact in all_facts] == [
        snapshot.declaration_anchor.own_lineage,
        "before",
        "after",
    ]
    assert [fact.id for fact in runtime_facts] == ["after"]


def test_fresh_epoch_ignores_pre_anchor_owned_vertex_tick_for_continuity():
    snapshot, locator = _fresh_snapshot(
        ticks=(
            Tick(
                "old-vertex-tick",
                "effective",
                2.0,
                None,
                "effective",
                {},
                4,
                0,
                "{}",
            ),
        )
    )
    wire = _fake_declaration_record(snapshot)
    wire["sig"] = "outer-signature"
    (
        candidate,
        _effective,
        _docs,
        _sources,
        _all_facts,
        all_ticks,
        _runtime_facts,
        runtime_ticks,
    ) = _build_effective_arrival_candidate(
        snapshot,
        ReadBasis(_head().lineage, _head(), _head(), "test-view"),
        locator,
        wire_genesis_record=wire,
    )

    assert candidate.state("note") == {"count": 0}
    assert [tick.id for tick in all_ticks] == ["old-vertex-tick"]
    assert runtime_ticks == ()


def test_fresh_marker_must_match_the_physical_genesis_payload():
    snapshot, _locator = _fresh_snapshot()
    wire = _fake_declaration_record(snapshot)
    wire["sig"] = "outer-signature"
    physical_payload = json.loads(wire["body"]["payload"])
    physical_payload["runtime_epoch"] = "strict"
    wire["body"]["payload"] = json.dumps(physical_payload, separators=(",", ":"))

    with pytest.raises(DeclarationResolutionError, match="projection differs"):
        runtime_epoch_from_anchor(snapshot.declaration_anchor, wire_record=wire)


@pytest.mark.parametrize("protocol", [0, -1])
def test_unsupported_legacy_protocol_does_not_downgrade_to_strict(protocol):
    with pytest.raises(UnsupportedProtocol):
        _runtime_epoch_payload({"protocol": protocol, "documents": []}, 5)
