"""Rule 8: signing domain constants live in libs/custody only."""

from __future__ import annotations

from ._helpers import (
    REPO_ROOT,
    _rel,
    _src_py_files,
)

_DOMAIN_LITERALS = ("loops-tick-v1", "loops-fact-v1")
_DOMAIN_HOME = "libs/custody/src/custody/signing.py"


def test_domain_constants_confined_to_custody():
    """The domain-separation literals appear in exactly one source file.

    ``loops-tick-v1``/``loops-fact-v1`` are the store's at-rest signing
    format (design/architecture/custody-lib-extraction). This pin is
    string-level, not import-level, on purpose: re-hardcoding the literal
    instead of importing TICK_DOMAIN/FACT_DOMAIN would pass any import
    ratchet while silently forking the format. Import the constants.
    """
    assert (REPO_ROOT / _DOMAIN_HOME).exists(), f"custody moved? {_DOMAIN_HOME}"

    violations = []
    for root_name in ("libs", "apps"):
        for pkg_dir in (REPO_ROOT / root_name).iterdir():
            if not pkg_dir.is_dir():
                continue
            for py_file in _src_py_files(pkg_dir):
                rel = _rel(py_file)
                if rel == _DOMAIN_HOME:
                    continue
                text = py_file.read_text()
                for literal in _DOMAIN_LITERALS:
                    if literal in text:
                        violations.append(f"  {rel} contains {literal!r}")

    assert not violations, (
        f"Signing domain literals belong to {_DOMAIN_HOME} only — "
        "import TICK_DOMAIN/FACT_DOMAIN from custody instead:\n"
        + "\n".join(violations)
    )
