"""A Git update can leave ignored tests/cache directories for a retired package."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dev_test_ignores_retired_package_residue(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.write_bytes((ROOT / "dev").read_bytes())
    for name in ("libs/core", "apps/loops-min"):
        package = tmp_path / name
        (package / "tests").mkdir(parents=True)
        (package / "pyproject.toml").write_text("# synthetic package metadata\n")
    residue = tmp_path / "apps/loops/tests/__pycache__/test_old.pyc"
    residue.parent.mkdir(parents=True)
    residue.write_bytes(b"leave ignored residue alone")
    binary = tmp_path / "bin"
    binary.mkdir()
    uv = binary / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$UV_CALLS"\n'
        'case " $* " in *" --package loops "*) exit 73 ;; esac\n'
    )
    uv.chmod(0o700)
    calls = tmp_path / "calls.txt"
    environment = os.environ.copy()
    environment.update(PATH=f"{binary}:/usr/bin:/bin", UV_CALLS=str(calls))
    result = subprocess.run(
        ["/bin/bash", str(dev), "test"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text().splitlines() == [
        "run pytest tests/ --ignore=tests/chaos -q",
        "run --package core pytest libs/core/tests -q",
        "run --package loops-min pytest apps/loops-min/tests -q",
    ]
    assert residue.read_bytes() == b"leave ignored residue alone"
