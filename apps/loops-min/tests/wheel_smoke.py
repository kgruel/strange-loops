"""Exercise every installed root-wheel JSON-client entry point outside the checkout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CLIENT_ALIASES = ("sl", "loops", "loops-min")


def _invoke(
    executable: Path,
    environment: dict[str, str],
    cwd: Path,
    *arguments: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *arguments],
        cwd=cwd,
        env=environment,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _run(
    executable: Path,
    environment: dict[str, str],
    cwd: Path,
    *arguments: str,
    input_text: str | None = None,
) -> dict[str, object]:
    process = _invoke(executable, environment, cwd, *arguments, input_text=input_text)
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(process.stdout)


def _assert_installed_entry_points(
    python: Path, environment: dict[str, str], cwd: Path
) -> None:
    """Resolve root-wheel metadata without ever importing the old frontend."""
    inspection = """
import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path

expected = {name: "loops_min.main:main" for name in ("sl", "loops", "loops-min")}
distribution = importlib.metadata.distribution("strange-loops")
entry_points = {
    point.name: point
    for point in distribution.entry_points
    if point.group == "console_scripts" and point.name in expected
}
assert {name: entry_points[name].value for name in expected} == expected
resolved = {name: entry_points[name].load() for name in expected}
from loops_min.main import main
assert all(function is main for function in resolved.values())
assert "loops" not in sys.modules
assert importlib.util.find_spec("loops") is None
assert importlib.util.find_spec("painted") is None
assert not any(str(path).startswith("loops/") for path in distribution.files)

import loops_min
import sdk
install_root = Path(sys.prefix).resolve()
module_paths = [Path(module.__file__).resolve() for module in (loops_min, sdk)]
assert all(path.is_relative_to(install_root) for path in module_paths), module_paths
print(json.dumps([str(path) for path in module_paths]))
"""
    process = subprocess.run(
        [str(python), "-c", inspection],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    module_paths = json.loads(process.stdout)
    assert len(module_paths) == 2


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: wheel_smoke.py PATH_TO_INSTALLED_ROOT_LOOPS_MIN")
    loops_min = Path(sys.argv[1]).resolve()
    assert loops_min.is_file(), loops_min
    console_directory = loops_min.parent
    consoles = {name: console_directory / name for name in CLIENT_ALIASES}
    for name, console in consoles.items():
        assert console.is_file(), f"missing installed {name} executable: {console}"
        assert os.access(console, os.X_OK), (
            f"installed {name} is not executable: {console}"
        )
    python = console_directory / "python"
    assert python.is_file(), python

    with tempfile.TemporaryDirectory(prefix="loops-min-wheel-smoke-") as temporary:
        root = Path(temporary)
        run_root = root / "run-outside-checkout"
        run_root.mkdir()
        environment = os.environ.copy()
        for name in tuple(environment):
            if name in {
                "PYTHONPATH",
                "PYTHONHOME",
                "LOOPS_CLAUDE_HOOK_CONFIG",
            } or name.startswith("HOOK_"):
                environment.pop(name)
        environment.update(
            {
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "LOOPS_HOME": str(root / "loops-home"),
            }
        )

        _assert_installed_entry_points(python, environment, run_root)
        for name, console in consoles.items():
            help_result = _invoke(console, environment, run_root, "--help")
            assert help_result.returncode == 0, help_result.stdout + help_result.stderr
            assert "preview" in help_result.stdout, name

        console = consoles["loops-min"]
        custody = root / "custody"
        target = root / "sample.vertex"
        ledger = root / "sample.arrival"
        credentials = [
            "--credential-root",
            str(custody),
            "--credential-namespace",
            "tenant",
            "--receipt-observer",
            "alice",
        ]
        created = _run(
            console,
            environment,
            run_root,
            "credential-create",
            str(custody),
            "--namespace",
            "tenant",
            "--observer",
            "alice",
            "--token",
            "smoke-alice",
        )
        assert created["ok"] is True
        initialized = _run(
            console,
            environment,
            run_root,
            "init",
            str(target),
            "--name",
            "sample",
            "--location",
            str(ledger),
            "--observer",
            "alice",
            *credentials,
        )
        assert initialized["ok"] is True
        strict_summary = _run(
            console, environment, run_root, "summary", str(target), "--arrival-only"
        )
        assert strict_summary["ok"] is True
        assert strict_summary["result"]["read_path"] == "arrival"

        payload = root / "payload.json"
        payload.write_text('{\n  "message": "héllo\\nfile"\n}\n', encoding="utf-8")
        before_preview = ledger.read_bytes()
        preview = _run(
            console,
            environment,
            run_root,
            "preview",
            str(target),
            "item",
            "--payload-file",
            str(payload),
            "--observer",
            "alice",
            "--id",
            "preview-id",
            *credentials,
        )
        assert preview["ok"] is True
        assert preview["result"]["admitted"] is True
        assert ledger.read_bytes() == before_preview
        emitted_file = _run(
            console,
            environment,
            run_root,
            "emit",
            str(target),
            "item",
            "--payload-file",
            str(payload),
            "--observer",
            "alice",
            "--id",
            "file-id",
            *credentials,
        )
        assert emitted_file["ok"] is True
        emitted_stdin = _run(
            console,
            environment,
            run_root,
            "emit",
            str(target),
            "item",
            "--payload-file",
            "-",
            "--observer",
            "alice",
            "--id",
            "stdin-id",
            *credentials,
            input_text='{"message":"stdin"}\n',
        )
        assert emitted_stdin["ok"] is True
        facts = _run(
            console,
            environment,
            run_root,
            "facts",
            str(target),
            "--limit",
            "10",
            "--order",
            "oldest",
        )
        assert facts["ok"] is True
        assert facts["result"]["truncated"] is False
        assert [(item["id"], item["payload"]) for item in facts["result"]["items"]] == [
            ("file-id", {"message": "héllo\nfile"}),
            ("stdin-id", {"message": "stdin"}),
        ]
        metadata = _run(
            console,
            environment,
            run_root,
            "facts",
            str(target),
            "--arrival-only",
            "--metadata-only",
            "--limit",
            "5",
            "--order",
            "newest",
        )
        assert metadata["ok"] is True
        assert metadata["result"]["metadata_only"] is True
        assert all("payload" not in item for item in metadata["result"]["items"])
        bulk = _run(
            console,
            environment,
            run_root,
            "emit-batch",
            str(target),
            "--facts-json",
            json.dumps(
                [
                    {
                        "id": f"bulk-{number}",
                        "kind": "item",
                        "observer": "alice",
                        "payload": {"number": number},
                    }
                    for number in range(49)
                ]
            ),
            *credentials,
        )
        assert bulk["ok"] is True
        history = _run(
            console,
            environment,
            run_root,
            "facts",
            str(target),
            "--all",
            "--order",
            "oldest",
        )
        assert history["ok"] is True
        assert history["result"]["complete"] is True
        # Exercise aliases only after preserving this pre-alias history contract.
        assert history["result"]["item_count"] == 51
        assert [item["id"] for item in history["result"]["items"]][:2] == [
            "file-id",
            "stdin-id",
        ]

        missing = root / "missing.vertex"
        alias_errors: list[tuple[int, dict[str, object]]] = []
        for name, alias in consoles.items():
            alias_id = f"alias-{name}-write"
            emitted = _run(
                alias,
                environment,
                run_root,
                "emit",
                str(target),
                "item",
                "--payload-json",
                json.dumps({"alias": name}),
                "--observer",
                "alice",
                "--id",
                alias_id,
                *credentials,
            )
            assert emitted["ok"] is True
            assert emitted["result"]["write_path"] == "arrival"
            assert emitted["result"]["id"] == alias_id
            assert all(
                emitted["result"][field] is True
                for field in ("stored", "witnessed", "signed")
            )
            alias_facts = _run(
                alias,
                environment,
                run_root,
                "facts",
                str(target),
                "--arrival-only",
                "--limit",
                "10",
                "--order",
                "newest",
            )
            assert alias_facts["ok"] is True
            assert any(
                item["id"] == alias_id for item in alias_facts["result"]["items"]
            )
            failed = _invoke(alias, environment, run_root, "summary", str(missing))
            assert failed.returncode == 4, failed.stdout + failed.stderr
            envelope = json.loads(failed.stdout)
            assert envelope["ok"] is False
            assert envelope["error"]["type"] == "TargetNotFound"
            alias_errors.append((failed.returncode, envelope))
        assert alias_errors[1:] == [alias_errors[0], alias_errors[0]]

        current = target.read_text(encoding="utf-8")
        assert current.endswith("}\n")
        proposal = root / "seal.vertex"
        proposal.write_text(
            current[:-2] + '  boundary when="seal"\n}\n', encoding="utf-8"
        )
        declared = _run(
            console,
            environment,
            run_root,
            "declaration",
            str(target),
            "--proposed-file",
            str(proposal),
            "--observer",
            "alice",
            *credentials,
        )
        assert declared["ok"] is True
        seal = _run(
            console,
            environment,
            run_root,
            "seal",
            str(target),
            "--payload-json",
            "{}",
            "--observer",
            "alice",
            "--id",
            "smoke-seal",
            *credentials,
        )
        assert seal["ok"] is True
        assert seal["result"]["sealed"] is True
        assert seal["result"]["receipt"]["tick_mark"] == "sample"
        verified = _run(console, environment, run_root, "verify", str(target))
        assert verified["ok"] is True
        assert verified["result"]["level"] == "full"


if __name__ == "__main__":
    main()
