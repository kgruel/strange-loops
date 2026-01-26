"""Tests for the full wired pipeline experiment.

Tests the FormProjection bridge and render_dashboard function,
verifying that all 5 libraries integrate correctly.
"""

from __future__ import annotations

import time

import pytest
from facts import Event
from shapes import Field, Fold, Form

from apps.pipeline import (
    FormProjection,
    PULSE_FORM,
    render_dashboard,
    _make_latest,
    _make_count,
    _make_upsert,
    _make_collect,
    _make_sum,
)


# ---------------------------------------------------------------------------
# FormProjection tests
# ---------------------------------------------------------------------------


class TestFormProjection:
    """Tests for FormProjection bridge."""

    def test_initial_state_matches_form(self):
        proj = FormProjection(PULSE_FORM)
        state = proj.state
        assert state["last_seen"] == ""
        assert state["event_count"] == 0
        assert state["services"] == {}
        assert state["history"] == []
        assert state["total_requests"] == 0

    def test_apply_extracts_event_data(self):
        proj = FormProjection(PULSE_FORM)
        event = Event.log_signal(
            "heartbeat",
            service="api-gateway",
            status="healthy",
            latency_ms=12.5,
            requests=42,
            peer="api-gateway",
            ts=1000.0,
        )
        new_state = proj.apply(proj.state, event)
        # count should have incremented
        assert new_state["event_count"] == 1
        # service should be upserted
        assert "api-gateway" in new_state["services"]
        svc = new_state["services"]["api-gateway"]
        assert svc["service"] == "api-gateway"
        assert svc["status"] == "healthy"
        assert svc["latency_ms"] == 12.5
        # total_requests should be summed
        assert new_state["total_requests"] == 42
        # history should contain one entry
        assert len(new_state["history"]) == 1

    @pytest.mark.asyncio
    async def test_consume_updates_version(self):
        proj = FormProjection(PULSE_FORM)
        assert proj.version == 0
        event = Event.log_signal(
            "heartbeat",
            service="cache",
            status="degraded",
            latency_ms=150.0,
            requests=10,
            peer="cache",
        )
        await proj.consume(event)
        assert proj.version == 1
        assert proj.state["event_count"] == 1

    @pytest.mark.asyncio
    async def test_multiple_events_accumulate(self):
        proj = FormProjection(PULSE_FORM)
        for i in range(5):
            event = Event.log_signal(
                "heartbeat",
                service=f"svc-{i}",
                status="healthy",
                latency_ms=10.0,
                requests=10,
                peer=f"svc-{i}",
            )
            await proj.consume(event)
        assert proj.state["event_count"] == 5
        assert len(proj.state["services"]) == 5
        assert proj.state["total_requests"] == 50

    def test_apply_returns_new_state(self):
        """apply() must return a new dict (not mutate the original)."""
        proj = FormProjection(PULSE_FORM)
        original = proj.state
        event = Event.log_signal(
            "heartbeat",
            service="worker",
            status="down",
            latency_ms=999.0,
            requests=0,
            peer="worker",
        )
        new_state = proj.apply(original, event)
        # Original state should be unchanged
        assert original["event_count"] == 0
        assert new_state["event_count"] == 1
        assert new_state is not original


# ---------------------------------------------------------------------------
# Fold builder tests
# ---------------------------------------------------------------------------


class TestFoldBuilders:
    """Tests for individual fold builder functions."""

    def test_make_latest(self):
        fn = _make_latest("last_seen")
        state = {"last_seen": ""}
        fn(state, {"_ts": 1234.5})
        assert state["last_seen"] == 1234.5

    def test_make_count(self):
        fn = _make_count("event_count")
        state = {"event_count": 0}
        fn(state, {})
        fn(state, {})
        assert state["event_count"] == 2

    def test_make_sum(self):
        fn = _make_sum("total_requests", "requests")
        state = {"total_requests": 0}
        fn(state, {"requests": 10})
        fn(state, {"requests": 25})
        assert state["total_requests"] == 35


# ---------------------------------------------------------------------------
# Render function tests
# ---------------------------------------------------------------------------


class TestRenderDashboard:
    """Tests for render_dashboard function."""

    def test_empty_state_renders(self):
        state = PULSE_FORM.initial_state()
        block = render_dashboard(state, 80, 24)
        assert block.height > 0
        assert block.width > 0

    def test_populated_state_renders(self):
        state = PULSE_FORM.initial_state()
        state["event_count"] = 42
        state["total_requests"] = 500
        state["services"] = {
            "api-gateway": {
                "service": "api-gateway",
                "status": "healthy",
                "latency_ms": 12.5,
                "requests": 100,
            },
            "cache": {
                "service": "cache",
                "status": "degraded",
                "latency_ms": 200.0,
                "requests": 50,
            },
        }
        state["history"] = [
            {
                "service": "api-gateway",
                "status": "healthy",
                "latency_ms": 12.5,
                "_ts": time.time(),
            }
        ]
        block = render_dashboard(state, 80, 24)
        assert block.height > 0
