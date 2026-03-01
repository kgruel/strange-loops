"""Golden test infrastructure — compare rendered output against committed files."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

import pytest

GOLDENS_DIR = Path(__file__).parent / "goldens"


@dataclass
class Golden:
    """Compare rendered text against committed golden files."""

    test_module: str
    test_name: str
    update: bool

    def assert_match(self, text: str, name: str) -> None:
        """Compare *text* against ``goldens/{module}/{test}/{name}.txt``."""
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
            pytest.fail(f"Golden mismatch for {path}:\n{''.join(diff)}")


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    module = request.node.module.__name__
    name = request.node.name
    update = request.config.getoption("--update-goldens")
    return Golden(test_module=module, test_name=name, update=update)
