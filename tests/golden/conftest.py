"""Golden file fixture for demo integration tests.

The --update-goldens flag is registered in the root tests/conftest.py
(pytest_addoption must run before collection reaches subdirectories).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

import pytest

GOLDENS_DIR = Path(__file__).parent / "goldens"


@pytest.fixture(autouse=True)
def _reset_ambient():
    """Reset icon/palette ContextVars so test order doesn't matter."""
    from painted.icon_set import reset_icons
    from painted.palette import reset_palette

    reset_icons()
    reset_palette()
    yield
    reset_icons()
    reset_palette()


@dataclass
class Golden:
    """Compare rendered text against committed golden files."""

    test_module: str  # e.g. "test_demo_testing"
    test_name: str  # e.g. "test_testing_demo[MINIMAL]"
    update: bool

    def assert_match(self, text: str, name: str) -> None:
        """Compare *text* against ``goldens/{module}/{test}/{name}.txt``."""
        # Normalize: right-strip each line, ensure trailing newline
        normalized = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"

        path = GOLDENS_DIR / self.test_module / self.test_name / f"{name}.txt"

        if not path.exists() or self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(normalized)
            if not self.update:
                return  # first run — bootstrap, pass
            return

        expected = path.read_text()
        if normalized != expected:
            diff = difflib.unified_diff(
                expected.splitlines(keepends=True),
                normalized.splitlines(keepends=True),
                fromfile=str(path),
                tofile="actual",
            )
            diff_text = "".join(diff)
            pytest.fail(f"Golden mismatch for {path}:\n{diff_text}")


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    module = request.node.module.__name__  # e.g. "test_demo_testing"
    name = request.node.name  # e.g. "test_testing_demo[MINIMAL]"
    update = request.config.getoption("--update-goldens")
    return Golden(test_module=module, test_name=name, update=update)
