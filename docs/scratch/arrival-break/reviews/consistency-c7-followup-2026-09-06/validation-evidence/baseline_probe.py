"""Execute only the committed pre-fix resolver against new public regressions."""
import ast
import importlib
import subprocess

import pytest
from engine.arrival_registry import descriptor_for
from lang import parse_vertex_file

module = importlib.import_module('sdk.read')
source = subprocess.check_output(
    ['git', 'show', 'f5563d2f:libs/sdk/src/sdk/read.py'], text=True
)
node = next(
    node for node in ast.parse(source).body
    if isinstance(node, ast.FunctionDef)
    and node.name == '_aggregate_aware_arrival_descriptor'
)
namespace = dict(module.__dict__)
namespace.update(descriptor_for=descriptor_for, parse_vertex_file=parse_vertex_file)
exec(compile(ast.Module(body=[node], type_ignores=[]), '<committed-resolver>', 'exec'), namespace)
module._aggregate_aware_arrival_descriptor = namespace['_aggregate_aware_arrival_descriptor']
raise SystemExit(pytest.main(['-q', '--tb=short', 'tests/test_arrival_aggregate_resolution.py']))
