"""Outer-Loop Tier 7: SDK Chaos & Disaster Recovery Tests.

Tests SDK fault tolerance under disk exhaustion and interrupted declarative ceremonies.
"""

from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from sdk import (
    EmissionFailed,
    emit_fact,
    init_vertex,
    inspect_declaration,
    read_summary,
    recover_ceremony,
)


def test_sdk_emit_disk_full_resilience(tmp_path: Path) -> None:
    """sdk.emit_fact must fail gracefully under disk errors without corrupting the vertex."""
    vertex_path = tmp_path / "sdk_fault.vertex"
    init_vertex(vertex_path, name="sdk_fault", store_type="sqlite")

    # Initial valid emission
    r1 = emit_fact(
        vertex_path, "note", {"msg": "initial"}, observer="test", admit_undeclared=True
    )
    assert r1.id != ""
    assert read_summary(vertex_path).fact_total == 1

    # Simulate ENOSPC / disk full on subsequent emission
    from engine.program import VertexProgram

    with patch.object(
        VertexProgram,
        "receive",
        side_effect=sqlite3.OperationalError("database or disk is full"),
    ):
        with pytest.raises((EmissionFailed, sqlite3.OperationalError)):
            emit_fact(
                vertex_path,
                "note",
                {"msg": "should fail"},
                observer="test",
                admit_undeclared=True,
            )

    # Store remains clean and readable
    summary = read_summary(vertex_path)
    assert summary.fact_total == 1
    assert summary.agreement is True


def test_sdk_interrupted_ceremony_recovery(tmp_path: Path) -> None:
    """sdk.recover_ceremony must cleanly classify already-applied and pending intents."""
    vertex_path = tmp_path / "ceremony_crash.vertex"
    init_vertex(vertex_path, name="ceremony_crash", store_type="sqlite")

    # When no intent file exists at path, recovery safely answers already-applied
    intent_path = Path(str(vertex_path) + ".intent")
    recovery_res = recover_ceremony(intent_path)
    assert recovery_res["classification"] == "already-applied"
    assert recovery_res["finished"] is False

    # Declaration inspection remains valid
    inspection = inspect_declaration(vertex_path)
    assert inspection.name == "ceremony_crash"
