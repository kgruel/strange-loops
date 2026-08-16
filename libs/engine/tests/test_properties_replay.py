"""Property-based tests for engine replay order, fold determinism, and witness invariance.

Validates invariants from SPEC §9.3:
- Replay follows receipt order (append order) and never re-sorts by (ts, id).
- Fold determinism given a fixed append sequence.
- Witness prefix invariance under direct append of backdated facts.
- Witness prefix invariance under merge-ingested backdated facts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from atoms import Fact
from hypothesis import given, settings
from hypothesis import strategies as st
from lang import parse_vertex_file
from lang.document import genesis_payload

from engine.sqlite_store import SqliteStore
from engine.store_reader import StoreReader
from engine.vertex_reader import vertex_fold
from engine.witness import resolve_witness_position
from tests.strategies import (
    fact_and_id_lists,
    payloads,
    timestamps,
)

# =============================================================================
# Vertex Scaffold & Helpers
# =============================================================================

_VERTEX_KDL = """name "test_vertex"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
  thread {{ fold {{ items "by" "name" }} }}
  system {{ fold {{ items "collect" 50 }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
"""


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


def _scaffold_vertex(dir_path: Path) -> tuple[Path, Path]:
    """Create a .vertex file and return (vertex_path, store_db_path)."""
    store_path = dir_path / "store.db"
    vpath = dir_path / "test.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store_path))
    return vpath, store_path


def _init_store(store_path: Path) -> None:
    """Initialize a fresh empty store."""
    s = SqliteStore(
        path=store_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    s.close()


def _absorb_genesis(vpath: Path, store_path: Path) -> str:
    """Run genesis absorb ceremony to adopt the store with lineage."""
    ast = parse_vertex_file(vpath)
    docs = genesis_payload(ast)["documents"]
    s = SqliteStore(
        path=store_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    res = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return str(res["lineage"])


def _ingest_facts(store_path: Path, fact_pairs: list[tuple[str, Fact]]) -> None:
    """Ingest a list of (fact_id, Fact) pairs into a store via SqliteStore.append."""
    s = SqliteStore(
        path=store_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact in fact_pairs:
        s.append(fact, id_override=fid)
    s.close()


def _merge_facts_into_store(target_store: Path, fact_pairs: list[tuple[str, Fact]]) -> None:
    """Merge facts into target store using cross-store merge semantics (INSERT OR IGNORE)."""
    conn = sqlite3.connect(str(target_store))
    for fid, fact in fact_pairs:
        payload_data = fact.payload if isinstance(fact.payload, dict) else fact.to_dict()["payload"]
        conn.execute(
            "INSERT OR IGNORE INTO facts (id, kind, ts, observer, origin, payload, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (fid, fact.kind, fact.ts, fact.observer, fact.origin, json.dumps(payload_data)),
        )
    conn.commit()
    conn.close()


def _extract_fold_items(res: Any) -> dict[str, list[dict[str, Any]]]:
    """Extract section items from either a FoldState or a WitnessFold."""
    fold_state = res.fold if hasattr(res, "fold") else res
    return {
        sec.kind: [item.payload for item in sec.items]
        for sec in fold_state.sections
    }


# =============================================================================
# 1. Replay Receipt-Order Determinism
# =============================================================================


class TestReplayReceiptOrderProperties:
    """Property tests asserting receipt-order replay determinism per SPEC §9.3.

    Replay order IS append order (``facts.rowid`` ASC). Permutation
    invariance is definitionally false: ingest order is fold order. What
    survives is determinism GIVEN an append sequence — the same sequence
    always replays to the same ordered list — plus the guarantee that
    replay is a faithful reading of the append sequence, never a re-sort
    by ``ts`` or ``id``.
    """

    @settings(max_examples=200, deadline=None)
    @given(fact_pairs=fact_and_id_lists(min_size=2, max_size=15))
    def test_replay_deterministic_given_append_sequence(
        self, fact_pairs: list[tuple[str, Fact]]
    ) -> None:
        """The same append sequence always replays to the same ordered list."""
        n_trials = 5
        replayed_results: list[list[tuple[float, str, str, dict]]] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for i in range(n_trials):
                db_path = tmp_path / f"store_{i}.db"
                _init_store(db_path)
                _ingest_facts(db_path, fact_pairs)

                with StoreReader(db_path) as reader:
                    kinds = sorted({f.kind for _, f in fact_pairs})
                    store_replay: list[tuple[float, str, str, dict]] = []
                    for kind in kinds:
                        for row in reader.facts_by_kind(kind):
                            store_replay.append(
                                (row["ts"], row["id"], row["kind"], row["payload"])
                            )
                    replayed_results.append(store_replay)

        first_replay = replayed_results[0]
        for idx, other_replay in enumerate(replayed_results[1:], start=1):
            assert other_replay == first_replay, f"Trial {idx} replayed in different order"

    @settings(max_examples=200, deadline=None)
    @given(fact_pairs=fact_and_id_lists(min_size=2, max_size=15))
    def test_replay_follows_append_sequence_per_kind(
        self, fact_pairs: list[tuple[str, Fact]]
    ) -> None:
        """Replay returns each kind's facts in the order they were appended."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "store.db"
            _init_store(db_path)
            _ingest_facts(db_path, fact_pairs)

            with StoreReader(db_path) as reader:
                for kind in sorted({f.kind for _, f in fact_pairs}):
                    appended = [fid for fid, f in fact_pairs if f.kind == kind]
                    replayed = [row["id"] for row in reader.facts_by_kind(kind)]
                    assert replayed == appended

    @settings(max_examples=200, deadline=None)
    @given(
        ts=timestamps(),
        id_a=st.sampled_from(["01TESTULID0000000000000001", "01ARZ3NDEKTSV4RRFFQ69G5FA0"]),
        id_b=st.sampled_from(["01TESTULID0000000000000002", "01ARZ3NDEKTSV4RRFFQ69G5FA1"]),
    )
    def test_replay_does_not_tie_break_by_fact_id(self, ts: float, id_a: str, id_b: str) -> None:
        """Timestamp ties replay in append order — the ULID never re-sorts them."""
        if id_a == id_b:
            id_b = id_a + "Z"

        min_id, max_id = (id_a, id_b) if id_a < id_b else (id_b, id_a)

        fact_min = Fact(kind="decision", ts=ts, payload={"topic": "min"}, observer="kyle")
        fact_max = Fact(kind="decision", ts=ts, payload={"topic": "max"}, observer="kyle")

        # Append the HIGHER id first: under receipt order it stays first.
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "store.db"
            _init_store(db_path)
            _ingest_facts(db_path, [(max_id, fact_max), (min_id, fact_min)])

            with StoreReader(db_path) as reader:
                rows = reader.facts_by_kind("decision")
                assert len(rows) == 2
                assert rows[0]["id"] == max_id
                assert rows[1]["id"] == min_id


# =============================================================================
# 2. Fold Determinism
# =============================================================================


class TestFoldDeterminismProperties:
    """Property tests asserting fold determinism per SPEC §9.3."""

    @settings(max_examples=200, deadline=None)
    @given(fact_pairs=fact_and_id_lists(min_size=2, max_size=15))
    def test_fold_state_deterministic_given_append_sequence(
        self, fact_pairs: list[tuple[str, Fact]]
    ) -> None:
        """The same append sequence always folds to the same state (SPEC §9.3).

        Under receipt order the ingest permutation IS the fold order, so
        cross-permutation invariance no longer holds. Determinism given a
        fixed append sequence is what replaces it.
        """
        n_trials = 5
        fold_states: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for i in range(n_trials):
                sub_dir = tmp_path / f"trial_{i}"
                sub_dir.mkdir()
                vpath, store_path = _scaffold_vertex(sub_dir)
                _init_store(store_path)
                _ingest_facts(store_path, fact_pairs)

                res = vertex_fold(vpath)
                fold_states.append(_extract_fold_items(res))

        first_state = fold_states[0]
        for idx, other_state in enumerate(fold_states[1:], start=1):
            assert other_state == first_state, f"Trial {idx} produced different fold state"


# =============================================================================
# 3. Witness Prefix Invariance Under Direct Append
# =============================================================================


class TestWitnessAppendInvarianceProperties:
    """Property tests asserting witness prefix invariance under appends per SPEC §9.3."""

    @settings(max_examples=200, deadline=None)
    @given(
        initial_facts=fact_and_id_lists(min_size=1, max_size=10),
        backdated_delta=st.floats(min_value=1.0, max_value=1e6, allow_nan=False),
        future_delta=st.floats(min_value=1.0, max_value=1e6, allow_nan=False),
        extra_payload=payloads(),
    )
    def test_witness_prefix_invariant_under_direct_append(
        self,
        initial_facts: list[tuple[str, Fact]],
        backdated_delta: float,
        future_delta: float,
        extra_payload: dict[str, Any],
    ) -> None:
        """A witness position P captures an immutable prefix unaffected by appends (SPEC §9.3)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sub_dir = Path(tmp_dir)
            vpath, store_path = _scaffold_vertex(sub_dir)
            _init_store(store_path)
            _ingest_facts(store_path, initial_facts)

            # Record witness position P at current store head
            pos_p = resolve_witness_position(store_path, "head")

            # Record fold state at position P
            fold_at_p_before = vertex_fold(vpath, at=pos_p)
            items_before = _extract_fold_items(fold_at_p_before)

            # Calculate backdated and future timestamps
            min_ts = min(f.ts for _, f in initial_facts)
            max_ts = max(f.ts for _, f in initial_facts)
            backdated_ts = min_ts - backdated_delta
            future_ts = max_ts + future_delta

            backdated_fact = Fact(
                kind="decision",
                ts=backdated_ts,
                payload={**extra_payload, "topic": "backdated_topic"},
                observer="kyle",
            )
            future_fact = Fact(
                kind="thread",
                ts=future_ts,
                payload={"name": "future_thread"},
                observer="kyle",
            )

            # Append new facts (including backdated) to the store
            _ingest_facts(
                store_path,
                [
                    ("01BACKDATEDFACT00000000000", backdated_fact),
                    ("01FUTUREFACT0000000000000", future_fact),
                ],
            )

            # Re-read at position P
            fold_at_p_after = vertex_fold(vpath, at=pos_p)
            items_after = _extract_fold_items(fold_at_p_after)

            # Invariant: fold state anchored at P is completely unchanged
            assert items_after == items_before

            # Verify that head did advance and reflects the new facts
            head_pos = resolve_witness_position(store_path, "head")
            assert head_pos.rowid > pos_p.rowid
            fold_head = vertex_fold(vpath, at=head_pos)
            items_head = _extract_fold_items(fold_head)
            decision_topics = [p.get("topic") for p in items_head.get("decision", [])]
            assert "backdated_topic" in decision_topics


# =============================================================================
# 4. Witness Prefix Invariance Under Merge-Ingested Backdated Facts
# =============================================================================


class TestWitnessMergeInvarianceProperties:
    """Property tests asserting witness prefix invariance under merge-ingestion per SPEC §9.3."""

    @settings(max_examples=200, deadline=None)
    @given(
        store_a_facts=fact_and_id_lists(min_size=1, max_size=10),
        store_b_facts=fact_and_id_lists(min_size=1, max_size=5),
        backdated_delta=st.floats(min_value=1.0, max_value=1e6, allow_nan=False),
        merge_payload=payloads(),
    )
    def test_witness_prefix_invariant_under_merge_ingested_backdated_facts(
        self,
        store_a_facts: list[tuple[str, Fact]],
        store_b_facts: list[tuple[str, Fact]],
        backdated_delta: float,
        merge_payload: dict[str, Any],
    ) -> None:
        """A witness position P remains invariant when backdated facts are merged (SPEC §9.3)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 1. Setup Store A (adopted with vertex)
            dir_a = tmp_path / "vertex_a"
            dir_a.mkdir()
            va, sa = _scaffold_vertex(dir_a)
            _init_store(sa)
            _absorb_genesis(va, sa)
            _ingest_facts(sa, store_a_facts)

            # Record witness position P on Store A
            pos_a_initial = resolve_witness_position(sa, "head")
            fold_a_initial = vertex_fold(va, at=pos_a_initial)
            items_a_initial = _extract_fold_items(fold_a_initial)

            # 2. Setup Store B with a backdated fact relative to Store A
            min_ts_a = min(f.ts for _, f in store_a_facts)
            backdated_ts = min_ts_a - backdated_delta
            backdated_fact = Fact(
                kind="decision",
                ts=backdated_ts,
                payload={**merge_payload, "topic": "merged_backdate"},
                observer="kyle",
            )

            # 3. Simulate merge: merge Store B's facts into Store A
            merged_facts = list(store_b_facts) + [("01MERGEDBACKDATE000000000", backdated_fact)]
            _merge_facts_into_store(sa, merged_facts)

            # 4. Re-evaluate Store A at original witness position P
            fold_a_after = vertex_fold(va, at=pos_a_initial)
            items_a_after = _extract_fold_items(fold_a_after)

            # Invariant: fold at witness position P is unaffected by merged backdated facts
            assert items_a_after == items_a_initial

            # Verify that head fold on Store A incorporates the merged backdated fact
            head_a = resolve_witness_position(sa, "head")
            fold_a_head = vertex_fold(va, at=head_a)
            head_items = _extract_fold_items(fold_a_head)
            head_decision_topics = [
                item.get("topic")
                for item in head_items.get("decision", [])
            ]
            assert "merged_backdate" in head_decision_topics
