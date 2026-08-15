"""Rule 16: hot-path libs keep their import footprint (lazy-import ratchet)."""

from __future__ import annotations

import json as _json
import subprocess
import sys
import textwrap

from ._helpers import REPO_ROOT

# The cold-start libs on sl's hot path deliberately defer typing/pathlib/ckdl
# behind __getattr__ tables and TYPE_CHECKING-shaped tricks (`if False:`,
# `TYPE_CHECKING = False`). The wins are measured, not aesthetic: the
# autoresearch lazy-imports run cut `import lang` from 4.7ms to 3.5ms, with
# `typing` alone worth ~1.4ms — and sl pays that cost on every CLI invocation.
# The idiom is exactly what a well-meaning cleanup pass "fixes" (one such pass
# was caught and reverted 2026-08-14), so the invariant lives here instead of
# in review vigilance. Allowlists are SHRINK-ONLY: removing a module is
# progress, adding one means an eager import leaked into the hot path — defer
# it instead, or (with a measurement justifying it) grow the entry in the same
# change that documents why.
_IMPORT_FOOTPRINT_ALLOWLIST: dict[str, set[str]] = {
    "atoms": {"__future__", "types"},
    "engine": set(),
    "lang": {"__future__"},
}


def test_hot_path_libs_import_footprint():
    """Bare `import <lib>` must load nothing outside the lib but its allowlist.

    Runs each import in a fresh subprocess (this process has long since loaded
    typing) and diffs sys.modules, reporting top-level module names only.
    """
    prog = textwrap.dedent(
        """
        import json, sys
        lib = sys.argv[1]
        base = set(sys.modules)
        __import__(lib)
        new = {m.split(".")[0] for m in set(sys.modules) - base}
        new -= {lib}
        print(json.dumps(sorted(new)))
        """
    )
    violations = []
    for lib, allowed in sorted(_IMPORT_FOOTPRINT_ALLOWLIST.items()):
        proc = subprocess.run(
            [sys.executable, "-c", prog, lib],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, f"import {lib} failed:\n{proc.stderr}"
        loaded = set(_json.loads(proc.stdout))
        extra = loaded - allowed
        if extra:
            violations.append(
                f"  {lib}: imports {sorted(extra)} eagerly (allowlist: {sorted(allowed)})"
            )
    assert not violations, (
        "hot-path libs must not grow their import-time footprint (defer the "
        "import, or grow the allowlist only with a measurement in the same "
        "change):\n" + "\n".join(violations)
    )
