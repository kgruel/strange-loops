"""Tests for migrate.transform — the Transformer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.arrival import (
    GENESIS_KIND,
    KEY_INTRODUCTION_KIND,
    ArrivalLog,
    AuthorshipUnverified,
    verify_authorship,
)
from engine.arrival_contract import RecordDraft
from lang import ObserverDecl, VertexFile, parse_vertex

from migrate.legacy_ids import FactRow, Transform, identity, ulid_migration
from migrate.refusals import (
    BatchRegroupRefused,
    DeclarationKeyRefused,
    LegacySourceRefused,
    MigrationRefused,
    MissingCustodianKeyRefused,
)
from migrate.transform import (
    DroppedUnit,
    GenesisRequirements,
    TransformExceptions,
    TransformResult,
    coerce_vertex,
    transform,
)

from ._fixtures import (
    ALL_FACT_ROWS,
    ALL_TICK_ROWS,
    BATCH_LINE_ALICE,
    BATCH_ROW_1,
    BATCH_ROW_2,
    FACT_CANONICAL_ULID_SIGNED,
    FACT_CANONICAL_ULID_UNSIGNED,
    FACT_UUID4_SIGNED,
    FACT_UUID4_UNSIGNED,
    TICK_1,
    TICK_2,
    build_absent_observer_jsonl,
    build_codec_invalid_sqlite,
    build_combined_defects_jsonl,
    build_empty_observer_sqlite,
    build_flat_equivalent_jsonl,
    build_mixed_observer_jsonl,
    build_synthetic_jsonl,
    build_synthetic_sqlite,
    build_type_error_batch_jsonl,
)

ARRIVAL_DOMAIN = "test-arrival-v1"


def _ed25519_verify(key_b64: str, signature: str, digest: str) -> bool:
    from sign import ed25519

    try:
        public = ed25519.public_key_from_b64(key_b64)
    except ValueError:
        return False
    return ed25519.verify(public, signature, digest.encode(), domain=ARRIVAL_DOMAIN)


class CustodianFixture:
    """One observer's real Ed25519 keypair plus injected signer."""

    def __init__(self, tmp_path: Path, name: str) -> None:
        from sign import ed25519

        self.name = name
        self.keypair = ed25519.load_or_generate(tmp_path / "keys" / name)
        self.public = self.keypair.public_b64

    def signer(self, observer: str, digest: str) -> str | None:
        from sign import ed25519

        return ed25519.sign(self.keypair, digest.encode(), domain=ARRIVAL_DOMAIN)


def _make_vertex_file(
    custodian: str,
    observers: list[tuple[str, str | None]],
) -> VertexFile:
    decls = tuple(
        ObserverDecl(name=name, key=key)
        for name, key in observers
    )
    return VertexFile(
        name=custodian,
        loops={},
        observers=decls,
    )


@pytest.fixture
def kyle(tmp_path: Path) -> CustodianFixture:
    return CustodianFixture(tmp_path, "kyle")


@pytest.fixture
def alice(tmp_path: Path) -> CustodianFixture:
    return CustodianFixture(tmp_path, "alice")


@pytest.fixture
def bob(tmp_path: Path) -> CustodianFixture:
    return CustodianFixture(tmp_path, "bob")


# ---------------------------------------------------------------------------
# 1. Signature byte-preservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["jsonl", "sqlite"])
def test_signature_byte_preservation_and_honest_absence(tmp_path: Path, kyle, alice, bob, fmt: str) -> None:
    """Authored inner fact signatures ride verbatim byte-for-byte; unsigned rows stay unsigned;
    payload text is preserved verbatim without re-serialization.
    """
    if fmt == "jsonl":
        source_path = build_synthetic_jsonl(tmp_path / "legacy.jsonl")
    else:
        source_path = build_synthetic_sqlite(tmp_path / "legacy.sqlite")

    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public), ("bob", bob.public)])
    result = transform(source_path, vf, rule=identity(), signer=kyle.signer)

    # Key introductions are first 2 drafts (alice, bob)
    migrated_drafts = [d for d in result.drafts if d.kind != KEY_INTRODUCTION_KIND]

    # Check signed facts carry exact signature bytes
    uuid4_signed = next(d for d in migrated_drafts if d.body.get("id") == FACT_UUID4_SIGNED["id"])
    assert uuid4_signed.body["signature"] == FACT_UUID4_SIGNED["signature"]
    assert uuid4_signed.body["payload"] == FACT_UUID4_SIGNED["payload"]
    assert uuid4_signed.signature is None  # outer-unsigned

    canonical_signed = next(d for d in migrated_drafts if d.body.get("id") == FACT_CANONICAL_ULID_SIGNED["id"])
    assert canonical_signed.body["signature"] == FACT_CANONICAL_ULID_SIGNED["signature"]
    assert canonical_signed.body["payload"] == FACT_CANONICAL_ULID_SIGNED["payload"]
    assert canonical_signed.signature is None  # outer-unsigned

    # Check signed batch row carries exact signature bytes (F7b)
    if fmt == "jsonl":
        batch_draft = next(d for d in migrated_drafts if d.kind == "batch")
        assert batch_draft.body["rows"][0]["id"] == BATCH_ROW_1["id"]
        assert "signature" not in batch_draft.body["rows"][0]
        assert batch_draft.body["rows"][1]["id"] == BATCH_ROW_2["id"]
        assert batch_draft.body["rows"][1]["signature"] == "sig-alice-batch-2"

    # Check unsigned facts honestly omit signature
    uuid4_unsigned = next(d for d in migrated_drafts if d.body.get("id") == FACT_UUID4_UNSIGNED["id"])
    assert "signature" not in uuid4_unsigned.body
    assert uuid4_unsigned.body["payload"] == FACT_UUID4_UNSIGNED["payload"]
    assert uuid4_unsigned.signature is None

    canonical_unsigned = next(d for d in migrated_drafts if d.body.get("id") == FACT_CANONICAL_ULID_UNSIGNED["id"])
    assert "signature" not in canonical_unsigned.body
    assert canonical_unsigned.body["payload"] == FACT_CANONICAL_ULID_UNSIGNED["payload"]
    assert canonical_unsigned.signature is None


# ---------------------------------------------------------------------------
# 2. Key-introduction ordering and authority validity
# ---------------------------------------------------------------------------


def test_key_introduction_ordering_and_authority_validity(tmp_path: Path, kyle, alice, bob) -> None:
    """Key introductions precede all migrated records, are signed by the custodian,
    and verify against Arrival authority semantics (verify_authorship).
    """
    source_path = build_synthetic_jsonl(tmp_path / "legacy.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public), ("bob", bob.public)])

    result = transform(source_path, vf, rule=identity(), signer=kyle.signer)

    # 1. Check genesis requirements
    assert result.genesis == GenesisRequirements(custodian="kyle", key=kyle.public)

    # 2. Check draft order: key introductions at ordinals 1..2
    assert len(result.drafts) >= 2
    draft_alice = result.drafts[0]
    draft_bob = result.drafts[1]

    assert draft_alice.kind == KEY_INTRODUCTION_KIND
    assert draft_alice.observer == "kyle"
    assert draft_alice.body == {"observer": "alice", "key": alice.public}
    assert draft_alice.signature is not None

    assert draft_bob.kind == KEY_INTRODUCTION_KIND
    assert draft_bob.observer == "kyle"
    assert draft_bob.body == {"observer": "bob", "key": bob.public}
    assert draft_bob.signature is not None

    # All remaining drafts are migrated fact/batch/tick records, all outer-unsigned
    for draft in result.drafts[2:]:
        assert draft.kind in ("fact", "batch", "tick")
        assert draft.signature is None

    # 3. Materialize Arrival log and assert authority walk succeeds
    log_path = tmp_path / "target.arrival"
    log = ArrivalLog.mint(
        log_path,
        observer=result.genesis.custodian,
        key=result.genesis.key,
        signer=kyle.signer,
    )
    for draft in result.drafts:
        log.append(
            draft.kind,
            dict(draft.body),
            observer=draft.observer,
            origin=draft.origin,
            at=draft.authored_at,
            signer=(lambda obs, dig, sig=draft.signature: sig) if draft.signature else None,
        )

    resolutions = verify_authorship(log, _ed25519_verify)
    # Ordinal 0 (genesis), ordinal 1 (intro alice), ordinal 2 (intro bob)
    assert len(resolutions) == 3
    assert (resolutions[0].ordinal, resolutions[0].observer, resolutions[0].key) == (0, "kyle", kyle.public)
    assert (resolutions[1].ordinal, resolutions[1].observer, resolutions[1].key) == (1, "kyle", kyle.public)
    assert (resolutions[2].ordinal, resolutions[2].observer, resolutions[2].key) == (2, "kyle", kyle.public)

    # After ordinal 2, alice and bob keys are valid in the log!
    # Append a live record signed by alice and verify it resolves under alice's key introduced at ordinal 1
    log.append("fact", {"id": "01ARZ3NDEKTSV4RRFFQ69G5F99", "kind": "event", "ts": 2000.0, "observer": "alice", "origin": "live", "payload": "{}"}, observer="alice", signer=alice.signer)
    resolutions_after = verify_authorship(log, _ed25519_verify)
    assert len(resolutions_after) == 4
    live_res = resolutions_after[3]
    assert live_res.observer == "alice"
    assert live_res.key == alice.public
    assert live_res.introduced_ordinal == 1


# ---------------------------------------------------------------------------
# 3. §G.3 exception edges
# ---------------------------------------------------------------------------


def test_section_g3_exception_edges_land_in_report_and_do_not_refuse(tmp_path: Path, kyle, alice) -> None:
    """§G.3 edges:
    - Declared observer with key=None -> skipped from intros, in keyless_declared_observers
    - Undeclared observer appearing in rows (carol) -> admitted, in undeclared_row_observers
    Neither causes a refusal.
    """
    source_path = build_synthetic_jsonl(tmp_path / "legacy.jsonl")
    # bob is declared with key=None (dan is also declared with key=None); carol is undeclared in .vertex
    vf = _make_vertex_file(
        "kyle",
        [
            ("kyle", kyle.public),
            ("alice", alice.public),
            ("dan", None),  # keyless declared
        ],
    )
    result = transform(source_path, vf, rule=identity(), signer=kyle.signer)

    # Edge 1: dan in keyless_declared_observers
    assert "dan" in result.exceptions.keyless_declared_observers
    # dan has no key introduction draft
    intro_observers = [d.body["observer"] for d in result.drafts if d.kind == KEY_INTRODUCTION_KIND]
    assert "dan" not in intro_observers
    assert "alice" in intro_observers

    # Edge 2: bob and carol appear in legacy source rows (FACT_UUID4_UNSIGNED is bob, FACT_CANONICAL_ULID_UNSIGNED is carol)
    # Both bob and carol are undeclared in vf.observers:
    assert "bob" in result.exceptions.undeclared_row_observers
    assert "carol" in result.exceptions.undeclared_row_observers

    # Rows from undeclared observers are still admitted into drafts
    migrated_observers = {d.observer for d in result.drafts if d.kind == "fact"}
    assert "carol" in migrated_observers
    assert "bob" in migrated_observers


# ---------------------------------------------------------------------------
# 4. Grouping grammar
# ---------------------------------------------------------------------------


def test_grouping_grammar_batch_vs_flat(tmp_path: Path, kyle, alice) -> None:
    """A 2-row single-observer batch line -> ONE batch record draft.
    The same rows flat -> TWO fact record drafts.
    Outputs are not identical: grouping is semantic per §04.
    """
    batch_source = build_synthetic_jsonl(tmp_path / "batch.jsonl")
    flat_source = build_flat_equivalent_jsonl(tmp_path / "flat.jsonl")

    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public)])

    batch_result = transform(batch_source, vf, rule=identity(), signer=kyle.signer)
    flat_result = transform(flat_source, vf, rule=identity(), signer=kyle.signer)

    # Batch source has 1 batch draft
    batch_drafts = [d for d in batch_result.drafts if d.kind == "batch"]
    assert len(batch_drafts) == 1
    batch_draft = batch_drafts[0]
    assert batch_draft.observer == "alice"
    assert len(batch_draft.body["rows"]) == 2

    # Flat source has 0 batch drafts and 2 additional fact drafts
    flat_batch_drafts = [d for d in flat_result.drafts if d.kind == "batch"]
    assert len(flat_batch_drafts) == 0

    # Total record counts differ
    assert len(batch_result.drafts) + 1 == len(flat_result.drafts)
    assert batch_result.drafts != flat_result.drafts


# ---------------------------------------------------------------------------
# 5. M-4 Native tick conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["jsonl", "sqlite"])
def test_m4_native_tick_conversion_with_envelope_preservation(tmp_path: Path, kyle, alice, fmt: str) -> None:
    """Legacy ticks convert to native Arrival 'tick' records (not 'tick.<name>' facts).
    The tick's signed envelope and chain fields round-trip verbatim.
    """
    if fmt == "jsonl":
        source_path = build_synthetic_jsonl(tmp_path / "legacy.jsonl")
    else:
        source_path = build_synthetic_sqlite(tmp_path / "legacy.sqlite")

    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public)])
    result = transform(source_path, vf, rule=identity(), signer=kyle.signer)

    tick_drafts = [d for d in result.drafts if d.kind == "tick"]
    assert len(tick_drafts) == 2

    # Check no 'tick.<name>' fact drafts exist
    fact_kinds = [d.body.get("kind") for d in result.drafts if d.kind == "fact"]
    assert not any(k and k.startswith("tick.") for k in fact_kinds)

    # Check tick 1 (unsigned, no chain)
    t1 = next(d for d in tick_drafts if d.body["id"] == TICK_1["id"])
    assert t1.observer == "kyle"  # custody-producer label = destination genesis custodian
    assert t1.body["name"] == "heartbeat"
    assert t1.body["ts"] == 1006.0
    assert t1.body["since"] == 1000.0
    assert t1.body["origin"] == "system"
    assert t1.body["payload"] == '{"seq":1}'
    assert "signature" not in t1.body
    assert t1.signature is None

    # Check tick 2 (signed, with chain fields)
    t2 = next(d for d in tick_drafts if d.body["id"] == TICK_2["id"])
    assert t2.observer == "kyle"
    assert t2.body["name"] == "checkpoint"
    assert t2.body["ts"] == 1007.0
    assert t2.body["since"] == 1006.0
    assert t2.body["origin"] == "system"
    assert t2.body["payload"] == '{"seq":2}'
    assert t2.body["prev_hash"] == "prevhash123"
    assert t2.body["window_start"] == "01ARZ3NDEKTSV4RRFFQ69G5FT1"
    assert t2.body["fact_cursor"] == "01ARZ3NDEKTSV4RRFFQ69G5FB2"
    assert t2.body["window_hash"] == "winhash123"
    assert t2.body["signature"] == "sig-tick-2"
    assert t2.signature is None


# ---------------------------------------------------------------------------
# 6. Determinism & ULID Migration
# ---------------------------------------------------------------------------


def test_transform_determinism_and_ulid_migration(tmp_path: Path, kyle, alice) -> None:
    """Transform run twice over the same input produces byte-identical sequences.
    With ulid_migration, old->new id mapping is deterministic and reproducible without a stored map.
    """
    source_path = build_synthetic_jsonl(tmp_path / "legacy.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public)])

    res1 = transform(source_path, vf, rule=ulid_migration(), signer=kyle.signer)
    res2 = transform(source_path, vf, rule=ulid_migration(), signer=kyle.signer)

    # 1. Byte-identical drafts and metadata
    assert res1.genesis == res2.genesis
    assert res1.exceptions == res2.exceptions
    assert len(res1.drafts) == len(res2.drafts)
    assert res1.drafts == res2.drafts

    # 2. Check ULID migration rule migrated non-canonical IDs
    for draft in res1.drafts:
        if draft.kind == "fact":
            fact_id = draft.body["id"]
            assert len(fact_id) == 26
            assert fact_id.isupper()
        elif draft.kind == "batch":
            for row in draft.body["rows"]:
                fact_id = row["id"]
                assert len(fact_id) == 26
                assert fact_id.isupper()


# ---------------------------------------------------------------------------
# 7. Seam defense
# ---------------------------------------------------------------------------


def test_seam_defense_refuses_mixed_observer_batch(tmp_path: Path, kyle) -> None:
    """Handing the transformer a mixed-observer batch raises LegacySourceRefused (GF-3)."""
    source_path = build_mixed_observer_jsonl(tmp_path / "mixed.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public)])

    with pytest.raises(LegacySourceRefused) as exc_info:
        transform(source_path, vf, signer=kyle.signer)

    exc = exc_info.value
    assert isinstance(exc, MigrationRefused)
    assert len(exc.mixed_observer_lines) == 2


def test_seam_defense_refuses_absent_observer_batch(tmp_path: Path, kyle) -> None:
    """Handing the transformer an absent-observer batch raises LegacySourceRefused."""
    source_path = build_absent_observer_jsonl(tmp_path / "absent.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public)])

    with pytest.raises(LegacySourceRefused) as exc_info:
        transform(source_path, vf, signer=kyle.signer)

    exc = exc_info.value
    assert isinstance(exc, MigrationRefused)
    assert len(exc.absent_observer_lines) == 1


def test_seam_defense_refuses_codec_invalid_batch(tmp_path: Path, kyle) -> None:
    """Handing the transformer a codec-invalid batch raises LegacySourceRefused."""
    source_path = build_type_error_batch_jsonl(tmp_path / "type_err.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public)])

    with pytest.raises(LegacySourceRefused) as exc_info:
        transform(source_path, vf, signer=kyle.signer)

    exc = exc_info.value
    assert isinstance(exc, MigrationRefused)
    assert len(exc.codec_invalid_lines) == 1


def test_intra_batch_row_order_preserved(tmp_path: Path, kyle, alice) -> None:
    """F7a: A batch group's emitted draft preserves exact intra-batch source row order."""
    source_path = build_synthetic_jsonl(tmp_path / "batch.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public)])
    result = transform(source_path, vf, rule=identity(), signer=kyle.signer)

    batch_draft = next(d for d in result.drafts if d.kind == "batch")
    assert [r["id"] for r in batch_draft.body["rows"]] == [BATCH_ROW_1["id"], BATCH_ROW_2["id"]]


def test_partial_batch_drop_refused(tmp_path: Path, kyle, alice) -> None:
    """F3: A rule that drops some rows of a batch group raises BatchRegroupRefused."""
    source_path = build_synthetic_jsonl(tmp_path / "batch.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public)])

    def drop_one(row: FactRow) -> FactRow | None:
        if row.id == BATCH_ROW_1["id"]:
            return None
        return row

    partial_rule = Transform(rule="drop-one", map_fact=drop_one)
    with pytest.raises(BatchRegroupRefused) as exc_info:
        transform(source_path, vf, rule=partial_rule, signer=kyle.signer)

    assert "dropped 1 of 2 rows in batch" in str(exc_info.value)


def test_full_unit_drop_recorded_in_exception_report(tmp_path: Path, kyle, alice) -> None:
    """F3: A rule dropping an entire unit records it in TransformExceptions.dropped_units."""
    source_path = build_synthetic_jsonl(tmp_path / "batch.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("alice", alice.public)])

    def drop_selected(row: FactRow) -> FactRow | None:
        if row.id in (FACT_UUID4_SIGNED["id"], BATCH_ROW_1["id"], BATCH_ROW_2["id"]):
            return None
        return row

    drop_rule = Transform(rule="drop-selected", map_fact=drop_selected)
    result = transform(source_path, vf, rule=drop_rule, signer=kyle.signer)

    dropped = result.exceptions.dropped_units
    assert len(dropped) == 2
    assert dropped[0] == DroppedUnit(coordinate=1, kind="fact", rule="drop-selected")
    assert dropped[1] == DroppedUnit(coordinate=6, kind="batch", rule="drop-selected")

    emitted_ids = {
        d.body.get("id")
        for d in result.drafts
        if d.kind == "fact"
    }
    assert FACT_UUID4_SIGNED["id"] not in emitted_ids
    assert not any(d.kind == "batch" for d in result.drafts)


def test_transform_requires_signer(tmp_path: Path, kyle) -> None:
    """F4: transform() requires signer parameter; omitting it raises TypeError."""
    source_path = build_synthetic_jsonl(tmp_path / "test.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public)])

    with pytest.raises(TypeError):
        transform(source_path, vf)  # type: ignore[call-arg]


def test_malformed_declared_key_refused(tmp_path: Path, kyle) -> None:
    """F5: A malformed declared key shape raises DeclarationKeyRefused at transform setup."""
    source_path = build_synthetic_jsonl(tmp_path / "test.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public), ("bob", "aW52YWxpZA==")])

    with pytest.raises(DeclarationKeyRefused) as exc_info:
        transform(source_path, vf, signer=kyle.signer)

    assert "declaration carries a key of the wrong shape for 'bob'" in str(exc_info.value)


def test_missing_custodian_key_refused(tmp_path: Path, kyle) -> None:
    """F6e: Missing custodian key in .vertex raises MissingCustodianKeyRefused."""
    source_path = build_synthetic_jsonl(tmp_path / "test.jsonl")
    vf = _make_vertex_file("kyle", [("kyle", None)])

    with pytest.raises(MissingCustodianKeyRefused):
        transform(source_path, vf, signer=kyle.signer)


def test_sqlite_seam_defense_refuses_empty_observer(tmp_path: Path, kyle) -> None:
    """F1: Handing the transformer a SQLite store with observer='' raises LegacySourceRefused."""
    source_path = build_empty_observer_sqlite(tmp_path / "empty_obs.sqlite")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public)])

    with pytest.raises(LegacySourceRefused) as exc_info:
        transform(source_path, vf, signer=kyle.signer)

    exc = exc_info.value
    assert isinstance(exc, MigrationRefused)
    assert len(exc.absent_observer_lines) == 2


def test_sqlite_seam_defense_refuses_codec_invalid_ts(tmp_path: Path, kyle) -> None:
    """F1: Handing the transformer a SQLite store with ts as TEXT raises LegacySourceRefused."""
    source_path = build_codec_invalid_sqlite(tmp_path / "bad_ts.sqlite")
    vf = _make_vertex_file("kyle", [("kyle", kyle.public)])

    with pytest.raises(LegacySourceRefused) as exc_info:
        transform(source_path, vf, signer=kyle.signer)

    exc = exc_info.value
    assert isinstance(exc, MigrationRefused)
    assert len(exc.codec_invalid_lines) == 1
    assert "fact field 'ts' must be a finite number" in exc.codec_invalid_lines[0][1]

