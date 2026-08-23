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
import contextlib
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
        assert "facts has NULL arrival_ordinal" in counts.detail

    def test_l1_detects_null_arrival_seq_with_location_claim(self, tmp_path: Path):
        """SOL-HIGH-04: Non-NULL ordinal + NULL seq => counts check fails with location claim."""
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=3)
        conn = sqlite3.connect(db_path)
        try:
            # Recreate facts table without NOT NULL to allow NULL arrival_seq
            conn.execute("CREATE TEMP TABLE facts_backup AS SELECT * FROM facts")
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
            # Insert a rogue row with arrival_ordinal = 5 (non-NULL) but arrival_seq = NULL
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, arrival_ordinal, arrival_seq) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, 5, NULL)",
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
        assert "this index holds a row carrying no arrival coordinate (facts has NULL arrival_seq)" in counts.detail

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

    def test_marked_open_trusts_structure_but_audit_detects_coordinate_tamper(
        self, tmp_path: Path
    ):
        """SOL-HIGH-10 claim-boundary pin: a MARKED, structurally-complete index
        whose coordinates were shifted out-of-band (marker and resume mark
        retained) reopens without an O(log) content walk — content agreement is
        the AUDIT surface's claim, not the open path's — and the L1 audit then
        detects the tamper via the rewound check with a location claim.
        """
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=2)
        store.close()

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("UPDATE facts SET arrival_ordinal = arrival_ordinal + 100")
            conn.commit()
        finally:
            conn.close()

        # Reopen through the public constructor: accepted (structure is valid,
        # marker is authority for the open path's structural claim).
        reopened = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
            tick_signer=_tick_signer,
            fact_signer=_fact_signer,
        )
        reopened.close()

        # The audit surface owns the content claim, and detects the tamper.
        report = audit_agreement(log_path)
        assert not report.ok
        rewound = next(c for c in report.checks if c.name == "rewound")
        assert not rewound.ok
        assert rewound.at_ordinal == 102
        assert "beyond consumed ordinal 2" in rewound.detail


# ===========================================================================
# G-D3-2: Bounded work, deterministically instrumented
# ===========================================================================


@contextlib.contextmanager
def _record_verification_counter():
    """Quantity seam counter: counts anchor validation attempts and verified walk records.

    - anchor: calls to ArrivalLog.anchor (validating single anchor record)
    - walk: records verified in ArrivalLog._verify_from (the single verification loop
      for all walks — both from zero and resumed suffix)
    - total: anchor + walk
    """
    counts = {"anchor": 0, "walk": 0}

    orig_anchor = ArrivalLog.anchor
    orig_verify_from = ArrivalLog._verify_from

    def counting_anchor(self_log, mark):
        counts["anchor"] += 1
        return orig_anchor(self_log, mark)

    def counting_verify_from(self_log, fh, *, expected, prev, lineage):
        for item in orig_verify_from(self_log, fh, expected=expected, prev=prev, lineage=lineage):
            counts["walk"] += 1
            yield item

    with patch.object(ArrivalLog, "anchor", counting_anchor), \
         patch.object(ArrivalLog, "_verify_from", counting_verify_from):
        yield counts


class TestGateD3_2_BoundedWorkInstrumentation:
    """G-D3-2: bounded work, deterministically instrumented (NO timing):

    Test-scoped counter on record-verification seam asserts EXACT bounds:
    - healthy N-record: anchor (1) + 0 suffix = 1 record verified
    - K behind: 1 anchor + K suffix = 1 + K records verified
    - anchor-failed: 1 anchor attempt + 0 suffix = 1 record verified (NO walk from zero)
    - --deep: 1 + N records verified (1 anchor in L1 base + N records in full walk).
    """

    def test_healthy_store_verifies_exactly_anchor_plus_zero_suffix(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=10)

        with _record_verification_counter() as counts:
            report = audit_agreement(log_path)

        assert report.ok
        assert counts["anchor"] == 1
        assert counts["walk"] == 0
        assert counts["anchor"] + counts["walk"] == 1

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

        with _record_verification_counter() as counts:
            report = audit_agreement(log_path)

        assert not report.ok
        assert report.index_behind is True
        assert counts["anchor"] == 1
        assert counts["walk"] == k_behind
        assert counts["anchor"] + counts["walk"] == 1 + k_behind

    def test_anchor_failed_corrupted_offset_verifies_single_record_no_walk(self, tmp_path: Path):
        """Gate W4-1 reproduction fixture: mark current, offset corrupted mid-record.

        Anchor validation fails => L1 verifies O(1) records (assert via quantity seam),
        consumed check reports unverifiable with NO behind_by magnitude, sibling counts check
        still truthfully reports all facts accounted for.
        """
        n_facts = 200
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=n_facts)

        # Corrupt the offset in the index's store_meta table to point mid-record
        conn = sqlite3.connect(db_path)
        try:
            cur_offset = int(conn.execute(
                f"SELECT value FROM store_meta WHERE key = '{ARRIVAL_OFFSET_KEY}'"
            ).fetchone()[0])
            corrupted_offset = cur_offset - 5
            conn.execute(
                f"UPDATE store_meta SET value = ? WHERE key = '{ARRIVAL_OFFSET_KEY}'",
                (str(corrupted_offset),),
            )
            conn.commit()
        finally:
            conn.close()

        with _record_verification_counter() as counts:
            report = audit_agreement(log_path)

        assert not report.ok
        assert report.index_behind is False

        # Quantity seam: anchor failed => exactly 1 record verified (anchor attempt), NO walk from zero
        assert counts["anchor"] == 1
        assert counts["walk"] == 0
        assert counts["anchor"] + counts["walk"] == 1

        # Check consumed: unverifiable with NO behind_by magnitude
        consumed = next(c for c in report.checks if c.name == "consumed")
        assert not consumed.ok
        assert consumed.behind_by == 0
        assert consumed.at_ordinal == n_facts
        assert "anchor verification failed; consumed position unverifiable" in consumed.detail
        assert str(n_facts) in consumed.detail

        # Sibling counts check: truthfully reports all facts accounted for
        counts_check = next(c for c in report.checks if c.name == "counts")
        assert counts_check.ok
        assert f"{n_facts} fact(s), 0 tick(s) accounted for" in counts_check.detail

        # Consumed edge check: failed anchor verification
        edge_check = next(c for c in report.checks if c.name == "consumed_edge")
        assert not edge_check.ok
        assert "failed anchor verification" in edge_check.detail
        assert edge_check.at_ordinal == n_facts

    def test_deep_audit_verifies_full_n_records(self, tmp_path: Path):
        n_facts = 7
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=n_facts)
        # Total arrival records = 1 genesis + 7 facts = 8 records.
        expected_n = 1 + n_facts

        with _record_verification_counter() as counts:
            report = audit_deep(log_path)

        assert report.ok
        assert counts["anchor"] == 1
        assert counts["walk"] == expected_n
        total_verified = counts["anchor"] + counts["walk"]
        assert total_verified == 1 + expected_n


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


# ===========================================================================
# G-D3-5: SOL-WP4-01: beyond_offset dissolved without shim
# ===========================================================================


class TestGateD3_5_CheckDissolvesBeyondOffset:
    """SOL-WP4-01: Check dissolves beyond_offset into behind_by/at_ordinal — no shim."""

    def test_check_has_no_beyond_offset_attribute_and_as_dict_has_no_such_key(self):
        c = Check("consumed", False, "index is behind arrival", behind_by=3, at_ordinal=2)
        with pytest.raises(AttributeError):
            _ = c.beyond_offset  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            _ = getattr(c, "beyond_offset")
        d = c.as_dict()
        assert "beyond_offset" not in d
        assert d == {
            "check": "consumed",
            "ok": False,
            "detail": "index is behind arrival",
            "behind_by": 3,
            "at_ordinal": 2,
        }

    def test_agreement_reports_checks_contain_no_beyond_offset(self, tmp_path: Path):
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=3)
        report = audit_agreement(log_path)
        assert report.ok
        for c in report.checks:
            with pytest.raises(AttributeError):
                _ = c.beyond_offset  # type: ignore[attr-defined]
            assert "beyond_offset" not in c.as_dict()

        report_dict = report.as_dict()
        assert "checks" in report_dict
        for cd in report_dict["checks"]:
            assert "beyond_offset" not in cd
