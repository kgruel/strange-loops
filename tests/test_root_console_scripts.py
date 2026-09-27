"""Root-wheel console-script delivery metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_console_scripts_use_the_json_client() -> None:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        scripts = tomllib.load(project_file)["project"]["scripts"]

    expected = {name: "loops_min.main:main" for name in ("sl", "loops", "loops-min")}
    assert {name: scripts.get(name) for name in expected} == expected
