"""Exercise the installed root-wheel loops-min entry point outside the checkout."""

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
    input_text: str | None = None,
) -> dict[str, object]:
    process = subprocess.run(
        [str(executable), *arguments],
        cwd=cwd,
        env=environment,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(process.stdout)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: wheel_smoke.py PATH_TO_INSTALLED_LOOPS_MIN")
    console = Path(sys.argv[1]).resolve()
    assert console.is_file(), console
    python = console.parent / "python"
    assert python.is_file(), python

    with tempfile.TemporaryDirectory(prefix="loops-min-wheel-smoke-") as temporary:
        root = Path(temporary)
        run_root = root / "run-outside-checkout"
        run_root.mkdir()
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.update(
            {
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "LOOPS_HOME": str(root / "loops-home"),
            }
        )

        help_result = subprocess.run(
            [str(console), "--help"],
            cwd=run_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr
        assert "preview" in help_result.stdout

        imports = subprocess.run(
            [
                str(python),
                "-c",
                "import json, loops_min, sdk; print(json.dumps([loops_min.__file__, sdk.__file__]))",
            ],
            cwd=run_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert imports.returncode == 0, imports.stdout + imports.stderr
        install_root = Path(sys.prefix).resolve()
        for module_path in json.loads(imports.stdout):
            assert Path(module_path).resolve().is_relative_to(install_root), module_path

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
            console, environment, run_root, "facts", str(target),
            "--limit", "10", "--order", "oldest",
        )
        assert facts["ok"] is True
        assert facts["result"]["truncated"] is False
        assert [(item["id"], item["payload"]) for item in facts["result"]["items"]] == [
            ("file-id", {"message": "héllo\nfile"}),
            ("stdin-id", {"message": "stdin"}),
        ]
        verified = _run(console, environment, run_root, "verify", str(target))
        assert verified["ok"] is True
        assert verified["result"]["level"] == "full"


if __name__ == "__main__":
    main()
