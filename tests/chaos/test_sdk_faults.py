"""Outer-Loop Tier 7: SDK Chaos & Disaster Recovery Tests.

Tests SDK fault tolerance under real SQLite disk exhaustion, interrupted
declarative ceremonies (post-commit crash and pre-commit crash recovery),
missing intent file recovery, and read-only permission constraints.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from custody import ensure_signing_key
from engine.ceremony import (
    _write_intent,
    apply_declaration_update,
    plan_declaration_update,
)
from engine.residence import index_path_for
from lang import add_vertex_kind
from sdk import (
    EmissionFailed,
    emit_fact,
    init_vertex,
    inspect_declaration,
    read_summary,
    recover_ceremony,
)
from sdk.emit import CustodyCredentialProvider
from sdk.kind import _default_loop_def


def test_sdk_emit_disk_full_resilience(tmp_path: Path) -> None:
    """sdk.emit_fact must fail gracefully under real disk exhaustion without corrupting the vertex."""
    vertex_path = tmp_path / "sdk_fault.vertex"
    init_vertex(vertex_path, name="sdk_fault", store_type="sqlite")

    # Initial valid emission
    r1 = emit_fact(
        vertex_path, "note", {"msg": "initial"}, observer="test", admit_undeclared=True
    )
    assert r1.id != ""
    assert read_summary(vertex_path).fact_total == 1

    # Measure current page count of the store database
    decl = inspect_declaration(vertex_path)
    assert decl.store_path is not None
    db_path = index_path_for(decl.store_path)
    conn = sqlite3.connect(db_path)
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    conn.close()

    # Apply real SQLite PRAGMA max_page_count ceiling at the lowest connection boundary
    real_connect = sqlite3.connect

    def connect_with_limit(*args, **kwargs):
        c = real_connect(*args, **kwargs)
        c.execute(f"PRAGMA max_page_count = {pages}")
        return c

    with (
        patch("sqlite3.connect", side_effect=connect_with_limit),
        pytest.raises(EmissionFailed, match=r"database or disk is full"),
    ):
        emit_fact(
            vertex_path,
            "note",
            {"msg": "should fail" * 1000},
            observer="test",
            admit_undeclared=True,
        )

    # Store remains clean and readable
    summary = read_summary(vertex_path)
    assert summary.fact_total == 1
    assert summary.agreement is True


def test_sdk_interrupted_ceremony_post_commit_recovery(tmp_path: Path) -> None:
    """sdk.recover_ceremony must complete an interrupted ceremony where the store committed before file update."""
    vertex_path = tmp_path / "ceremony_postcommit.vertex"
    init_vertex(vertex_path, name="ceremony_postcommit", store_type="sqlite")
    ensure_signing_key(vertex_path, "admin")

    # Plan adding a new kind definition
    orig_text = vertex_path.read_text(encoding="utf-8")
    new_text = add_vertex_kind(orig_text, "audit", _default_loop_def())
    preview = plan_declaration_update(vertex_path, proposed_text=new_text)
    assert preview.applicable

    # Simulate process crash / write failure after store commit, before declaration file replace
    def failing_writer(path: Path, text: str | None) -> None:
        raise OSError("Simulated crash between store commit and file replace")

    res = apply_declaration_update(
        preview,
        observer="admin",
        credentials=CustodyCredentialProvider(),
        write_file=failing_writer,
    )
    assert res.status == "needs-recovery"
    intent_path = res.intent_path
    assert intent_path.exists()

    # The vertex declaration file still has the original content (un-reconciled)
    assert "audit" not in vertex_path.read_text(encoding="utf-8")

    # Running recover_ceremony detects committed store, finishes the atomic file update, and clears intent
    recovery_res = recover_ceremony(intent_path)
    assert recovery_res["classification"] == "safe-to-finish"
    assert recovery_res["finished"] is True
    assert not intent_path.exists()
    assert "audit" in vertex_path.read_text(encoding="utf-8")

    # Inspection confirms new kind is active
    decl = inspect_declaration(vertex_path)
    assert "audit" in decl.declared_kinds


def test_sdk_interrupted_ceremony_pre_commit_recovery(tmp_path: Path) -> None:
    """sdk.recover_ceremony must void an intent if a crash occurred before the store absorbed the change."""
    vertex_path = tmp_path / "ceremony_precommit.vertex"
    init_vertex(vertex_path, name="ceremony_precommit", store_type="sqlite")
    ensure_signing_key(vertex_path, "admin")

    orig_text = vertex_path.read_text(encoding="utf-8")
    new_text = add_vertex_kind(orig_text, "audit", _default_loop_def())
    preview = plan_declaration_update(vertex_path, proposed_text=new_text)

    # Write intent file simulating crash before store absorb
    intent_path = _write_intent(preview, "admin")
    assert intent_path.exists()

    # recover_ceremony sees store still at pre-ceremony state, classifies as not-applied, and removes void intent
    recovery_res = recover_ceremony(intent_path)
    assert recovery_res["classification"] == "not-applied"
    assert recovery_res["finished"] is False
    assert not intent_path.exists()
    assert "audit" not in vertex_path.read_text(encoding="utf-8")

    decl = inspect_declaration(vertex_path)
    assert "audit" not in decl.declared_kinds


def test_sdk_missing_intent_file_recovery(tmp_path: Path) -> None:
    """sdk.recover_ceremony handles a non-existent intent file cleanly, returning already-applied."""
    vertex_path = tmp_path / "ceremony_absent.vertex"
    init_vertex(vertex_path, name="ceremony_absent", store_type="sqlite")

    # When no intent file exists at path, recovery safely answers already-applied
    intent_path = Path(str(vertex_path) + ".intent")
    assert not intent_path.exists()
    recovery_res = recover_ceremony(intent_path)
    assert recovery_res["classification"] == "already-applied"
    assert recovery_res["finished"] is False

    # Declaration inspection remains valid
    inspection = inspect_declaration(vertex_path)
    assert inspection.name == "ceremony_absent"


def test_sdk_emit_readonly_permission_resilience(tmp_path: Path) -> None:
    """sdk.emit_fact fails with EmissionFailed when underlying store file is read-only, while reads work."""
    vertex_path = tmp_path / "sdk_readonly.vertex"
    init_vertex(vertex_path, name="sdk_readonly", store_type="sqlite")

    # Initial valid emission
    emit_fact(vertex_path, "note", {"msg": "initial"}, observer="test", admit_undeclared=True)
    assert read_summary(vertex_path).fact_total == 1

    decl = inspect_declaration(vertex_path)
    assert decl.store_path is not None
    db_path = index_path_for(decl.store_path)

    os.chmod(db_path, stat.S_IRUSR)
    try:
        # Emission fails cleanly under read-only permissions
        with pytest.raises(EmissionFailed):
            emit_fact(vertex_path, "note", {"msg": "fail"}, observer="test", admit_undeclared=True)

        # Reads still work
        summary = read_summary(vertex_path)
        assert summary.fact_total == 1
    finally:
        os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)
