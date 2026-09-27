"""Root-wheel console-script delivery metadata."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_root_console_scripts_use_the_json_client() -> None:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        scripts = tomllib.load(project_file)["project"]["scripts"]

    expected = {name: "loops_min.main:main" for name in ("sl", "loops", "loops-min")}
    assert {name: scripts.get(name) for name in expected} == expected


def test_root_package_retires_the_legacy_frontend_not_migration() -> None:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        metadata = tomllib.load(project_file)

    retired = ROOT / "apps" / "loops"
    assert not (retired / "pyproject.toml").exists()
    assert not list((retired / "src").rglob("*.py"))
    assert "apps/loops" not in metadata["tool"]["uv"]["workspace"]["members"]
    build = metadata["tool"]["hatch"]["build"]
    for entries in (build["only-include"], build["targets"]["wheel"]["packages"]):
        assert "apps/loops/src/loops" not in entries
        assert "apps/loops-min/src/loops_min" in entries
        assert "libs/migrate/src/migrate" in entries
    assert not any(
        dep.startswith("painted") for dep in metadata["project"]["dependencies"]
    )


def test_retirement_allows_ignored_residue(tmp_path, monkeypatch) -> None:
    metadata = (ROOT / "pyproject.toml").read_bytes()
    (tmp_path / "pyproject.toml").write_bytes(metadata)
    residue = tmp_path / "apps/loops/src/loops/__pycache__/main.cpython-313.pyc"
    residue.parent.mkdir(parents=True)
    residue.write_bytes(b"ignored cache sentinel")
    private = tmp_path / "apps/loops/keys/private-sentinel"
    private.parent.mkdir()
    private.write_bytes(b"unrelated private residue: do not delete")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    test_root_package_retires_the_legacy_frontend_not_migration()
    assert residue.read_bytes() == b"ignored cache sentinel"
    assert private.read_bytes() == b"unrelated private residue: do not delete"


@pytest.mark.parametrize("relative", ["pyproject.toml", "src/loops/main.py"])
def test_retirement_refuses_remaining_legacy_source(
    tmp_path, monkeypatch, relative
) -> None:
    (tmp_path / "pyproject.toml").write_bytes((ROOT / "pyproject.toml").read_bytes())
    source = tmp_path / "apps/loops" / relative
    source.parent.mkdir(parents=True)
    source.write_text("# leftover source\n")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    with pytest.raises(AssertionError):
        test_root_package_retires_the_legacy_frontend_not_migration()


def _dependency_name(requirement: str) -> str:
    """Compare distribution names, not extras, version ranges or markers."""
    match = re.match(r"[A-Za-z0-9_.-]+", requirement)
    assert match is not None, requirement
    return re.sub(r"[-_.]+", "-", match.group()).lower()


def test_flat_wheel_declares_vendored_third_party_dependencies() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        root = tomllib.load(stream)
    projects = {}
    for member in root["tool"]["uv"]["workspace"]["members"]:
        with (ROOT / member / "pyproject.toml").open("rb") as stream:
            projects[member] = tomllib.load(stream)["project"]
    workspace_names = {
        _dependency_name(project["name"]) for project in projects.values()
    }
    required = set()
    packages = root["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packages
    for package in packages:
        owner = package.split("/src/", 1)[0]
        for dependency in projects[owner].get("dependencies", []):
            name = _dependency_name(dependency)
            if name not in workspace_names:
                required.add(name)
    declared = {
        _dependency_name(dependency) for dependency in root["project"]["dependencies"]
    }
    assert required <= declared, (
        f"flat wheel missing dependencies: {sorted(required - declared)}"
    )
