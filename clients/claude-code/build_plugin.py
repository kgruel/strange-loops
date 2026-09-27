"""Stage the fixed Claude Code Arrival plugin into a fresh directory."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

FILES = (
    ".claude-plugin/plugin.json",
    "hooks/hooks.json",
    "hooks/arrival_session.py",
    "README.md",
)

_METADATA_FIELDS = {"name", "version", "description", "author", "homepage", "keywords"}

_EXPECTED_HOOKS = {
    "hooks": {
        "SessionStart": [
            {
                "matcher": "startup|resume|clear|fork",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/arrival_session.py" '
                            "start"
                        ),
                    }
                ],
            }
        ],
        "SessionEnd": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/arrival_session.py" '
                            "end"
                        ),
                        "timeout": 60,
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/arrival_session.py" '
                            "stop"
                        ),
                    }
                ]
            }
        ],
    }
}


class BuildError(Exception):
    """The requested artifact cannot safely be reported as ready."""


def _regular_file(root: Path, relative: str) -> Path:
    path = root
    for component in Path(relative).parts:
        path /= component
        if path.is_symlink():
            raise BuildError(f"symlink in required source path: {path}")
    if not path.is_file():
        raise BuildError(f"required regular file is missing: {path}")
    return path


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BuildError(f"duplicate JSON metadata key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise BuildError(f"invalid JSON metadata constant: {value}")


def _json_file(root: Path, relative: str) -> dict[str, Any]:
    path = _regular_file(root, relative)
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid JSON metadata in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"JSON metadata must be an object: {path}")
    return value


def _validate_plugin(root: Path) -> None:
    for relative in FILES:
        _regular_file(root, relative)

    manifest = _json_file(root, ".claude-plugin/plugin.json")
    if set(manifest) - _METADATA_FIELDS:
        raise BuildError(
            "unsupported plugin metadata: additional components are not staged"
        )
    if manifest.get("name") != "loops":
        raise BuildError("plugin metadata must name the plugin 'loops'")
    if manifest.get("version") != "0.2.0":
        raise BuildError("plugin metadata must have version 0.2.0")

    hooks = _json_file(root, "hooks/hooks.json")
    if hooks != _EXPECTED_HOOKS:
        raise BuildError(
            "hook metadata does not match the fixed Arrival lifecycle wiring"
        )


def _output_path(argument: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(argument)))


def stage(output: Path) -> None:
    source = Path(__file__).resolve().parent
    _validate_plugin(source)

    # exists() misses dangling symlinks, while lexists() refuses them too.
    if os.path.lexists(output):
        raise BuildError(f"output path already exists (including symlinks): {output}")

    # A copy failure intentionally leaves any partial local directory for inspection.
    # It is not a transactional publication and this builder never overwrites it.
    output.mkdir()
    for relative in FILES:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)

    _validate_plugin(output)
    for relative in FILES:
        if (source / relative).read_bytes() != (output / relative).read_bytes():
            raise BuildError(f"copied file differs from source: {relative}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: build_plugin.py OUTPUT_DIRECTORY", file=sys.stderr)
        return 2
    try:
        output = _output_path(argv[0])
        stage(output)
    except (BuildError, OSError, UnicodeError) as exc:
        print(f"build_plugin.py: {exc}", file=sys.stderr)
        return 1
    print(f"staged Claude plugin directory: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
