#!/bin/bash
set -euo pipefail

# Run loops app tests to ensure nothing is broken
echo "Running loops tests..."
uv run --package loops pytest apps/loops/tests -x -q --tb=short \
    --ignore=apps/loops/tests/golden 2>&1 | tail -5

# Also run core libs to catch cross-package breakage
echo "Running lang tests..."
uv run --package lang pytest libs/lang/tests -x -q --tb=short 2>&1 | tail -5
echo "Running engine tests..."
uv run --package engine pytest libs/engine/tests -x -q --tb=short 2>&1 | tail -5
echo "Running atoms tests..."
uv run --package atoms pytest libs/atoms/tests -x -q --tb=short 2>&1 | tail -5

# Verify no trivial tests (warning only)
echo "Checking for trivial tests..."
uv run python -c "
import ast, sys, pathlib

errors = []
for path in pathlib.Path('apps/loops/tests').rglob('test_*.py'):
    if 'golden' in str(path):
        continue
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
            has_assert = any(
                isinstance(n, ast.Assert) or
                (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and
                 isinstance(n.value.func, ast.Attribute) and
                 n.value.func.attr.startswith('assert'))
                for n in ast.walk(node)
            )
            has_raises = any(
                isinstance(n, ast.Call) and
                (hasattr(n.func, 'attr') and n.func.attr == 'raises')
                for n in ast.walk(node)
            )
            if not has_assert and not has_raises:
                errors.append(f'{path}:{node.lineno} {node.name} has no assertions')

if errors:
    print(f'WARNING: {len(errors)} tests without explicit assertions (may be does-not-raise tests):')
    for e in errors:
        print(f'  {e}')
else:
    print('All loops tests have assertions.')
"

echo "All checks passed."
