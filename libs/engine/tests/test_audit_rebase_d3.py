"""Slice D / WP-4 — audit re-base (D3) gate verification tests.

`docs/scratch/arrival-sliceD/design-proposal.md` §D3 re-bases the canonical agreement
audit from byte offsets onto arrival coordinates `(arrival_ordinal, arrival_seq)`
and multiset digest comparison for derived `.jsonl`.

Gates covered:
- G-D3-1: L1 detects:
          - index behind arrival (behind_by=K, at_ordinal=X)
          - out-of-band insert (arrival_ordinal IS NULL backstop)
          - edit to the last consumed row (at_ordinal=X)
          - rewound marker (offending_ord > consumed_ord)
          each with the expected coordinate in detail.
- G-D3-2: Bounded work, deterministically instrumented (NO timing):
          Test-scoped counter on record-verification seam asserts EXACT bounds:
          - healthy N-record: anchor (1) + 0 suffix = 1 record verified
          - K behind: 1 anchor + K suffix = 1 + K records verified
          - --deep: N records
          - neither ArrivalLog.read nor ArrivalLog.walk called in L1.
- G-D3-3: Torn arrival tail: L1 reports index_behind=True ("behind"), never "tampered".
- G-D3-4: Derived .jsonl reordered => multiset audit agrees; DUPLICATED line detected;
          removed line detected.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from atoms import Fact
from engine.arrival import ArrivalLog, ResumeMark
from engine.arrival_projection import audit_derived_log, derived_log_path_for, rederive_projections
from engine.arrival_store import (
    ARRIVAL_LINEAGE_KEY,
    ARRIVAL_OFFSET_KEY,
    ARRIVAL_ORDINAL_KEY,
    ArrivalStore,
)
from engine.canonical_audit import (
    AgreementReport,
    Check,
    audit_agreement,
    audit_deep,
)
from engine.jsonl_codec import object_of_fact_row
from engine.sqlite_store import gen_id

_SAMPLE_PUBKEY = base64.b64encode(b"\x00" * 32).decode()
_SAMPLE_SIG = base64.b64encode(b"\x01" * 64).decode()


def _fact_signer(obs: str, dig: bytes) -> str:
    return _SAMPLE_SIG


def _tick_signer(obs: str, dig: bytes) -> str:
    return _SAMPLE_SIG


def _create_arrival_store(tmp_path: Path, n_facts: int = 5) -> tuple[Path, Path, ArrivalStore]:
    log_path = tmp_path / "store.arrival"
    db_path = tmp_path / "store.db"

    ArrivalLog.mint(
        log_path,
        observer="kyle",
        signer=lambda obs, dig: _SAMPLE_SIG,
        key=_SAMPLE_PUBKEY,
    )
    store = ArrivalStore(
        path=db_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        tick_signer=_tick_signer,
        fact_signer=_fact_signer,
    )

    for i in range(n_facts):
        store.append(Fact.of("note", "kyle", n=i, text=f"fact_{i}"))

    return log_path, db_path, store


# ===========================================================================
# G-D3-1: L1 error coordinate detection
# ===========================================================================


class TestGateD3_1_DetectionCoordinates:
    """G-D3-1: L1 detects:

    - index behind arrival (behind_by=K, at_ordinal=X)
    - out-of-band insert (arrival_ordinal IS NULL backstop)
    - edit to the last consumed row (at_ordinal=X)
    - rewound marker (offending_ord > consumed_ord)
    each with the expected coordinate in the message/detail.
    """

    def test_l1_detects_index_behind_arrival_with_coordinates(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=3)
        # Store has genesis (ord 0) + 3 facts (ord 1, 2, 3). Mark is at ord 3.
        # Now append 2 more records directly to the arrival log, bypassing the index.
        log = ArrivalLog(log_path)
        log.append(
            "fact",
            object_of_fact_row((gen_id(), "note", 1700000000.0, "kyle", "", json.dumps({"n": 4}))),
            observer="kyle",
        )
        log.append(
            "fact",
            object_of_fact_row((gen_id(), "note", 1700000001.0, "kyle", "", json.dumps({"n": 5}))),
            observer="kyle",
        )

        report = audit_agreement(log_path)
        assert not report.ok
        assert report.index_behind is True

        consumed = next(c for c in report.checks if c.name == "consumed")
        assert not consumed.ok
        assert consumed.behind_by == 2
        assert consumed.at_ordinal == 3
        assert "behind arrival by 2 record(s)" in consumed.detail
        assert "consumed through ordinal 3" in consumed.detail

    def test_l1_detects_out_of_band_insert_null_coordinate(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=3)
        # Recreate facts table with nullable arrival_ordinal to simulate a corrupt/legacy index
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE facts_backup AS SELECT * FROM facts")
            conn.execute("DROP TABLE facts")
            conn.execute(
                "CREATE TABLE facts ("
                "id TEXT PRIMARY KEY, kind TEXT, ts REAL, observer TEXT, origin TEXT, "
                "payload TEXT, signature TEXT, arrival_ordinal INTEGER, arrival_seq INTEGER"
                ")"
            )
            conn.execute(
                "INSERT INTO facts SELECT id, kind, ts, observer, origin, payload, signature, "
                "arrival_ordinal, arrival_seq FROM facts_backup"
            )
            conn.execute("DROP TABLE facts_backup")
            # Insert a rogue row with arrival_ordinal = NULL
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                (gen_id(), "rogue", 1700000000.0, "attacker", "", "{}"),
            )
            conn.commit()
        finally:
            conn.close()

        report = audit_agreement(log_path)
        assert not report.ok
        assert report.index_behind is False

        counts = next(c for c in report.checks if c.name == "counts")
        assert not counts.ok
        assert "this index holds a row carrying no arrival coordinate" in counts.detail

    def test_l1_detects_edit_to_last_consumed_row(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=3)
        # Identify the last consumed row ID
        conn = sqlite3.connect(db_path)
        try:
            last_row = conn.execute(
                "SELECT id, arrival_ordinal FROM facts ORDER BY arrival_ordinal DESC, arrival_seq DESC LIMIT 1"
            ).fetchone()
            last_id, last_ord = last_row[0], last_row[1]
            # Edit payload of the last row in the index
            conn.execute(
                "UPDATE facts SET payload = ? WHERE id = ?",
                (json.dumps({"tampered": True}), last_id),
            )
            conn.commit()
        finally:
            conn.close()

        report = audit_agreement(log_path)
        assert not report.ok
        assert report.index_behind is False

        edge = next(c for c in report.checks if c.name == "consumed_edge")
        assert not edge.ok
        assert edge.at_ordinal == last_ord
        assert f"consumed arrival fact {last_id} at ordinal {last_ord} does not match" in edge.detail
        assert "the index was edited out of band" in edge.detail

    def test_l1_detects_rewound_marker_with_coordinates(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=4)
        # Current mark is at ord 4. Manually rewind store_meta's arrival_ordinal to 2.
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                f"UPDATE store_meta SET value = '2' WHERE key = '{ARRIVAL_ORDINAL_KEY}'"
            )
            conn.commit()
        finally:
            conn.close()

        report = audit_agreement(log_path)
        assert not report.ok
        assert report.index_behind is False

        rewound = next(c for c in report.checks if c.name == "rewound")
        assert not rewound.ok
        assert rewound.at_ordinal == 4
        assert "index holds row(s) at arrival ordinal 4 beyond consumed ordinal 2" in rewound.detail
        assert "the marker was rewound, which no writer produces" in rewound.detail


# ===========================================================================
# G-D3-2: Bounded work, deterministically instrumented
# ===========================================================================


class TestGateD3_2_BoundedWorkInstrumentation:
    """G-D3-2: bounded work, deterministically instrumented (NO timing):

    Test-scoped counter on record-verification seam asserts EXACT bounds:
    - healthy N-record: anchor (1) + 0 suffix = 1 record verified
    - K behind: 1 anchor + K suffix = 1 + K records verified
    - --deep: N records
    - neither ArrivalLog.read nor ArrivalLog.walk called in L1.
    """

    def test_healthy_store_verifies_exactly_anchor_plus_zero_suffix(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=10)

        # Instrument ArrivalLog.anchor and _walk_tail
        anchor_calls = 0
        suffix_records_verified = 0

        orig_anchor = ArrivalLog.anchor
        orig_walk_tail = ArrivalLog._walk_tail

        def counting_anchor(self_log, mark):
            nonlocal anchor_calls
            anchor_calls += 1
            return orig_anchor(self_log, mark)

        def counting_walk_tail(self_log, offset, anchor, lineage):
            nonlocal suffix_records_verified
            for rec in orig_walk_tail(self_log, offset, anchor, lineage):
                suffix_records_verified += 1
                yield rec

        with patch.object(ArrivalLog, "anchor", counting_anchor), \
             patch.object(ArrivalLog, "_walk_tail", counting_walk_tail), \
             patch.object(ArrivalLog, "read", side_effect=AssertionError("read() called in L1")), \
             patch.object(ArrivalLog, "walk", side_effect=AssertionError("walk() called in L1")):
            report = audit_agreement(log_path)

        assert report.ok
        assert anchor_calls == 1
        assert suffix_records_verified == 0

    def test_k_behind_store_verifies_exactly_one_anchor_plus_k_suffix(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=5)
        k_behind = 4

        log = ArrivalLog(log_path)
        for i in range(k_behind):
            log.append(
                "fact",
                object_of_fact_row((gen_id(), "note", 1700000000.0 + i, "kyle", "", json.dumps({"extra": i}))),
                observer="kyle",
            )

        anchor_calls = 0
        suffix_records_verified = 0

        orig_anchor = ArrivalLog.anchor
        orig_walk_tail = ArrivalLog._walk_tail

        def counting_anchor(self_log, mark):
            nonlocal anchor_calls
            anchor_calls += 1
            return orig_anchor(self_log, mark)

        def counting_walk_tail(self_log, offset, anchor, lineage):
            nonlocal suffix_records_verified
            for rec in orig_walk_tail(self_log, offset, anchor, lineage):
                suffix_records_verified += 1
                yield rec

        with patch.object(ArrivalLog, "anchor", counting_anchor), \
             patch.object(ArrivalLog, "_walk_tail", counting_walk_tail), \
             patch.object(ArrivalLog, "read", side_effect=AssertionError("read() called in L1")), \
             patch.object(ArrivalLog, "walk", side_effect=AssertionError("walk() called in L1")):
            report = audit_agreement(log_path)

        assert not report.ok
        assert report.index_behind is True
        assert anchor_calls == 1
        assert suffix_records_verified == k_behind

    def test_deep_audit_verifies_full_n_records(self, tmp_path: Path):
        n_facts = 7
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=n_facts)
        # Total arrival records = 1 genesis + 7 facts = 8 records.
        expected_n = 1 + n_facts

        walked_records = 0
        orig_walk = ArrivalLog.walk

        def counting_walk(self_log):
            nonlocal walked_records
            for rec in orig_walk(self_log):
                walked_records += 1
                yield rec

        with patch.object(ArrivalLog, "walk", counting_walk):
            report = audit_deep(log_path)

        assert report.ok
        assert walked_records == expected_n


# ===========================================================================
# G-D3-3: Torn arrival tail reports behind, never tampered
# ===========================================================================


class TestGateD3_3_TornArrivalTail:
    """G-D3-3: torn arrival tail: L1 reports 'behind' (index_behind=True), never 'tampered'."""

    def test_torn_arrival_tail_reports_index_behind(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=3)
        # Append incomplete bytes (a torn line without a trailing newline) to the arrival log
        with log_path.open("ab") as fh:
            fh.write(b'{"ord": 4, "t": "fact", "torn": true')

        report = audit_agreement(log_path)
        assert not report.ok
        assert report.index_behind is True

        consumed = next(c for c in report.checks if c.name == "consumed")
        assert not consumed.ok
        assert consumed.behind_by > 0
        assert "log ends mid-record" in consumed.detail or "behind arrival" in consumed.detail


# ===========================================================================
# G-D3-4: Derived .jsonl multiset audit
# ===========================================================================


class TestGateD3_4_MultisetDerivedLogAudit:
    """G-D3-4: derived .jsonl reordered => multiset audit agrees; DUPLICATED line detected; removed line detected."""

    def test_reordered_derived_jsonl_multiset_audit_agrees(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=5)
        rederive_projections(log_path, derived_log=True)
        derived_jsonl = derived_log_path_for(log_path)
        assert derived_jsonl.exists()

        # Reorder lines of the derived .jsonl
        lines = derived_jsonl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 3
        # Permute lines (e.g. reverse them)
        permuted_lines = list(reversed(lines))
        derived_jsonl.write_text("\n".join(permuted_lines) + "\n", encoding="utf-8")

        result = audit_derived_log(log_path)
        assert result.ok
        assert result.missing == 0
        assert result.extra == 0
        assert "agrees with" in result.detail

        # Also deep audit includes derived_log check
        report = audit_deep(log_path)
        assert report.ok
        derived_check = next(c for c in report.checks if c.name == "derived_log")
        assert derived_check.ok

    def test_duplicated_line_in_derived_jsonl_is_detected(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=4)
        rederive_projections(log_path, derived_log=True)
        derived_jsonl = derived_log_path_for(log_path)
        assert derived_jsonl.exists()

        lines = derived_jsonl.read_text(encoding="utf-8").strip().splitlines()
        # Duplicate the second line
        lines.append(lines[1])
        derived_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = audit_derived_log(log_path)
        assert not result.ok
        assert result.missing == 0
        assert result.extra == 1
        assert "1 line(s) it never carried are present" in result.detail

        report = audit_deep(log_path)
        assert not report.ok
        derived_check = next(c for c in report.checks if c.name == "derived_log")
        assert not derived_check.ok

    def test_removed_line_in_derived_jsonl_is_detected(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=4)
        rederive_projections(log_path, derived_log=True)
        derived_jsonl = derived_log_path_for(log_path)
        assert derived_jsonl.exists()

        lines = derived_jsonl.read_text(encoding="utf-8").strip().splitlines()
        # Remove one line
        removed_line = lines.pop(2)
        derived_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = audit_derived_log(log_path)
        assert not result.ok
        assert result.missing == 1
        assert result.extra == 0
        assert "1 record(s) the arrival log carries are absent" in result.detail

        report = audit_deep(log_path)
        assert not report.ok
        derived_check = next(c for c in report.checks if c.name == "derived_log")
        assert not derived_check.ok
