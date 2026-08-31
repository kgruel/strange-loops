"""Shared test fixtures for migrate test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect state root to a test-isolated temporary directory.

    Autouse rather than per-test: guarantees no test writes head observations
    or probes into the developer's real ~/.local/state/loops.
    """
    state_dir = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))
    return state_dir
