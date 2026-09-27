"""Installed-wheel smoke for the stdlib Claude Arrival adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(
    executable: Path,
    environment: dict[str, str],
    cwd: Path,
    *arguments: str,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *arguments],
        cwd=cwd,
        env=environment,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def _ok(
    executable: Path, environment: dict[str, str], cwd: Path, *arguments: str
) -> dict:
    process = _run(executable, environment, cwd, *arguments)
    assert process.returncode == 0, process.stdout + process.stderr
    value = json.loads(process.stdout)
    assert value["ok"] is True
    return value["result"]


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: installed_smoke.py INSTALLED_LOOPS_MIN PLUGIN_DIRECTORY"
        )
    console, plugin = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    assert console.is_file() and (plugin / "hooks" / "arrival_session.py").is_file()
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))[
        "hooks"
    ]
    installed_python = console.with_name("python")
    assert installed_python.is_file()
    with tempfile.TemporaryDirectory(prefix="loops-claude-adapter-smoke-") as temporary:
        root = Path(temporary)
        outside = root / "outside-checkout"
        outside.mkdir()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
            and key != "LOOPS_CLAUDE_HOOK_CONFIG"
            and not key.startswith("HOOK_")
        }
        environment.update(
            {
                "LOOPS_HOME": str(root / "loops"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "CLAUDE_PLUGIN_ROOT": str(plugin),
                # Exercise the registered python3 lookup, not a rewritten command.
                "PATH": str(console.parent) + os.pathsep + environment.get("PATH", ""),
            }
        )
        imports = subprocess.run(
            [
                str(installed_python),
                "-c",
                "import json, loops_min, sdk; print(json.dumps([loops_min.__file__, sdk.__file__]))",
            ],
            cwd=outside,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert imports.returncode == 0, imports.stdout + imports.stderr
        install_root = installed_python.parent.parent.resolve()
        assert all(
            Path(path).resolve().is_relative_to(install_root)
            for path in json.loads(imports.stdout)
        )
        custody, target, ledger = (
            root / "custody",
            root / "adapter.vertex",
            root / "adapter.arrival",
        )
        credentials = [
            "--credential-root",
            str(custody),
            "--credential-namespace",
            "tenant",
            "--receipt-observer",
            "alice",
        ]
        _ok(
            console,
            environment,
            outside,
            "credential-create",
            str(custody),
            "--namespace",
            "tenant",
            "--observer",
            "alice",
            "--token",
            "adapter-smoke",
        )
        _ok(
            console,
            environment,
            outside,
            "init",
            str(target),
            "--name",
            "adapter-smoke",
            "--location",
            str(ledger),
            "--observer",
            "alice",
            *credentials,
        )
        proposal = root / "boundary.vertex"
        current = target.read_text(encoding="utf-8")
        proposal.write_text(
            current[:-2]
            + '  session { fold { items "by" "name" } }\n  boundary when="seal"\n}\n',
            encoding="utf-8",
        )
        _ok(
            console,
            environment,
            outside,
            "declaration",
            str(target),
            "--proposed-file",
            str(proposal),
            "--observer",
            "alice",
            *credentials,
        )
        config = root / "hook.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "binary": str(console),
                    "target": str(target),
                    "credential_root": str(custody),
                    "credential_namespace": "tenant",
                    "observer": "alice",
                    "receipt_observer": "alice",
                }
            ),
            encoding="utf-8",
        )
        environment["LOOPS_CLAUDE_HOOK_CONFIG"] = str(config)
        start = _run(
            Path("/bin/sh"),
            environment,
            outside,
            "-c",
            hooks["SessionStart"][0]["hooks"][0]["command"],
            stdin='{"hook_event_name":"SessionStart"}',
        )
        assert start.returncode == 0, start.stdout + start.stderr
        start_output = json.loads(start.stdout)
        context = json.loads(start_output["hookSpecificOutput"]["additionalContext"])
        assert set(start_output) == {"hookSpecificOutput"}
        assert (
            context["status"] == "open"
            and context["summary"]["name"] == "adapter-smoke"
        )
        assert context["activity"]["items"][0]["origin"] == ""
        assert context["open"]["signed"] is True
        end = _run(
            Path("/bin/sh"),
            environment,
            outside,
            "-c",
            hooks["SessionEnd"][0]["hooks"][0]["command"],
            stdin='{"hook_event_name":"SessionEnd"}',
        )
        assert end.returncode == 0, end.stdout + end.stderr
        diagnostics = [json.loads(line) for line in end.stderr.splitlines()]
        receipt = diagnostics[-1]
        assert diagnostics[0]["status"] == "close_confirmed_seal_pending"
        assert receipt["seal"]["vertex_name"] == "adapter-smoke"
        assert receipt["close"]["receipt"]["signed"] is True
        assert receipt["seal"]["receipt"]["signed"] is True
        assert (
            receipt["seal"]["tick_mark"] == "adapter-smoke"
            and receipt["seal"]["tick_id"]
        )
        before_stop = ledger.read_bytes()
        stop = _run(
            Path("/bin/sh"),
            environment,
            outside,
            "-c",
            hooks["Stop"][0]["hooks"][0]["command"],
            stdin='{"hook_event_name":"Stop","last_assistant_message":"Finished."}',
        )
        assert stop.returncode == 0, stop.stdout + stop.stderr
        assert stop.stdout == stop.stderr == ""
        assert ledger.read_bytes() == before_stop
        assert (
            _ok(console, environment, outside, "verify", str(target))["level"] == "full"
        )


if __name__ == "__main__":
    main()
