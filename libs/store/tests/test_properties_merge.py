"""Property-based tests for store merge algebra, transport roundtrip, and witness invariance.

Validates:
- Merge commutativity: merge(A, B) == merge(B, A) in fact set and replay sequence.
- Merge associativity: merge(merge(A, B), C) == merge(A, merge(B, C)).
- Merge idempotence: merge(A, A) and repeated merge operations are no-ops.
- Id-collision behavior probe: primary-key deduplication (target-wins).
- Transport roundtrip: slice -> push -> receive preserves fact set and replay sequence.
- JSONL <-> SQLite consistency: export_jsonl -> rebuild_jsonl preserves replay sequences.
- Witness prefix invariance: merging backdated facts preserves earlier witness fold.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from atoms import Fact
from engine.sqlite_store import SqliteStore
from engine.store_reader import StoreReader
from engine.vertex_reader import vertex_fold
from engine.witness import resolve_witness_position
from hypothesis import given, settings
from hypothesis import strategies as st
from lang import parse_vertex_file
from lang.document import genesis_payload

from store import (
    LocalTransport,
    export_jsonl,
    merge_store,
    push_store,
    rebuild_jsonl,
)
from tests.strategies import (
    fact_and_id_lists,
    payloads,
    timestamps,
)

# =============================================================================
# Helper Utilities & Strategies
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


def _populate_store(store_path: Path, fact_pairs: list[tuple[str, Fact]]) -> None:
    """Populate a store with fact pairs."""
    _init_store(store_path)
    s = SqliteStore(
        path=store_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact in fact_pairs:
        s.append(fact, id_override=fid)
    s.close()


def _read_all_facts(store_path: Path) -> list[dict[str, Any]]:
    """Read all stored facts in deterministic (ts, id) replay order."""
    with StoreReader(store_path) as reader:
        stats = reader.fact_kind_stats()
        kinds = sorted(stats.keys())
        all_facts: list[dict[str, Any]] = []
        for kind in kinds:
            all_facts.extend(reader.facts_by_kind(kind))
        return sorted(all_facts, key=lambda f: (f["ts"], f["id"]))


def _extract_fold_items(res: Any) -> dict[str, list[dict[str, Any]]]:
    """Extract section items from either a FoldState or a WitnessFold."""
    fold_state = res.fold if hasattr(res, "fold") else res
    return {
        sec.kind: [item.payload for item in sec.items]
        for sec in fold_state.sections
    }


def two_stores_strategy(
    min_size: int = 1, max_size: int = 12
) -> st.SearchStrategy[tuple[list[tuple[str, Fact]], list[tuple[str, Fact]]]]:
    """Generate two stores from a shared universe of immutable facts."""
    return fact_and_id_lists(min_size=min_size, max_size=max_size).flatmap(
        lambda pool: st.tuples(
            st.lists(
                st.sampled_from(pool), min_size=1, max_size=len(pool), unique_by=lambda x: x[0]
            ),
            st.lists(
                st.sampled_from(pool), min_size=1, max_size=len(pool), unique_by=lambda x: x[0]
            ),
        )
    )


ThreeStores = tuple[
    list[tuple[str, Fact]],
    list[tuple[str, Fact]],
    list[tuple[str, Fact]],
]


def three_stores_strategy(
    min_size: int = 1, max_size: int = 12
) -> st.SearchStrategy[ThreeStores]:
    """Generate three stores from a shared universe of immutable facts."""
    return fact_and_id_lists(min_size=min_size, max_size=max_size).flatmap(
        lambda pool: st.tuples(
            st.lists(
                st.sampled_from(pool), min_size=1, max_size=len(pool), unique_by=lambda x: x[0]
            ),
            st.lists(
                st.sampled_from(pool), min_size=1, max_size=len(pool), unique_by=lambda x: x[0]
            ),
            st.lists(
                st.sampled_from(pool), min_size=1, max_size=len(pool), unique_by=lambda x: x[0]
            ),
        )
    )


# =============================================================================
# 1. Merge Commutativity
# =============================================================================


class TestMergeCommutativityProperties:
    """Property tests asserting merge commutativity."""

    @settings(deadline=None, max_examples=50)
    @given(stores=two_stores_strategy(min_size=1, max_size=10))
    def test_merge_commutativity(
        self,
        stores: tuple[list[tuple[str, Fact]], list[tuple[str, Fact]]],
    ) -> None:
        """merge(A, B) and merge(B, A) yield identical fact sets and replay sequences."""
        facts_a, facts_b = stores
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            sa = tmp_path / "a.db"
            sb = tmp_path / "b.db"
            _populate_store(sa, facts_a)
            _populate_store(sb, facts_b)

            # Target 1: copy A, merge B into it
            t1 = tmp_path / "t1.db"
            shutil.copy2(str(sa), str(t1))
            merge_store(t1, sb)

            # Target 2: copy B, merge A into it
            t2 = tmp_path / "t2.db"
            shutil.copy2(str(sb), str(t2))
            merge_store(t2, sa)

            facts_t1 = _read_all_facts(t1)
            facts_t2 = _read_all_facts(t2)

            # Fact sets are identical
            set_t1 = {(f["id"], f["kind"], f["ts"], str(f["payload"])) for f in facts_t1}
            set_t2 = {(f["id"], f["kind"], f["ts"], str(f["payload"])) for f in facts_t2}
            assert set_t1 == set_t2

            # Replay sequences are identical
            seq_t1 = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in facts_t1]
            seq_t2 = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in facts_t2]
            assert seq_t1 == seq_t2


# =============================================================================
# 2. Merge Associativity
# =============================================================================


class TestMergeAssociativityProperties:
    """Property tests asserting merge associativity."""

    @settings(deadline=None, max_examples=50)
    @given(stores=three_stores_strategy(min_size=1, max_size=8))
    def test_merge_associativity(
        self,
        stores: tuple[list[tuple[str, Fact]], list[tuple[str, Fact]], list[tuple[str, Fact]]],
    ) -> None:
        """Merging ((A + B) + C) yields the same fact set and replay order as (A + (B + C))."""
        facts_a, facts_b, facts_c = stores
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            sa = tmp_path / "a.db"
            sb = tmp_path / "b.db"
            sc = tmp_path / "c.db"
            _populate_store(sa, facts_a)
            _populate_store(sb, facts_b)
            _populate_store(sc, facts_c)

            # Left association: (A merge B) merge C
            left = tmp_path / "left.db"
            shutil.copy2(str(sa), str(left))
            merge_store(left, sb)
            merge_store(left, sc)

            # Right association: A merge (B merge C)
            bc = tmp_path / "bc.db"
            shutil.copy2(str(sb), str(bc))
            merge_store(bc, sc)

            right = tmp_path / "right.db"
            shutil.copy2(str(sa), str(right))
            merge_store(right, bc)

            facts_left = _read_all_facts(left)
            facts_right = _read_all_facts(right)

            seq_left = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in facts_left]
            seq_right = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in facts_right]
            assert seq_left == seq_right


# =============================================================================
# 3. Merge Idempotence
# =============================================================================


class TestMergeIdempotenceProperties:
    """Property tests asserting merge idempotence."""

    @settings(deadline=None, max_examples=50)
    @given(
        facts_a=fact_and_id_lists(min_size=1, max_size=10),
        facts_b=fact_and_id_lists(min_size=1, max_size=10),
    )
    def test_merge_idempotence(
        self,
        facts_a: list[tuple[str, Fact]],
        facts_b: list[tuple[str, Fact]],
    ) -> None:
        """Self-merges and repeated merge operations leave store contents unchanged."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            sa = tmp_path / "a.db"
            sb = tmp_path / "b.db"
            _populate_store(sa, facts_a)
            _populate_store(sb, facts_b)

            target = tmp_path / "target.db"
            shutil.copy2(str(sa), str(target))

            # 1. Self-merge is a no-op
            res_self = merge_store(target, target)
            assert res_self.facts_added == 0
            assert _read_all_facts(target) == _read_all_facts(sa)

            # 2. First merge of B adds facts
            merge_store(target, sb)
            state_after_first = _read_all_facts(target)

            # 3. Second merge of B is an idempotent no-op
            res_second = merge_store(target, sb)
            state_after_second = _read_all_facts(target)

            assert res_second.facts_added == 0
            assert res_second.facts_skipped == len(facts_b)
            assert state_after_second == state_after_first


# =============================================================================
# 4. ID-Collision Behavior Probe
# =============================================================================


class TestMergeIdCollisionProbe:
    """Probe tests asserting the engine's primary-key collision resolution policy."""

    @settings(deadline=None, max_examples=50)
    @given(
        fid=st.sampled_from(["01TESTULID0000000000000001", "01ARZ3NDEKTSV4RRFFQ69G5FA0"]),
        ts_a=timestamps(),
        ts_b=timestamps(),
        payload_a=payloads(),
        payload_b=payloads(),
    )
    def test_merge_id_collision_preserves_target_and_deduplicates(
        self,
        fid: str,
        ts_a: float,
        ts_b: float,
        payload_a: dict[str, Any],
        payload_b: dict[str, Any],
    ) -> None:
        """On ID collision, merge preserves target's row and ignores incoming duplicate."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            sa = tmp_path / "a.db"
            sb = tmp_path / "b.db"

            fact_a = Fact(kind="decision", ts=ts_a, payload=payload_a, observer="alice")
            fact_b = Fact(kind="decision", ts=ts_b, payload=payload_b, observer="bob")

            _populate_store(sa, [(fid, fact_a)])
            _populate_store(sb, [(fid, fact_b)])

            # Merge B into A
            res = merge_store(sa, sb)

            # Target A preserved, B skipped
            assert res.facts_added == 0
            assert res.facts_skipped == 1

            with StoreReader(sa) as reader:
                rows = reader.facts_by_kind("decision")
                assert len(rows) == 1
                assert rows[0]["id"] == fid
                assert rows[0]["observer"] == "alice"
                assert rows[0]["ts"] == ts_a


# =============================================================================
# 5. Transport / Serialization Roundtrip
# =============================================================================


class TestTransportRoundtripProperties:
    """Property tests asserting transport slice and push/receive roundtrip fidelity."""

    @settings(deadline=None, max_examples=50)
    @given(facts=fact_and_id_lists(min_size=1, max_size=12))
    def test_transport_slice_push_roundtrip(
        self,
        facts: list[tuple[str, Fact]],
    ) -> None:
        """Transporting a slice via push/receive preserves fact set and replay sequence."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            source = tmp_path / "source.db"
            remote = tmp_path / "remote.db"

            _populate_store(source, facts)

            # Push all facts through LocalTransport
            transport = LocalTransport()
            push_res = push_store(source, transport, remote_path=remote)

            assert push_res.sliced_facts == len(facts)
            assert push_res.receive.status == "created"
            assert push_res.receive.facts == len(facts)

            source_facts = _read_all_facts(source)
            remote_facts = _read_all_facts(remote)

            seq_source = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in source_facts]
            seq_remote = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in remote_facts]
            assert seq_remote == seq_source


# =============================================================================
# 6. JSONL <-> SQLite Consistency
# =============================================================================


class TestJsonlSqliteConsistencyProperties:
    """Property tests asserting JSONL export and SQLite rebuild consistency."""

    @settings(deadline=None, max_examples=50)
    @given(facts=fact_and_id_lists(min_size=1, max_size=12))
    def test_jsonl_sqlite_roundtrip_replay_consistency(
        self,
        facts: list[tuple[str, Fact]],
    ) -> None:
        """Exporting a store to JSONL and rebuilding it preserves the exact replay sequence."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            source = tmp_path / "source.db"
            jsonl_path = tmp_path / "log.jsonl"
            rebuilt = tmp_path / "rebuilt.db"

            _populate_store(source, facts)

            export_res = export_jsonl(source, jsonl_path)
            assert export_res.facts == len(facts)

            rebuild_res = rebuild_jsonl(jsonl_path, rebuilt)
            assert rebuild_res.facts == len(facts)

            source_facts = _read_all_facts(source)
            rebuilt_facts = _read_all_facts(rebuilt)

            seq_source = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in source_facts]
            seq_rebuilt = [(f["ts"], f["id"], f["kind"], f["payload"]) for f in rebuilt_facts]
            assert seq_rebuilt == seq_source


# =============================================================================
# 7. Witness Prefix Invariance Under Real Merge
# =============================================================================


class TestWitnessRealMergeInvarianceProperties:
    """Property tests asserting witness prefix invariance under real libs/store merge."""

    @settings(deadline=None, max_examples=50)
    @given(
        store_a_facts=fact_and_id_lists(min_size=1, max_size=10),
        store_b_facts=fact_and_id_lists(min_size=1, max_size=5),
        backdated_delta=st.floats(min_value=1.0, max_value=1e6, allow_nan=False),
        merge_payload=payloads(),
    )
    def test_witness_prefix_invariance_under_real_merge(
        self,
        store_a_facts: list[tuple[str, Fact]],
        store_b_facts: list[tuple[str, Fact]],
        backdated_delta: float,
        merge_payload: dict[str, Any],
    ) -> None:
        """Witness position P on store A is invariant under merged backdated facts (SPEC §9.3)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 1. Setup Store A (adopted with vertex)
            dir_a = tmp_path / "vertex_a"
            dir_a.mkdir()
            va, sa = _scaffold_vertex(dir_a)
            _absorb_genesis(va, sa)

            s_a = SqliteStore(
                path=sa,
                serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
                deserialize=Fact.from_dict,
            )
            for fid, fact in store_a_facts:
                s_a.append(fact, id_override=fid)
            s_a.close()

            # Record witness position P on Store A
            pos_a = resolve_witness_position(sa, "head")
            fold_at_p_before = vertex_fold(va, at=pos_a)
            items_before = _extract_fold_items(fold_at_p_before)

            # 2. Setup Store B with a backdated fact relative to Store A
            min_ts_a = min(f.ts for _, f in store_a_facts)
            backdated_ts = min_ts_a - backdated_delta
            backdated_fact = Fact(
                kind="decision",
                ts=backdated_ts,
                payload={**merge_payload, "topic": "real_merge_backdate"},
                observer="kyle",
            )

            sb = tmp_path / "b.db"
            merged_b_facts = list(store_b_facts) + [("01REALMERGEBACKDATE00000", backdated_fact)]
            _populate_store(sb, merged_b_facts)

            # 3. Run REAL libs/store merge_store into Store A
            merge_res = merge_store(sa, sb)
            assert merge_res.facts_added >= 1

            # 4. Re-evaluate Store A at witness position P
            fold_at_p_after = vertex_fold(va, at=pos_a)
            items_after = _extract_fold_items(fold_at_p_after)

            # Invariant: fold at witness position P is completely unchanged
            assert items_after == items_before

            # Verify that head fold includes the backdated merged fact
            head_a = resolve_witness_position(sa, "head")
            fold_head = vertex_fold(va, at=head_a)
            head_items = _extract_fold_items(fold_head)
            head_decision_topics = [
                item.get("topic")
                for item in head_items.get("decision", [])
            ]
            assert "real_merge_backdate" in head_decision_topics
