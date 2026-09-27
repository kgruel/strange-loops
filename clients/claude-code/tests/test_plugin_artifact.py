"""Integration and fault tests for the fixed Claude plugin delivery artifact."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CLIENT_ROOT = Path(__file__).parents[1]
ALLOWLIST = {
    ".claude-plugin/plugin.json",
    "hooks/hooks.json",
    "hooks/arrival_session.py",
    "README.md",
}


def _environment(root: Path) -> dict[str, str]:
    excluded = {
        "LOOPS_CLAUDE_HOOK_CONFIG",
        "LOOPS_HOME",
        "XDG_STATE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "PYTHONPATH",
        "PYTHONHOME",
        "UV_PROJECT_ENVIRONMENT",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in excluded and not key.startswith("HOOK_")
    }
    environment.update(
        {
            "LOOPS_HOME": str(root / "loops-home"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "UV_PROJECT_ENVIRONMENT": str(root / "uv-environment"),
        }
    )
    return environment


def _source_copy(root: Path) -> Path:
    source = root / "plugin-source"
    shutil.copytree(CLIENT_ROOT, source)
    (source / "commands").mkdir()
    (source / "commands" / "legacy.md").write_text("legacy command", encoding="utf-8")
    (source / "skills" / "legacy").mkdir(parents=True)
    (source / "skills" / "legacy" / "SKILL.md").write_text(
        "legacy skill", encoding="utf-8"
    )
    (source / "hooks" / "legacy-hook.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (source / "hooks" / "extra-hooks.json").write_text("{}\n", encoding="utf-8")
    return source


def _build(source: Path, output: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(source / "build_plugin.py"), str(output)],
        cwd=root / "outside-checkout",
        env=_environment(root),
        text=True,
        capture_output=True,
        check=False,
    )


def _files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def test_builder_stages_only_fixed_plugin_files_and_wiring(tmp_path: Path) -> None:
    source = _source_copy(tmp_path)
    outside = tmp_path / "outside-checkout"
    outside.mkdir()
    artifact = tmp_path / "arrival-plugin"

    process = _build(source, artifact, tmp_path)

    assert process.returncode == 0, process.stderr
    assert _files(artifact) == ALLOWLIST
    for relative in ALLOWLIST:
        assert (artifact / relative).read_bytes() == (source / relative).read_bytes()

    manifest = json.loads(
        (artifact / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "loops"
    assert manifest["version"] == "0.2.0"

    hooks = json.loads((artifact / "hooks" / "hooks.json").read_text(encoding="utf-8"))[
        "hooks"
    ]
    assert set(hooks) == {"SessionStart", "SessionEnd", "Stop"}
    for event in hooks.values():
        command = event[0]["hooks"][0]["command"]
        executable, registered_path, action = shlex.split(command)
        assert executable == "python3"
        assert action in {"start", "end", "stop"}
        relative = registered_path.removeprefix("${CLAUDE_PLUGIN_ROOT}/")
        assert relative != registered_path
        resolved = (artifact / relative).resolve(strict=True)
        assert resolved.is_relative_to(artifact.resolve())
        assert resolved.is_file()


@pytest.mark.parametrize("disabled", [False, True])
def test_staged_adapter_exits_without_reading_stdin_when_unset_or_disabled(
    tmp_path: Path, disabled: bool
) -> None:
    source = _source_copy(tmp_path)
    outside = tmp_path / "outside-checkout"
    outside.mkdir()
    artifact = tmp_path / "arrival-plugin"
    assert _build(source, artifact, tmp_path).returncode == 0

    environment = _environment(tmp_path)
    if disabled:
        selected = tmp_path / "disabled.json"
        selected.write_text('{"enabled": false}', encoding="utf-8")
        environment["LOOPS_CLAUDE_HOOK_CONFIG"] = str(selected)
    process = subprocess.Popen(
        [sys.executable, str(artifact / "hooks" / "arrival_session.py"), "start"],
        cwd=outside,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Keep stdin open and empty: a read-to-EOF would block instead of exiting.
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate()

    assert process.returncode == 0, stderr
    assert stdout == ""
    assert stderr == ""


def test_builder_refuses_existing_outputs(tmp_path: Path) -> None:
    source = _source_copy(tmp_path)
    outside = tmp_path / "outside-checkout"
    outside.mkdir()

    existing = tmp_path / "existing-output"
    existing.mkdir()
    existing_sentinel = existing / "sentinel"
    existing_sentinel.write_text("keep", encoding="utf-8")
    existing_result = _build(source, existing, tmp_path)
    assert existing_result.returncode == 1
    assert existing_sentinel.read_text(encoding="utf-8") == "keep"

    symlink_parent = tmp_path / "symlink-parent"
    symlink_parent.mkdir()
    parent_sentinel = symlink_parent / "sentinel"
    parent_sentinel.write_text("keep", encoding="utf-8")
    missing_target = symlink_parent / "missing-output"
    dangling = tmp_path / "dangling-output"
    dangling.symlink_to(missing_target)
    dangling_result = _build(source, dangling, tmp_path)
    assert dangling_result.returncode == 1
    assert dangling.is_symlink()
    assert os.readlink(dangling) == str(missing_target)
    assert not missing_target.exists()
    assert parent_sentinel.read_text(encoding="utf-8") == "keep"

    regular = tmp_path / "output-file"
    regular.write_text("keep file", encoding="utf-8")
    assert _build(source, regular, tmp_path).returncode == 1
    assert regular.read_text(encoding="utf-8") == "keep file"

    live_link = tmp_path / "live-symlink-output"
    live_link.symlink_to(existing, target_is_directory=True)
    assert _build(source, live_link, tmp_path).returncode == 1
    assert live_link.is_symlink()
    assert os.readlink(live_link) == str(existing)
    assert _files(existing) == {"sentinel"}
    assert existing_sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "component",
    ["hooks", "commands", "skills", "mcpServers", "outputStyles", "lspServers"],
)
def test_builder_refuses_manifest_component_overrides(
    tmp_path: Path, component: str
) -> None:
    source = _source_copy(tmp_path)
    (tmp_path / "outside-checkout").mkdir()
    manifest_path = source / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[component] = "./legacy-component.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    artifact = tmp_path / "arrival-plugin"

    process = _build(source, artifact, tmp_path)

    assert process.returncode == 1, process.stdout + process.stderr
    assert "unsupported plugin metadata" in process.stderr
    assert not artifact.exists()


@pytest.mark.parametrize(
    "invalid_json",
    [
        '{"name":"legacy","name":"loops","version":"0.2.0"}',
        '{"name":"loops","version":"0.2.0","keywords":[NaN]}',
    ],
)
def test_builder_refuses_ambiguous_or_nonstandard_metadata(
    tmp_path: Path, invalid_json: str
) -> None:
    source = _source_copy(tmp_path)
    (tmp_path / "outside-checkout").mkdir()
    (source / ".claude-plugin" / "plugin.json").write_text(
        invalid_json, encoding="utf-8"
    )
    artifact = tmp_path / "arrival-plugin"

    process = _build(source, artifact, tmp_path)

    assert process.returncode == 1, process.stdout + process.stderr
    assert not artifact.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "symlink",
        "hooks-directory-symlink",
        "manifest-directory-symlink",
        "version",
        "wiring",
    ],
)
def test_builder_refuses_invalid_source_before_creating_output(
    tmp_path: Path, fault: str
) -> None:
    source = _source_copy(tmp_path)
    (tmp_path / "outside-checkout").mkdir()
    if fault in {"missing", "symlink"}:
        readme = source / "README.md"
        readme.unlink()
        if fault == "symlink":
            external = tmp_path / "external-readme"
            external.write_text("outside source", encoding="utf-8")
            readme.symlink_to(external)
    elif fault in {"hooks-directory-symlink", "manifest-directory-symlink"}:
        directory = source / (
            "hooks" if fault.startswith("hooks") else ".claude-plugin"
        )
        external = tmp_path / "external-directory"
        directory.rename(external)
        directory.symlink_to(external, target_is_directory=True)
    elif fault == "version":
        manifest_path = source / ".claude-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "0.1.0"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (source / "hooks" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    artifact = tmp_path / "arrival-plugin"

    process = _build(source, artifact, tmp_path)

    assert process.returncode == 1, process.stdout + process.stderr
    assert not artifact.exists()


def test_builder_refuses_missing_parent(tmp_path: Path) -> None:
    source = _source_copy(tmp_path)
    (tmp_path / "outside-checkout").mkdir()
    parent = tmp_path / "missing-parent"
    result = _build(source, parent / "artifact", tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert not parent.exists()
    assert "staged Claude plugin" not in result.stdout


@pytest.mark.parametrize("failure", ["mid-copy", "post-copy-verification"])
def test_builder_never_reports_failed_output_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    failure: str,
) -> None:
    source = _source_copy(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "plugin_builder", source / "build_plugin.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    copy = shutil.copy2

    def faulty_copy(src: Path, dst: Path) -> Path:
        if failure == "mid-copy" and src.name == "hooks.json":
            raise OSError("injected copy failure")
        result = copy(src, dst)
        if failure == "post-copy-verification" and src.name == "README.md":
            dst.write_text("injected copy corruption", encoding="utf-8")
        return result

    monkeypatch.setattr(builder.shutil, "copy2", faulty_copy)
    artifact = tmp_path / "arrival-plugin"
    assert builder.main([str(artifact)]) == 1
    output = capsys.readouterr()
    assert output.err
    assert "staged Claude plugin" not in output.out
    assert _files(artifact) == (
        {".claude-plugin/plugin.json"} if failure == "mid-copy" else ALLOWLIST
    )
