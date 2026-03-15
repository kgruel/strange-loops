"""Tests that enforce layer boundaries between engine components.

The engine has clear layer responsibilities:
- Store: append/read data (Store protocol)
- Projection: fold events into state (fold_one, fold_one_mut)
- Loop: fold + boundary semantics
- Vertex: routing, replay, boundary orchestration

These tests catch violations where one layer reaches into another's
internals — e.g. the store directly manipulating projection state
instead of calling through the projection interface.
"""

import ast
import inspect
from pathlib import Path

import pytest

ENGINE_SRC = Path(__file__).resolve().parent.parent / "src" / "engine"


def _get_source(module_name: str) -> str:
    """Read source code for an engine module."""
    return (ENGINE_SRC / f"{module_name}.py").read_text()


def _attribute_accesses_in_function(source: str, func_name: str) -> list[str]:
    """Extract all attribute accesses (obj.attr) in a specific function."""
    tree = ast.parse(source)
    accesses = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute):
                    accesses.append(child.attr)
    return accesses


# ---------------------------------------------------------------------------
# Store must not reach into Projection internals
# ---------------------------------------------------------------------------

PROJECTION_INTERNALS = {"_state", "_version"}


class TestStoreDoesNotReachIntoProjection:
    """SqliteStore should not access Projection._state, _version, or cursor.

    The store protocol is read/write data. Fold logic belongs in Projection.
    If the store needs to fold, it should call through the Projection
    interface (fold_one, fold_one_mut), not manipulate internals directly.
    """

    def test_replay_into_does_not_access_projection_internals(self):
        source = _get_source("sqlite_store")
        accesses = _attribute_accesses_in_function(source, "replay_into")
        violations = [a for a in accesses if a in PROJECTION_INTERNALS]
        assert not violations, (
            f"SqliteStore.replay_into() accesses Projection internals: {violations}. "
            f"Use Projection.fold_one_mut() instead of reaching into _state/_version directly."
        )

    def test_no_store_method_accesses_projection_internals(self):
        """Broader check: no method in sqlite_store.py should access projection internals."""
        source = _get_source("sqlite_store")
        tree = ast.parse(source)
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr in PROJECTION_INTERNALS:
                        violations.append((node.name, child.attr))
        assert not violations, (
            f"SqliteStore methods access Projection internals: {violations}. "
            f"Store protocol is read/write data — fold logic belongs in Projection."
        )


# ---------------------------------------------------------------------------
# Vertex.replay should use Projection interface, not internals
# ---------------------------------------------------------------------------

class TestVertexReplayUsesProjectionInterface:
    """Vertex.replay() should fold through Projection methods, not by
    directly manipulating _state/_version.

    The Projection interface (fold_one, fold_one_mut) is the contract.
    Bypassing it duplicates fold logic and creates divergence risk.
    """

    def test_replay_does_not_access_projection_state_directly(self):
        source = _get_source("vertex")
        accesses = _attribute_accesses_in_function(source, "replay")
        # Filter: _state/_version on projection objects (not self._state which is vertex's own)
        # We check for _state and _version — vertex.replay should not touch these
        # on any object except self.
        # The proxy: if replay accesses _state or _version, it's likely reaching
        # into a projection. Vertex's own state is accessed via self._store,
        # self._replaying etc, not _state/_version.
        violations = [a for a in accesses if a in PROJECTION_INTERNALS]
        assert not violations, (
            f"Vertex.replay() accesses Projection internals: {violations}. "
            f"Use loop._projection.fold_one_mut() or loop.receive() instead."
        )
