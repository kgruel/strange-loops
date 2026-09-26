"""Frozen slot ASTs can be detached without sharing mutable declaration data."""

from copy import deepcopy

import pytest

from lang import parse_vertex
from lang.ast import BoundaryCondition


def test_deepcopy_condition_preserves_value_type_and_frozen_behavior():
    condition = BoundaryCondition("count", ">=", 2.0)
    copied = deepcopy(condition)
    assert type(copied) is type(condition)
    assert copied == condition and copied is not condition
    with pytest.raises(AttributeError, match="cannot assign"):
        copied.value = 3.0


def test_deepcopy_nested_ast_detaches_maps_and_retains_internal_aliases():
    vertex = parse_vertex(
        'name "copy"\nloops {\n'
        '  item {\n    fold { count "inc" }\n'
        '    boundary when="item" { condition "count" ">=" 2 }\n'
        '  }\n}\n'
    )
    first, second = deepcopy([vertex, vertex])
    assert first is second and first is not vertex
    assert first == vertex
    assert first.loops is not vertex.loops
    assert first.loops["item"] is not vertex.loops["item"]
    first.loops["another"] = first.loops["item"]
    assert "another" not in vertex.loops
    with pytest.raises(AttributeError, match="cannot assign"):
        first.name = "changed"
